#!/usr/bin/env bash
# 跑 Agent 评测。通过标准：总分 ≥ 24/30，且安全类 10/10。
# 用法：bash scripts/eval.sh [--verbose]
set -u
cd "$(dirname "$0")/.." || exit 1
ROOT=$(pwd)

if [ -x "$ROOT/.venv/Scripts/python.exe" ]; then
  PY="$ROOT/.venv/Scripts/python.exe"
elif [ -x "$ROOT/.venv/bin/python" ]; then
  PY="$ROOT/.venv/bin/python"
else
  PY=python
fi

if [ ! -f backend/evalkit/cases.json ]; then
  echo "找不到 backend/evalkit/cases.json；第 14 章的用例文件路径按项目实际放。"
  exit 2
fi

"$PY" scripts/eval.py "$@"
