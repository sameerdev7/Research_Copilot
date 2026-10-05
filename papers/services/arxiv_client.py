from __future__ import annotations

from dataclasses import dataclass
from xml.etree import ElementTree

import requests

ARXIV_API_URL = "http://export.arxiv.org/api/query"
ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}
REQUEST_TIMEOUT = 15


@dataclass
class ArxivPaper:
    arxiv_id: str
    title: str
    authors: list[str]
    abstract: str
    pdf_url: str

    def as_dict(self) -> dict:
        return {
            "arxiv_id": self.arxiv_id,
            "title": self.title,
            "authors": self.authors,
            "abstract": self.abstract,
            "pdf_url": self.pdf_url,
        }


def _clean(text: str | None) -> str:
    return " ".join((text or "").split())


def _parse_entry(entry: ElementTree.Element) -> ArxivPaper:
    raw_id = _clean(entry.findtext("atom:id", default="", namespaces=ATOM_NS))
    # raw_id looks like http://arxiv.org/abs/2401.01234v2
    arxiv_id = raw_id.rsplit("/", 1)[-1]

    title = _clean(entry.findtext("atom:title", default="", namespaces=ATOM_NS))
    abstract = _clean(entry.findtext("atom:summary", default="", namespaces=ATOM_NS))

    authors = [
        _clean(author.findtext("atom:name", default="", namespaces=ATOM_NS))
        for author in entry.findall("atom:author", ATOM_NS)
    ]

    pdf_url = ""
    for link in entry.findall("atom:link", ATOM_NS):
        if link.get("title") == "pdf" or link.get("type") == "application/pdf":
            pdf_url = link.get("href", "")
            break
    if not pdf_url and arxiv_id:
        pdf_url = f"https://arxiv.org/pdf/{arxiv_id}"

    return ArxivPaper(arxiv_id=arxiv_id, title=title, authors=authors, abstract=abstract, pdf_url=pdf_url)


def _query(params: dict) -> list[ArxivPaper]:
    response = requests.get(ARXIV_API_URL, params=params, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    root = ElementTree.fromstring(response.content)
    return [_parse_entry(entry) for entry in root.findall("atom:entry", ATOM_NS)]


# search arXiv by topic
def search(query: str, max_results: int = 10) -> list[dict]:
    papers = _query(
        {
            "search_query": f"all:{query}",
            "start": 0,
            "max_results": max_results,
            "sortBy": "relevance",
            "sortOrder": "descending",
        }
    )
    return [p.as_dict() for p in papers]


# fetch metadata for explicit arXiv ids
def get_by_ids(arxiv_ids: list[str]) -> list[dict]:
    if not arxiv_ids:
        return []
    papers = _query({"id_list": ",".join(arxiv_ids), "max_results": len(arxiv_ids)})
    return [p.as_dict() for p in papers]
