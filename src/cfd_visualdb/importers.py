from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pyvista as pv


def sha256_file(path: str | Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _array_range(array) -> tuple[float | None, float | None, int]:
    values = np.asarray(array)
    components = 1 if values.ndim == 1 else int(values.shape[1])
    numeric = values.astype(float, copy=False)
    if components > 1:
        numeric = np.linalg.norm(numeric, axis=1)
    finite = numeric[np.isfinite(numeric)]
    if not finite.size:
        return None, None, components
    return float(finite.min()), float(finite.max()), components


def inspect_dataset(path: str | Path) -> tuple[pv.DataSet, dict]:
    source = Path(path).resolve()
    if source.suffix.lower() not in {".vtu", ".vtp"}:
        raise ValueError("Only .vtu and .vtp files are supported in this prototype")
    mesh = pv.read(source)
    fields = []
    for association, collection in (("point", mesh.point_data), ("cell", mesh.cell_data)):
        for name in collection.keys():
            try:
                minimum, maximum, components = _array_range(collection[name])
            except (TypeError, ValueError):
                minimum, maximum = None, None
                components = int(collection[name].shape[1]) if collection[name].ndim > 1 else 1
            fields.append({"name": str(name), "association": association, "components": components,
                           "minimum": minimum, "maximum": maximum})
    return mesh, {
        "name": source.stem,
        "file_path": str(source),
        "file_hash": sha256_file(source),
        "dataset_type": type(mesh).__name__,
        "point_count": int(mesh.n_points),
        "cell_count": int(mesh.n_cells),
        "fields": fields,
    }


