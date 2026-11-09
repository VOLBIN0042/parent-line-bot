"""將公開 PDF 轉成 LINE Bot 使用的索引，需另外安裝 PyMuPDF。"""
import argparse
import gzip
import json
from pathlib import Path
import re

import pymupdf


def page_chunks(text):
    # 避免把同頁的不同參數混成一筆。長段落以重疊視窗保留前後文。
    sections = re.split(r"(?=■\s*[A-Za-z]\d{1,2}[-－]\d{2})", text)
    for section in sections:
        section = section.strip()
        for start in range(0, len(section), 1450):
            yield section[start:start + 1700]
            if start + 1700 >= len(section):
                break


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sources", type=Path, nargs="+", help="PDF 檔案或含 PDF 的資料夾")
    parser.add_argument("--output", type=Path, default=Path("manuals.json.gz"))
    args = parser.parse_args()
    files = sorted({p.resolve() for src in args.sources for p in (
        src.glob("*.pdf") if src.is_dir() else [src]
    )})
    if not files:
        parser.error("找不到 PDF")
    chunks = []
    for path in files:
        model = re.search(r"[A-Za-z]+\d+[A-Za-z0-9]*", path.stem)
        model = model[0].upper() if model else ""
        start = len(chunks)
        with pymupdf.open(path) as pdf:
            empty_pages = 0
            for page in pdf:
                body = page.get_text().strip()
                if not body:
                    empty_pages += 1
                    continue
                for part in page_chunks(body):
                    chunks.append({"source": path.name, "model": model,
                                   "page": page.number + 1, "text": part})
            if len(chunks) == start:
                parser.error(f"{path.name} 無可擷取文字，請先做 OCR")
            print(f"{path.name}：{len(pdf)} 頁、{len(chunks) - start} 個片段、{empty_pages} 頁無文字")
    # 完成擷取後才取代上一版索引。
    payload = json.dumps(chunks, ensure_ascii=False, separators=(",", ":")).encode()
    temp = args.output.with_suffix(args.output.suffix + ".tmp")
    temp.write_bytes(gzip.compress(payload, mtime=0))
    temp.replace(args.output)


if __name__ == "__main__":
    main()
