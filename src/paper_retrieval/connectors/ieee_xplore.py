from __future__ import annotations

import httpx

from ..models import PaperDocument, SearchRequest
from .base import PaperSearchConnector


class IeeeXplorePaperConnector(PaperSearchConnector):
    """IEEE Xplore 官方检索接口。"""

    source_name = "ieee_xplore"
    _endpoint = "https://ieeexploreapi.ieee.org/api/v1/search/articles"

    def __init__(self, api_key: str | None = None, client: httpx.Client | None = None):
        """初始化 IEEE Xplore 客户端；没有 API Key 时保留连接器但不参与默认全源检索。"""

        self.api_key = (api_key or "").strip()
        self.client = client or httpx.Client(timeout=30.0)

    @property
    def configured(self) -> bool:
        """返回是否已经配置 IEEE Xplore API Key。"""

        return bool(self.api_key)

    def search(self, request: SearchRequest) -> list[PaperDocument]:
        """调用 IEEE Xplore API 并转换为统一论文对象。"""

        if not self.configured:
            raise RuntimeError("IEEE Xplore 未配置 API Key，请在 config/system.yaml 中填写 ieee_xplore_api_key")
        response = self.client.get(self._endpoint, params=self._params(request))
        response.raise_for_status()
        return self._parse_payload(response.json(), request)

    async def async_search(
        self,
        request: SearchRequest,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> list[PaperDocument]:
        """异步调用 IEEE Xplore API。"""

        if not self.configured:
            raise RuntimeError("IEEE Xplore 未配置 API Key，请在 config/system.yaml 中填写 ieee_xplore_api_key")
        resolved_client = client or httpx.AsyncClient(timeout=30.0)
        owns_client = client is None
        try:
            response = await resolved_client.get(self._endpoint, params=self._params(request), timeout=30.0)
        finally:
            if owns_client:
                await resolved_client.aclose()
        response.raise_for_status()
        return self._parse_payload(response.json(), request)

    def _params(self, request: SearchRequest) -> dict[str, str | int]:
        """构造 IEEE Xplore API 参数。"""

        query = request.query.strip() or request.keyword_expression.strip() or request.topic.strip()
        if not query:
            query = " ".join(request.keywords[:5])
        return {
            "apikey": self.api_key,
            "querytext": query,
            "max_records": max(1, request.limit),
            "start_record": 1,
        }

    def _parse_payload(self, payload: dict[str, object], request: SearchRequest) -> list[PaperDocument]:
        """解析 IEEE Xplore 返回的 articles 列表。"""

        papers: list[PaperDocument] = []
        for raw in payload.get("articles", []) or []:
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
        """把 IEEE Xplore 的单条记录转换为统一论文对象。"""

        if not isinstance(raw, dict):
            return None
        title = str(raw.get("title") or "").strip()
        if not title:
            return None
        authors: list[str] = []
        author_data = raw.get("authors") or {}
        author_items = author_data.get("authors") if isinstance(author_data, dict) else author_data
        if isinstance(author_items, list):
            for item in author_items:
                if isinstance(item, dict):
                    name = str(item.get("full_name") or item.get("name") or "").strip()
                else:
                    name = str(item).strip()
                if name:
                    authors.append(name)
        doi = str(raw.get("doi") or "").strip()
        article_number = str(raw.get("article_number") or raw.get("document_id") or "").strip()
        paper_id = doi or article_number or title
        return PaperDocument(
            id=paper_id,
            paperId=paper_id,
            title=title,
            authors=authors,
            abstract=str(raw.get("abstract") or "").strip() or None,
            year=_optional_int(raw.get("publication_year") or raw.get("publicationYear")),
            venue=str(raw.get("publication_title") or raw.get("publicationTitle") or "").strip() or None,
            url=str(raw.get("html_url") or raw.get("htmlUrl") or "").strip() or None,
            pdf_url=str(raw.get("pdf_url") or raw.get("pdfUrl") or "").strip() or None,
            doi=doi or None,
            source=self.source_name,
            metadata={"ieee_article_number": article_number},
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
