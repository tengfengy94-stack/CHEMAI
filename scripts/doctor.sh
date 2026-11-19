#!/usr/bin/env bash
# 开工体检：每章开始前跑一次，全绿才开工。
# 用法：bash scripts/doctor.sh
# 退出码：0 = 全绿；1 = 有红项
set -u
cd "$(dirname "$0")/.." || exit 1
ROOT=$(pwd)
LOG_DIR="${TMPDIR:-/tmp}"

GREEN='\033[32m'; RED='\033[31m'; YELLOW='\033[33m'; NC='\033[0m'
fail=0
ok()   { printf "${GREEN}[OK]${NC}   %s\n" "$1"; }
bad()  { printf "${RED}[FAIL]${NC} %s\n" "$1"; fail=1; }
warn() { printf "${YELLOW}[WARN]${NC} %s\n" "$1"; }

# Python 一律用项目根目录的 .venv，不退回系统解释器
if [ -x "$ROOT/.venv/Scripts/python.exe" ]; then
  PY="$ROOT/.venv/Scripts/python.exe"
elif [ -x "$ROOT/.venv/bin/python" ]; then
  PY="$ROOT/.venv/bin/python"
else
  PY=""
fi

echo "== 环境 =="
if command -v node >/dev/null 2>&1; then
  v=$(node -v | tr -d 'v')
  lowest=$(printf '%s\n20.19\n' "$v" | sort -V | head -1)
  if [ "$lowest" = "20.19" ]; then ok "Node $v"; else bad "Node $v（需要 ≥ 20.19）"; fi
else
  bad "Node 未安装"
fi

if [ -n "$PY" ]; then
  py=$("$PY" -V 2>&1 | awk '{print $2}')
  case "$py" in 3.12*) ok "Python $py（.venv）" ;; *) bad "Python $py（.venv 需要 3.12）" ;; esac
else
  bad "没有 .venv（在项目根目录用 Python 3.12 建：python -m venv .venv）"
fi

if command -v git >/dev/null 2>&1; then ok "Git $(git --version | awk '{print $3}')"; else bad "Git 未安装"; fi

echo
echo "== 依赖 =="
if [ -f backend/requirements.txt ] && [ -n "$PY" ]; then
  installed=$("$PY" -m pip list --format=freeze 2>/dev/null | cut -d= -f1 | tr 'A-Z' 'a-z' | tr '-' '_')
  missing=""
  while IFS= read -r line || [ -n "$line" ]; do
    line=$(printf '%s' "$line" | tr -d '\r')
    case "$line" in ""|\#*|-*) continue ;; esac
    name=$(printf '%s' "$line" | sed 's/[^A-Za-z0-9_.-].*//' | tr 'A-Z' 'a-z' | tr '-' '_')
    [ -z "$name" ] && continue
    if ! printf '%s\n' "$installed" | grep -qx "$name"; then missing="$missing $name"; fi
  done < backend/requirements.txt
  if [ -z "$missing" ]; then
    ok "requirements.txt 里的依赖已安装"
  else
    bad "缺少依赖:$missing（.venv/Scripts/python.exe -m pip install -r backend/requirements.txt）"
  fi
elif [ -f backend/requirements.txt ]; then
  bad "有 requirements.txt 但没有 .venv，无法核对依赖"
elif [ -d backend ]; then
  bad "还没有 backend/requirements.txt"
else
  bad "还没有 backend/（第 02 章建）"
fi

if [ -d frontend/node_modules ]; then ok "前端依赖已安装"; else bad "frontend/node_modules 不存在（cd frontend && npm install）"; fi

echo
echo "== 数据 =="
if [ -f chemai.db ]; then ok "数据库文件存在（chemai.db）"; else bad "chemai.db 不存在（执行迁移后会建）"; fi

echo
echo "== 测试 =="
if [ -n "$PY" ] && [ -d backend/tests ] && [ -n "$(ls -A backend/tests 2>/dev/null)" ]; then
  if (cd backend && "$PY" -m pytest -q >"$LOG_DIR/chemai_doctor_pytest.log" 2>&1); then
    ok "pytest 全绿"
  else
    bad "pytest 有失败，日志见 $LOG_DIR/chemai_doctor_pytest.log"
  fi
else
  bad "还没有测试（backend/tests/）"
fi

echo
echo "== 后端健康 =="
health_ok() { curl -fsS --max-time 2 http://127.0.0.1:8000/api/health >/dev/null 2>&1; }
if [ -z "$PY" ] || [ ! -d backend ]; then
  bad "后端还不存在，无法检查 /api/health"
elif health_ok; then
  # dev.sh 起的后端已经在 8000 上，直接用它，不再另起一个
  ok "GET /api/health 正常（使用已在运行的后端）"
else
  ( cd backend && exec "$PY" -m uvicorn app.main:app --port 8000 >"$LOG_DIR/chemai_doctor_uvicorn.log" 2>&1 ) &
  pid=$!
  health=0
  for _ in $(seq 1 20); do
    sleep 0.5
    if health_ok; then health=1; break; fi
  done
  # Git Bash 下 $! 是 MSYS 的进程号，要换成 Windows 进程号才能用 taskkill
  if [ -r "/proc/$pid/winpid" ]; then
    taskkill //T //F //PID "$(cat "/proc/$pid/winpid")" >/dev/null 2>&1
  else
    kill "$pid" 2>/dev/null
  fi
  wait "$pid" 2>/dev/null
  if [ "$health" = "1" ]; then ok "GET /api/health 正常"; else bad "后端起不来或 /api/health 非 200，日志见 $LOG_DIR/chemai_doctor_uvicorn.log"; fi
fi

echo
if [ "$fail" -ne 0 ]; then
  printf "${RED}体检未通过，先修再开工。${NC}\n"
  exit 1
fi
printf "${GREEN}体检通过，可以开工。${NC}\n"
