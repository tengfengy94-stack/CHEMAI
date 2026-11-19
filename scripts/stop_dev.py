"""停掉本项目的前后端（8000 后端、5173 前端）。由 scripts/stop-dev.sh 调用。

只停属于本项目的进程：
  1. 命令行带 "uvicorn app.main:app" 或本项目 frontend\\node_modules\\...vite 的进程，连同整棵子进程树；
  2. uvicorn --reload 的工作进程命令行里只有 "spawn_main(parent_pid=N)"，看不出是谁的。
     端口 8000/5173 的登记占用者 N 如果是上面那类进程、或已经退出，就把 parent_pid=N 的子进程一起停。
别的程序占着端口不动它。

用法：python stop_dev.py <项目根目录>
"""
import csv
import io
import os
import re
import subprocess
import sys

PORTS = (8000, 5173)


def windows_processes():
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,CommandLine"
         " | ConvertTo-Csv -NoTypeInformation"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=True,
    ).stdout
    procs = {}
    for row in csv.DictReader(io.StringIO(out)):
        procs[int(row["ProcessId"])] = (int(row["ParentProcessId"] or 0), row["CommandLine"] or "")
    return procs


def port_owners():
    out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, errors="replace").stdout
    owners = set()
    for line in out.splitlines():
        if "LISTENING" in line and re.search(r":(%s)\s" % "|".join(map(str, PORTS)), line):
            owners.add(int(line.split()[-1]))
    return owners


def main(root):
    vite_marker = os.path.join(root, "frontend", "node_modules").lower()

    def ours(cmd):
        c = cmd.lower()
        return "uvicorn app.main:app" in c or (vite_marker in c and "vite" in c)

    procs = windows_processes()
    targets = {pid for pid, (_, cmd) in procs.items() if ours(cmd)}

    for owner in port_owners():
        if owner not in procs or ours(procs[owner][1]):
            if owner in procs:
                targets.add(owner)
            marker = f"spawn_main(parent_pid={owner},"
            targets |= {pid for pid, (_, cmd) in procs.items() if marker in cmd}

    queue = list(targets)
    while queue:
        parent = queue.pop()
        for pid, (ppid, _) in procs.items():
            if ppid == parent and pid not in targets:
                targets.add(pid)
                queue.append(pid)

    targets.discard(os.getpid())
    for pid in targets:
        subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1]))
