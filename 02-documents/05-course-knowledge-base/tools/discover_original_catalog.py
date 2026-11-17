"""Read the author's ten public economics-category index pages."""
import concurrent.futures
import json
import re
from pathlib import Path
from collect_sources import request, DOM, clean
from collect_originals import canonical

ROOT = Path(__file__).resolve().parents[1]


def read_page(page):
    url = f"https://blog.sina.com.cn/s/articlelist_1215172700_10_{page}.html"
    status, final, ct, raw = request(url)
    out = ROOT / "sources/originals/catalog"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"page-{page:02}.html").write_bytes(raw)
    links = []
    for node in DOM(raw.decode("utf-8")).root.walk():
        if node.tag != "a":
            continue
        found = re.search(r"教你炒股票\s*(\d+)", node.text())
        target = canonical(node.attrs.get("href", ""))
        if found and target and 1 <= int(found[1]) <= 108:
            links.append({"number": int(found[1]), "catalog_title": clean(node.text()), "url": target, "catalog_url": url})
    return page, links


def main():
    entries = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        for page, links in pool.map(read_page, range(1, 11)):
            print("catalog", page, "course links", len(links), flush=True)
            for link in links:
                entries[link["number"]] = link
    result = sorted(entries.values(), key=lambda item: item["number"])
    (ROOT / "sources/originals/catalog-links.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"found": len(result), "missing": sorted(set(range(1,109)) - set(entries))}), flush=True)


if __name__ == "__main__":
    main()
