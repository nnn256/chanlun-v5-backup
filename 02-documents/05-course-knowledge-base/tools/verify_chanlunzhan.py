"""Verify archived evidence, source coverage, new links, offline retrieval and rollback."""
from __future__ import annotations

from collections import Counter
from datetime import datetime
import difflib
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "sources/chanlunzhan"
DELIVERY = ROOT / "delivery/chanlunzhan-20261108"
NOTES = ["12-缠论站系统学习总纲.md", "13-缠论站26课学习卡片.md", "14-缠论站52词条速查.md",
         "15-缠论站口径差异与原文核对.md", "16-缠论站学习计划与自测.md", "17-缠论站113篇原文与补充索引.md"]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def command(args, cwd=None):
    process = subprocess.run(args, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return {"command": args, "cwd": str(cwd or ROOT), "stdout": process.stdout,
            "stderr": process.stderr, "exit_code": process.returncode}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    failures, checks = [], []
    manifest = json.loads((SOURCE / "manifest.json").read_text(encoding="utf-8"))
    images = json.loads((SOURCE / "images-manifest.json").read_text(encoding="utf-8"))
    sitemap_urls = {e.text for e in ET.fromstring((SOURCE / "sitemap.xml").read_bytes()).findall(".//{*}loc")}
    if {r["url"] for r in manifest} != sitemap_urls or len(manifest) != len(sitemap_urls):
        failures.append("Sitemap URL set, unique count and manifest differ")
    for item in manifest:
        if item["status"] != "ok":
            failures.append("Failed page: " + item["url"])
            continue
        for key, digest in [("raw_file", "sha256"), ("text_file", "text_sha256")]:
            p = ROOT / item[key]
            if not p.is_file() or sha(p) != item[digest]:
                failures.append("Hash/existence mismatch: " + item[key])
        text = (ROOT / item["text_file"]).read_text(encoding="utf-8")
        if "\ufffd" in text:
            failures.append("Unicode replacement in text: " + item["text_file"])
        if urlsplit(item["url"]).path.startswith(("/practice/", "/stocks/", "/data/")):
            failures.append("Excluded interactive path in archive")
    categories = dict(Counter(item["category"] for item in manifest))
    expected = {"catalog": 3, "glossary": 52, "lesson": 26, "original_reprint": 113, "site_info": 3, "stage": 8}
    if categories != expected:
        failures.append("Snapshot coverage differs: " + str(categories))
    numbered = sorted(int(urlsplit(r["url"]).path.split("/")[-1]) for r in manifest
                      if r["category"] == "original_reprint" and urlsplit(r["url"]).path.split("/")[-1].isdigit())
    if numbered != list(range(1, 109)):
        failures.append("Original numbered coverage is not exactly 1..108")
    checks.append({"check": "sitemap_pages_and_hashes", "pages": len(manifest), "categories": categories,
                   "numbered_originals": len(numbered), "raw_bytes": sum(r["bytes"] for r in manifest),
                   "extracted_markdown_chars": sum(r["text_chars"] for r in manifest),
                   "dynamic_chart_placeholders": sum(r["dynamic_chart_placeholder"] for r in manifest)})
    for im in images:
        if im["status"] != "ok" or not (ROOT / im.get("file", "missing-image")).is_file():
            failures.append("Missing image: " + im["url"])
        elif sha(ROOT / im["file"]) != im["sha256"]:
            failures.append("Image hash mismatch: " + im["file"])
    image_urls = {im["url"] for im in images if im["status"] == "ok"}
    referred = {im["url"] for rec in manifest for im in rec["images"]}
    if image_urls != referred or len(images) != 43:
        failures.append("Incomplete static image coverage")
    checks.append({"check": "static_images", "count": len(image_urls), "bytes": sum(im.get("bytes", 0) for im in images)})

    # The older source collections are checked read-only; their old report stays intact.
    legacy_count = 0
    for name in ["sources/manifest.json", "sources/originals/manifest.json", "sources/supplements/manifest.json"]:
        path = ROOT / name
        if not path.exists():
            continue
        for rec in json.loads(path.read_text(encoding="utf-8")):
            if rec.get("status") != "ok":
                continue
            legacy_count += 1
            p = ROOT / rec["raw_file"]
            if not p.is_file() or sha(p) != rec["sha256"] or not (ROOT / rec["text_file"]).is_file():
                failures.append("Legacy source integrity problem: " + rec["url"])
    checks.append({"check": "legacy_sources_read_only", "count": legacy_count})

    docs = [ROOT / "README.md", ROOT / "data_structure.md", SOURCE / "README.md", *[ROOT / "notes" / n for n in NOTES]]
    link_count, image_links = 0, 0
    for path in [*docs, *[ROOT / r["text_file"] for r in manifest]]:
        text = path.read_text(encoding="utf-8")
        if "\ufffd" in text:
            failures.append("Invalid decoded document: " + str(path))
        for match in re.finditer(r"(!?)\[[^\]\n]*\]\(([^)\n]+)\)", text):
            link = match[2].split("#", 1)[0].strip("<>")
            if not link or re.match(r"[a-zA-Z][\w+.-]*:", link):
                continue
            target = (path.parent / link).resolve()
            # The report is written after successful checks below.
            if target == DELIVERY / "VERIFICATION.md":
                continue
            if not target.is_file():
                failures.append(f"Broken local link: {path.relative_to(ROOT)} -> {link}")
            link_count += 1
            image_links += bool(match[1])
    if image_links != 43:
        failures.append("Not all static figure references became local links")
    if len(re.findall(r"^### \d{2} ", (ROOT / "notes" / NOTES[1]).read_text(encoding="utf-8"), re.M)) != 26:
        failures.append("Lesson card count mismatch")
    checks.append({"check": "documents_and_links", "authored_documents": len(docs), "local_links": link_count, "local_image_links": image_links})

    search_tool = ROOT / "tools/search_kb.py"
    runs = []
    for query, scope in [("特征序列", "chanlunzhan"), ("中枢", "chanlunzhan"), ("二买", "chanlunzhan"),
                         ("三买", "all"), ("走势终完美", "originals")]:
        result = command([sys.executable, str(search_tool), query, "--scope", scope, "--limit", "2", "--json"])
        try:
            hits = json.loads(result["stdout"])
            if result["exit_code"] or len(hits) != 2 or any(not Path(hit["file"]).is_file() for hit in hits):
                raise ValueError("Missing or invalid search hits")
            if scope == "chanlunzhan" and any(not h["source_url"] or not h["source_layer"].startswith("site_") for h in hits):
                raise ValueError("Missing source-layer metadata")
        except Exception as exc:
            failures.append(f"Search {query}/{scope}: {exc}")
        runs.append(result)
    checks.append({"check": "offline_search_cli", "runs": runs})

    existing = json.loads((DELIVERY / "baseline.json").read_text(encoding="utf-8"))
    created_roots = ["sources/chanlunzhan", "data_structure.md", *["notes/" + n for n in NOTES],
                     "tools/collect_chanlunzhan.py", "tools/build_chanlunzhan_indices.py", "tools/verify_chanlunzhan.py"]
    additions = []
    for name in created_roots:
        path = ROOT / name
        additions.extend(sorted(path.rglob("*")) if path.is_dir() else [path])
    additions = [p for p in additions if p.is_file() and "__pycache__" not in p.parts]
    package = {"modified_existing": [{"file": item["file"], "sha256": sha(ROOT / item["file"])} for item in existing],
               "created_roots": created_roots,
               "created_files": [{"file": p.relative_to(ROOT).as_posix(), "sha256": sha(p)} for p in additions]}
    (DELIVERY / "MODIFIED_FILES.json").write_text(json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8")
    patch = []
    for item in existing:
        name = item["file"]
        before = (DELIVERY / "baseline" / name).read_text(encoding="utf-8").splitlines(keepends=True)
        after = (ROOT / name).read_text(encoding="utf-8").splitlines(keepends=True)
        patch.extend(difflib.unified_diff(before, after, fromfile="a/" + name, tofile="b/" + name))
    # Cache evidence is reconstructed by the collector; the patch stores authored files.
    for p in additions:
        if p.suffix not in {".py", ".md"} or p.is_relative_to(SOURCE):
            continue
        name = p.relative_to(ROOT).as_posix()
        patch.extend(difflib.unified_diff([], p.read_text(encoding="utf-8").splitlines(keepends=True), fromfile="/dev/null", tofile="b/" + name))
    (DELIVERY / "DIFF_FILE.patch").write_text("".join(patch), encoding="utf-8")

    # Same path, same invocation, three states on a small independent copy.
    with tempfile.TemporaryDirectory(prefix="chanlunzhan-rollback-") as temp:
        clone = Path(temp) / "library"
        target = clone / "tools/search_kb.py"
        target.parent.mkdir(parents=True)
        for item in existing:
            dst = clone / item["file"]
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(DELIVERY / "baseline" / item["file"], dst)
        args = [sys.executable, str(target), "二买", "--scope", "chanlunzhan", "--limit", "2", "--json"]
        before = command(args, clone)
        for item in package["modified_existing"]:
            shutil.copy2(ROOT / item["file"], clone / item["file"])
        text_dir = clone / "sources/chanlunzhan/text"
        text_dir.mkdir(parents=True)
        shutil.copy2(SOURCE / "text/learn__maimaidian__second-type.md", text_dir)
        changed = command(args, clone)
        rollback = command([sys.executable, str(DELIVERY / "ROLLBACK.py"), "--root", str(clone), "--execute"], clone)
        restored = command(args, clone)
        hashes = [{"file": r["file"], "restored_sha256": sha(clone / r["file"]), "expected_sha256": r["sha256"]} for r in existing]
        if before["exit_code"] != 2 or changed["exit_code"] != 0 or rollback["exit_code"] != 0 or restored["exit_code"] != 2:
            failures.append("Three-leg rollback behavior failed")
        if any(r["restored_sha256"] != r["expected_sha256"] for r in hashes):
            failures.append("Rollback did not restore pristine hashes")
        if text_dir.exists() or not json.loads(rollback["stdout"]).get("executed"):
            failures.append("Rollback did not archive extension additions")
        checks.append({"check": "three_leg_rollback_independent_copy", "baseline": before, "modified": changed,
                       "rollback": rollback, "restored": restored, "hashes": hashes,
                       "temporary_copy_removed_after_check": True})
    for item in package["modified_existing"]:
        if sha(ROOT / item["file"]) != item["sha256"]:
            failures.append("Delivered file changed during independent rollback drill")

    report = {"verified_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds"),
              "status": "pass" if not failures else "fail", "checks": checks, "failures": failures}
    (DELIVERY / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    literal = []
    for result in runs:
        literal += ["COMMAND " + json.dumps(result["command"], ensure_ascii=False), "EXIT " + str(result["exit_code"]),
                    "STDOUT\n" + result["stdout"], "STDERR\n" + result["stderr"]]
    for name, result in [("BASELINE", before), ("MODIFIED", changed), ("ROLLBACK", rollback), ("RESTORED", restored)]:
        literal += [name, "COMMAND " + json.dumps(result["command"], ensure_ascii=False), "EXIT " + str(result["exit_code"]),
                    "STDOUT\n" + result["stdout"], "STDERR\n" + result["stderr"]]
    (DELIVERY / "VERIFICATION.txt").write_text("\n".join(literal), encoding="utf-8")
    lines = ["# 缠论站补充核验", "", "日期：" + report["verified_at"], "", "结果：**" + report["status"].upper() + "**", "",
             f"205/205静态页、26课、52词条、编号1—108课及5补充篇均存在；43/43静态原图已保存并改为本地引用。逐个校验原始响应、正文及原图SHA-256。原有{legacy_count}份成功来源也做了只读完整性检查。", "",
             f"新增学习笔记6份；完整目录、入口与分层索引一并检查。核对{link_count}个内部文件链接（含{image_links}个图片链接）。5组离线检索使用真实命令行输出核对来源与位置。", "",
             "独立小副本三腿检验：基线工具不支持新scope而返回2；修改后返回0和真实来源结果；实际运行回退脚本后恢复原哈希，同一命令再次返回2。正式交付文件保持修改后状态。临时副本核验完已清理，逐项输出保存在txt/json。", "",
             "## 四件套", "", "- [修改文件与哈希](MODIFIED_FILES.json)：原有两文件及新增文件清单。",
             "- [变更补丁](DIFF_FILE.patch)：README、检索工具和新增手写文档/工具。来源缓存不重复嵌入补丁，以采集脚本与清单复现。",
             "- [实际命令、输出与退出码](VERIFICATION.txt)及[机器报告](verification.json)。",
             "- [回退脚本](ROLLBACK.py)：默认预览，执行需加`--execute`。校验两份基线后恢复，并将本次新增内容移入归档目录；已有后续改动则拒绝覆盖。", "",
             "## 仍未验证", "", "- 23个页面中的客户端图表、训练/个股页、浏览器学习状态、网站算法源码及81课图例测试。",
             "- 转载与作者原版的逐字校勘，以及评论者的真实身份。",
             "- 区间套的多周期真实样本复现、行情收益、任何交易执行。", "",
             "正文字符统计含Markdown和评论，不称‘作者原文字数’。网站课程、词典间差异另见口径核对。", ""]
    if failures:
        lines += ["## 失败项", "", *["- " + failure for failure in failures], ""]
    (DELIVERY / "VERIFICATION.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"status": report["status"], "pages": len(manifest), "images": len(images),
                      "legacy_sources": legacy_count, "local_links": link_count, "failures": failures}, ensure_ascii=False, indent=2))
    return bool(failures)


if __name__ == "__main__":
    raise SystemExit(main())
