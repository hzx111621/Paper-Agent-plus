from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Request

from src.repositories.sessions.sqlite import SQLiteSessionRepository
from src.services.sessions import SessionError


JsonObject = dict[str, Any]
_PASSWORD_ITERATIONS = 260_000
_TOKEN_DAYS = 30
_USERNAME_PATTERN = re.compile(r"^[^\s]{2,32}$")
_PASSWORD_RESET_CODES: dict[str, tuple[str, float]] = {}


def register(repo: SQLiteSessionRepository, username: str, password: str) -> JsonObject:
    """注册本地账户，并返回登录后前端需要保存的令牌。"""

    normalized_username = _validate_credentials(username, password)
    if repo.find_user_by_username(normalized_username) is not None:
        raise SessionError("用户名已经存在", 409)

    first_user = repo.user_count() == 0
    user_id = f"user_{secrets.token_hex(12)}"
    try:
        repo.register_user(user_id, normalized_username, _hash_password(password))
    except Exception as exc:
        # 中文说明：数据库的唯一约束是最后一道保险，避免并发注册时出现重复用户名。
        if "UNIQUE" in str(exc).upper():
            raise SessionError("用户名已经存在", 409) from exc
        raise

    if first_user:
        # 中文说明：项目在加入登录前已经可能生成过 local-user 会话，首次注册时把它们接到新账户下。
        repo.claim_legacy_sessions(user_id)
    return _login_payload(repo, user_id, normalized_username)


def login(repo: SQLiteSessionRepository, username: str, password: str) -> JsonObject:
    """验证用户名和密码，并签发新的登录令牌。"""

    normalized_username = _validate_credentials(username, password)
    user = repo.find_user_by_username(normalized_username)
    if user is None or not _verify_password(password, str(user.get("password_hash") or "")):
        raise SessionError("用户名或密码错误", 401)
    return _login_payload(repo, str(user["id"]), str(user["username"]))


def current_user(repo: SQLiteSessionRepository, request: Request) -> JsonObject:
    """从 Authorization 请求头读取当前账户，没有有效登录时返回 401。"""

    authorization = request.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise SessionError("请先登录", 401)
    user = repo.find_user_by_token(_token_hash(token.strip()))
    if user is None:
        raise SessionError("登录已失效，请重新登录", 401)
    return {"id": str(user["id"]), "username": str(user["username"])}


def logout(repo: SQLiteSessionRepository, request: Request) -> None:
    """撤销当前登录令牌。"""

    authorization = request.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() == "bearer" and token.strip():
        repo.revoke_auth_token(_token_hash(token.strip()))


def change_password(repo: SQLiteSessionRepository, request: Request, old_password: str, new_password: str) -> JsonObject:
    """验证旧密码后修改当前账户密码，并注销其他设备。"""

    user = current_user(repo, request)
    record = repo.find_user_by_username(str(user["username"]))
    if record is None or not _verify_password(old_password, str(record.get("password_hash") or "")):
        raise SessionError("原密码不正确", 400)
    _validate_credentials(str(user["username"]), new_password)
    authorization = request.headers.get("Authorization", "")
    _, _, token = authorization.partition(" ")
    repo.update_password_for_user(str(user["id"]), _hash_password(new_password))
    repo.revoke_other_auth_tokens(str(user["id"]), _token_hash(token.strip()))
    return {"changed": True}


def delete_account(repo: SQLiteSessionRepository, request: Request, password: str) -> JsonObject:
    """验证密码后删除当前账户及其全部数据。"""

    user = current_user(repo, request)
    record = repo.find_user_by_username(str(user["username"]))
    if record is None or not _verify_password(password, str(record.get("password_hash") or "")):
        raise SessionError("密码不正确，账户未删除", 400)
    repo.delete_account_for_user(str(user["id"]))
    return {"deleted": True}


def create_password_reset_code(repo: SQLiteSessionRepository, username: str) -> JsonObject:
    """为本地账户生成一次性找回密码验证码。"""

    normalized = str(username or "").strip()
    user = repo.find_user_by_username(normalized)
    if user is None:
        raise SessionError("用户名不存在", 404)
    code = secrets.token_urlsafe(8)
    _PASSWORD_RESET_CODES[normalized] = (code, time.time() + 600)
    # 中文说明：这是单机版，没有邮箱或短信服务，所以暂时把验证码直接返回给页面显示。
    return {"username": normalized, "reset_code": code, "expires_in": 600}


def reset_password(repo: SQLiteSessionRepository, username: str, code: str, new_password: str) -> JsonObject:
    """使用十分钟内有效的一次性验证码重置密码。"""

    normalized = str(username or "").strip()
    stored = _PASSWORD_RESET_CODES.get(normalized)
    if not stored or stored[0] != str(code or "").strip() or stored[1] < time.time():
        raise SessionError("找回密码验证码无效或已过期", 400)
    user = repo.find_user_by_username(normalized)
    if user is None:
        raise SessionError("用户名不存在", 404)
    _validate_credentials(normalized, new_password)
    repo.update_password_for_user(str(user["id"]), _hash_password(new_password))
    repo.backend.delete_auth_tokens_for_user(str(user["id"]))
    _PASSWORD_RESET_CODES.pop(normalized, None)
    return {"reset": True}


def _login_payload(repo: SQLiteSessionRepository, user_id: str, username: str) -> JsonObject:
    """创建一个只返回给当前浏览器的明文令牌。"""

    token = secrets.token_urlsafe(32)
    expires_at = (datetime.now(timezone.utc) + timedelta(days=_TOKEN_DAYS)).isoformat()
    repo.issue_auth_token(_token_hash(token), user_id, expires_at)
    return {
        "token": token,
        "expires_at": expires_at,
        "user": {"id": user_id, "username": username},
    }


def _validate_credentials(username: str, password: str) -> str:
    """统一校验账户输入，避免注册和登录对同一字段使用不同规则。"""

    normalized_username = str(username or "").strip()
    if not _USERNAME_PATTERN.fullmatch(normalized_username):
        raise SessionError("用户名长度需为 2 到 32 个字符，且不能包含空格", 400)
    if not isinstance(password, str) or not 6 <= len(password) <= 128:
        raise SessionError("密码长度需为 6 到 128 个字符", 400)
    return normalized_username


def _hash_password(password: str) -> str:
    """使用标准库 PBKDF2 加盐保存密码，避免明文落盘。"""

    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PASSWORD_ITERATIONS)
    return "$".join(
        (
            "pbkdf2_sha256",
            str(_PASSWORD_ITERATIONS),
            base64.urlsafe_b64encode(salt).decode("ascii"),
            base64.urlsafe_b64encode(digest).decode("ascii"),
        )
    )


def _verify_password(password: str, encoded: str) -> bool:
    """按保存的参数重新计算密码哈希，并使用恒定时间比较结果。"""

    try:
        algorithm, iterations_text, salt_text, digest_text = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations_text)
        salt = base64.urlsafe_b64decode(salt_text.encode("ascii"))
        expected = base64.urlsafe_b64decode(digest_text.encode("ascii"))
    except (ValueError, TypeError):
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


def _token_hash(token: str) -> str:
    """数据库只保存令牌哈希，即使数据库被读取也不会直接暴露登录令牌。"""

    return hashlib.sha256(token.encode("utf-8")).hexdigest()
