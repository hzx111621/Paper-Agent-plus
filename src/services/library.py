from __future__ import annotations

import base64
import html
import json
import re
import uuid
from pathlib import Path
from typing import Any

from src.repositories.sessions.sqlite import SQLiteSessionRepository
from src.services.sessions import SessionError
from src.utils.read_utils.pdf_parsers import get_pdf_parser


JsonObject = dict[str, Any]


def list_session_papers(
    repo: SQLiteSessionRepository,
    session_key: str,
    user_id: str,
    *,
    query: str = "",
    sort: str = "relevance",
    descending: bool = True,
    page: int = 1,
    page_size: int = 20,
) -> JsonObject:
    """读取会话最新检索结果，并合并当前账户的收藏状态。"""

    session = repo.get_for_user(session_key, user_id)
    papers = _papers_from_latest_ranked_artifact(repo, session)
    result: list[JsonObject] = []
    for item in papers:
        saved = repo.save_user_paper(user_id, item)
        if query.strip() and not _matches(saved, query):
            continue
        result.append(saved)

    result.sort(key=lambda item: _sort_value(item, sort), reverse=descending)
    total = len(result)
    safe_page = max(1, int(page))
    safe_size = min(100, max(1, int(page_size)))
    start = (safe_page - 1) * safe_size
    return {
        "papers": result[start : start + safe_size],
        "total": total,
        "page": safe_page,
        "page_size": safe_size,
        "pages": (total + safe_size - 1) // safe_size,
        "stats": _session_stats(repo, session),
    }


def list_library(repo: SQLiteSessionRepository, user_id: str, **filters: Any) -> JsonObject:
    """读取当前账户的个人论文库。"""

    papers, total = repo.list_user_papers(
        user_id,
        query=str(filters.get("query") or ""),
        tag=str(filters.get("tag") or ""),
        favorite_only=_as_bool(filters.get("favorite_only")),
        focused_only=_as_bool(filters.get("focused_only")),
        ignored=_optional_bool(filters.get("ignored")),
        sort=str(filters.get("sort") or "updated_at"),
        descending=not str(filters.get("direction") or "desc").lower().startswith("asc"),
        page=max(1, int(filters.get("page") or 1)),
        page_size=min(100, max(1, int(filters.get("page_size") or 20))),
    )
    page = max(1, int(filters.get("page") or 1))
    page_size = min(100, max(1, int(filters.get("page_size") or 20)))
    return {
        "papers": papers,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
    }


def update_paper(repo: SQLiteSessionRepository, user_id: str, paper_id: str, patch: JsonObject) -> JsonObject:
    """更新论文的重点、忽略、收藏、标签和笔记。"""

    return repo.update_user_paper(user_id, paper_id, patch)


def upload_pdf(
    repo: SQLiteSessionRepository,
    session_key: str,
    user_id: str,
    filename: str,
    content_base64: str,
) -> JsonObject:
    """保存并解析本地 PDF，生成可参与工作流的本地论文记录。"""

    repo.get_for_user(session_key, user_id)
    safe_name = Path(filename or "paper.pdf").name
    if not safe_name.lower().endswith(".pdf"):
        raise SessionError("只支持上传 PDF 文件", 400)
    try:
        content = base64.b64decode(content_base64, validate=True)
    except Exception as exc:
        raise SessionError("PDF 文件内容无效", 400) from exc
    if not content:
        raise SessionError("PDF 文件不能为空", 400)
    paper_id = f"local_{uuid.uuid4().hex}"
    relative_path = f"uploads/{paper_id}_{safe_name}"
    artifact = repo.write_artifact(
        session_key,
        "local_pdf",
        safe_name,
        content,
        relative_path=relative_path,
        metadata={"paper_id": paper_id, "format": "pdf", "origin": "upload"},
    )
    source_path = Path(str(artifact["path"]))
    parsed = get_pdf_parser().parse(source_path)
    text = "\n\n".join(page.text for page in parsed.pages).strip()
    title = _title_from_pdf_text(text) or Path(safe_name).stem
    paper = {
        "id": paper_id,
        "paperId": paper_id,
        "title": title,
        "authors": [],
        "year": None,
        "source": "local_upload",
        "abstract": text[:12000],
        "url": "",
        "pdf_url": f"/api/sessions/{session_key}/artifacts/{artifact['id']}",
        "metadata": {
            "local": True,
            "full_text": text,
            "filename": safe_name,
            "parse_warnings": parsed.warnings,
            "artifact_id": artifact["id"],
        },
    }
    saved = repo.save_user_paper(user_id, paper)
    repo.associate_paper_for_user(session_key, user_id, paper_id, "upload")
    return {"paper": saved, "artifact": artifact, "warnings": parsed.warnings}


