from __future__ import annotations

import copy
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from src.llm.config import SystemConfig


JsonObject = dict[str, Any]


class SettingsRepository:
    """基于 JSON 文件或内存快照的设置仓储。

    中文说明：
    这个仓储只负责配置数据的读取与保存，不负责配置校验、补默认值、
    也不负责拼装前端响应结构。这样服务层可以专注业务规则，仓储层专注 IO。
    """

    def __init__(
        self,
        path: str | Path | None = None,
        initial: JsonObject | None = None,
        system_path: str | Path | None = None,
        system: SystemConfig | JsonObject | None = None,
    ):
        """初始化设置仓储。"""

        self.path = Path(path) if path else None
        self.system_path = Path(system_path) if system_path else Path("config/system.yaml")
        self._memory = copy.deepcopy(initial or {})
        self._system = system if isinstance(system, SystemConfig) else SystemConfig.from_dict(system)

    def load(self) -> JsonObject:
        """读取当前配置快照。"""

        if self.path and self.path.exists():
            return json.loads(self.path.read_text(encoding="utf-8"))
        return copy.deepcopy(self._memory)

    def save(self, data: JsonObject) -> None:
        """保存配置快照。"""

        normalized = copy.deepcopy(data)
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
        self._memory = normalized

    def system(self) -> SystemConfig:
        """读取系统级默认配置。"""

        if self.path:
            return SystemConfig.load(self.system_path)
        return self._system

    def save_deep_read_limit(self, value: int) -> None:
        """保存系统默认深度阅读数量，并保留现有 system.yaml 的其它内容。"""

        if self.path:
            self.system_path.parent.mkdir(parents=True, exist_ok=True)
            text = self.system_path.read_text(encoding="utf-8") if self.system_path.exists() else "read:\n"
            lines = text.splitlines()
            read_start = next((index for index, line in enumerate(lines) if line.strip() == "read:"), None)
            if read_start is None:
                if lines and lines[-1].strip():
                    lines.append("")
                lines.extend(["read:", f"  deep_read_limit: {value}"])
            else:
                read_end = len(lines)
                for index in range(read_start + 1, len(lines)):
                    stripped = lines[index].strip()
                    if stripped and not lines[index].startswith(" "):
                        read_end = index
                        break
                limit_index = next(
                    (index for index in range(read_start + 1, read_end) if lines[index].strip().startswith("deep_read_limit:")),
                    None,
                )
                if limit_index is None:
                    lines.insert(read_start + 1, f"  deep_read_limit: {value}")
                else:
                    lines[limit_index] = f"  deep_read_limit: {value}"
            self.system_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return

        # 中文说明：内存仓储主要用于轻量调用和联调，没有文件时直接更新内存配置。
        self._system = replace(self._system, read=replace(self._system.read, deep_read_limit=value))

    def save_paper_retrieval_keys(self, *, ieee_xplore_api_key: str | None = None, elsevier_api_key: str | None = None) -> None:
        """保存论文来源密钥，并保留 system.yaml 中的其它配置。"""

        if self.path:
            self.system_path.parent.mkdir(parents=True, exist_ok=True)
            text = self.system_path.read_text(encoding="utf-8") if self.system_path.exists() else ""
            lines = text.splitlines()
            section_start = next((index for index, line in enumerate(lines) if line.strip() == "paper_retrieval:"), None)
            if section_start is None:
                if lines and lines[-1].strip():
                    lines.append("")
                lines.extend(["paper_retrieval:", "  openalex_api_key: null", "  semantic_scholar_api_key: null"])
                section_start = len(lines) - 3
            section_end = len(lines)
            for index in range(section_start + 1, len(lines)):
                if lines[index].strip() and not lines[index].startswith(" "):
                    section_end = index
                    break
            for key, value in (("ieee_xplore_api_key", ieee_xplore_api_key), ("elsevier_api_key", elsevier_api_key)):
                if value is None or not str(value).strip():
                    continue
                line = f"  {key}: {value.strip()}"
                key_index = next(
                    (index for index in range(section_start + 1, section_end) if lines[index].strip().startswith(f"{key}:")),
                    None,
                )
                if key_index is None:
                    lines.insert(section_end, line)
                    section_end += 1
                else:
                    lines[key_index] = line
            self.system_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return

        self._system = replace(
            self._system,
            paper_retrieval=replace(
                self._system.paper_retrieval,
                ieee_xplore_api_key=ieee_xplore_api_key or self._system.paper_retrieval.ieee_xplore_api_key,
                elsevier_api_key=elsevier_api_key or self._system.paper_retrieval.elsevier_api_key,
            ),
        )
