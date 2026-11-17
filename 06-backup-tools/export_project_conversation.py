"""Export only the selected project's user-visible chat, never raw rollouts.

Uses a read-only SQLite snapshot and capped, streamed rollout reads. Intermediate
records contain only normalized visible items and are deleted on success.
"""
from __future__ import annotations

import argparse
import base64
import collections
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile

DEFAULT_THREAD = "01a1a7f3-80e6-7283-826a-e2aa51f6fa26"
MAX_PART = 2 * 1024 * 1024
ALLOWED = {
    "usermessage", "agentmessage", "commandexecution", "filechange", "imageview",
    "collabagenttoolcall", "subagentactivity", "extension", "mcptoolcall",
    "websearch", "plan", "error", "contextcompaction",
}
SKIP_TYPES = {"reasoning", "contextcompaction"}
TYPE_NAMES = {
    "usermessage": "userMessage", "agentmessage": "agentMessage",
    "commandexecution": "commandExecution", "filechange": "fileChange",
    "imageview": "imageView", "collabagenttoolcall": "collabAgentToolCall",
    "subagentactivity": "subAgentActivity", "extension": "extension",
    "mcptoolcall": "mcpToolCall", "websearch": "webSearch", "plan": "plan",
    "error": "error",
}
SECRET_PATTERNS = [
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----.*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", re.S)),
    ("github_token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{25,})\b")),
    ("api_token", re.compile(r"\b(?:sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}|glpat-[A-Za-z0-9_-]{15,}|xox[baprs]-[A-Za-z0-9-]{15,}|AIza[A-Za-z0-9_-]{30,}|AKIA[A-Z0-9]{16})\b")),
    ("bearer", re.compile(r"(?i)\bBearer\s+[A-Za-z0-9_.~+/-]{24,}={0,2}")),
    ("credential_url", re.compile(r"(?i)https?://[^\s/:@]{1,100}:[^\s/@]{4,200}@")),
    ("assigned_secret", re.compile(r"(?im)(\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|password|passwd|secret[_-]?key)\b\s*[\"']?\s*[:=]\s*[\"'])([^\"'\r\n]{8,})([\"'])")),
]
IMAGE_PATH = re.compile(r"[A-Za-z]:[\\/][^\r\n<>\"]+?\.(?:png|jpe?g|webp|gif|bmp)(?=$|[\s)\]\"'])", re.I)


def iso_ms(ms):
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_ms(value):
    if isinstance(value, (int, float)):
        return int(value if value > 1e12 else value * 1000)
    if isinstance(value, str):
        try:
            return int(dt.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)
        except ValueError:
            pass
    return 0


def normalize_kind(value):
    return re.sub(r"[^a-z]", "", str(value).lower())


def redact(value, counts):
    if isinstance(value, str):
        for name, pattern in SECRET_PATTERNS:
            if name == "assigned_secret":
                value, n = pattern.subn(lambda m: m[1] + "[REDACTED]" + m[3], value)
            elif name == "credential_url":
                value, n = pattern.subn("https://[REDACTED]@", value)
            else:
                value, n = pattern.subn("[REDACTED]", value)
            counts[name] += n
        return value
    if isinstance(value, dict):
        return {k: redact(v, counts) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, counts) for v in value]
    return value


def text_content(content):
    if isinstance(content, str):
        return content
    return "\n".join(z.get("text", "") for z in (content or []) if isinstance(z, dict) and isinstance(z.get("text"), str))


def user_fingerprint(content):
    text = re.sub(r"<image\b[^>]*>\s*</image>", "", text_content(content), flags=re.I)
    return hashlib.sha256(" ".join(text.split()).encode()).hexdigest()


def path_key(value):
    return os.path.normcase(os.path.normpath(value.removeprefix("\\\\?\\")))


