from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import List

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


def main() -> int:
    if len(sys.argv) < 4:
        print(
            "Usage: python docx_dump_paragraphs.py <unzipped_docx_dir> <start_idx> <end_idx> [--out <path>]"
        )
        return 2

    base = Path(sys.argv[1]).resolve()
    start = int(sys.argv[2])
    end = int(sys.argv[3])
    out_path: Path | None = None
    if len(sys.argv) >= 6 and sys.argv[4] == "--out":
        out_path = Path(sys.argv[5]).resolve()

    document_xml = base / "word" / "document.xml"
    tree = ET.parse(document_xml)
    root = tree.getroot()
    body = root.find(qn("body"))
    if body is None:
        return 1
    paras = body.findall(qn("p"))

    start = max(0, start)
    end = min(len(paras) - 1, end)
    lines: List[str] = []
    for i in range(start, end + 1):
        p = paras[i]
        txt = para_text(p)
        sty = para_style(p)
        if not txt:
            continue
        lines.append(f"[{i:04d}] style={sty or '-'}  {txt}")

    content = "\n".join(lines) + ("\n" if lines else "")
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(content, encoding="utf-8")
    else:
        sys.stdout.write(content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
