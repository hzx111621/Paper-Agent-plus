from __future__ import annotations

import copy
import json
import shutil
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from posixpath import normpath
from typing import Any

from src.models.sessions import SessionRecord, utc_now
from src.services.sessions import SessionError
from src.utils import get_logger
from src.utils.readable_id import create_readable_id

from .base import JsonObject, SessionRepository


logger = get_logger(__name__)


def _optional_db_int(value: Any) -> int | None:
    """把前端传来的年份或数量转换成 SQLite 可接受的整数。"""

    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_db_float(value: Any) -> float | None:
    """把相关度分数转换成数字，格式不对时按空值保存。"""

    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class SessionStoreBackend:
    """基于 SQLite 与文件系统的会话存储后端。"""

    def __init__(self, storage_root: Path | str):
        """初始化持久化后端，并确保基础目录与表结构存在。"""

        self.storage_root = Path(storage_root)
        self.storage_root.mkdir(parents=True, exist_ok=True)
        self.database_path = self.storage_root / "session_store.db"
        self.sessions_dir = self.storage_root / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self._initialize_schema()

    def has_sessions(self) -> bool:
        """判断当前数据库中是否已经存在会话记录。"""

        with self._connection() as connection:
            row = connection.execute("SELECT COUNT(1) AS count FROM session").fetchone()
        return bool(row and int(row["count"]) > 0)

    def user_count(self) -> int:
        """返回已注册的本地账户数量。"""

        with self._connection() as connection:
            row = connection.execute("SELECT COUNT(1) AS count FROM app_user").fetchone()
        return int(row["count"]) if row else 0

    def create_user(self, user_id: str, username: str, password_hash: str, created_at: str) -> None:
        """保存一个新账户，只存密码哈希，不保存明文密码。"""

        with self._connection() as connection:
            connection.execute(
                "INSERT INTO app_user (id, username, password_hash, created_at) VALUES (?, ?, ?, ?)",
                (user_id, username, password_hash, created_at),
            )

    def get_user_by_username(self, username: str) -> JsonObject | None:
        """按用户名读取账户信息。"""

        with self._connection() as connection:
            row = connection.execute(
                "SELECT id, username, password_hash, created_at FROM app_user WHERE username = ?",
                (username,),
            ).fetchone()
        return dict(row) if row else None

    def get_user_by_id(self, user_id: str) -> JsonObject | None:
        """按账户编号读取公开账户信息。"""

        with self._connection() as connection:
            row = connection.execute(
                "SELECT id, username, created_at FROM app_user WHERE id = ?",
                (user_id,),
            ).fetchone()
        return dict(row) if row else None

    def create_auth_token(self, token_hash: str, user_id: str, created_at: str, expires_at: str) -> None:
        """保存登录令牌的哈希值和过期时间。"""

        with self._connection() as connection:
            connection.execute(
                "INSERT INTO auth_token (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                (token_hash, user_id, created_at, expires_at),
            )

    def get_user_by_token(self, token_hash: str, now: str) -> JsonObject | None:
        """验证令牌是否存在且仍在有效期内。"""

        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT u.id, u.username, u.created_at
                FROM auth_token AS t
                JOIN app_user AS u ON u.id = t.user_id
                WHERE t.token_hash = ? AND t.expires_at > ?
                """,
                (token_hash, now),
            ).fetchone()
        return dict(row) if row else None

    def delete_auth_token(self, token_hash: str) -> None:
        """注销一个登录令牌。"""

        with self._connection() as connection:
            connection.execute("DELETE FROM auth_token WHERE token_hash = ?", (token_hash,))

    def list_auth_tokens(self, user_id: str) -> list[JsonObject]:
        """读取账户的登录令牌摘要，不返回令牌原文。"""

        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT token_hash, created_at, expires_at
                FROM auth_token
                WHERE user_id = ?
                ORDER BY created_at DESC
                """,
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_auth_tokens_for_user(self, user_id: str, except_token_hash: str | None = None) -> None:
        """删除账户的登录令牌，可保留当前浏览器令牌。"""

        with self._connection() as connection:
            if except_token_hash:
                connection.execute(
                    "DELETE FROM auth_token WHERE user_id = ? AND token_hash <> ?",
                    (user_id, except_token_hash),
                )
            else:
                connection.execute("DELETE FROM auth_token WHERE user_id = ?", (user_id,))

    def update_user_password(self, user_id: str, password_hash: str) -> None:
        """更新账户密码哈希。"""

        with self._connection() as connection:
            connection.execute("UPDATE app_user SET password_hash = ? WHERE id = ?", (password_hash, user_id))

    def delete_user(self, user_id: str) -> list[str]:
        """删除账户及其数据，并返回需要清理的会话目录编号。"""

        with self._connection() as connection:
            rows = connection.execute("SELECT id FROM session WHERE user_id = ?", (user_id,)).fetchall()
            session_ids = [str(row["id"]) for row in rows]
            connection.execute("DELETE FROM user_paper WHERE user_id = ?", (user_id,))
            connection.execute("DELETE FROM session_paper WHERE user_id = ?", (user_id,))
            connection.execute("DELETE FROM session WHERE user_id = ?", (user_id,))
            connection.execute("DELETE FROM app_user WHERE id = ?", (user_id,))
        return session_ids

    def claim_legacy_sessions(self, user_id: str) -> None:
        """把注册前属于本地默认账户的历史会话交给首个注册用户。"""

        with self._connection() as connection:
            connection.execute("UPDATE session SET user_id = ? WHERE user_id = 'local-user'", (user_id,))

    def create_session(
        self,
        session_id: str,
        title: str,
        created_at: str,
        updated_at: str,
        user_id: str,
        workspace_scope: JsonObject | None,
        metadata: JsonObject | None = None,
        status: str = "created",
    ) -> None:
        """创建一条新的会话主记录。"""

        payload = dict(metadata or {})
        payload.setdefault("schema_version", 1)
        payload["workspace_scope"] = workspace_scope
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO session (
                    id, user_id, title, status, created_at, updated_at, last_message_at, summary, metadata, run_started_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    user_id,
                    title,
                    status,
                    created_at,
                    updated_at,
                    None,
                    "",
                    self._dump_json(payload),
                    None,
                ),
            )
        self.ensure_session_layout(session_id)

    def get_session(self, session_id: str) -> JsonObject | None:
        """读取单条会话主记录，并把 JSON 字段还原为普通对象。"""

        with self._connection() as connection:
            row = connection.execute("SELECT * FROM session WHERE id = ?", (session_id,)).fetchone()
        if row is None:
            return None
        return self._row_to_session(row)

    def get_session_for_user(self, session_id: str, user_id: str) -> JsonObject | None:
        """只读取指定账户拥有的会话。"""

        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM session WHERE id = ? AND user_id = ?",
                (session_id, user_id),
            ).fetchone()
        return self._row_to_session(row) if row else None

    def list_sessions(self) -> list[JsonObject]:
        """按更新时间倒序返回全部会话摘要原始数据。"""

        with self._connection() as connection:
            rows = connection.execute("SELECT * FROM session ORDER BY updated_at DESC").fetchall()
        return [self._row_to_session(row) for row in rows]

    def list_sessions_for_user(self, user_id: str, include_archived: bool = False) -> list[JsonObject]:
        """按更新时间倒序返回指定账户的会话摘要。"""

        with self._connection() as connection:
            if include_archived:
                rows = connection.execute(
                    "SELECT * FROM session WHERE user_id = ? ORDER BY updated_at DESC",
                    (user_id,),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM session WHERE user_id = ? AND archived = 0 ORDER BY updated_at DESC",
                    (user_id,),
                ).fetchall()
        return [self._row_to_session(row) for row in rows]

    def list_session_paper_ids(self, session_id: str) -> list[str]:
        """读取当前会话中由用户上传或手动加入的论文编号。"""

        with self._connection() as connection:
            rows = connection.execute(
                "SELECT paper_id FROM session_paper WHERE session_id = ? ORDER BY created_at ASC",
                (session_id,),
            ).fetchall()
        return [str(row["paper_id"]) for row in rows]

    def associate_session_paper(self, session_id: str, user_id: str, paper_id: str, origin: str) -> None:
        """把论文和会话关联起来，重复关联时只更新来源。"""

        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO session_paper (session_id, user_id, paper_id, origin, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(session_id, paper_id) DO UPDATE SET origin = excluded.origin
                """,
                (session_id, user_id, paper_id, origin, utc_now()),
            )

    def upsert_user_paper(self, user_id: str, paper: JsonObject) -> JsonObject:
        """保存或更新账户论文库中的一篇论文。"""

        now = utc_now()
        paper_id = str(paper.get("paperId") or paper.get("id") or "").strip()
        if not paper_id:
            raise ValueError("paper_id is required")
        existing = self.get_user_paper(user_id, paper_id)
        values = {
            "title": str(paper.get("title") or "").strip(),
            "authors": json.dumps(paper.get("authors") or [], ensure_ascii=False),
            "year": _optional_db_int(paper.get("year")),
            "source": str(paper.get("source") or "").strip(),
            "abstract": str(paper.get("abstract") or ""),
            "url": str(paper.get("url") or "").strip(),
            "pdf_url": str(paper.get("pdf_url") or "").strip(),
            "doi": str(paper.get("doi") or "").strip(),
            "relevance_score": _optional_db_float(paper.get("relevance_score")),
            "metadata": json.dumps(paper.get("metadata") or {}, ensure_ascii=False),
        }
        with self._connection() as connection:
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO user_paper (
                        user_id, paper_id, title, authors, year, source, abstract, url, pdf_url, doi,
                        relevance_score, metadata, favorite, focused, ignored, tags, note, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, '[]', '', ?, ?)
                    """,
                    (
                        user_id,
                        paper_id,
                        values["title"],
                        values["authors"],
                        values["year"],
                        values["source"],
                        values["abstract"],
                        values["url"],
                        values["pdf_url"],
                        values["doi"],
                        values["relevance_score"],
                        values["metadata"],
                        now,
                        now,
                    ),
                )
            else:
                connection.execute(
                    """
                    UPDATE user_paper
                    SET title = ?, authors = ?, year = ?, source = ?, abstract = ?, url = ?, pdf_url = ?, doi = ?,
                        relevance_score = ?, metadata = ?, updated_at = ?
                    WHERE user_id = ? AND paper_id = ?
                    """,
                    (
                        values["title"],
                        values["authors"],
                        values["year"],
                        values["source"],
                        values["abstract"],
                        values["url"],
                        values["pdf_url"],
                        values["doi"],
                        values["relevance_score"],
                        values["metadata"],
                        now,
                        user_id,
                        paper_id,
                    ),
                )
        return self.get_user_paper(user_id, paper_id) or {}

    def get_user_paper(self, user_id: str, paper_id: str) -> JsonObject | None:
        """读取账户论文库中的一篇论文。"""

        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM user_paper WHERE user_id = ? AND paper_id = ?",
                (user_id, paper_id),
            ).fetchone()
        return self._row_to_user_paper(row) if row else None

    def update_user_paper(self, user_id: str, paper_id: str, patch: JsonObject) -> JsonObject:
        """更新论文的收藏、重点、忽略、标签和个人笔记。"""

        current = self.get_user_paper(user_id, paper_id)
        if current is None:
            raise SessionError(f"paper not found: {paper_id}", 404)
        favorite = int(bool(patch.get("favorite", current["favorite"])))
        focused = int(bool(patch.get("focused", current["focused"])))
        ignored = int(bool(patch.get("ignored", current["ignored"])))
        tags = patch.get("tags", current.get("tags") or [])
        if not isinstance(tags, list):
            raise ValueError("tags must be a list")
        note = str(patch.get("note", current.get("note") or ""))
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE user_paper
                SET favorite = ?, focused = ?, ignored = ?, tags = ?, note = ?, updated_at = ?
                WHERE user_id = ? AND paper_id = ?
                """,
                (favorite, focused, ignored, json.dumps(tags, ensure_ascii=False), note, utc_now(), user_id, paper_id),
            )
        return self.get_user_paper(user_id, paper_id) or {}

    def list_user_papers(
        self,
        user_id: str,
        *,
        query: str = "",
        tag: str = "",
        favorite_only: bool = False,
        focused_only: bool = False,
        ignored: bool | None = None,
        sort: str = "updated_at",
        descending: bool = True,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[JsonObject], int]:
        """分页读取账户论文库，并支持标题、作者、标签和状态筛选。"""

        allowed_sort = {"updated_at": "updated_at", "year": "year", "title": "title", "relevance": "relevance_score"}
        order_column = allowed_sort.get(sort, "updated_at")
        order_direction = "DESC" if descending else "ASC"
        clauses = ["user_id = ?"]
        params: list[Any] = [user_id]
        if query.strip():
            clauses.append("(title LIKE ? OR authors LIKE ? OR abstract LIKE ?)")
            needle = f"%{query.strip()}%"
            params.extend([needle, needle, needle])
        if tag.strip():
            clauses.append("tags LIKE ?")
            params.append(f'%"{tag.strip()}"%')
        if favorite_only:
            clauses.append("favorite = 1")
        if focused_only:
            clauses.append("focused = 1")
        if ignored is not None:
            clauses.append("ignored = ?")
            params.append(int(ignored))
        where = " AND ".join(clauses)
        offset = max(0, page - 1) * max(1, page_size)
        with self._connection() as connection:
            count_row = connection.execute(f"SELECT COUNT(1) AS count FROM user_paper WHERE {where}", params).fetchone()
            rows = connection.execute(
                f"SELECT * FROM user_paper WHERE {where} ORDER BY {order_column} {order_direction}, paper_id ASC LIMIT ? OFFSET ?",
                [*params, max(1, page_size), offset],
            ).fetchall()
        return [self._row_to_user_paper(row) for row in rows], int(count_row["count"] if count_row else 0)

    def _row_to_user_paper(self, row: sqlite3.Row) -> JsonObject:
        """把论文库数据库记录转换成前端可直接展示的对象。"""

        return {
            "paperId": row["paper_id"],
            "id": row["paper_id"],
            "title": row["title"],
            "authors": self._load_json_list(row["authors"]),
            "year": row["year"],
            "source": row["source"],
            "abstract": row["abstract"],
            "url": row["url"],
            "pdf_url": row["pdf_url"],
            "doi": row["doi"],
            "relevance_score": row["relevance_score"],
            "metadata": self._load_json(row["metadata"]),
            "favorite": bool(row["favorite"]),
            "focused": bool(row["focused"]),
            "ignored": bool(row["ignored"]),
            "tags": self._load_json_list(row["tags"]),
            "note": row["note"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _load_json_list(self, payload: str | None) -> list[Any]:
        """读取 JSON 数组字段，格式异常时返回空数组。"""

        if not payload:
            return []
        try:
            value = json.loads(payload)
        except json.JSONDecodeError:
            return []
        return value if isinstance(value, list) else []

    def delete_session(self, session_id: str) -> None:
        """删除指定会话的数据库记录和文件系统目录。"""

        with self._connection() as connection:
            connection.execute("DELETE FROM session WHERE id = ?", (session_id,))
        session_dir = self.sessions_dir / session_id
        if session_dir.exists():
            shutil.rmtree(session_dir)

    def update_workspace_scope(self, session_id: str, workspace_scope: JsonObject | None, updated_at: str) -> None:
        """更新会话工作区范围信息，并同步刷新更新时间。"""

        record = self.get_session(session_id)
        if record is None:
            return
        metadata = dict(record.get("metadata") or {})
        metadata["workspace_scope"] = workspace_scope
        with self._connection() as connection:
            connection.execute(
                "UPDATE session SET metadata = ?, updated_at = ? WHERE id = ?",
                (self._dump_json(metadata), updated_at, session_id),
            )

    def update_run_started_at(self, session_id: str, run_started_at: str | None, updated_at: str) -> None:
        """更新当前会话的运行中时间戳。"""

        with self._connection() as connection:
            connection.execute(
                "UPDATE session SET run_started_at = ?, updated_at = ? WHERE id = ?",
                (run_started_at, updated_at, session_id),
            )

    def update_status(self, session_id: str, status: str, updated_at: str) -> None:
        """更新会话状态，并把更新时间一并写回数据库。"""

        with self._connection() as connection:
            connection.execute(
                "UPDATE session SET status = ?, updated_at = ? WHERE id = ?",
                (status, updated_at, session_id),
            )

    def update_title(self, session_id: str, title: str, updated_at: str) -> None:
        """更新会话标题，通常用于首次用户输入后的自动命名。"""

        with self._connection() as connection:
            connection.execute(
                "UPDATE session SET title = ?, updated_at = ? WHERE id = ?",
                (title, updated_at, session_id),
            )

    def update_archived(self, session_id: str, archived: bool, updated_at: str) -> None:
        """更新会话归档状态。"""

        with self._connection() as connection:
            connection.execute(
                "UPDATE session SET archived = ?, updated_at = ? WHERE id = ?",
                (int(archived), updated_at, session_id),
            )

    def append_message(
        self,
        session_id: str,
        message_id: str,
        role: str,
        content: str,
        created_at: str,
        parent_id: str | None = None,
        metadata: JsonObject | None = None,
    ) -> None:
        """向消息表追加一条会话消息，并维护会话摘要字段。"""

        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO session_message (id, session_id, role, content, created_at, parent_id, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message_id,
                    session_id,
                    role,
                    content,
                    created_at,
                    parent_id,
                    self._dump_json(metadata or {}),
                ),
            )
            connection.execute(
                """
                UPDATE session
                SET updated_at = ?, last_message_at = ?, summary = ?
                WHERE id = ?
                """,
                (created_at, created_at, content[:120], session_id),
            )

    def list_messages(self, session_id: str) -> list[JsonObject]:
        """按时间顺序读取某个会话下的全部消息。"""

        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT id, role, content, created_at, parent_id, metadata
                FROM session_message
                WHERE session_id = ?
                ORDER BY created_at ASC, rowid ASC
                """,
                (session_id,),
            ).fetchall()
        return [self._row_to_message(row) for row in rows]

    def append_event(
        self,
        session_id: str,
        event_type: str,
        content: str,
        created_at: str,
        metadata: JsonObject | None = None,
        event_id: str | None = None,
    ) -> JsonObject:
        """追加单条过程事件，并同步写入会话目录下的 `events.jsonl`。"""

        normalized_event_id = event_id or uuid.uuid4().hex
        payload = metadata or {}
        with self._connection() as connection:
            seq_row = connection.execute(
                "SELECT COALESCE(MAX(seq_no), 0) + 1 AS next_seq FROM session_event WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            seq_no = int(seq_row["next_seq"]) if seq_row else 1
            connection.execute(
                """
                INSERT INTO session_event (id, session_id, event_type, content, created_at, seq_no, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    normalized_event_id,
                    session_id,
                    event_type,
                    content,
                    created_at,
                    seq_no,
                    self._dump_json(payload),
                ),
            )
        event_record = {
            "id": normalized_event_id,
            "session_id": session_id,
            "event_type": event_type,
            "content": content,
            "created_at": created_at,
            "seq_no": seq_no,
            "metadata": payload,
        }
        self._append_event_jsonl(session_id, event_record)
        return event_record

    def list_events(self, session_id: str) -> list[JsonObject]:
        """按序号顺序读取指定会话的完整事件流。"""

        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT id, event_type, content, created_at, seq_no, metadata
                FROM session_event
                WHERE session_id = ?
                ORDER BY seq_no ASC
                """,
                (session_id,),
            ).fetchall()
        return [self._row_to_event(row) for row in rows]

    def append_artifact_record(
        self,
        session_id: str,
        artifact_type: str,
        name: str,
        path: str,
        size: int,
        created_at: str,
        metadata: JsonObject | None = None,
        artifact_id: str | None = None,
    ) -> JsonObject:
        """向产物表追加一条产物登记记录。"""

        normalized_artifact_id = artifact_id or uuid.uuid4().hex
        payload = metadata or {}
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO session_artifact (id, session_id, artifact_type, name, path, size, created_at, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    normalized_artifact_id,
                    session_id,
                    artifact_type,
                    name,
                    path,
                    size,
                    created_at,
                    self._dump_json(payload),
                ),
            )
        return {
            "id": normalized_artifact_id,
            "artifact_type": artifact_type,
            "name": name,
            "path": path,
            "size": size,
            "created_at": created_at,
            "metadata": payload,
        }

    def list_artifacts(self, session_id: str) -> list[JsonObject]:
        """读取会话关联的全部产物记录。"""

        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT id, artifact_type, name, path, size, created_at, metadata
                FROM session_artifact
                WHERE session_id = ?
                ORDER BY created_at ASC, rowid ASC
                """,
                (session_id,),
            ).fetchall()
        return [self._row_to_artifact(row) for row in rows]

    def ensure_session_layout(self, session_id: str) -> Path:
        """确保会话目录及其子目录存在，并返回会话根目录。"""

        session_dir = self.sessions_dir / session_id
        (session_dir / "artifacts").mkdir(parents=True, exist_ok=True)
        (session_dir / "exports").mkdir(parents=True, exist_ok=True)
        (session_dir / "snapshots").mkdir(parents=True, exist_ok=True)
        events_file = session_dir / "events.jsonl"
        if not events_file.exists():
            events_file.touch()
        return session_dir

    def write_artifact_file(
        self,
        session_id: str,
        relative_path: str,
        content: str | bytes,
        *,
        encoding: str = "utf-8",
    ) -> Path:
        """把产物内容写入会话目录，并返回最终文件路径。"""

        session_dir = self.ensure_session_layout(session_id)
        normalized_relative_path = normpath(relative_path).replace("\\", "/").lstrip("/")
        if normalized_relative_path in {"", "."} or normalized_relative_path.startswith("../"):
            raise ValueError(f"invalid artifact path: {relative_path}")
        target_path = session_dir / Path(normalized_relative_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target_path.write_bytes(content)
        else:
            target_path.write_text(content, encoding=encoding)
        return target_path

    def _initialize_schema(self) -> None:
        """初始化 SQLite 表结构与必要索引。"""

        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS session (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_message_at TEXT,
                    summary TEXT NOT NULL DEFAULT '',
                    metadata TEXT NOT NULL DEFAULT '{}',
                    run_started_at TEXT,
                    archived INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS app_user (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS auth_token (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES app_user(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_auth_token_user_id ON auth_token(user_id);

                CREATE TABLE IF NOT EXISTS session_event (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    seq_no INTEGER NOT NULL,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    UNIQUE(session_id, seq_no),
                    FOREIGN KEY(session_id) REFERENCES session(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS session_message (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    parent_id TEXT,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY(session_id) REFERENCES session(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS session_artifact (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    artifact_type TEXT NOT NULL,
                    name TEXT NOT NULL,
                    path TEXT NOT NULL,
                    size INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY(session_id) REFERENCES session(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_session_updated_at ON session(updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_session_user_id ON session(user_id);
                CREATE INDEX IF NOT EXISTS idx_session_event_session_seq ON session_event(session_id, seq_no);
                CREATE INDEX IF NOT EXISTS idx_session_message_session_created ON session_message(session_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_session_artifact_session_created ON session_artifact(session_id, created_at);

                CREATE TABLE IF NOT EXISTS session_paper (
                    session_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    paper_id TEXT NOT NULL,
                    origin TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (session_id, paper_id),
                    FOREIGN KEY(session_id) REFERENCES session(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS user_paper (
                    user_id TEXT NOT NULL,
                    paper_id TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    authors TEXT NOT NULL DEFAULT '[]',
                    year INTEGER,
                    source TEXT NOT NULL DEFAULT '',
                    abstract TEXT NOT NULL DEFAULT '',
                    url TEXT NOT NULL DEFAULT '',
                    pdf_url TEXT NOT NULL DEFAULT '',
                    doi TEXT NOT NULL DEFAULT '',
                    relevance_score REAL,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    favorite INTEGER NOT NULL DEFAULT 0,
                    focused INTEGER NOT NULL DEFAULT 0,
                    ignored INTEGER NOT NULL DEFAULT 0,
                    tags TEXT NOT NULL DEFAULT '[]',
                    note TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, paper_id),
                    FOREIGN KEY(user_id) REFERENCES app_user(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_user_paper_updated_at ON user_paper(user_id, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_user_paper_source ON user_paper(user_id, source);
                """
            )
            # 中文说明：旧数据库已经创建过 session 表时，CREATE TABLE 不会自动增加新字段，
            # 所以这里单独补一次 archived，保证升级旧项目后归档功能仍然可用。
            columns = {str(row["name"]) for row in connection.execute("PRAGMA table_info(session)").fetchall()}
            if "archived" not in columns:
                connection.execute("ALTER TABLE session ADD COLUMN archived INTEGER NOT NULL DEFAULT 0")

    def _connect(self) -> sqlite3.Connection:
        """创建一条开启外键约束与行字典访问的 SQLite 连接。"""

        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @contextmanager
    def _connection(self):
        """提供会自动关闭的 SQLite 连接上下文。"""

        connection = self._connect()
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _append_event_jsonl(self, session_id: str, event_record: JsonObject) -> None:
        """把结构化事件同步追加写入磁盘 JSONL 文件。"""

        session_dir = self.ensure_session_layout(session_id)
        events_file = session_dir / "events.jsonl"
        with events_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event_record, ensure_ascii=False) + "\n")

    def _row_to_session(self, row: sqlite3.Row) -> JsonObject:
        """把 `session` 表记录转换成更易消费的字典结构。"""

        metadata = self._load_json(row["metadata"])
        return {
            "key": row["id"],
            "user_id": row["user_id"],
            "title": row["title"],
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "last_message_at": row["last_message_at"],
            "summary": row["summary"],
            "metadata": metadata,
            "workspace_scope": metadata.get("workspace_scope"),
            "run_started_at": row["run_started_at"],
            "archived": bool(row["archived"]) if "archived" in row.keys() else False,
        }

    def _row_to_message(self, row: sqlite3.Row) -> JsonObject:
        """把消息表记录还原成线程视图兼容的消息对象。"""

        metadata = self._load_json(row["metadata"])
        return {
            "id": row["id"],
            "role": row["role"],
            "content": row["content"],
            "created_at": row["created_at"],
            "parent_id": row["parent_id"],
            **metadata,
        }

    def _row_to_event(self, row: sqlite3.Row) -> JsonObject:
        """把事件表记录转换成会话详情接口可直接返回的对象。"""

        return {
            "id": row["id"],
            "event_type": row["event_type"],
            "content": row["content"],
            "created_at": row["created_at"],
            "seq_no": row["seq_no"],
            "metadata": self._load_json(row["metadata"]),
        }

    def _row_to_artifact(self, row: sqlite3.Row) -> JsonObject:
        """把产物表记录转换成普通字典。"""

        return {
            "id": row["id"],
            "artifact_type": row["artifact_type"],
            "name": row["name"],
            "path": row["path"],
            "size": row["size"],
            "created_at": row["created_at"],
            "metadata": self._load_json(row["metadata"]),
        }

    def _dump_json(self, payload: JsonObject) -> str:
        """把字典安全序列化成 UTF-8 友好的 JSON 字符串。"""

        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    def _load_json(self, payload: str | None) -> JsonObject:
        """把 JSON 文本安全反序列化为空字典或普通字典。"""

        if not payload:
            return {}
        loaded = json.loads(payload)
        return loaded if isinstance(loaded, dict) else {}


