from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

import xml.etree.ElementTree as ET


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def qn(tag: str) -> str:
    return f"{{{W_NS}}}{tag}"


def iter_text(node: ET.Element) -> str:
    parts: List[str] = []
    for t in node.iter(qn("t")):
        if t.text:
            parts.append(t.text)
    return "".join(parts)


def normalize_whitespace(text: str) -> str:
    text = text.replace("\u3000", " ")
    text = re.sub(r"[ \t\r\n]+", " ", text)
    return text.strip()


def estimate_counts(text: str) -> Dict[str, int]:
    text = normalize_whitespace(text)
    if not text:
        return {"chars": 0, "cn_chars": 0, "words": 0}
    chars = len(text)
    cn_chars = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    words = len([w for w in re.split(r"\s+", text) if w])
    return {"chars": chars, "cn_chars": cn_chars, "words": words}


def parse_comments(comments_xml: Path) -> Dict[str, Dict[str, str]]:
    tree = ET.parse(comments_xml)
    root = tree.getroot()

    comments: Dict[str, Dict[str, str]] = {}
    for c in root.findall(qn("comment")):
        cid = c.attrib.get(qn("id")) or c.attrib.get("id")
        if cid is None:
            continue
        author = c.attrib.get(qn("author")) or c.attrib.get("author") or ""
        date = c.attrib.get(qn("date")) or c.attrib.get("date") or ""
        text = normalize_whitespace(iter_text(c))
        comments[str(cid)] = {"author": author, "date": date, "text": text}
    return comments


def extract_commented_ranges(document_xml: Path) -> Dict[str, List[Dict[str, object]]]:
    """Return mapping comment_id -> list of ranges, each range contains paragraph indices and text."""

    ranges: Dict[str, List[Dict[str, object]]] = defaultdict(list)
    active: List[str] = []

    para_index = -1
    para_text_parts: List[Tuple[str, List[str]]] = []  # (text, active_ids_snapshot)
    para_ids_seen: set[str] = set()

    def flush_paragraph() -> None:
        nonlocal para_text_parts, para_ids_seen
        if para_index < 0:
            return
        if not para_text_parts:
            para_ids_seen = set()
            return

        for cid in para_ids_seen:
            seg_parts: List[str] = []
            for text, ids in para_text_parts:
                if cid in ids and text:
                    seg_parts.append(text)
            seg = normalize_whitespace("".join(seg_parts))
            if seg:
                ranges[cid].append(
                    {
                        "paragraph_index": para_index,
                        "text": seg,
                        "counts": estimate_counts(seg),
                    }
                )

        para_text_parts = []
        para_ids_seen = set()

    context = ET.iterparse(document_xml, events=("start", "end"))
    for event, elem in context:
        tag = elem.tag
        if event == "start" and tag == qn("p"):
            flush_paragraph()
            para_index += 1
            para_text_parts = []
            para_ids_seen = set()

        if event == "start" and tag == qn("commentRangeStart"):
            cid = elem.attrib.get(qn("id")) or elem.attrib.get("id")
            if cid is not None:
                active.append(str(cid))

        if event == "start" and tag == qn("commentRangeEnd"):
            cid = elem.attrib.get(qn("id")) or elem.attrib.get("id")
            if cid is not None:
                s = str(cid)
                if s in active:
                    for i in range(len(active) - 1, -1, -1):
                        if active[i] == s:
                            active.pop(i)
                            break

        if event == "end" and tag == qn("t"):
            if elem.text:
                snapshot = list(active)
                para_text_parts.append((elem.text, snapshot))
                for cid in snapshot:
                    para_ids_seen.add(cid)

        if event == "end":
            elem.clear()

    flush_paragraph()
    return ranges


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python docx_comments_report.py <unzipped_docx_dir>")
        return 2

    base = Path(sys.argv[1]).resolve()
    comments_xml = base / "word" / "comments.xml"
    document_xml = base / "word" / "document.xml"
    if not comments_xml.exists() or not document_xml.exists():
        print(f"Missing comments.xml or document.xml under: {base}")
        return 2

    comments = parse_comments(comments_xml)
    ranges = extract_commented_ranges(document_xml)

    out: Dict[str, object] = {"doc": str(base), "comments": []}
    all_ids = set(comments.keys()) | set(ranges.keys())

    def sort_key(x: str):
        return int(x) if x.isdigit() else x

    for cid in sorted(all_ids, key=sort_key):
        c = comments.get(cid, {"author": "", "date": "", "text": ""})
        r = ranges.get(cid, [])
        merged = "\n".join([x["text"] for x in r])
        out["comments"].append(
            {
                "id": cid,
                **c,
                "target_ranges": r,
                "target_merged_text": normalize_whitespace(merged),
                "target_merged_counts": estimate_counts(merged),
            }
        )

    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
