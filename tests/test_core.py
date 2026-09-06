from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pyvista as pv

from cfd_visualdb.database import DatabaseAPI
from cfd_visualdb.importers import inspect_dataset
from cfd_visualdb.i18n import translate
from cfd_visualdb.roi import compute_roi_statistics
from cfd_visualdb.streamlines import StreamlineOptions, generate_streamlines, vector_fields
from cfd_visualdb.viewer import sync_camera_relative
from cfd_visualdb.main_window import LAYOUTS


def sample_surface(path: Path):
    mesh = pv.Plane(i_resolution=3, j_resolution=3).triangulate()
    mesh.point_data["TAWSS"] = np.linspace(0.1, 2.0, mesh.n_points)
    mesh.cell_data["OSI"] = np.linspace(0.0, 0.5, mesh.n_cells)
    mesh.save(path)
    return mesh


def test_import_database_and_roi(tmp_path):
    source = tmp_path / "wall.vtp"
    mesh = sample_surface(source)
    loaded, meta = inspect_dataset(source)
    assert loaded.n_cells == mesh.n_cells
    assert {f["name"] for f in meta["fields"]} >= {"TAWSS", "OSI"}
    assert len(meta["file_hash"]) == 64

    db = DatabaseAPI(tmp_path / "test.sqlite3")
    case_id = db.ensure_defaults()
    dataset_id = db.upsert_dataset(case_id, meta)
    assert db.dataset(dataset_id)["file_path"] == str(source.resolve())
    assert {f["name"] for f in db.fields(dataset_id)} >= {"TAWSS", "OSI"}

    ids = [0, 1, 2]
    area, statistics = compute_roi_statistics(mesh, ids)
    assert area > 0
    assert {s["field_name"] for s in statistics} >= {"TAWSS", "OSI"}
    roi_id = db.save_roi(dataset_id, "Aneurysm_01", meta["file_hash"], ids, area, statistics)
    assert roi_id > 0
    assert db.roi(roi_id)["area"] > 0
    assert db.roi_statistics(roi_id)
    db.delete_entity("case", case_id)
    assert db.dataset(dataset_id) is None
    assert source.exists()
    assert db.ensure_defaults() is None


def test_vtu_import(tmp_path):
    source = tmp_path / "volume.vtu"
    mesh = pv.ImageData(dimensions=(3, 3, 3)).cast_to_unstructured_grid()
    mesh.point_data["Velocity"] = np.ones((mesh.n_points, 3))
    mesh.save(source)
    loaded, meta = inspect_dataset(source)
    assert loaded.n_points == mesh.n_points
    velocity = next(field for field in meta["fields"] if field["name"] == "Velocity")
    assert velocity["components"] == 3
    assert velocity["minimum"] == velocity["maximum"]


def test_bilingual_resources():
    assert translate("zh", "camera_link") == "相机联动"
    assert translate("en", "camera_link") == "Camera link"
    assert translate("zh", "imported", count=2) == "已导入 2 个数据集"
    assert LAYOUTS["3×3"] == (3, 3)
    assert LAYOUTS["3×4"] == (3, 4)
    assert LAYOUTS["5×5"] == (5, 5)


def test_standard_streamline_generation():
    mesh = pv.ImageData(dimensions=(10, 7, 5), spacing=(0.5, 0.5, 0.5)).cast_to_unstructured_grid()
    mesh.point_data["velocity"] = np.tile([1.0, 0.1, 0.0], (mesh.n_points, 1))
    assert vector_fields(mesh) == [("velocity", "point")]
    options = StreamlineOptions(
        field="velocity", association="point", seed_count=30, direction="both",
        initial_step_length=0.2, max_length=20.0, terminal_speed=1e-12,
        tube_radius=0.0, line_width=1.0, context_opacity=0.18,
    )
    stream_mesh, scalar_name = generate_streamlines(mesh, options)
    assert stream_mesh.n_cells > 0
    assert scalar_name == "velocity magnitude"
    assert scalar_name in stream_mesh.point_data


def test_camera_sync_uses_model_relative_coordinates():
    class Camera:
        def __init__(self, position, focal, scale):
            self.position = position; self.focal_point = focal; self.parallel_scale = scale
            self.up = (0.0, 1.0, 0.0); self.view_angle = 30.0; self.parallel = 0
        def GetParallelProjection(self): return self.parallel
        def SetParallelProjection(self, value): self.parallel = value

    class Plotter:
        def __init__(self, camera): self.camera = camera
        def reset_camera_clipping_range(self): pass
        def render(self): pass

    mesh_a = pv.Cube(center=(0, 0, 0), x_length=2, y_length=2, z_length=2)
    mesh_b = pv.Cube(center=(1000, -500, 200), x_length=20, y_length=20, z_length=20)
    camera_a = Camera((4, 2, 3), (0.2, 0, 0), 1.5)
    camera_b = Camera((0, 0, 1), (0, 0, 0), 1.0)
    source = SimpleNamespace(state=SimpleNamespace(mesh=mesh_a), plotter=Plotter(camera_a))
    target = SimpleNamespace(state=SimpleNamespace(mesh=mesh_b), plotter=Plotter(camera_b))
    sync_camera_relative(source, target)
    source_offset = (np.asarray(camera_a.focal_point) - np.asarray(mesh_a.center)) / mesh_a.length
    target_offset = (np.asarray(camera_b.focal_point) - np.asarray(mesh_b.center)) / mesh_b.length
    source_view = (np.asarray(camera_a.position) - np.asarray(camera_a.focal_point)) / mesh_a.length
    target_view = (np.asarray(camera_b.position) - np.asarray(camera_b.focal_point)) / mesh_b.length
    assert np.allclose(target_offset, source_offset)
    assert np.allclose(target_view, source_view)
