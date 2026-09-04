from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from src.repositories.sessions.sqlite import SQLiteSessionRepository
from src.services.auth import current_user
from src.services.library import list_library, update_paper

JsonObject = dict[str, Any]


def create_library_router(repo: SQLiteSessionRepository) -> APIRouter:
    """创建个人论文库接口。"""

    router = APIRouter(prefix="/api/library", tags=["library"])

    @router.get("")
    async def get_library(request: Request) -> JsonObject:
        """分页读取当前账户保存的论文。"""

        user = current_user(repo, request)
        params = request.query_params
        return list_library(
            repo,
            str(user["id"]),
            query=str(params.get("query") or ""),
            tag=str(params.get("tag") or ""),
            favorite_only=params.get("favorite_only"),
            focused_only=params.get("focused_only"),
            ignored=params.get("ignored"),
            sort=str(params.get("sort") or "updated_at"),
            direction=str(params.get("direction") or "desc"),
            page=int(params.get("page") or 1),
            page_size=int(params.get("page_size") or 20),
        )

    @router.patch("/{paper_id}")
    async def patch_library_paper(paper_id: str, request: Request) -> JsonObject:
        """更新个人论文库中的论文。"""

        user = current_user(repo, request)
        return {"paper": update_paper(repo, str(user["id"]), paper_id, await _json_body(request))}

    return router


async def _json_body(request: Request) -> JsonObject:
    """读取 JSON 请求体。"""

    try:
        payload = await request.json()
    except Exception:
        return {}
    if not isinstance(payload, dict):
        raise ValueError("request body must be a JSON object")
    return payload
