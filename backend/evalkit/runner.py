"""评测批量运行：建库、起服务、登录、逐条读 SSE、查轨迹、判定与报告。"""
import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

from app import config
from evalkit.cases import CaseValidationError, EvalCase, load_cases
from evalkit.db import EvalFixture, build_eval_database, eval_database_path
from evalkit.judge import CaseResult, judge_case, summarize
from evalkit.references import build_reference_index


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _log_tail(path: Path, limit: int = 4000) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return text[-limit:]


def _start_server(database_url: str, smoke: bool, port: int | None = None) -> tuple:
    chosen = port or _free_port()
    env = os.environ.copy()
    env["CHEMAI_EVAL_MODE"] = "1"
    env["CHEMAI_DATABASE_URL"] = database_url
    if smoke:
        env["CHEMAI_FAKE_MODEL"] = "1"
        env["CHEMAI_FAKE_MODEL_DELAY"] = "0"

    log = tempfile.NamedTemporaryFile(
        mode="w+", suffix=".log", prefix="chemai-eval-", delete=False
    )
    log_path = Path(log.name)
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(chosen),
            "--log-level",
            "warning",
        ],
        cwd=str(config.BACKEND_DIR),
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    base = f"http://127.0.0.1:{chosen}"
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        if process.poll() is not None:
            text = _log_tail(log_path)
            log.close()
            raise RuntimeError(f"评测服务启动失败：\n{text}")
        try:
            response = httpx.get(f"{base}/api/health", timeout=2)
            if response.status_code == 200:
                return base, process, log, log_path
        except httpx.HTTPError:
            pass
        time.sleep(0.3)
    process.terminate()
    log.close()
    raise RuntimeError(f"评测服务 40 秒内没有就绪，日志：\n{_log_tail(log_path)}")


def _stop_server(process, log) -> None:
    try:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)
    except (subprocess.TimeoutExpired, OSError):
        try:
            process.kill()
            process.wait(timeout=5)
        except (subprocess.TimeoutExpired, OSError):
            pass
    finally:
        log.close()


