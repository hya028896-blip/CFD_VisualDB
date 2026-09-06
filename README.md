# CFD VisualDB

CFD VisualDB 是一个面向 CFD 仿真结果的桌面数据管理与多视图可视分析原型。它使用数据库组织 Project、Group、Case、Dataset 和 ROI，并直接读取本机的 VTU/VTP 文件进行三维显示、对比、流线分析与局部统计。

项目的定位不是复刻完整的 ParaView，而是在 VTK/PyVista 可视化能力之上，提供更适合批量病例管理和多模型比较的工作流。

> **隐私与数据安全**：本仓库只包含程序代码，不包含 SQLite 数据库、数据库备份、导入报告或 VTU/VTP 仿真结果。请勿提交含患者信息的真实数据。应用只在本机数据库中保存源文件绝对路径和元数据，不会自动复制、移动或删除源文件。

## 主要功能

- **分层数据管理**：Project → Group → Case → Dataset → ROI。
- **VTU/VTP 自动解析**：读取网格类型、点/单元数量、PointData/CellData 字段、分量数、数值范围与 SHA-256。
- **多视图比较**：支持 1×1、2×2、3×3、3×4、4×4、5×4 和 5×5 布局。
- **基础三维可视化**：旋转、缩放、平移、Surface、Wireframe 和标量云图。
- **联动控制**：相机联动、字段联动、色标联动，以及全局/独立/手动 Color Range。
- **流线分析**：标准 VTK RK45 积分，支持三分量速度场、种子密度、方向、步长、长度和终止速度等设置。
- **ROI 局部统计**：多角度累积选择、添加/去除/替换、撤销、保存与统计；ROI 绑定源文件哈希和 Cell IDs。
- **统计指标**：面积、面积加权均值、均值、中位数、P5/P10/P25/P75/P90/P95、Min、Max 和 STD。
- **中英文界面**：可在运行时切换中文或 English。
- **Python 扩展入口**：预留 `app.database`、`app.viewer`、`app.roi` 和 `app.case` 内部 API。

数据库只保存元数据和文件路径，不把大型仿真文件作为 BLOB 写入 SQLite。

## 技术栈

- Python 3.11+
- PySide6
- PyVista / VTK
- SQLite
- NumPy

## 安装与启动

### 1. 获取代码

```powershell
git clone https://github.com/hya028896-blip/CFD_VisualDB.git
Set-Location CFD_VisualDB
```

### 2. 创建虚拟环境并安装依赖

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .
```

### 3. 启动软件

```powershell
python run.py
```

在 Windows 上也可以双击 `start.cmd`。如果项目目录中存在 `.venv`，`run.py` 会优先使用该环境。

## 基本使用流程

1. 在左侧创建或选择 Project、Group 和 Case。
2. 点击导入按钮选择 `.vtu` 或 `.vtp` 文件，并确认目标层级。
3. 将 Dataset 从左侧拖入右侧任意视图。
4. 在视图顶部选择字段、Surface/Wireframe 和色彩范围。
5. 按需启用相机、字段或色标联动，进行多病例对比。
6. 选择活动视图后使用 ROI 工具，多角度累积选取关注区域并计算统计结果。
7. 对包含三分量速度场的数据集启用流线，调整种子密度和积分参数。

## 项目结构

```text
CFD_VisualDB/
├─ src/cfd_visualdb/          应用程序源码
│  ├─ database.py             SQLite 数据访问层
│  ├─ importers.py            VTU/VTP 元数据解析
│  ├─ viewer.py               多视图与 VTK 渲染
│  ├─ streamlines.py          流线计算与设置
│  ├─ roi.py                  ROI 统计逻辑
│  ├─ main_window.py          主界面与交互编排
│  └─ i18n.py                 中英文文本
├─ scripts/                   批量元数据导入工具
├─ tests/                     核心自动化测试
├─ data/                      本地数据库目录，不提交真实内容
├─ run.py                     启动入口
├─ start.cmd                  Windows 快捷启动
└─ pyproject.toml             项目与依赖配置
```

## Python API 入口

内置 Python Console 中预留了以下对象：

```python
app.database
app.viewer
app.roi
app.case
```

当前版本只实现了其中的部分接口，后续会逐步形成稳定的脚本 API。

## 开发与验证

```powershell
python -m pip install -e .
python -m pytest -q
python run.py --smoke-test
```

数据库默认位于 `data/cfd_visualdb.sqlite3`。也可以通过环境变量 `CFD_VISUALDB_DB` 指向其他本地位置。

## 后续计划

- 数据集时间序列与 PVD 支持
- ROI Grow/Shrink、Connected、Invert 与边界优化
- 数据库筛选、查询和统计结果导出
- Slice、Clip、Threshold 和 Contour
- Glyph 与更完整的流线种子工具
- 更稳定、覆盖面更广的 Python API

## 当前状态

这是一个可运行的早期原型，适合功能验证和工作流迭代。用于科研生产环境前，建议进一步补充大数据性能测试、异常恢复、数据迁移和结果复现验证。

## 许可证

本项目采用 [MIT License](LICENSE)。任何人都可以使用、复制、修改、合并、发布和再分发本软件，也可以用于商业用途，但必须保留原版权声明和许可证文本。

---

**English summary:** CFD VisualDB is a Python desktop prototype for organizing VTU/VTP simulation datasets and comparing them in synchronized multi-view VTK/PyVista renderers. It includes metadata indexing, scalar visualization, streamlines, persistent ROI selection and regional statistics while keeping large simulation files outside the SQLite database and Git repository.
