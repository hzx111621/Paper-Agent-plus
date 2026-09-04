from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from src.repositories.sessions.sqlite import SQLiteSessionRepository
from src.services.auth import (
    change_password,
    create_password_reset_code,
    current_user,
    delete_account,
    login,
    logout,
    register,
    reset_password,
)
from src.services.sessions import SessionError


JsonObject = dict[str, Any]


def create_auth_router(repo: SQLiteSessionRepository) -> APIRouter:
    """创建本地账户注册、登录、当前用户和注销接口。"""

    router = APIRouter(prefix="/api/auth", tags=["auth"])

    @router.post("/register", status_code=201)
    async def register_account(request: Request) -> JsonObject:
        """注册账户并自动登录。"""

        body = await _json_body(request)
        return register(repo, str(body.get("username") or ""), body.get("password"))

    @router.post("/login")
    async def login_account(request: Request) -> JsonObject:
        """登录已有账户。"""

        body = await _json_body(request)
        return login(repo, str(body.get("username") or ""), body.get("password"))

    @router.get("/me")
    async def get_current_account(request: Request) -> JsonObject:
        """返回当前登录账户。"""

        return {"user": current_user(repo, request)}

    @router.post("/logout")
    async def logout_account(request: Request) -> JsonObject:
        """注销当前浏览器令牌。"""

        current_user(repo, request)
        logout(repo, request)
        return {"logged_out": True}

    @router.post("/password")
    async def update_password(request: Request) -> JsonObject:
        """修改当前账户密码。"""

        body = await _json_body(request)
        return change_password(repo, request, str(body.get("old_password") or ""), str(body.get("new_password") or ""))

    @router.delete("/account")
    async def remove_account(request: Request) -> JsonObject:
        """删除当前账户。"""

        body = await _json_body(request)
        result = delete_account(repo, request, str(body.get("password") or ""))
        logout(repo, request)
        return result

    @router.get("/tokens")
    async def list_tokens(request: Request) -> JsonObject:
        """查看登录设备摘要。"""

        user = current_user(repo, request)
        return {"tokens": repo.list_auth_tokens_for_user(str(user["id"]))}

    @router.delete("/tokens/others")
    async def remove_other_tokens(request: Request) -> JsonObject:
        """撤销当前账户在其他设备上的令牌。"""

        user = current_user(repo, request)
        _, _, token = request.headers.get("Authorization", "").partition(" ")
        import hashlib

        repo.revoke_other_auth_tokens(str(user["id"]), hashlib.sha256(token.strip().encode()).hexdigest())
        return {"revoked": True}

    @router.post("/forgot-password")
    async def forgot_password(request: Request) -> JsonObject:
        """生成本地版找回密码验证码。"""

        body = await _json_body(request)
        return create_password_reset_code(repo, str(body.get("username") or ""))

    @router.post("/reset-password")
    async def reset_account_password(request: Request) -> JsonObject:
        """使用找回密码验证码重置密码。"""

        body = await _json_body(request)
        return reset_password(
            repo,
            str(body.get("username") or ""),
            str(body.get("reset_code") or ""),
            str(body.get("new_password") or ""),
        )

    return router


async def _json_body(request: Request) -> JsonObject:
    """读取 JSON 请求体，空请求体按空字典处理。"""

    try:
        payload = await request.json()
    except Exception:
        return {}
    if not isinstance(payload, dict):
        raise SessionError("request body must be a JSON object", 400)
    return payload
