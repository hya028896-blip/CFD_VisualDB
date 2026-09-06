from __future__ import annotations

import numpy as np
import pyvista as pv


PERCENTILES = (5, 10, 25, 75, 90, 95)


def _scalar_values(array: np.ndarray) -> np.ndarray:
    values = np.asarray(array, dtype=float)
    return np.linalg.norm(values, axis=1) if values.ndim > 1 else values


def compute_roi_statistics(mesh: pv.DataSet, cell_ids: list[int]) -> tuple[float, list[dict]]:
    if not cell_ids:
        raise ValueError("ROI has no selected cells")
    selected = mesh.extract_cells(np.asarray(cell_ids, dtype=int))
    measured = selected.compute_cell_sizes(length=False, area=True, volume=False)
    areas = np.asarray(measured.cell_data["Area"], dtype=float)
    total_area = float(np.nansum(areas))
    results = []
    sources = [("cell", measured.cell_data, set(mesh.cell_data.keys()))]
    try:
        converted = measured.point_data_to_cell_data(pass_point_data=True).cell_data
        sources.append(("point", converted, set(mesh.point_data.keys())))
    except Exception:
        pass
    seen = set()
    for association, data, allowed_names in sources:
        for name in allowed_names:
            if name not in data:
                continue
            if name in {"Area", "vtkOriginalCellIds", "vtkOriginalPointIds"} or (association, name) in seen:
                continue
            seen.add((association, name))
            try:
                values = _scalar_values(data[name])
            except (TypeError, ValueError):
                continue
            finite = np.isfinite(values)
            values = values[finite]
            weights = areas[finite] if len(areas) == len(finite) else np.ones(len(values))
            if not values.size:
                continue
            stats = {
                "area_weighted_mean": float(np.average(values, weights=weights)) if np.sum(weights) > 0 else None,
                "mean": float(np.mean(values)), "median": float(np.median(values)),
                "min": float(np.min(values)), "max": float(np.max(values)), "std": float(np.std(values)),
            }
            stats.update({f"p{p}": float(np.percentile(values, p)) for p in PERCENTILES})
            results.append({"field_name": str(name), "association": association, "statistics": stats})
    return total_area, results


class ROIAPI:
    def __init__(self, database):
        self.database = database

    def calculate(self, mesh: pv.DataSet, cell_ids: list[int]):
        return compute_roi_statistics(mesh, cell_ids)

    def save(self, dataset_id: int, name: str, source_hash: str, cell_ids: list[int], mesh: pv.DataSet) -> int:
        area, statistics = self.calculate(mesh, cell_ids)
        return self.database.save_roi(dataset_id, name, source_hash, cell_ids, area, statistics)

