"""Archive the public static learning sitemap; preserve provenance and limitations.

Uses the existing standard-library HTML parser. Resume validates both saved hashes.
Interactive /practice/, /stocks/ and /data/ paths are never requested.
"""
from __future__ import annotations

import concurrent.futures
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sys
import time
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

from collect_sources import DOM, clean, markdown

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "sources/chanlunzhan"
BASE = "https://chanlunzhan.com"
AGENT = "ChanlunStudyNotebook/1.0"


def stamp():
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def get(url):
    req = Request(url, headers={"User-Agent": AGENT, "Accept": "text/html,application/xml,text/plain"})
    with urlopen(req, timeout=30) as response:
        return response.status, response.url, response.headers.get("Content-Type", ""), response.read()


def kind(url):
    pieces = urlsplit(url).path.strip("/").split("/")
    if pieces[0] == "learn":
        return "lesson" if len(pieces) == 3 else "stage" if len(pieces) == 2 else "catalog"
    if pieces[0] == "glossary":
        return "glossary" if len(pieces) == 2 else "catalog"
    if pieces[0] == "108":
        return "original_reprint" if len(pieces) == 2 else "catalog"
    return "site_info"


def valid_cached(record):
    if record.get("status") != "ok":
        return False
    return all((ROOT / record[key]).is_file() and sha((ROOT / record[key]).read_bytes()) == record[digest]
               for key, digest in [("raw_file", "sha256"), ("text_file", "text_sha256")])


def collect(url, lastmod):
    path = urlsplit(url).path.strip("/") or "home"
    stem = path.replace("/", "__")
    rec = {"url": url, "category": kind(url), "sitemap_lastmod": lastmod, "retrieved_at": stamp()}
    try:
        # Reuse the two initial evidence probes instead of requesting them again.
        probe = DEST / f"{path}.html"
        if path in {"about", "learn"} and probe.exists():
            raw = probe.read_bytes()
            status, final_url, content_type = 200, url, "text/html"
            rec["reused_initial_probe"] = True
        else:
            time.sleep(0.15)
            status, final_url, content_type, raw = get(url)
        html = raw.decode("utf-8-sig")
        dom = DOM(html)
        main = next((n for n in dom.root.walk() if n.tag == "main"), None)
        if main is None:
            raise ValueError("Missing main element; HTTP status is insufficient")
        title = next((clean(n.text()) for n in main.walk() if n.tag == "h1"), "")
        body = re.sub(r"\n[ \t]*\n(?:[ \t]*\n)+", "\n\n", markdown(main, final_url)).strip()
        if not title or len(body) < 100 or "\ufffd" in title:
            raise ValueError("Missing title, very short body or corrupt Unicode")
        links = [{"text": clean(n.text()), "url": urljoin(final_url, n.attrs["href"])}
                 for n in main.walk() if n.tag == "a" and n.attrs.get("href")]
        images = [{"alt": n.attrs.get("alt", ""), "url": urljoin(final_url, n.attrs.get("src", ""))}
                  for n in main.walk() if n.tag == "img"]
        original_refs = sorted({i["url"] for i in links if urlsplit(i["url"]).path.startswith("/108/")})
        raw_path = DEST / "raw" / f"{stem}.html"
        text_path = DEST / "text" / f"{stem}.md"
        heading = (f"来源：{final_url}\n采集时间：{rec['retrieved_at']}\n"
                   f"资料层：{'本站转载与导读，未经逐字原版校勘' if kind(url) == 'original_reprint' else '本站课程/词典/说明'}\n"
                   "归档范围：静态正文与链接；交互图表、测验状态与浏览器学习进度未离线复现。\n\n")
        raw_path.write_bytes(raw)
        text_path.write_text(heading + body + "\n", encoding="utf-8")
        rec.update(status="ok", http_status=status, final_url=final_url, title=title,
                   content_type=content_type, bytes=len(raw), sha256=sha(raw),
                   raw_file=raw_path.relative_to(ROOT).as_posix(),
                   text_file=text_path.relative_to(ROOT).as_posix(),
                   text_sha256=sha(text_path.read_bytes()), text_chars=len(body),
                   headings=[{"level": int(n.tag[1]), "text": clean(n.text())}
                             for n in main.walk() if re.fullmatch(r"h[1-6]", n.tag)],
                   links=links, original_refs=original_refs, images=images,
                   svg_count=sum(n.tag == "svg" for n in main.walk()),
                   dynamic_chart_placeholder="图表加载中" in body,
                   dynamic_quiz_placeholder="出题" in body)
    except Exception as exc:
        rec.update(status="failed", error=f"{type(exc).__name__}: {exc}")
    return rec


