"""统一信封：所有接口成功失败都返回 {success, data, error}。"""
from typing import Any

from fastapi.responses import JSONResponse


def ok(data: Any, status_code: int = 200) -> JSONResponse:
    return JSONResponse({"success": True, "data": data, "error": None}, status_code=status_code)


def fail(message: str, status_code: int) -> JSONResponse:
    return JSONResponse({"success": False, "data": None, "error": message}, status_code=status_code)