class SQLiteSessionRepository(SessionRepository):
    """基于 SQLite 后端实现的会话仓储。"""

    def __init__(
        self,
        initial: list[JsonObject] | None = None,
        storage_root: Path | str | None = None,
        backend: SessionStoreBackend | None = None,
        default_user_id: str = "local-user",
    ):
        """初始化会话仓储，并在首次启动时可选导入初始数据。"""

        self.default_user_id = default_user_id
        self.backend = backend or SessionStoreBackend(storage_root or Path("data"))
        if initial and not self.backend.has_sessions():
            self._bootstrap_initial_sessions(initial)
        logger.info("会话仓储初始化完成", extra={"storage_root": str(self.backend.storage_root.resolve())})

    def create(self, title: str = "New chat", workspace_scope: JsonObject | None = None) -> SessionRecord:
        """创建新的会话记录。"""

        # 会话编号会出现在数据库、日志和本地目录中，因此保留创建时间，方便人工排查。
        key = create_readable_id()
        now = utc_now()
        self.backend.create_session(
            session_id=key,
            title=title,
            created_at=now,
            updated_at=now,
            user_id=self.default_user_id,
            workspace_scope=copy.deepcopy(workspace_scope),
            metadata={"schema_version": 1},
            status="created",
        )
        logger.info("创建新会话", extra={"session_key": key, "title": title})
        return self.get(key)

    def register_user(self, user_id: str, username: str, password_hash: str) -> None:
        """创建账户，并保留旧代码使用的会话仓储入口。"""

        self.backend.create_user(user_id, username, password_hash, utc_now())

    def user_count(self) -> int:
        """返回账户数量。"""

        return self.backend.user_count()

    def find_user_by_username(self, username: str) -> JsonObject | None:
        """按用户名查询账户。"""

        return self.backend.get_user_by_username(username)

    def find_user_by_id(self, user_id: str) -> JsonObject | None:
        """按账户编号查询账户。"""

        return self.backend.get_user_by_id(user_id)

    def issue_auth_token(self, token_hash: str, user_id: str, expires_at: str) -> None:
        """保存一个登录令牌哈希。"""

        self.backend.create_auth_token(token_hash, user_id, utc_now(), expires_at)

    def find_user_by_token(self, token_hash: str) -> JsonObject | None:
        """按登录令牌读取当前账户。"""

        return self.backend.get_user_by_token(token_hash, utc_now())

    def revoke_auth_token(self, token_hash: str) -> None:
        """撤销登录令牌。"""

        self.backend.delete_auth_token(token_hash)

    def claim_legacy_sessions(self, user_id: str) -> None:
        """把旧的本地会话归属到首个注册账户。"""

        self.backend.claim_legacy_sessions(user_id)

    def create_for_user(self, user_id: str, title: str = "New chat", workspace_scope: JsonObject | None = None) -> SessionRecord:
        """为指定账户创建会话。"""

        key = create_readable_id()
        now = utc_now()
        self.backend.create_session(
            session_id=key,
            title=title,
            created_at=now,
            updated_at=now,
            user_id=user_id,
            workspace_scope=copy.deepcopy(workspace_scope),
            metadata={"schema_version": 1},
            status="created",
        )
        return self.get(key)

    def list_for_user(self, user_id: str, include_archived: bool = False) -> list[JsonObject]:
        """只返回指定账户拥有的会话，默认隐藏已归档会话。"""

        return [
            self._hydrate_record(item).summary()
            for item in self.backend.list_sessions_for_user(user_id, include_archived=include_archived)
        ]

    def get_for_user(self, key: str, user_id: str) -> SessionRecord:
        """读取指定账户拥有的会话，不允许跨账户访问。"""

        raw_session = self.backend.get_session_for_user(key, user_id)
        if raw_session is None:
            raise SessionError(f"session not found: {key}", 404)
        return self._hydrate_record(raw_session)

    def delete_for_user(self, key: str, user_id: str) -> None:
        """删除指定账户拥有的会话。"""

        self.get_for_user(key, user_id)
        self.backend.delete_session(key)

    def archive_for_user(self, key: str, user_id: str, archived: bool = True) -> JsonObject:
        """归档或恢复指定账户的会话。"""

        self.get_for_user(key, user_id)
        self.backend.update_archived(key, archived, utc_now())
        self.backend.append_event(
            session_id=key,
            event_type="session_archived" if archived else "session_unarchived",
            content="archived" if archived else "unarchived",
            created_at=utc_now(),
            metadata={"archived": archived},
        )
        return self.get_for_user(key, user_id).summary()

    def rename_for_user(self, key: str, user_id: str, title: str) -> JsonObject:
        """修改指定账户的会话标题。"""

        self.get_for_user(key, user_id)
        normalized = " ".join(str(title or "").split()).strip()
        if not normalized:
            raise SessionError("会话标题不能为空", 400)
        normalized = normalized[:120]
        now = utc_now()
        self.backend.update_title(key, normalized, now)
        self.backend.append_event(
            session_id=key,
            event_type="summary_update",
            content=normalized,
            created_at=now,
            metadata={"title": normalized, "manual": True},
        )
        return self.get_for_user(key, user_id).summary()

    def list_auth_tokens_for_user(self, user_id: str) -> list[JsonObject]:
        """返回账户的登录设备摘要。"""

        return self.backend.list_auth_tokens(user_id)

    def revoke_other_auth_tokens(self, user_id: str, current_token_hash: str) -> None:
        """撤销除当前浏览器之外的所有登录令牌。"""

        self.backend.delete_auth_tokens_for_user(user_id, except_token_hash=current_token_hash)

    def update_password_for_user(self, user_id: str, password_hash: str) -> None:
        """更新指定账户的密码哈希。"""

        self.backend.update_user_password(user_id, password_hash)

    def delete_account_for_user(self, user_id: str) -> list[str]:
        """删除账户及其会话，并清理会话目录。"""

        session_ids = self.backend.delete_user(user_id)
        for session_id in session_ids:
            session_dir = self.backend.sessions_dir / session_id
            if session_dir.exists():
                shutil.rmtree(session_dir)
        return session_ids

    def save_user_paper(self, user_id: str, paper: JsonObject) -> JsonObject:
        """把一篇论文放入当前账户的论文库。"""

        return self.backend.upsert_user_paper(user_id, paper)

    def get_user_paper(self, user_id: str, paper_id: str) -> JsonObject | None:
        """读取当前账户论文库中的一篇论文。"""

        return self.backend.get_user_paper(user_id, paper_id)

    def update_user_paper(self, user_id: str, paper_id: str, patch: JsonObject) -> JsonObject:
        """更新论文状态、标签和笔记。"""

        return self.backend.update_user_paper(user_id, paper_id, patch)

    def list_user_papers(self, user_id: str, **filters: Any) -> tuple[list[JsonObject], int]:
        """分页读取当前账户的论文库。"""

        return self.backend.list_user_papers(user_id, **filters)

    def list_session_paper_ids_for_user(self, key: str, user_id: str) -> list[str]:
        """读取指定会话关联的论文编号。"""

        self.get_for_user(key, user_id)
        return self.backend.list_session_paper_ids(key)

    def associate_paper_for_user(self, key: str, user_id: str, paper_id: str, origin: str) -> None:
        """把论文关联到指定会话。"""

        self.get_for_user(key, user_id)
        self.backend.associate_session_paper(key, user_id, paper_id, origin)

    def get(self, key: str) -> SessionRecord:
        """根据会话键获取会话记录。"""

        raw_session = self.backend.get_session(key)
        if raw_session is None:
            logger.warning("会话不存在", extra={"session_key": key})
            raise SessionError(f"session not found: {key}", 404)
        return self._hydrate_record(raw_session)

    def list(self) -> list[JsonObject]:
        """返回按更新时间倒序排列的会话摘要列表。"""

        return [self._hydrate_record(item).summary() for item in self.backend.list_sessions()]

    def delete(self, key: str) -> None:
        """删除指定会话。"""

        self.get(key)
        self.backend.delete_session(key)
        logger.info("删除会话", extra={"session_key": key})

    def append_message(self, key: str, role: str, content: str, **extra: Any) -> JsonObject:
        """向指定会话追加一条消息。"""

        record = self.get(key)
        created_at = utc_now()
        message_id = str(extra.pop("id", uuid.uuid4().hex))
        payload = {
            "id": message_id,
            "role": role,
            "content": content,
            "created_at": created_at,
            **extra,
        }
        metadata = {
            item_key: item_value
            for item_key, item_value in payload.items()
            if item_key not in {"id", "role", "content", "created_at"}
        }
        self.backend.append_message(
            session_id=key,
            message_id=message_id,
            role=role,
            content=content,
            created_at=created_at,
            parent_id=metadata.get("parent_id"),
            metadata=metadata,
        )
        if role == "user" and (record.title == "New chat" or not record.title.strip()):
            self._rename_if_default_title(key, content[:40] or "New chat")
        logger.debug(
            "追加会话消息",
            extra={"session_key": key, "role": role, "content_length": len(content), "message_id": message_id},
        )
        return copy.deepcopy(payload)

    def append_event(
        self,
        key: str,
        event_type: str,
        content: str = "",
        metadata: JsonObject | None = None,
        created_at: str | None = None,
    ) -> JsonObject:
        """向指定会话追加一条结构化过程事件。"""

        self.get(key)
        return self.backend.append_event(
            session_id=key,
            event_type=event_type,
            content=content,
            created_at=created_at or utc_now(),
            metadata=copy.deepcopy(metadata or {}),
        )

    def write_artifact(
        self,
        key: str,
        artifact_type: str,
        name: str,
        content: str | bytes,
        *,
        relative_path: str,
        metadata: JsonObject | None = None,
        created_at: str | None = None,
        encoding: str = "utf-8",
    ) -> JsonObject:
        """向指定会话写入产物文件，并在仓储中登记元数据。"""

        self.get(key)
        resolved_created_at = created_at or utc_now()
        target_path = self.backend.write_artifact_file(
            session_id=key,
            relative_path=relative_path,
            content=content,
            encoding=encoding,
        )
        artifact_record = self.backend.append_artifact_record(
            session_id=key,
            artifact_type=artifact_type,
            name=name,
            path=str(target_path),
            size=target_path.stat().st_size,
            created_at=resolved_created_at,
            metadata=copy.deepcopy(metadata or {}),
        )
        logger.info(
            "写入会话产物",
            extra={
                "session_key": key,
                "artifact_type": artifact_type,
                "artifact_name": name,
                "artifact_path": str(target_path),
            },
        )
        return artifact_record

    def read_artifact_path(self, key: str, artifact_id: str) -> Path | None:
        """根据产物编号返回安全的产物文件路径。

        中文说明：
        先按 id 找到产物记录，再把记录里保存的路径做一次安全校验：路径解析后
        必须仍然位于当前会话目录内，并且文件确实存在，否则返回 None。这样即使
        历史数据里存了越界路径或被删除的文件，下载接口也不会把它读出去。
        """

        session = self.get(key)
        artifact = next(
            (item for item in session.artifacts if str(item.get("id") or "") == artifact_id),
            None,
        )
        if artifact is None:
            return None
        raw_path = str(artifact.get("path") or "").strip()
        if not raw_path:
            return None
        session_dir = (self.backend.sessions_dir / key).resolve()
        resolved = Path(raw_path).resolve(strict=False)
        if not resolved.is_relative_to(session_dir) or not resolved.is_file():
            logger.warning(
                "产物文件路径校验未通过，拒绝提供下载",
                extra={"session_key": key, "artifact_id": artifact_id, "artifact_path": raw_path},
            )
            return None
        return resolved

    def set_workspace_scope(self, key: str, workspace_scope: JsonObject | None) -> JsonObject:
        """更新会话的工作区范围信息。"""

        self.get(key)
        updated_at = utc_now()
        self.backend.update_workspace_scope(key, copy.deepcopy(workspace_scope), updated_at)
        self.backend.append_event(
            session_id=key,
            event_type="workspace_scope_update",
            content="workspace scope updated",
            created_at=updated_at,
            metadata={"workspace_scope": copy.deepcopy(workspace_scope)},
        )
        logger.info("更新会话工作区范围", extra={"session_key": key, "has_workspace_scope": workspace_scope is not None})
        return self.get(key).summary()

    def set_run_started_at(self, key: str, started_at: str | None) -> JsonObject:
        """更新会话当前回合的运行状态时间戳。"""

        self.get(key)
        updated_at = utc_now()
        self.backend.update_run_started_at(key, started_at, updated_at)
        if started_at is not None:
            self.backend.append_event(
                session_id=key,
                event_type="status_change",
                content="running",
                created_at=updated_at,
                metadata={"run_started_at": started_at},
            )
        logger.debug(
            "更新会话运行状态",
            extra={"session_key": key, "run_started_at": started_at, "is_running": started_at is not None},
        )
        return self.get(key).summary()

    def set_status(self, key: str, status: str) -> JsonObject:
        """显式更新会话状态，并同步写入状态变更事件。"""

        self.get(key)
        updated_at = utc_now()
        self.backend.update_status(key, status, updated_at)
        self.backend.append_event(
            session_id=key,
            event_type="status_change",
            content=status,
            created_at=updated_at,
            metadata={"status": status},
        )
        logger.info("更新会话状态", extra={"session_key": key, "status": status})
        return self.get(key).summary()

    def _bootstrap_initial_sessions(self, initial: list[JsonObject]) -> None:
        """把初始会话列表导入持久化后端。"""

        for item in initial:
            key = str(item.get("key") or create_readable_id())
            created_at = str(item.get("created_at") or utc_now())
            updated_at = str(item.get("updated_at") or created_at)
            workspace_scope = copy.deepcopy(item.get("workspace_scope"))
            self.backend.create_session(
                session_id=key,
                title=str(item.get("title") or "New chat"),
                created_at=created_at,
                updated_at=updated_at,
                user_id=str(item.get("user_id") or self.default_user_id),
                workspace_scope=workspace_scope,
                metadata=copy.deepcopy(item.get("metadata") or {"schema_version": 1}),
                status=str(item.get("status") or "created"),
            )
            for message in item.get("messages") or []:
                self.backend.append_message(
                    session_id=key,
                    message_id=str(message.get("id") or uuid.uuid4().hex),
                    role=str(message.get("role") or "user"),
                    content=str(message.get("content") or ""),
                    created_at=str(message.get("created_at") or utc_now()),
                    parent_id=message.get("parent_id"),
                    metadata={
                        entry_key: copy.deepcopy(entry_value)
                        for entry_key, entry_value in message.items()
                        if entry_key not in {"id", "role", "content", "created_at", "parent_id"}
                    },
                )

    def _hydrate_record(self, payload: JsonObject) -> SessionRecord:
        """把底层后端读取出的原始字典组装成 `SessionRecord`。"""

        messages = self.backend.list_messages(payload["key"])
        events = self.backend.list_events(payload["key"])
        artifacts = self.backend.list_artifacts(payload["key"])
        return SessionRecord(
            key=payload["key"],
            title=str(payload.get("title") or "New chat"),
            created_at=str(payload.get("created_at") or utc_now()),
            updated_at=str(payload.get("updated_at") or utc_now()),
            status=str(payload.get("status") or "created"),
            summary_text=str(payload.get("summary") or ""),
            messages=messages,
            events=events,
            artifacts=artifacts,
            workspace_scope=copy.deepcopy(payload.get("workspace_scope")),
            run_started_at=payload.get("run_started_at"),
            user_id=str(payload.get("user_id") or self.default_user_id),
            last_message_at=payload.get("last_message_at"),
            metadata=copy.deepcopy(payload.get("metadata") or {}),
            archived=bool(payload.get("archived", False)),
        )

    def _rename_if_default_title(self, key: str, title: str) -> None:
        """当新会话首次收到用户输入时，用输入摘要替换默认标题。"""

        record = self.get(key)
        if record.title != "New chat" and record.title.strip():
            return
        raw_session = self.backend.get_session(key)
        metadata = dict((raw_session or {}).get("metadata") or {})
        self.backend.update_title(key, title, utc_now())
        self.backend.append_event(
            session_id=key,
            event_type="summary_update",
            content=title,
            created_at=utc_now(),
            metadata={"title": title, **metadata},
        )