def collect_images(records, robot):
    """Preserve the original static figures without altering raw HTML evidence."""
    image_dir = DEST / "images"
    image_dir.mkdir(exist_ok=True)
    refs = sorted({im["url"] for rec in records.values() if rec.get("status") == "ok" for im in rec["images"]})
    results = []
    for url in refs:
        record = {"url": url, "retrieved_at": stamp()}
        try:
            if urlsplit(url).hostname != "chanlunzhan.com" or not robot.can_fetch(AGENT, url):
                raise ValueError("Image not in permitted public origin")
            name = urlsplit(url).path.strip("/").replace("/", "__")
            path = image_dir / name
            if path.exists():
                raw = path.read_bytes()
                status, content_type = 200, "image/png" if raw.startswith(b"\x89PNG") else "image/jpeg"
            else:
                time.sleep(0.12)
                status, final_url, content_type, raw = get(url)
            is_png = raw.startswith(b"\x89PNG\r\n\x1a\n")
            is_jpeg = raw.startswith(b"\xff\xd8\xff") and raw.rstrip().endswith(b"\xff\xd9")
            if not (is_png or is_jpeg) or len(raw) < 100:
                raise ValueError("Expected a PNG/JPEG figure, not an HTML error page")
            path.write_bytes(raw)
            record.update(status="ok", http_status=status, content_type=content_type,
                          bytes=len(raw), sha256=sha(raw), file=path.relative_to(ROOT).as_posix())
            for page in records.values():
                if page.get("status") != "ok" or not any(im["url"] == url for im in page["images"]):
                    continue
                text_path = ROOT / page["text_file"]
                text = text_path.read_text(encoding="utf-8")
                text = text.replace("](" + url + ")", "](../images/" + name + ")")
                text_path.write_text(text, encoding="utf-8")
                page["text_sha256"] = sha(text_path.read_bytes())
                for im in page["images"]:
                    if im["url"] == url:
                        im["local_file"] = path.relative_to(ROOT).as_posix()
        except Exception as exc:
            record.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        results.append(record)
    (DEST / "images-manifest.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    return results


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    for sub in ["raw", "text"]:
        (DEST / sub).mkdir(parents=True, exist_ok=True)
    for name in ["robots.txt", "sitemap.xml"]:
        if not (DEST / name).exists():
            (DEST / name).write_bytes(get(BASE + "/" + name)[3])
    robot = RobotFileParser()
    robot.parse((DEST / "robots.txt").read_text(encoding="utf-8").splitlines())
    targets = [(e.findtext("{*}loc"), e.findtext("{*}lastmod"))
               for e in ET.fromstring((DEST / "sitemap.xml").read_bytes()).findall("{*}url")]
    allowed, excluded = [], []
    for url, modified in targets:
        same_host = urlsplit(url).hostname == "chanlunzhan.com"
        forbidden = urlsplit(url).path.startswith(("/practice/", "/stocks/", "/data/"))
        if same_host and not forbidden and robot.can_fetch(AGENT, url):
            allowed.append((url, modified))
        else:
            excluded.append({"url": url, "reason": "off-domain or excluded by robots/path policy"})
    manifest_path = DEST / "manifest.json"
    old = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else []
    records = {r["url"]: r for r in old if valid_cached(r)}
    pending = [(url, modified) for url, modified in allowed if url not in records]
    print(json.dumps({"sitemap": len(targets), "allowed": len(allowed), "reused": len(records), "pending": len(pending)}, ensure_ascii=False), flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(collect, *item): item[0] for item in pending}
        for future in concurrent.futures.as_completed(futures):
            rec = future.result()
            records[rec["url"]] = rec
            # Checkpoints make interrupted collection safely resumable.
            manifest_path.write_text(json.dumps(sorted(records.values(), key=lambda r: r["url"]), ensure_ascii=False, indent=2), encoding="utf-8")
            if len(records) % 20 == 0 or rec["status"] != "ok":
                print(json.dumps({"completed": len(records), "last": rec["url"], "status": rec["status"], "error": rec.get("error")}, ensure_ascii=False), flush=True)
    images = collect_images(records, robot)
    manifest_path.write_text(json.dumps(sorted(records.values(), key=lambda r: r["url"]), ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {"checked_at": stamp(), "sitemap_urls": len(targets), "records": len(records),
               "ok": sum(r["status"] == "ok" for r in records.values()), "excluded": excluded,
               "failed": [r for r in records.values() if r["status"] != "ok"],
               "static_images_ok": sum(im["status"] == "ok" for im in images),
               "static_images_failed": [im for im in images if im["status"] != "ok"],
               "categories": {c: sum(r["category"] == c and r["status"] == "ok" for r in records.values())
                              for c in sorted({r["category"] for r in records.values()})}}
    (DEST / "collection-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return bool(summary["failed"] or summary["static_images_failed"]) or len(records) != len(allowed)


if __name__ == "__main__":
    raise SystemExit(main())