def clean_content(content):
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    out = []
    for z in content or []:
        if not isinstance(z, dict):
            continue
        typ = str(z.get("type", "")).lower()
        if typ in {"text", "input_text", "output_text"}:
            out.append({"type": "text", "text": z.get("text", "")})
        elif typ in {"local_image", "image"}:
            entry = {"type": "local_image"}
            if isinstance(z.get("path"), str):
                entry["path"] = z["path"]
            elif isinstance(z.get("image_url"), str) and not z["image_url"].startswith("data:"):
                entry["url"] = z["image_url"]
            else:
                entry["note"] = "Inline media bytes are not included in normalized JSONL."
            out.append(entry)
    return out


def visible_item(item):
    kind = normalize_kind(item.get("type"))
    if kind not in ALLOWED or kind in SKIP_TYPES:
        return None
    out = {"type": TYPE_NAMES[kind], "id": item.get("id", "")}
    if kind == "usermessage":
        out["content"] = clean_content(item.get("content"))
    elif kind == "agentmessage":
        phase = item.get("phase")
        if phase in {"analysis", "reasoning", "summary"}:
            return None
        out.update(text=item.get("text", text_content(item.get("content"))), phase=phase)
    elif kind == "commandexecution":
        aliases = {"command": "command", "cwd": "cwd", "status": "status", "aggregated_output": "output", "aggregatedOutput": "output", "exit_code": "exitCode", "exitCode": "exitCode", "duration": "duration", "durationMs": "durationMs"}
        for key, dest in aliases.items():
            if key in item:
                out[dest] = item[key]
    elif kind == "filechange":
        out.update(changes=item.get("changes"), status=item.get("status"))
        for key in ["stdout", "stderr"]:
            if key in item:
                out[key] = item[key]
    elif kind == "imageview":
        out["path"] = item.get("path")
    elif kind == "collabagenttoolcall":
        for key in ["tool", "status", "sender_thread_id", "senderThreadId", "receiver_thread_ids", "receiverThreadIds"]:
            if key in item:
                out[key] = item[key]
        # Child prompts, responses, and reasoning are deliberately outside scope.
        out["note"] = "Activity metadata only; child conversation contents are not exported."
    elif kind == "subagentactivity":
        for key in ["kind", "agent_thread_id", "agentThreadId", "agent_path", "agentPath"]:
            if key in item:
                out[key] = item[key]
    elif kind == "extension":
        for key in ["kind", "durationMs"]:
            if key in item:
                out[key] = item[key]
    else:
        # Allowlist display fields rather than copying an unknown UI structure.
        for key in ["text", "query", "action", "status", "result", "error", "message", "plan"]:
            if key in item:
                out[key] = item[key]
    return out


def read_jsonl_capped(path, cap):
    if path.suffix == ".zst":
        from compression import zstd
        with path.open("rb") as raw:
            # Compressed snapshots are immutable, and their compressed size is checked.
            if raw.seek(0, 2) != cap:
                raise RuntimeError("Compressed rollout changed before export")
            raw.seek(0)
            with zstd.open(raw, "rt", encoding="utf-8") as stream:
                for ordinal, line in enumerate(stream):
                    yield ordinal, line
        return
    with path.open("rb") as stream:
        ordinal = 0
        while stream.tell() < cap:
            left = cap - stream.tell()
            line = stream.readline(left)
            if not line.endswith(b"\n"):
                return
            yield ordinal, line
            ordinal += 1


