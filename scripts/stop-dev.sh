#!/usr/bin/env bash
# 停掉本项目的前后端（8000 后端、5173 前端），重启前用。
# 用法：bash scripts/stop-dev.sh
# 只停属于本项目的进程（判断规则见 stop_dev.py），别的程序占着端口不动它、只提示。
# 退出码：0 = 两个端口都空了；1 = 还有端口被占。
set -u
cd "$(dirname "$0")/.." || exit 1

if [ "${OS:-}" = "Windows_NT" ]; then
  "$(pwd)/.venv/Scripts/python.exe" -I "$(cygpath -w "$(pwd)/scripts/stop_dev.py")" "$(cygpath -w "$(pwd)")"
else
  pkill -f "uvicorn app.main:app" 2>/dev/null
  pkill -f "$(pwd)/frontend/node_modules/.*vite" 2>/dev/null
fi

busy=0
for port in 8000 5173; do
  for _ in 1 2 3 4 5 6; do
    curl -s -o /dev/null --max-time 1 "http://localhost:$port/" || break
    sleep 0.5
  done
  if curl -s -o /dev/null --max-time 1 "http://localhost:$port/"; then
    echo "端口 $port 还被占用（可能是别的程序），没有动它。"
    busy=1
  fi
done
[ "$busy" -eq 0 ] && echo "前后端已停止，8000 和 5173 空闲。"
exit "$busy"
