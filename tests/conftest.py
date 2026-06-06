"""pytest 根 conftest：确保项目根在 sys.path（db.tools 等模块可导入）。"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
