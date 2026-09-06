from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, notes TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS groups_ (
    id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL, notes TEXT DEFAULT '', UNIQUE(project_id, name)
);
CREATE TABLE IF NOT EXISTS cases (
    id INTEGER PRIMARY KEY, group_id INTEGER NOT NULL REFERENCES groups_(id) ON DELETE CASCADE,
    name TEXT NOT NULL, notes TEXT DEFAULT '', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(group_id, name)
);
CREATE TABLE IF NOT EXISTS datasets (
    id INTEGER PRIMARY KEY, case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    name TEXT NOT NULL, file_path TEXT NOT NULL, file_hash TEXT NOT NULL,
    dataset_type TEXT NOT NULL, point_count INTEGER NOT NULL, cell_count INTEGER NOT NULL,
    imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(case_id, file_path)
);
CREATE TABLE IF NOT EXISTS fields (
    id INTEGER PRIMARY KEY, dataset_id INTEGER NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    name TEXT NOT NULL, association TEXT NOT NULL, components INTEGER NOT NULL,
    minimum REAL, maximum REAL, UNIQUE(dataset_id, name, association)
);
CREATE TABLE IF NOT EXISTS rois (
    id INTEGER PRIMARY KEY, dataset_id INTEGER NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    name TEXT NOT NULL, source_hash TEXT NOT NULL, cell_ids_json TEXT NOT NULL,
    area REAL, creation_method TEXT NOT NULL DEFAULT 'manual', notes TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(dataset_id, name)
);
CREATE TABLE IF NOT EXISTS roi_statistics (
    id INTEGER PRIMARY KEY, roi_id INTEGER NOT NULL REFERENCES rois(id) ON DELETE CASCADE,
    field_name TEXT NOT NULL, association TEXT NOT NULL, statistics_json TEXT NOT NULL,
    UNIQUE(roi_id, field_name, association)
);
CREATE INDEX IF NOT EXISTS idx_datasets_case ON datasets(case_id);
CREATE INDEX IF NOT EXISTS idx_fields_dataset ON fields(dataset_id);
CREATE INDEX IF NOT EXISTS idx_rois_dataset ON rois(dataset_id);
"""


class DatabaseAPI:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as con:
            con.executescript(SCHEMA)

    @contextmanager
    def connect(self):
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def ensure_defaults(self) -> int | None:
        with self.connect() as con:
            if con.execute("SELECT COUNT(*) FROM projects").fetchone()[0] > 0:
                row = con.execute("SELECT id FROM cases ORDER BY id LIMIT 1").fetchone()
                return row[0] if row else None
            con.execute("INSERT OR IGNORE INTO projects(name) VALUES (?)", ("Default Project",))
            project_id = con.execute("SELECT id FROM projects WHERE name=?", ("Default Project",)).fetchone()[0]
            con.execute("INSERT OR IGNORE INTO groups_(project_id,name) VALUES (?,?)", (project_id, "Ungrouped"))
            group_id = con.execute("SELECT id FROM groups_ WHERE project_id=? AND name=?", (project_id, "Ungrouped")).fetchone()[0]
            con.execute("INSERT OR IGNORE INTO cases(group_id,name) VALUES (?,?)", (group_id, "Default Case"))
            return con.execute("SELECT id FROM cases WHERE group_id=? AND name=?", (group_id, "Default Case")).fetchone()[0]

    def create_project(self, name: str) -> int:
        with self.connect() as con:
            return con.execute("INSERT INTO projects(name) VALUES (?)", (name,)).lastrowid

    def create_group(self, project_id: int, name: str) -> int:
        with self.connect() as con:
            return con.execute("INSERT INTO groups_(project_id,name) VALUES (?,?)", (project_id, name)).lastrowid

    def create_case(self, group_id: int, name: str) -> int:
        with self.connect() as con:
            return con.execute("INSERT INTO cases(group_id,name) VALUES (?,?)", (group_id, name)).lastrowid

    def upsert_dataset(self, case_id: int, meta: dict[str, Any]) -> int:
        with self.connect() as con:
            existing = con.execute("SELECT id FROM datasets WHERE case_id=? AND file_path=?", (case_id, meta["file_path"])).fetchone()
            values = (meta["name"], meta["file_hash"], meta["dataset_type"], meta["point_count"], meta["cell_count"])
            if existing:
                dataset_id = existing[0]
                con.execute("UPDATE datasets SET name=?,file_hash=?,dataset_type=?,point_count=?,cell_count=?,imported_at=CURRENT_TIMESTAMP WHERE id=?", (*values, dataset_id))
                con.execute("DELETE FROM fields WHERE dataset_id=?", (dataset_id,))
            else:
                dataset_id = con.execute(
                    "INSERT INTO datasets(case_id,name,file_path,file_hash,dataset_type,point_count,cell_count) VALUES (?,?,?,?,?,?,?)",
                    (case_id, meta["name"], meta["file_path"], meta["file_hash"], meta["dataset_type"], meta["point_count"], meta["cell_count"]),
                ).lastrowid
            con.executemany("INSERT INTO fields(dataset_id,name,association,components,minimum,maximum) VALUES (?,?,?,?,?,?)",
                            [(dataset_id, f["name"], f["association"], f["components"], f["minimum"], f["maximum"]) for f in meta["fields"]])
            return dataset_id

    def tree(self) -> list[sqlite3.Row]:
        with self.connect() as con:
            return con.execute("""SELECT p.id project_id,p.name project_name,g.id group_id,g.name group_name,
                c.id case_id,c.name case_name,d.id dataset_id,d.name dataset_name,d.file_path,
                r.id roi_id,r.name roi_name FROM projects p
                LEFT JOIN groups_ g ON g.project_id=p.id LEFT JOIN cases c ON c.group_id=g.id
                LEFT JOIN datasets d ON d.case_id=c.id LEFT JOIN rois r ON r.dataset_id=d.id
                ORDER BY p.name,g.name,c.name,d.name,r.name""").fetchall()

    def cases(self) -> list[sqlite3.Row]:
        with self.connect() as con:
            return con.execute("SELECT c.*, p.id project_id, p.name project_name, g.name group_name FROM cases c JOIN groups_ g ON g.id=c.group_id JOIN projects p ON p.id=g.project_id ORDER BY p.name,g.name,c.name").fetchall()

    def delete_entity(self, kind: str, entity_id: int) -> None:
        tables = {"project": "projects", "group": "groups_", "case": "cases", "dataset": "datasets", "roi": "rois"}
        if kind not in tables:
            raise ValueError(f"Unsupported entity type: {kind}")
        with self.connect() as con:
            con.execute(f"DELETE FROM {tables[kind]} WHERE id=?", (entity_id,))

    def projects(self) -> list[sqlite3.Row]:
        with self.connect() as con:
            return con.execute("SELECT * FROM projects ORDER BY name").fetchall()

    def groups(self, project_id: int | None = None) -> list[sqlite3.Row]:
        with self.connect() as con:
            if project_id is None:
                return con.execute("SELECT g.*,p.name project_name FROM groups_ g JOIN projects p ON p.id=g.project_id ORDER BY p.name,g.name").fetchall()
            return con.execute("SELECT g.*,p.name project_name FROM groups_ g JOIN projects p ON p.id=g.project_id WHERE g.project_id=? ORDER BY g.name", (project_id,)).fetchall()

    def datasets(self, case_id: int | None = None) -> list[sqlite3.Row]:
        with self.connect() as con:
            if case_id is None:
                return con.execute("SELECT * FROM datasets ORDER BY name").fetchall()
            return con.execute("SELECT * FROM datasets WHERE case_id=? ORDER BY name", (case_id,)).fetchall()

    def dataset(self, dataset_id: int) -> sqlite3.Row | None:
        with self.connect() as con:
            return con.execute("SELECT * FROM datasets WHERE id=?", (dataset_id,)).fetchone()

    def fields(self, dataset_id: int) -> list[sqlite3.Row]:
        with self.connect() as con:
            return con.execute("SELECT * FROM fields WHERE dataset_id=? ORDER BY association,name", (dataset_id,)).fetchall()

    def save_roi(self, dataset_id: int, name: str, source_hash: str, cell_ids: Iterable[int], area: float, statistics: list[dict[str, Any]]) -> int:
        with self.connect() as con:
            roi_id = con.execute("INSERT INTO rois(dataset_id,name,source_hash,cell_ids_json,area) VALUES (?,?,?,?,?)",
                                 (dataset_id, name, source_hash, json.dumps(list(map(int, cell_ids))), area)).lastrowid
            con.executemany("INSERT INTO roi_statistics(roi_id,field_name,association,statistics_json) VALUES (?,?,?,?)",
                            [(roi_id, s["field_name"], s["association"], json.dumps(s["statistics"], ensure_ascii=False)) for s in statistics])
            return roi_id

    def roi(self, roi_id: int) -> sqlite3.Row | None:
        with self.connect() as con:
            return con.execute("SELECT r.*,d.name dataset_name FROM rois r JOIN datasets d ON d.id=r.dataset_id WHERE r.id=?", (roi_id,)).fetchone()

    def roi_statistics(self, roi_id: int) -> list[dict[str, Any]]:
        with self.connect() as con:
            rows = con.execute("SELECT field_name,association,statistics_json FROM roi_statistics WHERE roi_id=? ORDER BY association,field_name", (roi_id,)).fetchall()
            return [{"field_name": row["field_name"], "association": row["association"],
                     "statistics": json.loads(row["statistics_json"])} for row in rows]
