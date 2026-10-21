from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from src.repositories.sessions.sqlite import SQLiteSessionRepository
from src.services.auth import current_user
from src.services.library import delete_paper, list_library, update_paper
from src.repositories.settings.json import SettingsRepository
from src.services.paper_reading import reading_payload, run_paper_reading
from src.services.sessions import SessionError
from src.paper_retrieval.service import PaperSearchService

JsonObject = dict[str, Any]


def create_library_router(repo: SQLiteSessionRepository, settings: SettingsRepository) -> APIRouter:
    """创建个人论文库接口。"""

    router = APIRouter(prefix="/api/library", tags=["library"])
    # 记录正在处理的论文，重复点击直接提示，避免同一张图重复扣费。
    active: set[tuple[str, str]] = set()

    @router.post("/search")
    async def search_image_papers(request: Request) -> JsonObject:
        """为一图总结直接搜索论文，返回候选供用户选择，不启动整套综述流程。"""
        user_id = str(current_user(repo, request)["id"])
        query = str((await _json_body(request)).get("query") or "").strip()
        if not query or len(query) > 500:
            raise SessionError("请输入不超过 500 字的论文标题或关键词。", 400)
        result = await PaperSearchService().async_search(
            query=query, sources=["openalex", "arxiv", "semantic_scholar"], limit=10,
        )
        if not result.papers and result.errors:
            raise SessionError("在线论文来源暂时无法访问，请重试或直接上传 PDF。", 502)
        # 候选保存到当前账户，后续下载全文和生成图片仍会检查论文所属账户。
        return {"papers": [repo.save_user_paper(user_id, paper.to_dict()) for paper in result.papers], "unavailable_sources": list(result.errors)}

    # 部分来源使用 https://… 作为论文编号，因此允许编号包含斜杠。
    @router.get("/{paper_id:path}/reading")
    async def get_reading(paper_id: str, request: Request) -> JsonObject:
        """查看当前用户的精读和一图总结结果。"""
        user_id = str(current_user(repo, request)["id"])
        return {**reading_payload(repo, settings, user_id, paper_id), "running": (user_id, paper_id) in active}

    @router.post("/{paper_id:path}/reading/{action}")
    async def generate_reading(paper_id: str, action: str, request: Request) -> JsonObject:
        """明确点击按钮后才调用模型。"""
        user_id = str(current_user(repo, request)["id"])
        if action not in {"reading", "image"}:
            raise SessionError("未知阅读操作。", 400)
        key = (user_id, paper_id)
        if key in active:
            raise SessionError("这篇论文正在处理，请等待完成。", 409)
        active.add(key)
        try:
            return await run_paper_reading(repo, settings, user_id, paper_id, action)
        finally:
            active.discard(key)

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

    @router.patch("/{paper_id:path}")
    async def patch_library_paper(paper_id: str, request: Request) -> JsonObject:
        """更新个人论文库中的论文。"""

        user = current_user(repo, request)
        return {"paper": update_paper(repo, str(user["id"]), paper_id, await _json_body(request))}

    @router.delete("/{paper_id:path}")
    async def remove_library_paper(paper_id: str, request: Request) -> JsonObject:
        """删除资料库论文与其个人精读结果。"""

        user = current_user(repo, request)
        return delete_paper(repo, str(user["id"]), paper_id)

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
