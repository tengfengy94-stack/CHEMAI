"""运行器：合成 SSE 的正常结束、半截断流、只有心跳。"""
import json

import httpx

from evalkit.cases import EvalCase
from evalkit.runner import _fetch_trace, _stream_case

CASE = EvalCase(
    id="case-1",
    category="tool",
    account="student",
    username="s1",
    message="我哪块弱",
    expect_tool="student_profile",
)


def _client(body: bytes, status: int = 200) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status,
            content=body,
            headers={"content-type": "text/event-stream"},
        )

    return httpx.Client(transport=httpx.MockTransport(handler), base_url="http://test")


def test_stream_collects_tool_text_and_end():
    body = (
        'event: tool\ndata: {"name":"student_profile","label":"正在查"}\n\n'
        'event: text\ndata: {"delta":"你最弱的是氧化还原"}\n\n'
        "event: end\ndata: {}\n\n"
    ).encode()
    client = _client(body)
    try:
        answer, tools, status = _stream_case(client, CASE, "token", "case-1")
    finally:
        client.close()
    assert status == "ok"
    assert tools == ["student_profile"]
    assert answer == "你最弱的是氧化还原"


def test_stream_without_end_is_interrupted():
    body = 'event: text\ndata: {"delta":"说到一半"}\n\n'.encode()
    client = _client(body)
    try:
        answer, tools, status = _stream_case(client, CASE, "token", "case-1")
    finally:
        client.close()
    assert status == "流中断"
    assert answer == "说到一半"


def test_stream_with_only_heartbeat_is_interrupted():
    client = _client(b": ping\n\n")
    try:
        answer, tools, status = _stream_case(client, CASE, "token", "case-1")
    finally:
        client.close()
    assert status == "流中断"
    assert answer == ""
    assert tools == []


def test_stream_http_error_is_reported():
    client = _client(b'{"success":false}', status=500)
    try:
        _, _, status = _stream_case(client, CASE, "token", "case-1")
    finally:
        client.close()
    assert status == "HTTP 500"


def test_trace_404_means_empty():
    client = _client(b'{"success":false,"data":null,"error":"none"}', status=404)
    try:
        assert _fetch_trace(client, "token", "case-1", None) == []
    finally:
        client.close()
