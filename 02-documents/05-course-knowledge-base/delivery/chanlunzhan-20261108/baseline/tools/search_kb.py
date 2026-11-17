"""Offline, paragraph-based search over notes and verified source extracts."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
ALIASES = {
    "一买": ["一买", "第一类买点"], "二买": ["二买", "第二类买点"],
    "三买": ["三买", "第三类买点"], "一卖": ["一卖", "第一类卖点"],
    "二卖": ["二卖", "第二类卖点"], "三卖": ["三卖", "第三类卖点"],
    "背驰": ["背驰", "背弛"], "背弛": ["背驰", "背弛"],
    "小转大": ["小转大", "小级别转折", "小级别背驰引发"],
}


def search(query, scope="all", limit=10):
    groups = [ALIASES.get(word, [word]) for word in query.casefold().split()]
    if not groups:
        return []
    locations = {
        "notes": [ROOT / "notes"],
        "website": [ROOT / "sources/text"],
        "originals": [ROOT / "sources/originals/text", ROOT / "sources/supplements/text"],
        "reprints": [ROOT / "sources/supplements/text"],
        "all": [ROOT / "notes", ROOT / "sources/text", ROOT / "sources/originals/text", ROOT / "sources/supplements/text"],
    }
    hits = []
    for folder in locations[scope]:
        for path in sorted(folder.glob("*.md")):
            # Paragraph matching keeps multiple query terms in a meaningful context.
            lines = path.read_text(encoding="utf-8").splitlines()
            block, start, heading = [], 1, ""
            for number, line in enumerate(lines + [""], 1):
                if line.startswith("#"):
                    heading = line.lstrip("# ")
                if line.strip() and not line.lstrip().startswith("!["):
                    if not block:
                        start = number
                    block.append(line.strip())
                    continue
                text = " ".join(block)
                block = []
                folded = text.casefold()
                if text and all(any(term in folded for term in variants) for variants in groups):
                    positions = [folded.find(term) for variants in groups for term in variants if term in folded]
                    pos = max(0, min(positions) - 85)
                    excerpt = text[pos:pos + 360]
                    if pos:
                        excerpt = "…" + excerpt
                    if pos + 360 < len(text):
                        excerpt += "…"
                    priority = 100 if folder == ROOT / "notes" else 50 if folder == ROOT / "sources/text" else 20
                    count = sum(min(folded.count(term), 5) for variants in groups for term in variants)
                    hits.append({"file": str(path.resolve()), "line": start, "heading": heading, "excerpt": excerpt, "score": priority + count})
    hits.sort(key=lambda item: (-item["score"], item["file"], item["line"]))
    result, counts = [], {}
    for hit in hits:
        if counts.get(hit["file"], 0) >= 2:
            continue
        counts[hit["file"]] = counts.get(hit["file"], 0) + 1
        result.append(hit)
        if len(result) >= limit:
            break
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query")
    parser.add_argument("--scope", choices=["all", "notes", "website", "originals", "reprints"], default="all")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if not args.query.strip() or args.limit < 1:
        parser.error("query must be nonempty and --limit must be positive")
    result = search(args.query, args.scope, args.limit)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif not result:
        print("未找到同段包含所有关键词的结果；可减少关键词或更换术语。")
    else:
        for hit in result:
            print(f"{hit['file']}:{hit['line']}\n  {hit['heading']}\n  {hit['excerpt']}\n")


if __name__ == "__main__":
    main()
