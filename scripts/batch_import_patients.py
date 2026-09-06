from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from cfd_visualdb.database import DatabaseAPI
from cfd_visualdb.importers import inspect_dataset


STEP_PATTERN = re.compile(r"^all_results_(\d{5})\.(vtu|vtp)$", re.IGNORECASE)
AVERAGE_NAMES = {"average.vtp", "average_result.vtp"}


def selected_files(sim_dir: Path) -> list[Path]:
    result = []
    for path in sim_dir.iterdir():
        if not path.is_file():
            continue
        match = STEP_PATTERN.match(path.name)
        if match and 300 <= int(match.group(1)) <= 400:
            result.append(path.resolve())
        elif path.name.lower() in AVERAGE_NAMES:
            result.append(path.resolve())
    return sorted(result, key=lambda item: item.name.lower())


def discover(root: Path) -> dict[str, list[Path]]:
    patients = {}
    for patient_dir in sorted((path for path in root.iterdir() if path.is_dir()), key=lambda item: item.name.lower()):
        sim_dir = patient_dir / "sim-converted-results"
        if not sim_dir.is_dir():
            continue
        files = selected_files(sim_dir)
        if files:
            patients[patient_dir.name] = files
    return patients


def find_target_group(database: DatabaseAPI, project_name: str, group_name: str):
    with database.connect() as con:
        return con.execute(
            "SELECT g.id group_id,p.id project_id FROM groups_ g JOIN projects p ON p.id=g.project_id WHERE p.name=? AND g.name=?",
            (project_name, group_name),
        ).fetchone()


def parse_one(path: Path):
    _, metadata = inspect_dataset(path)
    return path, metadata


def source_snapshot(paths):
    return {str(path): (path.stat().st_size, path.stat().st_mtime_ns) for path in paths}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--database", type=Path, default=PROJECT_ROOT / "data" / "cfd_visualdb.sqlite3")
    parser.add_argument("--project", default="冠状动脉原始版数据")
    parser.add_argument("--group", default="患者vtp and vtu(300-400)")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    root = args.root.resolve()
    if not root.is_dir():
        raise SystemExit(f"Source root does not exist: {root}")
    patients = discover(root)
    all_paths = [path for paths in patients.values() for path in paths]
    counts = {name: len(paths) for name, paths in patients.items()}
    print(json.dumps({"root": str(root), "patients": len(patients), "files": len(all_paths),
                      "bytes": sum(path.stat().st_size for path in all_paths),
                      "non_43_counts": {name: count for name, count in counts.items() if count != 43}}, ensure_ascii=False), flush=True)
    if args.dry_run:
        return 0

    database = DatabaseAPI(args.database)
    target = find_target_group(database, args.project, args.group)
    if target is None:
        raise SystemExit(f"Target project/group not found: {args.project} / {args.group}")

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = PROJECT_ROOT / "data" / "backups" / f"cfd_visualdb-before-patient-import-{timestamp}.sqlite3"
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    source_con = sqlite3.connect(args.database)
    backup_con = sqlite3.connect(backup_path)
    source_con.backup(backup_con)
    backup_con.close(); source_con.close()
    print(f"BACKUP={backup_path}", flush=True)

    before = source_snapshot(all_paths)
    case_map = {}
    with database.connect() as con:
        for patient_name in patients:
            row = con.execute("SELECT id FROM cases WHERE group_id=? AND name=?", (target["group_id"], patient_name)).fetchone()
            if row:
                case_map[patient_name] = row[0]
            else:
                case_map[patient_name] = con.execute("INSERT INTO cases(group_id,name) VALUES (?,?)", (target["group_id"], patient_name)).lastrowid

    existing_by_case = {}
    with database.connect() as con:
        for patient_name, case_id in case_map.items():
            existing_by_case[case_id] = {row[0] for row in con.execute("SELECT file_path FROM datasets WHERE case_id=?", (case_id,))}
    tasks = [(patient_name, case_map[patient_name], path) for patient_name, paths in patients.items() for path in paths
             if str(path) not in existing_by_case[case_map[patient_name]]]
    skipped = len(all_paths) - len(tasks)
    print(f"TO_IMPORT={len(tasks)} SKIPPED_EXISTING={skipped} CASES={len(case_map)}", flush=True)

    imported = 0
    errors = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = {executor.submit(parse_one, path): (patient_name, case_id, path) for patient_name, case_id, path in tasks}
        for future in as_completed(futures):
            patient_name, case_id, path = futures[future]
            try:
                _, metadata = future.result()
                database.upsert_dataset(case_id, metadata)
                imported += 1
            except Exception as exc:
                errors.append({"patient": patient_name, "path": str(path), "error": repr(exc)})
            completed = imported + len(errors)
            if completed % 20 == 0 or completed == len(tasks):
                print(f"PROGRESS={completed}/{len(tasks)} IMPORTED={imported} ERRORS={len(errors)}", flush=True)

    after = source_snapshot(all_paths)
    changed_sources = [path for path, state in before.items() if after.get(path) != state]
    report = {
        "source_root": str(root), "project": args.project, "group": args.group,
        "patients": len(patients), "selected_files": len(all_paths), "skipped_existing": skipped,
        "imported": imported, "errors": errors, "source_files_changed": changed_sources,
        "database_backup": str(backup_path), "finished_at": datetime.now().isoformat(),
    }
    report_path = PROJECT_ROOT / "data" / f"patient-import-report-{timestamp}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"REPORT={report_path}", flush=True)
    print(f"DONE IMPORTED={imported} ERRORS={len(errors)} SOURCE_CHANGED={len(changed_sources)}", flush=True)
    return 1 if errors or changed_sources else 0


if __name__ == "__main__":
    raise SystemExit(main())
