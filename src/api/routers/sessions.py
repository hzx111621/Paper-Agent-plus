from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse

from src.repositories.sessions.sqlite import SQLiteSessionRepository
from src.services.auth import current_user
from src.services.session_runs import SessionRunService, encode_sse
from src.services.sessions import (
    MessageHandler,
    create_session,
    delete_session,
    fetch_thread,
    list_sessions,
    submit_message,
)
from src.services.library import export_session, list_session_papers, update_paper, upload_pdf


JsonObject = dict[str, Any]


def create_sessions_router(
    repo: SQLiteSessionRepository,
    message_handler: MessageHandler | None = None,
    run_service: SessionRunService | None = None,
) -> APIRouter:
    """创建会话相关的 FastAPI 路由。

    中文说明：
    该模块只负责请求解析与响应适配，不直接承载会话落库、run 编排和
    SSE 事件管理逻辑，核心业务统一委托给 service 层处理。
    """

    router = APIRouter(prefix="/api/sessions", tags=["sessions"])
    resolved_run_service = run_service or SessionRunService(repo=repo, message_handler=message_handler)

    @router.get("")
    async def get_sessions(request: Request) -> JsonObject:
        """返回会话列表。"""

        user = current_user(repo, request)
        return list_sessions(
            repo,
            user_id=str(user["id"]),
            include_archived=str(request.query_params.get("include_archived") or "").lower() in {"1", "true", "yes"},
        )

    @router.post("", status_code=201)
    async def post_session(request: Request) -> JsonObject:
        """创建一个新会话。"""

        user = current_user(repo, request)
        return create_session(repo, await _json_body(request), user_id=str(user["id"]))

    @router.get("/{session_key}/webui-thread")
    async def get_thread(session_key: str, request: Request) -> JsonObject:
        """读取指定会话的完整线程快照。"""

        user = current_user(repo, request)
        return fetch_thread(repo, session_key, user_id=str(user["id"]))

    @router.get("/{session_key}/papers")
    async def get_session_papers(session_key: str, request: Request) -> JsonObject:
        """返回当前会话的论文结果列表。"""

        user = current_user(repo, request)
        params = request.query_params
        return list_session_papers(
            repo,
            session_key,
            str(user["id"]),
            query=str(params.get("query") or ""),
            sort=str(params.get("sort") or "relevance"),
            descending=str(params.get("direction") or "desc").lower() != "asc",
            page=int(params.get("page") or 1),
            page_size=int(params.get("page_size") or 20),
        )

    @router.patch("/{session_key}/papers/{paper_id}")
    async def patch_session_paper(session_key: str, paper_id: str, request: Request) -> JsonObject:
        """更新当前账户对论文的收藏、重点、忽略、标签和笔记。"""

        user = current_user(repo, request)
        repo.get_for_user(session_key, str(user["id"]))
        return {"paper": update_paper(repo, str(user["id"]), paper_id, await _json_body(request))}

    @router.post("/{session_key}/uploads")
    async def upload_session_pdf(session_key: str, request: Request) -> JsonObject:
        """接收 base64 PDF，避免单机版额外依赖 multipart 组件。"""

        user = current_user(repo, request)
        body = await _json_body(request)
        return upload_pdf(
            repo,
            session_key,
            str(user["id"]),
            str(body.get("filename") or "paper.pdf"),
            str(body.get("content_base64") or ""),
        )

    @router.get("/{session_key}/artifacts/{artifact_id}")
    async def get_artifact(session_key: str, artifact_id: str, request: Request) -> FileResponse:
        """提供指定会话产物文件的预览或下载。

        中文说明：
        产物文件路径由仓储层做安全校验，只有位于该会话目录内的文件才会被返回；
        记录不存在、路径越界或文件已被删除时统一返回 404。
        """

        user = current_user(repo, request)
        repo.get_for_user(session_key, str(user["id"]))
        file_path = repo.read_artifact_path(session_key, artifact_id)
        if file_path is None:
            raise HTTPException(status_code=404, detail="artifact not found or unavailable")
        return FileResponse(
            file_path,
            filename=file_path.name,
            content_disposition_type="inline",
            media_type=_artifact_media_type(file_path),
        )

    @router.get("/{session_key}/exports/{export_format}")
    async def export_session_file(session_key: str, export_format: str, request: Request) -> Response:
        """导出综述或引用文件。"""

        user = current_user(repo, request)
        content, filename, media_type = export_session(repo, session_key, str(user["id"]), export_format)
        return Response(
            content=content,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @router.post("/{session_key}/reanalyze/{paper_id}", status_code=202)
    async def reanalyze_paper(session_key: str, paper_id: str, request: Request) -> JsonObject:
        """让工作流只围绕指定论文重新分析。"""

        user = current_user(repo, request)
        paper = repo.get_user_paper(str(user["id"]), paper_id)
        if paper is None:
            raise HTTPException(status_code=404, detail="paper not found")
        repo.get_for_user(session_key, str(user["id"]))
        body = await _json_body(request)
        body["content"] = str(body.get("content") or f"重新分析论文：{paper.get('title') or paper_id}")
        body["constraints"] = {"local_papers": [paper], "local_only": True}
        return await resolved_run_service.start_run(session_key, body)

    @router.patch("/{session_key}/rename")
    async def rename_session(session_key: str, request: Request) -> JsonObject:
        """修改会话标题。"""

        user = current_user(repo, request)
        body = await _json_body(request)
        return {"session": repo.rename_for_user(session_key, str(user["id"]), str(body.get("title") or ""))}

    @router.patch("/{session_key}/archive")
    async def archive_session(session_key: str, request: Request) -> JsonObject:
        """归档或恢复会话。"""

        user = current_user(repo, request)
        body = await _json_body(request)
        archived = body.get("archived", True) is not False
        return {"session": repo.archive_for_user(session_key, str(user["id"]), archived)}

    @router.delete("/{session_key}")
    async def remove_session(session_key: str, request: Request) -> JsonObject:
        """删除指定会话。"""

        user = current_user(repo, request)
        return delete_session(repo, session_key, user_id=str(user["id"]))

    @router.post("/{session_key}/messages")
    async def post_message(session_key: str, request: Request) -> JsonObject:
        """兼容旧版同步消息接口，提交后等待整次运行完成。"""

        body = await _json_body(request)
        user = current_user(repo, request)
        repo.get_for_user(session_key, str(user["id"]))
        # 旧接口会等待完整工作流结束，放到线程里执行，避免卡住其他异步请求。
        return await asyncio.to_thread(submit_message, repo, session_key, body, message_handler=message_handler)

    @router.post("/{session_key}/runs", status_code=202)
    async def post_run(session_key: str, request: Request) -> JsonObject:
        """创建一次新的后台运行，并返回对应的流地址。"""

        user = current_user(repo, request)
        repo.get_for_user(session_key, str(user["id"]))
        return await resolved_run_service.start_run(session_key, await _json_body(request))

    @router.post("/{session_key}/runs/{run_id}/cancel", status_code=202)
    async def cancel_run(session_key: str, run_id: str, request: Request) -> JsonObject:
        """接收用户主动停止请求，后台任务会在当前等待点尽快结束。"""

        user = current_user(repo, request)
        repo.get_for_user(session_key, str(user["id"]))
        return await resolved_run_service.cancel_run(session_key, run_id)

    @router.post("/{session_key}/runs/{run_id}/pause", status_code=202)
    async def pause_run(session_key: str, run_id: str, request: Request) -> JsonObject:
        """暂停当前运行；暂停后的会话可以用继续按钮恢复。"""

        user = current_user(repo, request)
        repo.get_for_user(session_key, str(user["id"]))
        return await resolved_run_service.cancel_run(session_key, run_id)

    @router.get("/{session_key}/runs/{run_id}/stream")
    async def stream_run(session_key: str, run_id: str, request: Request) -> StreamingResponse:
        """以 SSE 形式持续返回指定 run 的实时事件。"""

        user = current_user(repo, request)
        repo.get_for_user(session_key, str(user["id"]))

        async def _event_generator():
            """持续输出 SSE 事件，同时定期发送心跳避免连接被中间层回收。"""

            event_iterator = resolved_run_service.stream_events(session_key, run_id)
            while True:
                try:
                    event = await anext(event_iterator)
                except StopAsyncIteration:
                    break
                yield encode_sse(event)
            yield ": stream closed\n\n"

        return StreamingResponse(
            _event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    return router


async def _json_body(request: Request) -> JsonObject:
    """读取 JSON body；空 body 按空对象处理。"""

    try:
        payload = await request.json()
    except Exception:
        return {}
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ValueError("request body must be a JSON object")
    return payload


def _artifact_media_type(file_path: Path) -> str:
    """根据文件后缀返回适合浏览器预览的媒体类型。

    中文说明：
    Markdown 和 JSON 可以在新标签页里直接查看，其他类型走通用的二进制下载。
    """

    suffix = file_path.suffix.lower()
    if suffix == ".md":
        return "text/markdown; charset=utf-8"
    if suffix == ".json":
        return "application/json; charset=utf-8"
    return "application/octet-stream"
