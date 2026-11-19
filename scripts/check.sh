#!/usr/bin/env bash
# 章节验收：bash scripts/check.sh 05
# 只查行为，不查文件位置——文件放在哪由 AI 决定。
# 退出码：0 = 通过；1 = 有检查项失败；2 = 用法错误或章号未实现
set -u
cd "$(dirname "$0")/.." || exit 1
ROOT=$(pwd)
LOG_DIR="${TMPDIR:-/tmp}"

# Python 一律用项目根目录的 .venv
if [ -x "$ROOT/.venv/Scripts/python.exe" ]; then
  PY="$ROOT/.venv/Scripts/python.exe"
elif [ -x "$ROOT/.venv/bin/python" ]; then
  PY="$ROOT/.venv/bin/python"
else
  echo "没有 .venv：先在项目根目录用 Python 3.12 建虚拟环境（python -m venv .venv）"
  exit 1
fi

N="${1:-}"
if [ -z "$N" ]; then
  echo "用法：bash scripts/check.sh <章号>"
  echo "已实现的章号：02 03 04 05 06 07 08 09 10 11 12 13 14 15"
  exit 2
fi

GREEN='\033[32m'; RED='\033[31m'; NC='\033[0m'
fail=0
step=0
ok()  { printf "${GREEN}[OK]${NC}   %s\n" "$1"; }
bad() { printf "${RED}[FAIL]${NC} %s\n" "$1"; fail=1; }

# 每项在子 shell 里跑（cd 不串到下一项），每项单独一份日志
run() {
  step=$((step + 1))
  log="$LOG_DIR/chemai_check_${N}_${step}.log"
  if ( cd "$ROOT" && eval "$1" ) >"$log" 2>&1; then
    ok "$2"
  else
    bad "$2（日志 $log）"
  fi
}

echo "== 第 $N 章验收 =="

case "$N" in
  02)
    run "cd backend && \"$PY\" -m pytest -q" "全量测试"
    run "curl -fsS --max-time 5 http://127.0.0.1:8000/api/health" "后端健康检查（需先用 bash scripts/dev.sh 起服务）"
    ;;
  03|04|05|06|07|08|09|10|11|12|13)
    run "cd backend && \"$PY\" -m pytest -q" "全量测试"
    ;;
  14)
    run "cd backend && \"$PY\" -m pytest -q" "全量测试"
    run "\"$PY\" scripts/eval.py" "30 条评测通过（≥24/30 且安全 10/10）"
    ;;
  15)
    run "cd backend && \"$PY\" -m pytest -q" "全量测试"
    run "\"$PY\" scripts/eval.py" "评测通过"
    if [ -n "$(git tag -l v1.0.0)" ]; then ok "版本标记 v1.0.0"; else bad "缺少 tag v1.0.0"; fi
    ;;
  *)
    echo "还没有第 $N 章的检查项。让 AI 在 scripts/check.sh 的 case 里补一条。"
    exit 2
    ;;
esac

echo
if [ "$fail" -ne 0 ]; then
  printf "${RED}本章未通过，不要往下走。${NC}\n"
  exit 1
fi
printf "${GREEN}本章通过。${NC}\n"
