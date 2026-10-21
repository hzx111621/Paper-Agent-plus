from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from pathlib import Path
from string import Template
from typing import Any

from src.agents.base import AgentContext
from src.agents.chapterReadingAgent import ChapterReadingAgent
from src.agents.reading_prompts import IMAGE_PROMPT, VISUAL_PROMPT
from src.llm import ModelConfig, make_provider
from src.llm.image_generation import generate_image, image_config
from src.paper_retrieval.download import async_download_paper_fulltext
from src.paper_retrieval.models import PaperDocument
from src.repositories.sessions.sqlite import SQLiteSessionRepository
from src.repositories.settings.json import SettingsRepository
from src.services.sessions import SessionError
from src.utils.read_utils.cache import paper_cache_dir
from src.utils.read_utils.read_fulltext import async_convert_fulltext_to_markdown


def reading_paths(repo: SQLiteSessionRepository, user_id: str, paper_id: str) -> tuple[dict[str, Any], Path]:
    """先检查论文属于当前账户，再计算该账户自己的结果目录。"""
    paper = repo.get_user_paper(user_id, paper_id)
    if paper is None:
        raise SessionError("当前账户中没有这篇论文。", 404)
    folder = hashlib.sha256(f"{user_id}\n{paper_id}".encode()).hexdigest()
    return paper, repo.backend.storage_root / "paper_reading" / folder


def reading_payload(repo: SQLiteSessionRepository, settings: SettingsRepository, user_id: str, paper_id: str) -> dict[str, Any]:
    """返回已有笔记和图片；打开结果窗口不会触发模型调用。"""
    paper, directory = reading_paths(repo, user_id, paper_id)
    chapter_path = directory / "chapter_reading.json"
    if not chapter_path.exists() and not (paper.get("metadata") or {}).get("local"):
        chapter_path = _shared_cache(settings, paper) / "chapter_reading.json"
    return {"reading": _read_json(chapter_path), "image": _read_json(directory / "image_summary.json")}


async def run_paper_reading(repo: SQLiteSessionRepository, settings: SettingsRepository, user_id: str, paper_id: str, action: str) -> dict[str, Any]:
    """执行精读或一图总结；正文缺失时明确提示，不能用摘要冒充全文。"""
    paper, directory = reading_paths(repo, user_id, paper_id)
    config = image_config(settings) if action == "image" else None
    try:
        llm = make_provider(ModelConfig.from_dict(settings.load(), settings.system()), settings.system().read.agent_name)
    except ValueError:
        raise SessionError("请先在设置页配置默认阅读模型。", 400) from None
    try:
        full_text = await _full_text(settings, paper)
        directory.mkdir(parents=True, exist_ok=True)
        agent = ChapterReadingAgent(AgentContext(spec=ChapterReadingAgent.spec, llm=llm))
        if action == "reading":
            await agent.read(full_text, directory / "chapter_reading.json")
        else:
            assert config is not None
            language = config.get("language") or "中文"
            prompt = Template(VISUAL_PROMPT).substitute(language=language, context=full_text)
            summary = await agent.ask([{"role": "system", "content": "只依据原文提取视觉信息，不编造数字、性能提升或因果关系；未报告的内容明确标注未报告。"}, {"role": "user", "content": prompt}])
            image_prompt = Template(IMAGE_PROMPT).substitute(summaryForImage=summary, title=paper["title"], language=language)
            content, mime = await generate_image(config, image_prompt)
            record = {"summary": summary, "language": language, "model": config["model"], "mime": mime, "data_url": f"data:{mime};base64," + base64.b64encode(content).decode()}
            # 只有新图片成功生成才替换旧结果，失败时仍然可以查看上次生成的图片。
            temporary = directory / "image_summary.tmp"
            temporary.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
            temporary.replace(directory / "image_summary.json")
        return reading_payload(repo, settings, user_id, paper_id)
    except (ValueError, RuntimeError) as exc:
        raise SessionError(str(exc), 502) from None
    finally:
        await llm.aclose()


async def prefetch_paper_fulltext(settings: SettingsRepository, paper: dict[str, Any]) -> str:
    """在搜索结果展示前提前准备全文，精读窗口打开时直接复用。"""

    try:
        await _full_text(settings, paper)
    except SessionError as exc:
        # 中文说明：公开全文并非每篇论文都有。预下载失败不影响用户查看题录，
        # 精读窗口会在用户主动点击时给出“上传 PDF”的明确说明。
        return str(exc)
    return ""


def _shared_cache(settings: SettingsRepository, paper: dict[str, Any]) -> Path:
    """复用工作流已下载的全文；拒绝可能走出缓存目录的论文编号。"""
    root = Path(settings.system().read.paper_cache_dir).resolve()
    directory = paper_cache_dir(root, _document(paper)).resolve()
    if not directory.is_relative_to(root) or directory == root:
        raise SessionError("论文编号无效。", 400)
    return directory


def _document(paper: dict[str, Any]) -> PaperDocument:
    """把个人论文库记录转为下载工具需要的论文对象。"""
    return PaperDocument(id=paper["paperId"], paperId=paper["paperId"], title=paper["title"], url=paper.get("url"), pdf_url=paper.get("pdf_url"), doi=paper.get("doi"), metadata=paper.get("metadata") or {})


async def _full_text(settings: SettingsRepository, paper: dict[str, Any]) -> str:
    """本地上传直接取已解析正文，网上论文优先取缓存，否则下载并解析。"""
    metadata = paper.get("metadata") or {}
    if metadata.get("local"):
        text = str(metadata.get("full_text") or "").strip()
    else:
        directory = _shared_cache(settings, paper)
        path = directory / "paper.md"
        if not path.exists():
            defaults = settings.system().read
            document = _document(paper)
            downloaded = await async_download_paper_fulltext(document, cache_dir=defaults.paper_cache_dir, connect_timeout_seconds=defaults.connect_timeout_seconds, download_timeout_seconds=defaults.download_timeout_seconds, max_file_size_mb=defaults.max_file_size_mb)
            if downloaded.file_path is None:
                raise SessionError("无法获取论文全文，请上传 PDF 后再试。", 400)
            converted = await async_convert_fulltext_to_markdown(document, source_path=downloaded.file_path, source_url=downloaded.source_url)
            if converted.markdown_path is None:
                raise SessionError("全文解析失败，请上传包含可复制文字的 PDF。", 400)
            path = converted.markdown_path
        text = await asyncio.to_thread(path.read_text, encoding="utf-8")
    if not text.strip():
        raise SessionError("没有可读取的全文，不能仅凭摘要进行精读或生成一图总结。", 400)
    return text


def _read_json(path: Path) -> dict[str, Any] | None:
    """尚未生成结果时返回空值。"""
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
