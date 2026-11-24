"""评测入口：python scripts/eval.py [--smoke] [--references]。

check.sh 第 14、15 章固定调用这个路径。
"""
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from evalkit.runner import main  # noqa: E402 - 必须先加 backend 到 sys.path


if __name__ == "__main__":
    raise SystemExit(main())