def export_session(repo: SQLiteSessionRepository, session_key: str, user_id: str, export_format: str) -> tuple[bytes, str, str]:
    """导出最终综述或论文引用。"""

    session = repo.get_for_user(session_key, user_id)
    fmt = export_format.lower()
    papers = _papers_from_latest_ranked_artifact(repo, session)
    markdown = _latest_markdown(repo, session)
    if fmt in {"md", "markdown"}:
        return markdown.encode("utf-8"), "literature-review.md", "text/markdown; charset=utf-8"
    if fmt in {"bib", "bibtex"}:
        return _bibtex(papers).encode("utf-8"), "references.bib", "text/plain; charset=utf-8"
    if fmt in {"gb", "gbt", "gb7714"}:
        return _gb7714(papers).encode("utf-8"), "references-gbt7714.txt", "text/plain; charset=utf-8"
    if fmt == "apa":
        return _apa(papers).encode("utf-8"), "references-apa.txt", "text/plain; charset=utf-8"
    if fmt in {"doc", "docx", "word"}:
        body = html.escape(markdown).replace("\n", "<br>\n")
        document = f"<html><meta charset='utf-8'><body><pre>{body}</pre></body></html>"
        return document.encode("utf-8"), "literature-review.doc", "application/msword"
    if fmt == "pdf":
        return _simple_pdf(markdown), "literature-review.pdf", "application/pdf"
    raise SessionError("不支持的导出格式", 400)


def _papers_from_latest_ranked_artifact(repo: SQLiteSessionRepository, session: Any) -> list[JsonObject]:
    """从最新检索产物中取出带排序分数的论文。"""

    artifacts = [item for item in session.artifacts if item.get("artifact_type") == "paper_search_ranked_results"]
    if not artifacts:
        return []
    path = repo.read_artifact_path(session.key, str(artifacts[-1]["id"]))
    if path is None:
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    papers: list[JsonObject] = []
    for item in payload.get("scored_papers") or []:
        if not isinstance(item, dict):
            continue
        paper = dict(item.get("paper") or {})
        paper["relevance_score"] = item.get("score")
        papers.append(_normalise_paper(paper))
    if not papers:
        papers = [_normalise_paper(item) for item in payload.get("selected_papers") or [] if isinstance(item, dict)]
    return papers


def _session_stats(repo: SQLiteSessionRepository, session: Any) -> JsonObject:
    """汇总当前会话的检索、全文阅读和失败数量。"""

    stats = {"searched": 0, "selected": 0, "read_success": 0, "read_failed": 0}
    ranked = [item for item in session.artifacts if item.get("artifact_type") == "paper_search_manifest"]
    if ranked:
        path = repo.read_artifact_path(session.key, str(ranked[-1]["id"]))
        if path:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                stats["searched"] = int(payload.get("raw_paper_count") or 0)
                stats["selected"] = int(payload.get("selected_paper_count") or 0)
            except (OSError, ValueError, TypeError):
                pass
    read_manifests = [item for item in session.artifacts if item.get("artifact_type") == "paper_read_manifest"]
    if read_manifests:
        path = repo.read_artifact_path(session.key, str(read_manifests[-1]["id"]))
        if path:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                stats["read_success"] = int(payload.get("success_count") or payload.get("completed_count") or 0)
                stats["read_failed"] = int(payload.get("failed_count") or payload.get("failure_count") or 0)
            except (OSError, ValueError, TypeError):
                pass
    return stats


def _normalise_paper(paper: JsonObject) -> JsonObject:
    """把不同来源的字段整理成论文库统一字段。"""

    paper_id = str(paper.get("paperId") or paper.get("id") or paper.get("doi") or uuid.uuid4().hex)
    return {
        "id": paper_id,
        "paperId": paper_id,
        "title": str(paper.get("title") or "未命名论文"),
        "authors": [str(item) for item in paper.get("authors") or []],
        "year": paper.get("year") or None,
        "source": str(paper.get("source") or paper.get("venue") or ""),
        "abstract": str(paper.get("abstract") or ""),
        "url": str(paper.get("url") or ""),
        "pdf_url": str(paper.get("pdf_url") or ""),
        "doi": str(paper.get("doi") or ""),
        "relevance_score": paper.get("relevance_score"),
        "metadata": dict(paper.get("metadata") or {}),
    }


