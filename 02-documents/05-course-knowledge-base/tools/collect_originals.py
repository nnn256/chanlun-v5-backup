"""Follow numbered course links on the author's public Sina blog.

Only author 486e105c and course numbers 1..108 are followed. Seed links
come from Struct Guide's verified article links; supplemental posts stay
separately labelled. A successful HTTP response alone is not acceptance.
"""
import concurrent.futures
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo

from collect_sources import DOM, clean, markdown, request

ROOT = Path(__file__).resolve().parents[1]


def canonical(url):
    match = re.search(r"(?:blog_|/u/)(486e105c[0-9a-z]+)", url)
    return f"https://blog.sina.com.cn/s/blog_{match[1]}.html" if match else None


def fetch(url):
    result = {"url": url, "retrieved_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")}
    try:
        status, final, content_type, raw = request(url)
        dom = DOM(raw.decode("utf-8"))
        nodes = list(dom.root.walk())
        title_node = next(n for n in nodes if "articalTitle" in n.attrs.get("class", "").split())
        title = clean(title_node.text())
        article = next(n for n in nodes if "articalContent" in n.attrs.get("class", "").split())
        text = re.sub(r"\n[ \t]*\n(?:[ \t]*\n)+", "\n\n", markdown(article, final)).strip()
        if len(text) < 150:
            raise ValueError("Missing article body")
        match = re.search(r"教你炒股票\s*(\d+)", title)
        number = int(match[1]) if match else None
        stem = f"lesson-{number:03d}" if number else "supplement-" + url.split("blog_")[-1].split(".")[0]
        raw_file = ROOT / "sources/originals/raw" / (stem + ".html")
        text_file = ROOT / "sources/originals/text" / (stem + ".md")
        raw_file.write_bytes(raw)
        text_file.write_text(f"# {title}\n\n来源：{url}\n抓取：{result['retrieved_at']}\n\n{text}\n", encoding="utf-8")
        discovered = []
        for node in nodes:
            if node.tag != "a" or not node.attrs.get("href"):
                continue
            found = re.search(r"教你炒股票\s*(\d+)", node.text())
            link = canonical(node.attrs["href"])
            if found and link and 1 <= int(found[1]) <= 108:
                discovered.append({"number": int(found[1]), "title": clean(node.text()), "url": link})
        images = [{"alt": n.attrs.get("alt", ""), "url": n.attrs.get("real_src") or n.attrs.get("src", "")} for n in article.walk() if n.tag == "img"]
        result.update(status="ok", http_status=status, title=title, number=number, content_type=content_type, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(), text_chars=len(text), raw_file=raw_file.relative_to(ROOT).as_posix(), text_file=text_file.relative_to(ROOT).as_posix(), discovered=discovered, images=images)
    except Exception as exc:
        result.update(status="failed", error=f"{type(exc).__name__}: {exc}")
    return result


def main():
    for folder in ["sources/originals/raw", "sources/originals/text"]:
        (ROOT / folder).mkdir(parents=True, exist_ok=True)
    manifest_file = ROOT / "sources/originals/manifest.json"
    manifest = json.loads(manifest_file.read_text(encoding="utf-8")) if manifest_file.exists() else []
    visited = {item["url"] for item in manifest}
    seeds = {"https://blog.sina.com.cn/s/blog_486e105c01000461.html"}
    source_manifest = json.loads((ROOT / "sources/manifest.json").read_text(encoding="utf-8"))
    for item in source_manifest:
        if item["url"].endswith("/faq/how-to-read-108") or "/concept/" in item["url"]:
            seeds.update(canonical(link["url"]) for link in item.get("links", []) if canonical(link["url"]))
    for item in manifest:
        seeds.update(link["url"] for link in item.get("discovered", []))
    catalog_file = ROOT / "sources/originals/catalog-links.json"
    if catalog_file.exists():
        seeds.update(item["url"] for item in json.loads(catalog_file.read_text(encoding="utf-8")))
    frontier = sorted(seeds - visited)
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        while frontier and len(visited) < 140:
            pending = {pool.submit(fetch, url): url for url in frontier}
            next_frontier = set()
            for future in concurrent.futures.as_completed(pending):
                item = future.result()
                visited.add(item["url"])
                manifest.append(item)
                next_frontier.update(link["url"] for link in item.get("discovered", []))
                print(item["status"], item.get("number"), item.get("title", item.get("error")), flush=True)
                manifest_file.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            frontier = sorted(next_frontier - visited)
    numbers = {i["number"] for i in manifest if i.get("status") == "ok" and i.get("number")}
    print(json.dumps({"numbered_courses": len(numbers), "missing": sorted(set(range(1,109))-numbers), "failed": [i for i in manifest if i.get("status") != "ok"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