def _login(client: httpx.Client, username: str, password: str) -> str:
    response = client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("success"):
        raise RuntimeError(f"登录失败：{payload.get('error')}")
    return payload["data"]["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _teacher_class(client: httpx.Client, token: str, expected: int | None) -> int:
    response = client.get("/api/classes", headers=_auth(token))
    response.raise_for_status()
    payload = response.json()
    items = (payload.get("data") or {}).get("items") or []
    ids = [item["id"] for item in items]
    if expected is not None and expected in ids:
        return expected
    if ids:
        return ids[0]
    raise RuntimeError("教师账号没有带班，无法运行班级概况评测")


def _stream_case(
    client: httpx.Client,
    case: EvalCase,
    token: str,
    conversation_id: str,
) -> tuple[str, list[str], str]:
    body = {
        "message": case.message,
        "scene": case.scene,
        "conversation_id": conversation_id,
    }
    if case.class_id is not None:
        body["class_id"] = case.class_id

    deadline = time.monotonic() + case.timeout
    try:
        with client.stream(
            "POST",
            "/api/chat/stream",
            json=body,
            headers=_auth(token),
            timeout=httpx.Timeout(case.timeout, connect=10.0),
        ) as response:
            if response.status_code != 200:
                return "", [], f"HTTP {response.status_code}"
            answer = ""
            tools: list[str] = []
            ended = False
            current = None
            for line in response.iter_lines():
                if time.monotonic() > deadline:
                    return answer, tools, "超时"
                if not line:
                    continue
                if line.startswith("event:"):
                    current = line.split(":", 1)[1].strip()
                elif line.startswith("data:"):
                    try:
                        payload = json.loads(line.split(":", 1)[1].strip())
                    except json.JSONDecodeError:
                        payload = {}
                    if current == "tool":
                        tools.append(payload.get("name") or "")
                    elif current == "text":
                        answer += payload.get("delta") or ""
                    elif current == "end":
                        ended = True
            if not ended:
                return answer, tools, "流中断"
            return answer, tools, "ok"
    except httpx.TimeoutException:
        return "", [], "超时"
    except httpx.HTTPError as exc:
        return "", [], f"请求失败：{exc}"


def _fetch_trace(
    client: httpx.Client,
    token: str,
    conversation_id: str,
    class_id: int | None,
) -> list[dict]:
    params = {"conversation_id": conversation_id}
    if class_id is not None:
        params["class_id"] = class_id
    response = client.get("/api/eval/trace", headers=_auth(token), params=params)
    if response.status_code == 404:
        return []
    response.raise_for_status()
    payload = response.json()
    return (payload.get("data") or {}).get("items") or []


def _run_case(
    client: httpx.Client,
    case: EvalCase,
    token: str,
    conversation_id: str,
    index: dict,
) -> CaseResult:
    answer, tools, status = _stream_case(client, case, token, conversation_id)
    if status != "ok":
        return CaseResult(
            case.id,
            case.category,
            False,
            "内容不对",
            f"执行失败：{status}",
            {"actual_tools": tools, "answer": answer[:2000], "status": status},
        )
    try:
        trace = _fetch_trace(client, token, conversation_id, case.class_id)
    except httpx.HTTPError as exc:
        return CaseResult(
            case.id,
            case.category,
            False,
            "内容不对",
            f"读取工具轨迹失败：{exc}",
            {"actual_tools": tools, "answer": answer[:2000]},
        )
    result = judge_case(case, answer, trace, index)
    result.evidence.update(
        {
            "status": status,
            "actual_tools": tools,
            "answer": answer[:2000],
            "trace": trace,
        }
    )
    return result


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(config.PROJECT_ROOT),
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def _report_base(fixture: EvalFixture, mode: str, started: str) -> dict:
    model = "fake" if mode == "smoke" else config.model_config().model_name
    return {
        "mode": mode,
        "model_backend": model,
        "started_at": started,
        "database": fixture.database_url,
        "commit": _git_commit(),
    }


def _print_category(summary: dict) -> None:
    labels = {"tool": "工具选择", "answer": "答案质量", "safety": "安全"}
    for key in ("tool", "answer", "safety"):
        item = summary["categories"][key]
        print(f"{labels[key]:<6} {item['passed']}/{item['total']} 分 {item['score']}")


def _run_formal(
    client: httpx.Client,
    cases: list[EvalCase],
    fixture: EvalFixture,
    index: dict,
    run_id: str,
    verbose: bool = False,
) -> dict:
    started = datetime.now(timezone.utc).isoformat()
    tokens = {
        username: _login(client, username, fixture.password)
        for username in set(case.username for case in cases)
    }
    teacher_case = next((case for case in cases if case.account == "teacher"), None)
    if teacher_case is not None:
        expected = teacher_case.class_id
        resolved = _teacher_class(client, tokens[teacher_case.username], expected)
        if expected is not None and expected != resolved:
            raise RuntimeError(f"班级编号对不上：用例 {expected}，接口 {resolved}")
        for case in cases:
            if case.account == "teacher" and case.class_id != resolved:
                raise RuntimeError(f"教师用例 {case.id} 的班级编号不一致")

    results: list[CaseResult] = []
    for case in cases:
        conversation_id = f"{run_id}-{case.id}"
        result = _run_case(
            client,
            case,
            tokens[case.username],
            conversation_id,
            index,
        )
        results.append(result)
        mark = "PASS" if result.passed else f"FAIL[{result.failure_type}]"
        print(f"{mark:<18} {case.id} {result.detail}".rstrip())
        if verbose and not result.passed:
            print(json.dumps(result.evidence, ensure_ascii=False, indent=2))

    summary = summarize(results)
    report = {
        **_report_base(fixture, "real", started),
        "run_id": run_id,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        **summary,
        "cases": [
            {
                "id": result.case_id,
                "category": result.category,
                "passed": result.passed,
                "failure_type": result.failure_type,
                "detail": result.detail,
                "evidence": result.evidence,
            }
            for result in results
        ],
    }
    _print_category(summary)
    print(
        f"总分 {summary['score']}/{summary['total']}，"
        f"安全 {summary['categories']['safety']['passed']}/10 -> "
        f"{'通过' if summary['passed'] else '不通过'}"
    )
    return report


def _run_smoke(
    client: httpx.Client,
    cases: list[EvalCase],
    fixture: EvalFixture,
    index: dict,
    run_id: str,
) -> dict:
    started = datetime.now(timezone.utc).isoformat()
    selected = [case for case in cases if case.id in {"tool_student_profile", "tool_due_reviews"}]
    if len(selected) != 2:
        raise RuntimeError("冒烟用例缺失")
    token = _login(client, fixture.users["student"], fixture.password)
    results = []
    histories = []
    for case in selected:
        conversation_id = f"{run_id}-{case.id}"
        result = _run_case(client, case, token, conversation_id, index)
        results.append(result)
        history = client.get(
            "/api/chat/history",
            headers=_auth(token),
            params={"conversation_id": conversation_id},
        )
        history.raise_for_status()
        texts = [
            item.get("content")
            for item in (history.json().get("data") or {}).get("items") or []
        ]
        histories.append((case.message, texts))

    stream_ok = all(result.evidence.get("status") == "ok" for result in results)
    trace_ok = all(
        any(entry.get("tool") in {"student_profile", "due_reviews"} for entry in result.evidence.get("trace") or [])
        for result in results
    )
    messages = [message for message, _ in histories]
    isolation_ok = all(
        message in texts
        and all(other not in texts for other in messages if other != message)
        for message, texts in histories
    )
    checks = {
        "login": bool(token),
        "stream": stream_ok,
        "trace": trace_ok,
        "isolation": isolation_ok,
    }
    report = {
        **_report_base(fixture, "smoke", started),
        "run_id": run_id,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "formal_score": False,
        "checks": checks,
        "passed": all(checks.values()),
        "cases": [
            {
                "id": result.case_id,
                "category": result.category,
                "passed": result.passed,
                "failure_type": result.failure_type,
                "detail": result.detail,
                "evidence": result.evidence,
            }
            for result in results
        ],
    }
    for name, ok in checks.items():
        print(f"{'PASS' if ok else 'FAIL'} 冒烟检查：{name}")
    print("冒烟结果，不是正式分数。")
    return report


def _write_report(report: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="化学助教三十条评测")
    parser.add_argument("--smoke", action="store_true", help="只跑假模型冒烟，不输出正式分数")
    parser.add_argument("--verbose", action="store_true", help="失败用例打印完整证据")
    parser.add_argument("--references", action="store_true", help="导出评测库真实引用清单后退出")
    parser.add_argument("--database", type=Path, default=None, help="评测库路径")
    parser.add_argument("--report", type=Path, default=None, help="JSON 报告路径")
    parser.add_argument("--port", type=int, default=None, help="评测服务端口")
    args = parser.parse_args(argv)

    fixture = build_eval_database(args.database or eval_database_path())
    index = build_reference_index(fixture)
    if args.references:
        print(json.dumps(index, ensure_ascii=False, indent=2))
        return 0

    if not args.smoke and config.should_use_fake_model():
        print("正式评测需要真模型：请在 backend/.env 配置模型密钥，或加 --smoke 只跑冒烟。")
        return 2
    if not args.smoke:
        try:
            config.model_config()
        except config.ModelConfigError as exc:
            print(f"正式评测的模型配置不完整：{exc}")
            return 2

    try:
        cases = load_cases(index)
    except CaseValidationError as exc:
        print(f"用例不成立，停止评测：{exc}")
        return 2
    run_id = "r" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    started = time.monotonic()
    base, process, log, log_path = _start_server(
        fixture.database_url, smoke=args.smoke, port=args.port
    )
    try:
        with httpx.Client(base_url=base, timeout=70.0) as client:
            if args.smoke:
                report = _run_smoke(client, cases, fixture, index, run_id)
            else:
                report = _run_formal(
                    client, cases, fixture, index, run_id, verbose=args.verbose
                )
    except Exception as exc:  # noqa: BLE001 - 评测失败要给出日志尾部
        print(f"评测中断：{exc}")
        print(f"服务日志：\n{_log_tail(log_path)}")
        return 2
    finally:
        _stop_server(process, log)

    report["duration_seconds"] = round(time.monotonic() - started, 2)
    report_path = args.report or (config.PROJECT_ROOT / "eval-report.json")
    _write_report(report, report_path)
    print(f"报告：{report_path}")
    return 0 if report["passed"] else 1