def _matches(paper: JsonObject, query: str) -> bool:
    """在标题、作者、来源和摘要里做简单的全文筛选。"""

    needle = query.strip().lower()
    haystack = " ".join(
        [str(paper.get("title") or ""), " ".join(paper.get("authors") or []), str(paper.get("source") or ""), str(paper.get("abstract") or "")]
    ).lower()
    return needle in haystack


def _sort_value(paper: JsonObject, sort: str) -> Any:
    """返回论文列表排序字段。"""

    if sort == "year":
        return int(paper.get("year") or 0)
    if sort in {"title", "source"}:
        return str(paper.get(sort) or "").lower()
    return float(paper.get("relevance_score") or 0)


def _latest_markdown(repo: SQLiteSessionRepository, session: Any) -> str:
    """读取最终综述 Markdown，没有时用会话助手消息拼接。"""

    artifacts = [item for item in session.artifacts if item.get("artifact_type") == "final_review"]
    if artifacts:
        path = repo.read_artifact_path(session.key, str(artifacts[-1]["id"]))
        if path is not None:
            try:
                return path.read_text(encoding="utf-8")
            except OSError:
                pass
    messages = [str(item.get("content") or "") for item in session.messages if item.get("role") == "assistant"]
    return "\n\n".join(messages).strip() or "当前会话还没有最终综述。\n"


def _bibtex(papers: list[JsonObject]) -> str:
    """生成基础 BibTeX 引用。"""

    blocks = []
    for index, paper in enumerate(papers, start=1):
        key = re.sub(r"[^a-zA-Z0-9]+", "_", str(paper.get("title") or f"paper_{index}"))[:40].strip("_") or f"paper_{index}"
        authors = " and ".join(paper.get("authors") or []) or "Unknown"
        blocks.append(
            "@article{%s,\n  title = {%s},\n  author = {%s},\n  year = {%s},\n  journal = {%s},\n  doi = {%s}\n}"
            % (key, paper.get("title", ""), authors, paper.get("year") or "", paper.get("source", ""), paper.get("doi", ""))
        )
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def _gb7714(papers: list[JsonObject]) -> str:
    """生成适合复制到中文论文中的 GB/T 7714 基础格式。"""

    lines = []
    for index, paper in enumerate(papers, start=1):
        authors = "; ".join(paper.get("authors") or []) or "佚名"
        lines.append(
            f"[{index}] {authors}. {paper.get('title')}. {paper.get('source') or '未知来源'}, {paper.get('year') or 'n.d.'}."
        )
    return "\n".join(lines) + ("\n" if lines else "")


def _apa(papers: list[JsonObject]) -> str:
    """生成 APA 风格的基础引用。"""

    return "\n".join(
        f"{', '.join(paper.get('authors') or []) or 'Unknown'}. ({paper.get('year') or 'n.d.'}). {paper.get('title')}. {paper.get('source') or ''}. {paper.get('doi') or paper.get('url') or ''}".strip()
        for paper in papers
    ) + ("\n" if papers else "")


def _simple_pdf(text: str) -> bytes:
    """生成一个不依赖额外库的简单 PDF，确保用户始终能下载结果。"""

    safe = text.encode("latin-1", "replace").decode("latin-1")
    lines = safe.splitlines()[:180] or ["No content"]
    stream = "BT\n/F1 10 Tf\n50 780 Td\n" + "\n".join(f"({line[:110].replace('(', '[').replace(')', ']')}) Tj\n0 -14 Td" for line in lines) + "\nET"
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(stream.encode('latin-1'))} >>\nstream\n{stream}\nendstream",
    ]
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{number} 0 obj\n{obj}\nendobj\n".encode("latin-1"))
    xref = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("latin-1"))
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("latin-1"))
    output.extend(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode("latin-1"))
    return bytes(output)


def _title_from_pdf_text(text: str) -> str:
    """从 PDF 前几行里取一个看起来像标题的文本。"""

    for line in text.splitlines()[:12]:
        compact = " ".join(line.split())
        if 8 <= len(compact) <= 180 and not compact.lower().startswith(("abstract", "摘要", "keywords")):
            return compact
    return ""


def _as_bool(value: Any) -> bool:
    return str(value).lower() in {"1", "true", "yes", "on"}


def _optional_bool(value: Any) -> bool | None:
    if value is None or str(value).lower() in {"", "all", "none"}:
        return None
    return _as_bool(value)
