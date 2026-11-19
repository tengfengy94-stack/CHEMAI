"""登录凭证与权限判定：Argon2 密码哈希、JWT 双令牌、请求身份解析、三条归属判定。

token 的 payload 只带 sub 和 type，不带 role——角色与归属一律以查库结果为准
（design.md 决策 3、4）：管理员改掉某用户的角色，其已签发的 token 立即失去旧角色。
"""
import logging
import os
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, Request
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Class, User

ACCESS_MINUTES = 15
REFRESH_DAYS = 14
ALGORITHM = "HS256"
SECRET_ENV = "CHEMAI_JWT_SECRET"
_LOCAL_DEFAULT_SECRET = "chemai-local-dev-secret"

_warned_about_secret = False

password_hasher = PasswordHash.recommended()


def jwt_secret() -> str:
    """密钥取环境变量；用本地默认值时警告一次，提醒部署者配置。"""
    global _warned_about_secret
    secret = os.environ.get(SECRET_ENV)
    if secret:
        return secret
    if not _warned_about_secret:
        _warned_about_secret = True
        logging.getLogger("chemai").warning(
            "未设置 %s，正在使用本地默认密钥；对外部署前必须配置", SECRET_ENV
        )
    return _LOCAL_DEFAULT_SECRET


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return password_hasher.verify(password, password_hash)


# 用户名不存在时也对它跑一次校验：Argon2 很慢，跳过校验的响应快得多，
# 时序差异会泄露"这个用户名不存在"。预置一条哑哈希，失败路径耗时对齐。
_DUMMY_HASH = password_hasher.hash("chemai-dummy-account-not-real")


def dummy_verify(password: str) -> None:
    """只为消耗一次 Argon2 校验的时间，结果不读。"""
    password_hasher.verify(password, _DUMMY_HASH)


def create_token(username: str, token_type: str) -> str:
    if token_type == "access":
        lifetime = timedelta(minutes=ACCESS_MINUTES)
    elif token_type == "refresh":
        lifetime = timedelta(days=REFRESH_DAYS)
    else:
        raise ValueError(f"未知的令牌类型：{token_type}")
    payload = {
        "sub": username,
        "type": token_type,
        "exp": datetime.now(timezone.utc) + lifetime,
    }
    return jwt.encode(payload, jwt_secret(), algorithm=ALGORITHM)


def decode_token(token: str, expected_type: str) -> dict:
    """验签、验有效期、核对类型；任何一步不过都抛 jwt.InvalidTokenError。"""
    payload = jwt.decode(token, jwt_secret(), algorithms=[ALGORITHM])
    if payload.get("type") != expected_type:
        raise jwt.InvalidTokenError("令牌类型不对")
    return payload


class AuthRequiredError(Exception):
    """请求没带有效凭证，main.py 统一转成 401 中文信封。"""


class AccessDeniedError(Exception):
    """归属判定不过关，main.py 统一转成 403 中文信封。"""


def get_session(request: Request) -> Session:
    with request.app.state.session_factory() as session:
        yield session


def get_current_user(request: Request, session: Session = Depends(get_session)) -> User:
    """三层权限的第一层（登录校验）：验签后查库取当前用户，失败一律 401。

    角色从查库结果读，不从 token 读。
    """
    auth_header = request.headers.get("Authorization", "")
    scheme, _, token = auth_header.partition(" ")
    token = token.strip()
    message = "登录凭证无效或已过期，请重新登录"
    if scheme.lower() != "bearer" or not token:
        raise AuthRequiredError("请先登录")
    try:
        payload = decode_token(token, "access")
    except jwt.InvalidTokenError:
        raise AuthRequiredError(message) from None
    username = payload.get("sub")
    if not username:
        raise AuthRequiredError(message)
    user = session.scalar(select(User).where(User.username == username))
    if user is None:
        raise AuthRequiredError(message)
    return user


# ---- 三条权限规则的归属判定（design.md 决策 4 第二层）。 ----
# 管理员全通（设计/01 §6.3）；判定函数先立着，接口随各章节接线。


def require_owner(created_by: str, user: User) -> None:
    """规则① 只能改自己建的。"""
    if user.role == "admin":
        return
    if created_by != user.username:
        raise AccessDeniedError("不是这道题的创建者")


def require_self_data(owner_username: str, user: User) -> None:
    """规则② 只能看自己的。"""
    if user.role == "admin":
        return
    if owner_username != user.username:
        raise AccessDeniedError("只能看自己的数据")


def require_own_class(class_id: int, user: User, session: Session) -> None:
    """规则③ 只能看自己带的班。"""
    if user.role == "admin":
        return
    if user.role != "teacher":
        raise AccessDeniedError("只能看自己带的班的数据")
    owns = session.scalar(select(Class.id).where(Class.id == class_id, Class.teacher_id == user.id))
    if owns is None:
        raise AccessDeniedError("只能看自己带的班的数据")
