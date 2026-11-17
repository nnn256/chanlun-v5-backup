"""Fetch the public Chinese learning pages listed by Struct Guide's sitemap.

No login, plugin installation, video download, or market-data collection.
Raw responses, extracted article text, and link metadata form a source cache.
"""
from __future__ import annotations

import concurrent.futures
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://www.structguide.com"
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


class Node:
    def __init__(self, tag="root", attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []

    def walk(self):
        yield self
        for child in self.children:
            if isinstance(child, Node):
                yield from child.walk()

    def text(self):
        if self.tag in {"script", "style", "noscript"} or "header-anchor" in self.attrs.get("class", ""):
            return ""
        return "".join(c.text() if isinstance(c, Node) else c for c in self.children).replace("\u200b", "")


class DOM(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.stack = [self.root]
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def clean(value):
    return re.sub(r"[ \t\r\f\v]+", " ", value).strip()


def markdown(node, base):
    if isinstance(node, str):
        return node
    tag = node.tag
    if tag in {"script", "style", "noscript"} or "header-anchor" in node.attrs.get("class", ""):
        return ""
    if tag == "table":
        rows = []
        for row in node.walk():
            if row.tag == "tr":
                cells = [clean(c.text()).replace("|", "\\|") for c in row.children if isinstance(c, Node) and c.tag in {"td", "th"}]
                if cells:
                    rows.append(cells)
        if not rows:
            return ""
        n = max(map(len, rows))
        rows = [r + [""] * (n - len(r)) for r in rows]
        lines = ["| " + " | ".join(r) + " |" for r in rows]
        lines.insert(1, "| " + " | ".join(["---"] * n) + " |")
        return "\n\n" + "\n".join(lines) + "\n\n"
    if tag == "pre":
        return "\n\n```text\n" + node.text().strip() + "\n```\n\n"
    if tag == "svg":
        return "\n[SVG图中文字：" + clean(node.text()) + "]\n"
    if tag == "img":
        return "\n![" + node.attrs.get("alt", "原页插图") + "](" + urllib.parse.urljoin(base, node.attrs.get("src", "")) + ")\n"
    value = "".join(markdown(c, base) for c in node.children)
    if tag == "a" and clean(node.text()):
        return "[" + clean(value) + "](" + urllib.parse.urljoin(base, node.attrs.get("href", "")) + ")"
    if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
        return "\n\n" + "#" * int(tag[1]) + " " + clean(value) + "\n\n"
    if tag == "li":
        return "\n- " + value.strip() + "\n"
    if tag in {"p", "div", "section", "article", "ul", "ol", "blockquote", "figure", "figcaption", "details", "summary"}:
        return "\n\n" + value.strip() + "\n\n"
    if tag == "br":
        return "\n"
    if tag == "code":
        return "`" + value + "`"
    return value


def request(url):
    req = urllib.request.Request(url, headers={"User-Agent": "ChanlunStudyNotebook/1.0 (public educational pages)", "Accept": "text/html,application/xml,text/plain"})
    with urllib.request.urlopen(req, timeout=35) as response:
        return response.status, response.url, response.headers.get("Content-Type", ""), response.read()


def collect(url, lastmod):
    path = urllib.parse.urlsplit(url).path.strip("/") or "home"
    stem = path.replace("/", "__")
    result = {"url": url, "sitemap_lastmod": lastmod, "retrieved_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")}
    try:
        status, final_url, content_type, raw = request(url)
        html = raw.decode("utf-8-sig")
        dom = DOM(html)
        nodes = list(dom.root.walk())
        article = next((n for n in nodes if "vp-doc" in n.attrs.get("class", "").split()), None)
        if article is None:
            article = next((n for n in nodes if n.tag == "main"), None)
        if article is None:
            raise ValueError("No article or main element; extraction not accepted")
        title = next((clean(n.text()) for n in article.walk() if n.tag == "h1"), "")
        text = re.sub(r"\n[ \t]*\n(?:[ \t]*\n)+", "\n\n", markdown(article, final_url)).strip()
        if len(text) < 150 or not title:
            raise ValueError("Article too short or no h1")
        raw_path = ROOT / "sources" / "raw" / f"{stem}.html"
        text_path = ROOT / "sources" / "text" / f"{stem}.md"
        raw_path.write_bytes(raw)
        text_path.write_text(f"来源：{final_url}\n抓取：{result['retrieved_at']}\n\n{text}\n", encoding="utf-8")
        links = [{"text": clean(n.text()), "url": urllib.parse.urljoin(final_url, n.attrs["href"])} for n in article.walk() if n.tag == "a" and n.attrs.get("href") and clean(n.text())]
        result.update(status="ok", http_status=status, final_url=final_url, title=title, content_type=content_type, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(), raw_file=raw_path.relative_to(ROOT).as_posix(), text_file=text_path.relative_to(ROOT).as_posix(), text_chars=len(text), links=links)
    except Exception as exc:
        result.update(status="failed", error=f"{type(exc).__name__}: {exc}")
    return result


def main():
    for name in ["sources/raw", "sources/text", "notes", "tools"]:
        (ROOT / name).mkdir(parents=True, exist_ok=True)
    _, _, _, robots = request(BASE + "/robots.txt")
    _, _, _, sitemap = request(BASE + "/sitemap.xml")
    (ROOT / "sources/robots.txt").write_bytes(robots)
    (ROOT / "sources/sitemap.xml").write_bytes(sitemap)
    tree = ET.fromstring(sitemap)
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    targets = []
    for node in tree.findall("s:url", ns):
        url = node.findtext("s:loc", namespaces=ns)
        path = urllib.parse.urlsplit(url).path
        if path == "/" or path.startswith(("/en/", "/zh-tw/")) or path in {"/privacy", "/terms"}:
            continue
        targets.append((url, node.findtext("s:lastmod", namespaces=ns)))
    manifest = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(collect, *item): item[0] for item in targets}
        for future in concurrent.futures.as_completed(futures):
            item = future.result()
            manifest.append(item)
            print(item["status"], item["url"], item.get("text_chars", item.get("error", "")), flush=True)
    manifest.sort(key=lambda item: item["url"])
    (ROOT / "sources/manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"pages": len(manifest), "ok": sum(i["status"] == "ok" for i in manifest), "failed": [i for i in manifest if i["status"] != "ok"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
