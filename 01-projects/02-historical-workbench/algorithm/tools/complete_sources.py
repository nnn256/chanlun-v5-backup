"""Supplement unavailable lessons from a labelled, hashed public reprint."""
from datetime import datetime
import difflib
import hashlib
import json
from pathlib import Path
import re
import zipfile
from zoneinfo import ZoneInfo

PROJECT = Path(__file__).resolve().parents[1]
KB = PROJECT.parent / "缠论知识库"
ARCHIVE = PROJECT / "artifacts/research_sources/chanlun-main.zip"


def simplified(text):
    text = re.sub(r"!?\[[^\]]*\]\([^)]*\)", "", text)
    return re.sub(r"[^\w\u3400-\u9fff]", "", text)


def main():
    primary = json.loads((KB / "sources/originals/manifest.json").read_text(encoding="utf-8"))
    known = {item["number"]: item for item in primary if item.get("status") == "ok" and item.get("number")}
    folder = KB / "sources/supplements"
    for name in ["text", "raw"]:
        (folder / name).mkdir(parents=True, exist_ok=True)
    records, comparisons = [], []
    with zipfile.ZipFile(ARCHIVE) as z:
        courses = {}
        for name in z.namelist():
            match = re.fullmatch(r"chanlun-main/108/(\d+)\.(.+)\.md", name)
            if match and 1 <= int(match[1]) <= 108:
                courses[int(match[1])] = (name, match[2])
        for number, (name, title) in sorted(courses.items()):
            raw = z.read(name)
            text = raw.decode("utf-8-sig")
            # The repository combines lessons with unverified comment threads.
            # Archive the original bytes, but index only the lesson body.
            marker = re.search(r"\*\*本文评论", text)
            article = text[:marker.start()].rstrip() if marker else text
            if len(text) < 150:
                raise ValueError(f"Reprint lesson {number} has no substantial body")
            if number in known:
                a = simplified((KB / known[number]["text_file"]).read_text(encoding="utf-8"))
                b = simplified(text)
                comparison = difflib.SequenceMatcher(None, a, b).ratio()
                comparisons.append({"number": number, "text_similarity": round(comparison, 4), "primary_chars": len(a), "reprint_chars": len(b)})
                continue
            encoded_name = __import__("urllib.parse", fromlist=["quote"]).quote(name.split("chanlun-main/", 1)[1], safe="/")
            url = "https://github.com/lufanglei/chanlun/blob/main/" + encoded_name
            raw_path = folder / "raw" / f"lesson-{number:03d}.md"
            text_path = folder / "text" / f"lesson-{number:03d}.md"
            raw_path.write_bytes(raw)
            images = []
            def local_image(match):
                relative = match[1].removeprefix('./')
                member = 'chanlun-main/108/' + relative
                if not relative.startswith('pic/') or '..' in relative.split('/') or member not in z.namelist():
                    return match[0]
                image_bytes = z.read(member)
                image_path = folder / 'images' / Path(relative).name
                image_path.parent.mkdir(exist_ok=True)
                image_path.write_bytes(image_bytes)
                images.append({'file':image_path.relative_to(KB).as_posix(),'sha256':hashlib.sha256(image_bytes).hexdigest(),'archive_member':member})
                return '![](../images/' + image_path.name + ')'
            rendered = re.sub(r'!\[[^\]]*\]\(([^)]+)\)', local_image, article)
            text_path.write_text(f"# 教你炒股票{number}：{title}\n\n来源类型：第三方转载，尚未与作者站逐篇校核。\n转载地址：{url}\n归档：2026-11-06\n\n{rendered}\n", encoding="utf-8")
            records.append({"number": number, "title": f"教你炒股票{number}：{title}", "url": url,
                            "status": "ok", "source_type": "third_party_reprint", "author_site_verified": False,
                            "retrieved_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds"),
                            "archive_url": "https://codeload.github.com/lufanglei/chanlun/zip/refs/heads/main",
                            "archive_sha256": hashlib.sha256(ARCHIVE.read_bytes()).hexdigest(),
                            "archive_comment": z.comment.decode("ascii", errors="replace"), "archive_member": name,
                            "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw), "text_chars": len(article),
                            "editorial_processing": "lesson body separated at the repository comment-thread marker; original bytes retained",
                            "comment_thread_present": marker is not None,
                            "raw_file": raw_path.relative_to(KB).as_posix(), "text_file": text_path.relative_to(KB).as_posix(), "images": images})
    (folder / "manifest.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    (folder / "primary-comparisons.json").write_text(json.dumps(comparisons, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"primary": len(known), "reprint_supplements": len(records), "total_course_texts": len(known) + len(records),
                      "remaining": sorted(set(range(1,109)) - set(known) - {x['number'] for x in records}),
                      "comparison_note": "text similarity is evidence of overlap, not proof of authorship or edition identity"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
