from pathlib import Path
import os
import sys

PROJECT_ROOT = Path(__file__).resolve().parent
VENV_PYTHON = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"

# Keep launching reliable even when the terminal has Conda (base) activated.
# The project interpreter owns all GUI/VTK dependencies and is re-used here.
if VENV_PYTHON.exists() and Path(sys.executable).resolve() != VENV_PYTHON.resolve():
    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), str(Path(__file__).resolve()), *sys.argv[1:]])

sys.path.insert(0, str(PROJECT_ROOT / "src"))

from cfd_visualdb.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
