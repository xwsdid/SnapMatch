from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import xml.etree.ElementTree as ET


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def qn(tag: str) -> str:
    return f"{{{W_NS}}}{tag}"


def normalize_ws(text: str) -> str:
    text = text.replace("\u3000", " ")
    text = re.sub(r"[ \t\r\n]+", " ", text)
    return text.strip()


def para_text(p: ET.Element) -> str:
    parts: List[str] = []
    for t in p.iter(qn("t")):
        if t.text:
            parts.append(t.text)
    return normalize_ws("".join(parts))


def para_style(p: ET.Element) -> str:
    ppr = p.find(qn("pPr"))
    if ppr is None:
        return ""
    ps = ppr.find(qn("pStyle"))
    if ps is None:
        return ""
    return ps.attrib.get(qn("val")) or ps.attrib.get("val") or ""


def estimate_cn_chars(text: str) -> int:
    text = normalize_ws(text)
    return sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")


@dataclass
class ParagraphInfo:
    idx: int
    style: str
    text: str


def load_paragraphs(document_xml: Path) -> List[ParagraphInfo]:
    tree = ET.parse(document_xml)
    root = tree.getroot()
    body = root.find(qn("body"))
    if body is None:
        return []
    paras: List[ParagraphInfo] = []
    idx = 0
    for p in body.findall(qn("p")):
        text = para_text(p)
        style = para_style(p)
        paras.append(ParagraphInfo(idx=idx, style=style, text=text))
        idx += 1
    return paras


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python docx_section_report.py <unzipped_docx_dir>")
        return 2

    base = Path(sys.argv[1]).resolve()
    document_xml = base / "word" / "document.xml"
    if not document_xml.exists():
        print(f"Missing document.xml under: {base}")
        return 2

    paras = load_paragraphs(document_xml)

    # Heuristic:
    # style '2' appears to be centered一级标题; style '3' 二级标题; others正文。
    headings: List[Dict[str, object]] = []
    for p in paras:
        if p.style in {"2", "3", "4"} and p.text:
            # include as outline nodes
            headings.append(
                {
                    "paragraph_index": p.idx,
                    "style": p.style,
                    "title": p.text,
                    "cn_chars": estimate_cn_chars(p.text),
                }
            )

    # Build top-level sections based on style '2'
    sections: List[Dict[str, object]] = []
    top = [h for h in headings if h["style"] == "2"]
    for i, h in enumerate(top):
        start = int(h["paragraph_index"])
        end = int(top[i + 1]["paragraph_index"]) - 1 if i + 1 < len(top) else paras[-1].idx
        text_parts: List[str] = []
        for p in paras[start + 1 : end + 1]:
            if p.text:
                text_parts.append(p.text)
        merged = "\n".join(text_parts)
        sections.append(
            {
                "title": h["title"],
                "start_paragraph_index": start,
                "end_paragraph_index": end,
                "cn_chars": estimate_cn_chars(merged),
                "preview": normalize_ws(merged)[:240],
            }
        )

    print(json.dumps({"headings": headings, "top_sections": sections}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
