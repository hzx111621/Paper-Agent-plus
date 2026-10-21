from __future__ import annotations

import asyncio
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .base import AgentContext, AgentSpec, BaseAgent
from .reading_prompts import CHAPTER_PROMPT, DEEP_QUESTIONS, PLANNING_PROMPT


class ChapterReadingAgent(BaseAgent):
    """先识别章节，再依次精读；每轮完成后保存，失败重试时可以接着读。"""

    spec = AgentSpec(name="chapter_reading_agent", role="read", description="双阶段逐章精读论文全文。")

    def __init__(self, context: AgentContext):
        context.spec = self.spec
        super().__init__(context)

    def _run(self, state: dict[str, Any]) -> dict[str, Any]:
        """同步调用入口；网页和工作流使用下面的异步入口。"""
        return asyncio.run(self.read(str(state["full_text"]), Path(state["output_path"])))

    async def ask(self, messages: list[dict[str, Any]], semaphore: asyncio.Semaphore | None = None) -> str:
        """调用用户选择的阅读模型，并明确报告失败，避免保存空白笔记。"""
        if self.context.llm is None:
            raise RuntimeError("请先在设置中配置可用的阅读模型。")
        if semaphore is None:
            response = await self.context.llm.provider.chat(messages, temperature=0)
        else:
            async with semaphore:
                response = await self.context.llm.provider.chat(messages, temperature=0)
        self.report_usage(response)
        if not response.ok or not response.content.strip() or response.finish_reason in {"length", "max_tokens"}:
            raise RuntimeError("精读模型调用失败，请检查模型配置、额度或全文是否超出模型长度限制。")
        return response.content.strip()

    async def read(self, full_text: str, output_path: Path, semaphore: asyncio.Semaphore | None = None) -> dict[str, Any]:
        """每轮都提供全文；章节只携带上一轮问答，两个追问完全独立。"""
        fingerprint = hashlib.sha256(("chapter-v2\n" + full_text).encode()).hexdigest()
        record: dict[str, Any] = {"fingerprint": fingerprint, "chapters": [], "rounds": [], "markdown": "", "complete": False}
        if output_path.exists():
            saved = json.loads(output_path.read_text(encoding="utf-8"))
            if saved.get("fingerprint") == fingerprint:
                record = saved
        if record["complete"]:
            return record
        source = {"role": "system", "content": "只依据以下论文全文回答。原文未报告的结果不得编造。\n\n" + full_text}
        if not record["chapters"]:
            response = await self.ask([source, {"role": "user", "content": PLANNING_PROMPT}], semaphore)
            response = re.sub(r"^```(?:json)?\s*|\s*```$", "", response, flags=re.IGNORECASE)
            try:
                chapters = json.loads(response)["chapters"]
            except (ValueError, KeyError, TypeError) as exc:
                raise ValueError("章节识别未返回有效 JSON，请重试。") from exc
            if not isinstance(chapters, list) or len(chapters) < 2:
                raise ValueError("章节识别至少需要两个章节，请重试。")
            for chapter in chapters[:12]:
                if not isinstance(chapter, dict) or any(not isinstance(chapter.get(key), str) or not chapter[key].strip() for key in ("id", "title_zh", "title_en")):
                    raise ValueError("章节缺少 id、中文标题或英文标题，请重试。")
            record["chapters"] = chapters[:12]
            self._save(output_path, record)
        steps = [(c["title_zh"], CHAPTER_PROMPT.replace("{{title_zh}}", c["title_zh"]).replace("{{title_en}}", c["title_en"])) for c in record["chapters"]] + DEEP_QUESTIONS
        for index, (title, prompt) in enumerate(steps):
            if index < len(record["rounds"]):
                continue
            messages = [source]
            # 第一章只看全文；后续章节只补充上一章的问答，不累计所有历史。
            if 0 < index < len(record["chapters"]):
                previous = record["rounds"][-1]
                messages += [{"role": "user", "content": previous["prompt"]}, {"role": "assistant", "content": previous["content"]}]
            messages.append({"role": "user", "content": prompt})
            content = await self.ask(messages, semaphore)
            record["rounds"].append({"title": title, "prompt": prompt, "content": content})
            record["markdown"] = "\n\n".join(f"## {r['title']}\n\n{r['content']}" for r in record["rounds"])
            record["complete"] = len(record["rounds"]) == len(steps)
            self._save(output_path, record)
        return record

    @staticmethod
    def _save(path: Path, record: dict[str, Any]) -> None:
        """先写临时文件再替换，避免页面读取到只写了一半的笔记。"""
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
        path.with_suffix(".md").write_text(record["markdown"], encoding="utf-8")