def hash_file(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


class Parts:
    def __init__(self, directory, stem, suffix, header=""):
        self.directory, self.stem, self.suffix, self.header = directory, stem, suffix, header
        self.files = []
        self.stream = None
        self.size = 0

    def add(self, value):
        data = value.encode("utf-8")
        if len(data) > MAX_PART - len(self.header.encode("utf-8")):
            raise RuntimeError("Oversized record must be split before writing")
        if self.stream is None or self.size + len(data) > MAX_PART:
            if self.stream:
                self.stream.close()
            path = self.directory / f"{self.stem}-{len(self.files)+1:03d}.{self.suffix}"
            self.files.append(path)
            self.stream = path.open("wb")
            head = self.header.encode("utf-8")
            self.stream.write(head)
            self.size = len(head)
        self.stream.write(data)
        self.size += len(data)

    def close(self):
        if self.stream:
            self.stream.close()


def split_text_utf8(text, byte_limit):
    while len(text.encode("utf-8")) > byte_limit:
        piece = text[:byte_limit // 4]
        split = piece.rfind("\n")
        if split > len(piece) // 2:
            piece = piece[:split+1]
        yield piece
        text = text[len(piece):]
    if text:
        yield text


def render_record(record):
    item = record["item"]
    kind = item["type"]
    labels = {"userMessage": "用户", "agentMessage": "助手", "commandExecution": "命令与输出", "fileChange": "文件改动", "imageView": "查看图片", "collabAgentToolCall": "协作工具", "subAgentActivity": "子任务活动"}
    header = f"\n## {record['sequence']:05d} · {record['timestamp']} · {labels.get(kind, kind)}\n\n"
    if kind == "userMessage":
        chunks = []
        for content in item.get("content", []):
            if content["type"] == "text":
                chunks.append(content["text"])
            elif content.get("copied_attachment"):
                chunks.append(f"![用户附件](../{content['copied_attachment']})")
            else:
                chunks.append("附件引用：" + str(content.get("path", content.get("url", content.get("note")))))
        body = "\n\n".join(chunks)
    elif kind == "agentMessage":
        body = item.get("text", "")
    else:
        body = "````json\n" + json.dumps(item, ensure_ascii=False, indent=2) + "\n````"
    return header + body + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--thread-id", default=DEFAULT_THREAD)
    ap.add_argument("--codex-root", type=Path, default=Path(os.environ["USERPROFILE"]) / ".codex")
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    out = args.output
    out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()):
        raise RuntimeError("Output directory must be empty; do not overwrite a prior snapshot")
    (out / "markdown").mkdir()
    (out / "jsonl").mkdir()
    (out / "attachments").mkdir()
    snapshot_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds")
    audit = {"thread_id": args.thread_id, "snapshot_started_utc": snapshot_at, "scope": "Selected thread's recoverable user-visible items only", "excluded": ["assistant analysis and reasoning", "system/developer messages", "raw rollouts", "compaction/context snapshots", "other thread contents", "global Codex state/auth"], "sources": [], "skipped": collections.Counter(), "redactions": collections.Counter(), "warnings": []}
    inline_images = {}
    copied_hashes = {}
    state = sqlite3.connect(f"file:{(args.codex_root / 'state_5.sqlite').as_posix()}?mode=ro", uri=True)
    row = state.execute("SELECT id,rollout_path,created_at,updated_at,history_mode FROM threads WHERE id=?", (args.thread_id,)).fetchone()
    state.close()
    if not row:
        raise RuntimeError("Requested thread not found")
    current = Path(row[1].removeprefix("\\\\?\\"))
    paths = sorted(set(args.codex_root.joinpath("sessions").rglob(f"*{args.thread_id}*")) | {current})
    caps = []
    for path in paths:
        if not path.is_file() or not (path.name.endswith(".jsonl") or path.name.endswith(".jsonl.zst")):
            continue
        cap = path.stat().st_size
        first = next(read_jsonl_capped(path, cap), None)
        if first is None:
            continue
        meta = json.loads(first[1])
        payload = meta.get("payload", {})
        if meta.get("type") != "session_meta" or payload.get("id") != args.thread_id:
            audit["warnings"].append("Rejected filename match whose session_meta.id differs: " + path.name)
            continue
        caps.append((path, cap))
        audit["sources"].append({"kind": "capped_rollout", "file": path.name, "byte_cap": cap, "session_meta_id_verified": True, "history_base": payload.get("history_base")})
    if not caps:
        raise RuntimeError("No verified thread rollouts")
    scratch_dir = Path(tempfile.mkdtemp(prefix="chanlun-visible-export-"))
    work = sqlite3.connect(scratch_dir / "visible.sqlite3")
    work.execute("CREATE TABLE records(item_id TEXT PRIMARY KEY,ts INTEGER,priority INTEGER,item TEXT,source TEXT)")
    work.execute("CREATE TABLE raw_users(item_id TEXT PRIMARY KEY,ts INTEGER,item TEXT,source TEXT)")
    work.execute("CREATE TABLE user_fingerprints(fingerprint TEXT,ts INTEGER)")

    def insert(item, ts, source, priority):
        obj = visible_item(item)
        if obj is None:
            audit["skipped"][str(item.get("type", "unknown"))] += 1
            return
        obj = redact(obj, audit["redactions"])
        iid = obj.get("id") or hashlib.sha256((str(ts)+json.dumps(obj, sort_keys=True)).encode()).hexdigest()
        obj["id"] = iid
        work.execute("INSERT INTO records VALUES(?,?,?,?,?) ON CONFLICT(item_id) DO UPDATE SET ts=excluded.ts,priority=excluded.priority,item=excluded.item,source=excluded.source WHERE excluded.priority>records.priority", (iid, ts, priority, json.dumps(obj, ensure_ascii=False), source))

    history = sqlite3.connect(f"file:{(args.codex_root / 'thread_history_1.sqlite').as_posix()}?mode=ro", uri=True)
    history.execute("BEGIN")
    for item_id, ts, raw in history.execute("SELECT item_id,created_at_ms,item_json FROM thread_items WHERE thread_id=? ORDER BY created_at_ms,rollout_ordinal", (args.thread_id,)):
        insert(json.loads(raw), ts, "thread_history_projection", 1)
    audit["sources"].append({"kind": "thread_history_projection", "thread_id": args.thread_id, "snapshot_read_transaction": True, "scoped_rows": history.execute("SELECT count(*) FROM thread_items WHERE thread_id=?", (args.thread_id,)).fetchone()[0]})
    history.close()
    for path, cap in caps:
        for ordinal, line in read_jsonl_capped(path, cap):
            try:
                rec = json.loads(line)
            except (ValueError, UnicodeError):
                audit["skipped"]["malformed_jsonl"] += 1
                continue
            payload = rec.get("payload") or {}
            typ = rec.get("type")
            if typ == "event_msg" and payload.get("type") == "item_completed":
                if payload.get("thread_id") not in {None, args.thread_id}:
                    audit["skipped"]["foreign_thread_event"] += 1
                    continue
                item = payload.get("item") or {}
                ts = parse_ms(payload.get("started_at_ms")) or parse_ms(rec.get("timestamp"))
                insert(item, ts, path.name + ":" + str(ordinal), 2)
            elif typ == "response_item" and payload.get("type") == "message" and payload.get("role") == "user":
                # User-uploaded image bytes are visible user material. Recover only
                # this message's explicit image, never other files from Temp.
                explicit_paths = list(dict.fromkeys(m.group(0) for m in IMAGE_PATH.finditer(text_content(payload.get("content")))))
                image_parts = [c.get("image_url", "") for c in payload.get("content", []) if c.get("type") == "input_image"]
                if len(image_parts) == 1 and explicit_paths and image_parts[0].startswith("data:image/png;base64,"):
                    data = base64.b64decode(image_parts[0].split(",", 1)[1], validate=True)
                    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
                        raise RuntimeError("Inline user PNG has an invalid signature")
                    digest = hashlib.sha256(data).hexdigest()
                    if digest not in copied_hashes:
                        name = digest[:12] + "-" + Path(explicit_paths[0]).name
                        (out / "attachments" / name).write_bytes(data)
                        copied_hashes[digest] = "attachments/" + name
                    for referenced in explicit_paths:
                        inline_images[path_key(referenced)] = {"path": copied_hashes[digest], "sha256": digest, "bytes": len(data)}
                content = clean_content(payload.get("content"))
                text = text_content(content).lstrip()
                if text.startswith(("<environment_context>", "<external_browser_tabs>", "<turn_aborted>", "<subagent_notification>")):
                    audit["skipped"]["automatic_user_context"] += 1
                    continue
                item = redact({"type": "userMessage", "id": payload.get("id"), "content": content}, audit["redactions"])
                ts = parse_ms(rec.get("timestamp"))
                work.execute("INSERT OR IGNORE INTO raw_users VALUES(?,?,?,?)", (item["id"], ts, json.dumps(item, ensure_ascii=False), path.name+":"+str(ordinal)))
            elif typ == "response_item" and payload.get("type") in {"reasoning", "agent_message"}:
                audit["skipped"]["raw_" + payload["type"]] += 1
            elif typ == "response_item" and payload.get("type") == "message" and payload.get("role") in {"system", "developer"}:
                audit["skipped"]["instruction_message"] += 1
            elif typ == "compacted":
                audit["skipped"]["compaction_snapshot"] += 1
        work.commit()
    # Supplement only genuinely missing user messages, including user supplied
    # AGENTS text and user-input replies; never import context-injection blocks.
    for ts, raw in work.execute("SELECT ts,item FROM records WHERE json_extract(item,'$.type')='userMessage'"):
        work.execute("INSERT INTO user_fingerprints VALUES(?,?)", (user_fingerprint(json.loads(raw).get("content")), ts))
    for iid, ts, raw, source in work.execute("SELECT * FROM raw_users ORDER BY ts"):
        item = json.loads(raw)
        fp = user_fingerprint(item.get("content"))
        found = work.execute("SELECT 1 FROM user_fingerprints WHERE fingerprint=? AND abs(ts-?)<=5000 LIMIT 1", (fp, ts)).fetchone()
        if found:
            audit["skipped"]["duplicate_user_response"] += 1
        else:
            work.execute("INSERT OR IGNORE INTO records VALUES(?,?,?,?,?)", (iid, ts, 3, raw, source))
            work.execute("INSERT INTO user_fingerprints VALUES(?,?)", (fp, ts))
            audit.setdefault("supplemental_user_messages", 0)
            audit["supplemental_user_messages"] += 1
    work.commit()
    attachments = {}
    missing = []
    def attachment(path_value):
        original = path_value.strip().rstrip(".,;：")
        key = path_key(original)
        if key in attachments:
            return attachments[key]
        p = Path(original.removeprefix("\\\\?\\"))
        if not p.is_file() and key in inline_images:
            result = {"original_path": original, "status": "recovered_inline", **inline_images[key]}
        elif not p.is_file():
            result = {"original_path": original, "status": "missing"}
            missing.append(result)
        elif p.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}:
            result = {"original_path": original, "status": "unsupported"}
        else:
            digest = hash_file(p)
            if digest not in copied_hashes:
                name = digest[:12] + "-" + p.name
                dst = out / "attachments" / name
                shutil.copyfile(p, dst)
                copied_hashes[digest] = "attachments/" + name
            result = {"original_path": original, "status": "copied", "path": copied_hashes[digest], "sha256": digest, "bytes": p.stat().st_size}
        attachments[key] = result
        return result

    md = Parts(out / "markdown", "conversation", "md", "# 缠论项目窗口记录（可见内容）\n\n时间按 UTC 排序；中国时间为 UTC+8。工具记录保留可见命令、输出与补丁。\n")
    jl = Parts(out / "jsonl", "conversation", "jsonl")
    counts = collections.Counter()
    first_ts = last_ts = None
    for sequence, (iid, ts, raw, source) in enumerate(work.execute("SELECT item_id,ts,item,source FROM records ORDER BY ts,item_id"), 1):
        item = json.loads(raw)
        counts[item["type"]] += 1
        timestamp = iso_ms(ts)
        first_ts = first_ts or timestamp
        last_ts = timestamp
        if item["type"] == "userMessage":
            for content in item.get("content", []):
                if content.get("type") == "local_image" and content.get("path"):
                    found = attachment(content["path"])
                    if found.get("status") in {"copied", "recovered_inline"}:
                        content["copied_attachment"] = found["path"]
                if content.get("type") == "text":
                    for match in IMAGE_PATH.finditer(content.get("text", "")):
                        attachment(match.group(0))
        record = {"sequence": sequence, "timestamp": timestamp, "thread_id": args.thread_id, "source": source, "item": item}
        line = json.dumps(record, ensure_ascii=False) + "\n"
        if len(line.encode("utf-8")) <= MAX_PART:
            jl.add(line)
        else:
            # Preserve complete oversized payloads in ordered fragment records.
            serialized_item = json.dumps(item, ensure_ascii=False)
            fragments = list(split_text_utf8(serialized_item, MAX_PART // 2))
            for i, fragment in enumerate(fragments, 1):
                part = {k: v for k, v in record.items() if k != "item"}
                part.update(item_id=iid, item_type=item["type"], fragment_index=i, fragment_count=len(fragments), item_json_fragment=fragment)
                jl.add(json.dumps(part, ensure_ascii=False)+"\n")
        rendered = render_record(record)
        for fragment in split_text_utf8(rendered, MAX_PART-1024):
            md.add(fragment)
    md.close()
    jl.close()
    work.close()
    shutil.rmtree(scratch_dir)
    audit.update(first_visible_timestamp_utc=first_ts, last_visible_timestamp_utc=last_ts, exported_counts=dict(counts), exported_items=sum(counts.values()), markdown_parts=len(md.files), jsonl_parts=len(jl.files), copied_user_attachments=len(copied_hashes), missing_attachment_references=len(missing), snapshot_completed_utc=dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds"))
    audit["skipped"] = dict(audit["skipped"])
    audit["redactions"] = dict(audit["redactions"])
    audit["completeness"] = "All recognized visible UI items in the selected thread's verified local rollout snapshots plus its scoped UI projection, with missing raw user messages supplemented. Messages after the recorded byte caps and inaccessible attachments are outside this snapshot."
    (out / "export-audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    (out / "attachments-manifest.json").write_text(json.dumps(list(attachments.values()), ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    (out / "missing-attachments.json").write_text(json.dumps(missing, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    lines = ["# 缠论项目窗口备份", "", f"会话：`{args.thread_id}`", "", f"范围：{first_ts} 至 {last_ts}（UTC，中国时间加 8 小时）。", "", f"共 {sum(counts.values())} 条可见记录；Markdown {len(md.files)} 卷，JSONL {len(jl.files)} 卷，每卷不超过 2 MiB。", "", "## 顺序阅读", ""]
    lines.extend(f"{i}. [{p.name}](markdown/{p.name})" for i, p in enumerate(md.files, 1))
    lines += ["", "## 说明", "", "本快照包含本窗口可恢复的用户消息、助手可见回复，以及界面展示的命令、输出、补丁和活动记录。用户提供的历史 AGENTS 文本按用户材料保留。", "", "不包含助手分析/推理、系统和开发者消息、压缩上下文、其他窗口正文、全局认证配置或原始运行日志副本。子任务只保留本窗口显示的活动元数据。", "", f"用户图片已复制 {len(copied_hashes)} 个；找不到的引用 {len(missing)} 个，见 [missing-attachments.json](missing-attachments.json)。视频原文件没有复制到此会话目录。", "", f"疑似凭证匹配已替换 {sum(audit['redactions'].values())} 处，只记录类别和数量。", "", "导出期间本窗口仍可继续写入，记录止于审计文件中的源文件字节上限；本备份不是结束后的实时镜像。", "", "- [导出审计与完整性范围](export-audit.json)", "- [用户附件清单](attachments-manifest.json)", "- [文件 SHA-256](files-sha256.json)", "- [规范 JSONL](jsonl/)", ""]
    (out / "00-INDEX.md").write_text("\n".join(lines), encoding="utf-8")
    files = []
    for path in sorted(out.rglob("*")):
        if path.is_file():
            files.append({"path": path.relative_to(out).as_posix(), "bytes": path.stat().st_size, "sha256": hash_file(path)})
    (out / "files-sha256.json").write_text(json.dumps(files, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({k:audit[k] for k in ["thread_id","exported_counts","exported_items","markdown_parts","jsonl_parts","copied_user_attachments","missing_attachment_references","redactions","first_visible_timestamp_utc","last_visible_timestamp_utc"]},ensure_ascii=False))


if __name__ == "__main__":
    main()
