# CFD VisualDB

CFD 仿真数据管理与多视图可视分析桌面原型。当前版本专注于可运行的核心骨架，不尝试复制完整 ParaView Pipeline。

> 隐私与数据安全：仓库只包含程序代码，不包含 SQLite 数据库、数据库备份、导入报告或 VTU/VTP 仿真结果。请勿提交含患者信息的真实数据。应用仅在本机数据库中保存源文件绝对路径和元数据，不会自动复制或移动源文件。

## 已实现

- SQLite 层级：Project → Group → Case → Dataset → ROI。
- VTU/VTP 导入；数据库仅保存绝对路径、SHA-256、网格规模和字段元数据，不保存大型 BLOB。
- 自动识别网格类型、points/cells、PointData/CellData、分量数和数值范围；向量范围按模长统计。
- 1×1、2×2、4×4、5×4 独立视图；每个视图选择 Case、Dataset、Field 和 Surface/Wireframe。
- 旋转、缩放、平移、标量云图；Camera/Field 联动；全局、独立、手动 Color Range 与 Color Bar 同步入口。
- 可见 Cell 手动选择 ROI；保存源文件哈希与 Cell IDs，并计算面积、面积加权均值、均值、中位数、P5/P10/P25/P75/P90/P95、Min/Max/STD。
- 内置 Python Console；暴露 `app.database`、`app.viewer`、`app.roi`、`app.case`。
- 顶部可随时切换中文/English，选择会自动保存并在下次启动时恢复。
- 标准 VTK RK45 流线：三分量速度场、内部 Cell-center seeds、双向/正向/反向积分、步长、长度、终止速度、线管半径和背景透明度。
- 顶部颜色范围支持全局、独立和手动最小/最大值；手动范围同时用于当前云图或流线色标。
- 流线默认采用 ParaView 风格的 1 像素原生线；线宽可调，管径保持 0 时不会生成粗圆管。
- 视图背景可选白色、深色、浅灰、黑色或自定义颜色，并自动调整文字对比度。
- 导入时使用 Project → Group → Case 三级目标选择器，可在窗口内新建 Group/Case。
- 可删除 Project、Group、Case、Dataset 或 ROI；只删除数据库记录，不删除磁盘源文件。
- ROI 采用明确工作流：点击带编号的目标视图 → 开始框选 → 清除或保存并计算 → 在树中选择 ROI 查看统计表。
- ROI 框选支持跨角度累积：添加、去除、替换、撤销上一步和清除全部；按 R 暂停旋转后再继续框选，黄色高亮不会丢失。
- 多视图布局包括 1×1、2×2、3×3、3×4、4×4、5×4 和 5×5。
- 为 Slice/Clip/Threshold/Contour/Streamline/Glyph 保留基于 PyVista/VTK 的扩展层位置。

## 启动

在 PowerShell 中：

```powershell
Set-Location D:\CFD_VisualDB
python run.py
```

项目自带 `.venv` 独立运行环境。即使终端显示 Conda `(base)`，`python run.py` 也会自动切换到正确的项目解释器。也可以直接双击 `start.cmd` 启动。

首次进入已有默认层级 `Default Project / Ungrouped / Default Case`。也可以在左侧新建层级，选中目标 Case 后导入 `.vtu` 或 `.vtp`。

## ROI 操作

先在一个视图中载入 Dataset，再点击左侧 **Select ROI in active view**。选择可见网格单元后输入名称即可保存。ROI 会绑定导入时的源文件 SHA-256；源文件发生变化时，后续版本可据此拒绝错误复用或提示重新映射。

## 开发与验证

```powershell
python -m pip install -e .
python -m pytest -q
python run.py --smoke-test
```

数据库默认位于 `D:\CFD_VisualDB\data\cfd_visualdb.sqlite3`。可通过环境变量 `CFD_VISUALDB_DB` 指向其他位置。

## 下一阶段扩展点

建议按顺序补充：数据集时间序列/PVD、ROI 编辑（Grow/Shrink/Connected/Invert）、筛选查询、统计结果表格与 CSV 导出、Slice/Clip/Threshold/Contour，最后再加入 Streamline/Glyph 和更完整的 Python 命令 API。
