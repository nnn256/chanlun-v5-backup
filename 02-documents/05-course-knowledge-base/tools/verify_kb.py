"""Verify source hashes, authored internal links, course coverage and search."""
from __future__ import annotations
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from zoneinfo import ZoneInfo

from search_kb import search

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    failures, records = [], []
    report_path = ROOT / "VERIFICATION.md"
    if not report_path.exists():
        report_path.write_text("# 核验运行中\n\n完整结果将在本次检查结束后写入。\n", encoding="utf-8")
    site = json.loads((ROOT / "sources/manifest.json").read_text(encoding="utf-8"))
    original = json.loads((ROOT / "sources/originals/manifest.json").read_text(encoding="utf-8"))
    supplement_path = ROOT / "sources/supplements/manifest.json"
    supplements = json.loads(supplement_path.read_text(encoding="utf-8")) if supplement_path.exists() else []
    accepted = [item for item in site + original + supplements if item.get("status") == "ok"]
    for item in accepted:
        raw = ROOT / item["raw_file"]
        body = ROOT / item["text_file"]
        if not raw.is_file() or sha(raw) != item["sha256"]:
            failures.append("Source hash mismatch: " + item["url"])
        if not body.is_file() or len(body.read_text(encoding="utf-8")) < 150:
            failures.append("Missing/short article: " + item["url"])
    records.append({"check": "archived_sources", "count": len(accepted), "status": "pass" if not failures else "fail"})

    files = [ROOT / "README.md", ROOT / "来源目录.md", *sorted((ROOT / "notes").glob("*.md"))]
    link_count = 0
    for path in files:
        content = path.read_text(encoding="utf-8")
        if "\ufffd" in content:
            failures.append("Invalid decoded character: " + str(path))
        for match in re.finditer(r"(?<!!)\[[^\]\n]*\]\(([^)\n]+)\)", content):
            link = match[1].split("#", 1)[0].strip("<>")
            if not link or re.match(r"[a-zA-Z][\w+.-]*:", link):
                continue
            target = (path.parent / link).resolve()
            if not target.is_file():
                failures.append(f"Broken link: {path.name} -> {link}")
            link_count += 1
    records.append({"check": "authored_documents_and_local_links", "documents": len(files), "local_links": link_count})

    primary_numbers = {item["number"] for item in original if item.get("status") == "ok" and item.get("number")}
    numbers = primary_numbers | {item["number"] for item in supplements if item.get("status") == "ok"}
    index = (ROOT / "notes/04-原文课程索引.md").read_text(encoding="utf-8")
    rows = [int(m[1]) for m in re.finditer(r"^\| (\d+) \|", index, re.M)]
    if rows != list(range(1,109)):
        failures.append("Course index does not contain exactly 1..108")
    records.append({"check": "course_index", "indexed": len(rows), "archived": len(numbers), "missing": sorted(set(range(1,109)) - numbers)})

    examples = [("特征序列", "notes"), ("中枢 触边", "notes"), ("走势终完美", "originals")]
    for query, scope in examples:
        hits = search(query, scope, 3)
        if not hits:
            failures.append("Search returned no results: " + query)
        records.append({"check": "offline_search", "query": query, "scope": scope, "hits": len(hits), "first": hits[0] if hits else None})

    cli = subprocess.run([sys.executable, str(ROOT / "tools/search_kb.py"), "一买", "--scope", "notes", "--limit", "2", "--json"], capture_output=True, text=True, encoding="utf-8")
    try:
        cli_hits = json.loads(cli.stdout)
        if cli.returncode != 0 or len(cli_hits) != 2:
            raise ValueError("Search CLI smoke failed")
    except Exception as exc:
        failures.append(str(exc))
    records.append({"check": "search_cli", "exit_code": cli.returncode})

    # Roll back a deliberately small independent copy; the delivered library stays in place.
    check_parent = ROOT / "delivery/rollback-check"
    check_parent.mkdir(parents=True, exist_ok=True)
    clone = check_parent / "缠论知识库"
    if clone.exists():
        failures.append("Rollback check clone already exists; not overwriting")
    else:
        (clone / "sources").mkdir(parents=True)
        for name in ["README.md", "ROLLBACK.ps1", "sources/coverage.json"]:
            shutil.copy2(ROOT / name, clone / name)
        before_hash = sha(clone / "README.md")
        ps = shutil.which("pwsh") or shutil.which("powershell")
        if not ps:
            failures.append("PowerShell unavailable for rollback verification")
        else:
            result = subprocess.run([ps, "-NoProfile", "-File", str(clone / "ROLLBACK.ps1")], cwd=check_parent, capture_output=True, text=True, encoding="utf-8")
            try:
                receipt = json.loads(result.stdout.strip())
                destination = Path(receipt["Destination"])
                valid_parent = destination.resolve().parent == check_parent.resolve()
                if not valid_parent or result.returncode != 0 or clone.exists() or sha(destination / "README.md") != before_hash:
                    raise ValueError("Rollback relocation/hash verification failed")
                records.append({"check": "rollback_on_independent_copy", "exit_code": result.returncode, "stdout": receipt, "restored_content_sha256": before_hash, "status": "pass"})
            except Exception as exc:
                failures.append(f"Rollback check: {exc}; stdout={result.stdout}; stderr={result.stderr}")

    report = {"verified_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds"), "checks": records, "failures": failures, "status": "pass" if not failures else "fail"}
    (ROOT / "delivery/verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# 知识库采集与交付核验", "", "核验时间：" + report["verified_at"], "", "总体结果：**" + report["status"].upper() + "**", "",
             f"网站{len(site)}页中成功{sum(i.get('status')=='ok' for i in site)}页；课程正文{len(numbers)}篇，其中作者站{len(primary_numbers)}篇、转载补齐{len(numbers)-len(primary_numbers)}篇；另有补充博文1篇。成功正文总计{len(accepted)}份，逐份检查原始响应SHA-256及本地正文存在。", "",
             f"学习文档{len(files)}份，内部文件链接{link_count}个。逐号目录包含1—108课，实际缺少{108-len(numbers)}篇编号正文；缺失未计成功。", "",
             "离线检索核验：特征序列、中枢+触边、作者原文中的走势终完美均有结果；命令行一买检索的JSON输出能正确解析。", "",
             "回退核验：在delivery/rollback-check中的独立小副本上运行ROLLBACK.ps1，将副本移为同父目录备份；退出码、备份存在、源副本移走及README内容哈希一致均检查。交付知识库本身保持在原路径。", "",
             "## 真实的范围限制", "",
             "- 作者站仍未取得正文、现以标注转载补齐的编号：" + "、".join(map(str, sorted(set(range(1,109))-primary_numbers))) + "。",
             "- 有些新浪主站链接返回HTTP 200维护提示；正文容器缺失记录为失败。移动页抽样可读性不稳定，不将短片段当完整归档。",
             "- 5集视频采用官方配套文字和链接；B站公开接口返回412。未逐集观看或转写。",
             "- 原图、插件运行和各兼容平台未逐一实测；规则笔记依据公开文档，非插件源码审计。",
             "- 未进行行情分析、选股、交易或策略绩效验证。",
             "- 既有上层课程材料及算法保留，未将其代理结构改称严格复现。", "",
             "详细机器记录：[verification.json](delivery/verification.json)。新增学习文档与工具的创建补丁：[DIFF_FILE.patch](delivery/DIFF_FILE.patch)。安全回退脚本：[ROLLBACK.ps1](ROLLBACK.ps1)。补丁不重复嵌入来源缓存；缓存按各来源清单和哈希核验。", ""]
    if failures:
        lines += ["## 待处理失败", "", *["- " + item for item in failures], ""]
    (ROOT / "VERIFICATION.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"status": report["status"], "archived_sources": len(accepted), "documents": len(files), "local_links": link_count, "missing_courses": 108-len(numbers), "failures": failures}, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
