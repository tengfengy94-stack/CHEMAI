#!/usr/bin/env bash
# 同时启动前后端。Ctrl+C 一起停。
# 用法：bash scripts/dev.sh
# 启动前先执行数据库迁移（结构只由迁移建，不在启动时自动建表）。
set -u
cd "$(dirname "$0")/.." || exit 1
ROOT=$(pwd)

if [ -x "$ROOT/.venv/Scripts/python.exe" ]; then
  PY="$ROOT/.venv/Scripts/python.exe"
elif [ -x "$ROOT/.venv/bin/python" ]; then
  PY="$ROOT/.venv/bin/python"
else
  echo "没有 .venv：先在项目根目录用 Python 3.12 建虚拟环境（python -m venv .venv）"
  exit 1
fi

port_busy() { curl -s -o /dev/null --max-time 1 "http://localhost:$1/"; }
for port in 8000 5173; do
  if port_busy "$port"; then
    echo "端口 $port 已被占用：先运行 bash scripts/stop-dev.sh 停掉旧的前后端，再启动。"
    exit 1
  fi
done

echo "== 数据库迁移 =="
( cd backend && "$PY" -m alembic upgrade head ) || { echo "迁移失败，没有启动服务。"; exit 1; }
echo

echo "后端  http://127.0.0.1:8000   （健康检查 /api/health）"
echo "前端  http://localhost:5173"
echo

( cd backend && exec "$PY" -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000 ) &
BACK=$!

( cd frontend && exec npm run dev ) &
FRONT=$!

# Git Bash 下 $! 是 MSYS 进程号，taskkill 要用 Windows 进程号，并带 /T 连子进程一起停
stop() {
  local pid=$1
  if [ -r "/proc/$pid/winpid" ]; then
    taskkill //T //F //PID "$(cat "/proc/$pid/winpid")" >/dev/null 2>&1
  else
    kill "$pid" 2>/dev/null
  fi
}
cleanup() {
  stop "$BACK"
  stop "$FRONT"
  # uvicorn --reload 的工作进程、vite 不一定挂在上面两棵进程树下，按命令行兜底再清一遍
  bash "$ROOT/scripts/stop-dev.sh" >/dev/null 2>&1
  wait 2>/dev/null
  exit 0
}
trap cleanup INT TERM

wait
