from __future__ import annotations

import httpx

from ..models import PaperDocument, SearchRequest
from .base import PaperSearchConnector


class ElsevierPaperConnector(PaperSearchConnector):
    """Elsevier Scopus 官方检索接口。"""

    source_name = "elsevier_scopus"
    _endpoint = "https://api.elsevier.com/content/search/scopus"

    def __init__(self, api_key: str | None = None, client: httpx.Client | None = None):
        """初始化 Elsevier 客户端。"""

        self.api_key = (api_key or "").strip()
        self.client = client or httpx.Client(timeout=30.0)

    @property
    def configured(self) -> bool:
        """返回是否已经配置 Elsevier API Key。"""

        return bool(self.api_key)

    def search(self, request: SearchRequest) -> list[PaperDocument]:
        """调用 Scopus Search API 并转换结果。"""

        if not self.configured:
            raise RuntimeError("Elsevier 未配置 API Key，请在 config/system.yaml 中填写 elsevier_api_key")
        response = self.client.get(self._endpoint, params=self._params(request), headers=self._headers())
        response.raise_for_status()
        return self._parse_payload(response.json(), request)

    async def async_search(
        self,
        request: SearchRequest,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> list[PaperDocument]:
        """异步调用 Scopus Search API。"""

        if not self.configured:
            raise RuntimeError("Elsevier 未配置 API Key，请在 config/system.yaml 中填写 elsevier_api_key")
        resolved_client = client or httpx.AsyncClient(timeout=30.0)
        owns_client = client is None
        try:
            response = await resolved_client.get(
                self._endpoint,
                params=self._params(request),
                headers=self._headers(),
                timeout=30.0,
            )
        finally:
            if owns_client:
                await resolved_client.aclose()
        response.raise_for_status()
        return self._parse_payload(response.json(), request)

    def _headers(self) -> dict[str, str]:
        """构造 Elsevier API 请求头。"""

        return {
            "X-ELS-APIKey": self.api_key,
            "Accept": "application/json",
            "User-Agent": "papers-agents/0.1 paper-retrieval",
        }

    def _params(self, request: SearchRequest) -> dict[str, str | int]:
        """构造 Scopus 查询参数。"""

        raw_query = request.query.strip() or request.keyword_expression.strip() or request.topic.strip()
        if not raw_query:
            raw_query = " ".join(request.keywords[:5])
        if request.query.strip():
            query = f'TITLE("{request.query.strip().replace(chr(34), "")}")'
        else:
            query = f"TITLE-ABS-KEY({raw_query})"
        return {"query": query, "count": max(1, request.limit), "start": 0}

    def _parse_payload(self, payload: dict[str, object], request: SearchRequest) -> list[PaperDocument]:
        """解析 Scopus search-results.entries。"""

        root = payload.get("search-results") or {}
        entries = root.get("entry", []) if isinstance(root, dict) else []
        papers: list[PaperDocument] = []
        for raw in entries or []:
            paper = self._normalize_paper(raw)
            if paper is None or self._contains_excluded_terms(paper, request.excluded_terms):
                continue
            if request.year_from is not None and paper.year is not None and paper.year < request.year_from:
                continue
            if request.year_to is not None and paper.year is not None and paper.year > request.year_to:
                continue
            papers.append(paper)
        return papers[: request.limit]

    def _normalize_paper(self, raw: object) -> PaperDocument | None:
        """把 Scopus 的单条记录转换为统一论文对象。"""

        if not isinstance(raw, dict):
            return None
        title = str(raw.get("dc:title") or "").strip()
        if not title:
            return None
        doi = str(raw.get("prism:doi") or "").strip()
        eid = str(raw.get("eid") or "").strip()
        paper_id = doi or eid or title
        creator = str(raw.get("dc:creator") or "").strip()
        cover_date = str(raw.get("prism:coverDate") or "").strip()
        return PaperDocument(
            id=paper_id,
            paperId=paper_id,
            title=title,
            authors=[creator] if creator else [],
            abstract=str(raw.get("dc:description") or "").strip() or None,
            year=_optional_int(cover_date[:4]),
            venue=str(raw.get("prism:publicationName") or "").strip() or None,
            url=f"https://doi.org/{doi}" if doi else str(raw.get("prism:url") or "").strip() or None,
            doi=doi or None,
            source=self.source_name,
            publication_date=cover_date,
            metadata={"scopus_id": eid},
        )

    def _contains_excluded_terms(self, paper: PaperDocument, excluded_terms: list[str]) -> bool:
        """按标题和摘要过滤排除词。"""

        haystack = f"{paper.title} {paper.abstract or ''}".lower()
        return any(term.strip().lower() in haystack for term in excluded_terms if term.strip())


def _optional_int(value: object) -> int | None:
    """安全转换年份。"""

    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None
