#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WeChat-HTML-Viewer — 高度还原 PC 微信界面的离线聊天记录查看器
================================================================
- 纯 Python 3.9+ 标准库零依赖，100% 本地离线运行，绝不联网、绝不修改原导出文件
- 自动识别 WechatExporter 导出的单账号 / 多账号 HTML 归档目录
- SQLite FTS5 (trigram) + 严格正文匹配分组搜索（还原 PC 微信搜索逻辑）
- 支持 HTTP Range 音视频拖动播放，以及可选 ffmpeg 自动解码微信 WXGF / HEIC 原图
- 内置 --demo 零隐私纯虚构演示模式，3 秒预览完整界面
"""

import argparse
import hashlib
import html
import http.server
import json
import mimetypes
import os
import pathlib
import re
import shutil
import socket
import socketserver
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser

APP_VERSION = "1.0.0"
PROJECT_DIR = pathlib.Path(__file__).resolve().parent
WEB_DIR = PROJECT_DIR / "web"
VIEWER_HTML = WEB_DIR / "viewer.html"
CACHE_ROOT = PROJECT_DIR / ".viewer_cache"
CONFIG_FILE = PROJECT_DIR / ".viewer_config.json"
DEMO_DATA_DIR = PROJECT_DIR / "_demo_data"
DEFAULT_PORT = 18765

# Regexes for parsing standard WechatExporter HTML output
RE_INDEX_ROW = re.compile(
    r'<tr[^>]*>.*?<img\s+src="([^"]*)"[^>]*>.*?<a\s+href="([^"]+)">(.*?)</a>.*?</tr>',
    re.S | re.I,
)
RE_WXID_SUFFIX = re.compile(r"\s*（微信号：([^）]+)）\s*$")
RE_MSG_SPLIT = re.compile(r'(?=<div\s+class="msg\s+)')
RE_MSG_HEADER = re.compile(
    r'<div\s+class="msg\s+([^"]*)"[^>]*?msgid="([^"]*)"(?:[^>]*?msgtype="([^"]*)")?',
    re.I,
)
RE_NT_BOX = re.compile(
    r'<div\s+class="nt-box">\s*<span[^>]*class="dspname[^"]*"[^>]*>(.*?)</span>\s*([0-9]{4}-[0-9]{2}-[0-9]{2}\s+[0-9]{2}:[0-9]{2}:[0-9]{2})?',
    re.S | re.I,
)
RE_PRE_CONTENT = re.compile(r"<pre>(.*?)</pre>", re.S | re.I)
RE_EMOJI_TITLE = re.compile(r'<img[^>]+(?:rawemoji|title)="([^"]*)"[^>]*>', re.I)
RE_HTML_TAG = re.compile(r"<[^>]+>")
RE_MSG_JS_ARRAY = re.compile(r"var\s+msgArray\s*=\s*(\[.*\])\s*;", re.S)

_DECODE_LOCKS: dict[str, threading.Lock] = {}
_DECODE_LOCKS_GUARD = threading.Lock()


def detect_ffmpeg() -> str | None:
    found = shutil.which("ffmpeg")
    if found:
        return found
    for cand in (
        r"C:\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
        "/opt/homebrew/bin/ffmpeg",
        "/usr/local/bin/ffmpeg",
        "/usr/bin/ffmpeg",
    ):
        if os.path.isfile(cand):
            return cand
    return None


FFMPEG_EXE = detect_ffmpeg()


def strip_html_text(snippet: str) -> str:
    if not snippet:
        return ""
    s = RE_EMOJI_TITLE.sub(r"\1", snippet)
    s = RE_HTML_TAG.sub(" ", s)
    s = html.unescape(s)
    s = re.sub(r"[ \t\r\f\v]+", " ", s)
    s = re.sub(r"\n\s*\n+", "\n", s)
    return s.strip()


def classify_msg_type(classes: str, msgtype: str, block: str) -> str:
    mt = (msgtype or "").lower()
    cl = (classes or "").lower()
    if mt == "image" or "raw-img" in cl or 'class="image' in block:
        return "image"
    if mt == "video" or "<video" in block or "video-box" in block:
        return "video"
    if mt == "audio" or "playAudio(" in block or "voiceimg-" in block:
        return "audio"
    if "chat-notice" in cl:
        return "notice"
    if "[文件:" in block or "[文件]" in block:
        return "file"
    if mt == "49" or "appmsg" in block:
        return "link"
    return "text"


def parse_message_block(block: str):
    m = RE_MSG_HEADER.search(block)
    if not m:
        return None
    classes, msgid, msgtype = m.group(1), m.group(2), m.group(3) or ""
    nt = RE_NT_BOX.search(block)
    sender = ""
    ts = ""
    if nt:
        sender = html.unescape(RE_HTML_TAG.sub("", nt.group(1))).strip()
        ts = (nt.group(2) or "").strip()

    mtype = classify_msg_type(classes, msgtype, block)
    pre = RE_PRE_CONTENT.search(block)
    if pre:
        content = strip_html_text(pre.group(1))
    else:
        cb_idx = block.find('<div class="content-box">')
        content = strip_html_text(block[cb_idx:]) if cb_idx != -1 else ""

    if not content:
        content = {
            "image": "[图片]",
            "video": "[视频]",
            "audio": "[语音]",
            "file": "[文件]",
        }.get(mtype, "")

    return (msgid, mtype, sender, ts, content)


def parse_chat_messages(html_path: pathlib.Path):
    """Yield (msgid, mtype, sender, ts, content) from main HTML and paginated *_files/Data/msg-*.js."""
    try:
        raw = html_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return

    msgs_div_idx = raw.find('<div class="msgs"')
    if msgs_div_idx == -1:
        msgs_div_idx = raw.find('id="msgs-div"')
    if msgs_div_idx != -1:
        footer_idx = raw.find('<div id="footer"', msgs_div_idx)
        body_part = raw[msgs_div_idx:footer_idx] if footer_idx != -1 else raw[msgs_div_idx:]
        for chunk in RE_MSG_SPLIT.split(body_part):
            if chunk.startswith('<div class="msg '):
                parsed = parse_message_block(chunk)
                if parsed:
                    yield parsed

    data_dir = html_path.parent / f"{html_path.stem}_files" / "Data"
    if data_dir.is_dir():
        js_files = sorted(
            data_dir.glob("msg-*.js"),
            key=lambda p: int(m.group(1)) if (m := re.search(r"msg-(\d+)\.js$", p.name)) else 0,
        )
        for jf in js_files:
            try:
                js_txt = jf.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            m = RE_MSG_JS_ARRAY.search(js_txt)
            if not m:
                continue
            arr_str = m.group(1)
            try:
                items = json.loads(arr_str)
            except json.JSONDecodeError:
                try:
                    items = json.loads(arr_str, strict=False)
                except Exception:
                    continue
            for item in items:
                if isinstance(item, str):
                    parsed = parse_message_block(item)
                    if parsed:
                        yield parsed


def discover_accounts(archive_root: pathlib.Path) -> list[dict]:
    """
    Auto-detect WechatExporter accounts from either:
    1) Root export folder: index.html pointing to <Account>/index.html
    2) Direct account folder: index.html directly listing chat *.html files
    3) Parent folder containing subdirectories with index.html
    """
    archive_root = archive_root.resolve()
    accounts: list[dict] = []
    root_index = archive_root / "index.html"

    if root_index.is_file():
        raw = root_index.read_text(encoding="utf-8", errors="replace")
        rows = list(RE_INDEX_ROW.finditer(raw))
        sub_links = [m for m in rows if m.group(2).strip().lower().endswith("/index.html")]
        if sub_links:
            for m in sub_links:
                avatar_src = urllib.parse.unquote(html.unescape(m.group(1).strip()))
                href = urllib.parse.unquote(m.group(2).strip())
                acc_name = html.unescape(RE_HTML_TAG.sub("", m.group(3))).strip()
                sub_dir = (archive_root / href).parent.resolve()
                if not (sub_dir / "index.html").is_file():
                    continue
                # Compute avatar relative to sub_dir
                av_rel = ""
                if avatar_src:
                    av_abs = (archive_root / avatar_src).resolve()
                    try:
                        av_rel = av_abs.relative_to(sub_dir).as_posix()
                    except ValueError:
                        av_rel = ""
                accounts.append({
                    "id": hashlib.sha1(str(sub_dir).encode("utf-8")).hexdigest()[:12],
                    "name": acc_name or sub_dir.name,
                    "account_dir": sub_dir,
                    "avatar_rel": av_rel,
                })
        elif rows:
            # Direct account folder!
            accounts.append({
                "id": hashlib.sha1(str(archive_root).encode("utf-8")).hexdigest()[:12],
                "name": archive_root.name,
                "account_dir": archive_root,
                "avatar_rel": "",
            })

    if not accounts:
        # Fallback: scan immediate subdirectories for WechatExporter index.html
        for child in sorted(archive_root.iterdir()):
            if child.is_dir() and not child.name.startswith((".", "_")) and (child / "index.html").is_file():
                raw = (child / "index.html").read_text(encoding="utf-8", errors="replace")
                if RE_INDEX_ROW.search(raw):
                    accounts.append({
                        "id": hashlib.sha1(str(child.resolve()).encode("utf-8")).hexdigest()[:12],
                        "name": child.name,
                        "account_dir": child.resolve(),
                        "avatar_rel": "",
                    })

    return accounts


def parse_account_chats(account_dir: pathlib.Path) -> list[dict]:
    index_path = account_dir / "index.html"
    if not index_path.is_file():
        raise FileNotFoundError(f"找不到会话索引文件: {index_path}")
    raw = index_path.read_text(encoding="utf-8", errors="replace")
    chats = []
    for rank, m in enumerate(RE_INDEX_ROW.finditer(raw), start=1):
        avatar_rel = html.unescape(m.group(1).strip())
        href = m.group(2).strip()
        if href.lower().endswith("/index.html"):
            continue
        raw_label = html.unescape(RE_HTML_TAG.sub("", m.group(3))).strip()
        wxid = ""
        display_name = raw_label
        wm = RE_WXID_SUFFIX.search(raw_label)
        if wm:
            wxid = wm.group(1).strip()
            display_name = raw_label[: wm.start()].strip()
        is_group = 1 if "@chatroom" in urllib.parse.unquote(avatar_rel).lower() else 0
        filename = urllib.parse.unquote(href)
        chats.append({
            "rank": rank,
            "name": display_name or (filename[:-5] if filename.lower().endswith(".html") else filename),
            "raw_label": raw_label,
            "wxid": wxid,
            "href": href,
            "filename": filename,
            "avatar": avatar_rel,
            "is_group": is_group,
        })
    return chats


class ArchiveContext:
    """Holds active account state, SQLite index path, and cache folder."""

    def __init__(self, archive_root: pathlib.Path, accounts: list[dict], active_idx: int = 0, is_demo: bool = False):
        self.archive_root = archive_root.resolve()
        self.accounts = accounts
        self.active_idx = max(0, min(active_idx, len(accounts) - 1))
        self.is_demo = is_demo
        self.lock = threading.Lock()
        self.wxgf_cache_dir = CACHE_ROOT / "wxgf_cache"

    @property
    def active_account(self) -> dict:
        return self.accounts[self.active_idx]

    @property
    def account_dir(self) -> pathlib.Path:
        return self.active_account["account_dir"]

    @property
    def db_path(self) -> pathlib.Path:
        acc_id = self.active_account["id"]
        d = CACHE_ROOT / f"idx_{acc_id}"
        d.mkdir(parents=True, exist_ok=True)
        return d / "search_index.db"

    def ensure_index(self, force: bool = False):
        dbp = self.db_path
        if dbp.exists() and not force:
            try:
                conn = sqlite3.connect(dbp)
                cnt = conn.execute("SELECT COUNT(*) FROM chats").fetchone()[0]
                cols = [r[1] for r in conn.execute("PRAGMA table_info(chats)").fetchall()]
                if "hidden" not in cols:
                    conn.execute("ALTER TABLE chats ADD COLUMN hidden INTEGER NOT NULL DEFAULT 0")
                    conn.commit()
                conn.close()
                if cnt > 0:
                    return
            except Exception:
                pass

        t0 = time.time()
        acc_name = self.active_account["name"]
        print(f"[索引] 正在为账号「{acc_name}」建立本地离线全文索引...")
        chats = parse_account_chats(self.account_dir)

        tmp_db = dbp.with_suffix(".db.tmp")
        if tmp_db.exists():
            tmp_db.unlink()

        conn = sqlite3.connect(tmp_db)
        conn.execute("PRAGMA journal_mode = OFF")
        conn.execute("PRAGMA synchronous = OFF")
        conn.execute("PRAGMA temp_store = MEMORY")
        conn.executescript(
            """
            CREATE TABLE chats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rank INTEGER NOT NULL,
                name TEXT NOT NULL,
                raw_label TEXT NOT NULL,
                wxid TEXT NOT NULL,
                href TEXT NOT NULL,
                filename TEXT NOT NULL,
                avatar TEXT NOT NULL,
                is_group INTEGER NOT NULL,
                msg_count INTEGER NOT NULL DEFAULT 0,
                last_time TEXT NOT NULL DEFAULT '',
                last_preview TEXT NOT NULL DEFAULT '',
                hidden INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                msg_id TEXT NOT NULL,
                msg_type TEXT NOT NULL,
                sender TEXT NOT NULL,
                ts TEXT NOT NULL,
                content TEXT NOT NULL
            );
            CREATE INDEX idx_messages_chat ON messages(chat_id);
            CREATE VIRTUAL TABLE messages_fts USING fts5(
                content,
                sender,
                content='messages',
                content_rowid='id',
                tokenize='trigram'
            );
            """
        )

        cur = conn.cursor()
        total_msgs = 0
        for i, ch in enumerate(chats, start=1):
            html_path = self.account_dir / ch["filename"]
            cur.execute(
                """
                INSERT INTO chats(rank, name, raw_label, wxid, href, filename, avatar, is_group, hidden)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    ch["rank"], ch["name"], ch["raw_label"], ch["wxid"],
                    ch["href"], ch["filename"], ch["avatar"], ch["is_group"],
                ),
            )
            chat_id = cur.lastrowid

            batch = []
            msg_count = 0
            last_time = ""
            last_preview = ""
            if html_path.is_file():
                for msgid, mtype, sender, ts, content in parse_chat_messages(html_path):
                    batch.append((chat_id, msgid, mtype, sender, ts, content))
                    msg_count += 1
                    if ts:
                        last_time = ts
                    if content:
                        preview_text = content.replace("\n", " ")[:60]
                        last_preview = f"{sender}: {preview_text}" if (ch["is_group"] and sender) else preview_text
                    if len(batch) >= 2000:
                        cur.executemany(
                            "INSERT INTO messages(chat_id, msg_id, msg_type, sender, ts, content) VALUES (?, ?, ?, ?, ?, ?)",
                            batch,
                        )
                        batch.clear()
            if batch:
                cur.executemany(
                    "INSERT INTO messages(chat_id, msg_id, msg_type, sender, ts, content) VALUES (?, ?, ?, ?, ?, ?)",
                    batch,
                )

            cur.execute(
                "UPDATE chats SET msg_count=?, last_time=?, last_preview=? WHERE id=?",
                (msg_count, last_time, last_preview, chat_id),
            )
            total_msgs += msg_count
            if i % 150 == 0 or i == len(chats):
                print(f"[索引] 进度: {i}/{len(chats)} 会话，已解析 {total_msgs} 条消息...")

        conn.execute("INSERT INTO messages_fts(messages_fts) VALUES('rebuild')")
        conn.commit()
        conn.close()

        if dbp.exists():
            dbp.unlink()
        tmp_db.replace(dbp)
        print(f"[索引] 完成！共 {len(chats)} 个会话、{total_msgs} 条消息，耗时 {time.time() - t0:.1f} 秒。")

    def switch_account(self, acc_id: str) -> bool:
        with self.lock:
            for idx, a in enumerate(self.accounts):
                if a["id"] == acc_id:
                    self.active_idx = idx
                    self.ensure_index(force=False)
                    return True
        return False


def query_search(
    db_path: pathlib.Path,
    q: str,
    chat_id: int | None,
    msg_type: str,
    date_from: str,
    date_to: str,
    limit: int,
    offset: int,
    group_by_chat: bool = False,
):
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    q = (q or "").strip()
    tokens = [t for t in re.split(r"\s+", q) if t]

    where_clauses = []
    params = []

    # Strictly search message content ONLY (never pollute with sender nickname)
    use_fts = bool(tokens) and all(len(t) >= 3 for t in tokens)

    if use_fts:
        fts_expr = " AND ".join('content : "' + t.replace('"', '""') + '"' for t in tokens)
        base_from = (
            "FROM messages_fts f "
            "JOIN messages m ON m.id = f.rowid "
            "JOIN chats c ON c.id = m.chat_id"
        )
        where_clauses.append("messages_fts MATCH ?")
        params.append(fts_expr)
    else:
        base_from = "FROM messages m JOIN chats c ON c.id = m.chat_id"
        for t in tokens:
            where_clauses.append("m.content LIKE ?")
            params.append(f"%{t}%")

    if chat_id:
        where_clauses.append("m.chat_id = ?")
        params.append(chat_id)
    else:
        where_clauses.append("COALESCE(c.hidden, 0) = 0")
    if msg_type and msg_type != "all":
        where_clauses.append("m.msg_type = ?")
        params.append(msg_type)
    if date_from:
        where_clauses.append("m.ts >= ?")
        params.append(date_from + " 00:00:00")
    if date_to:
        where_clauses.append("m.ts <= ?")
        params.append(date_to + " 23:59:59")

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    if group_by_chat and not chat_id:
        grouped_rows = cur.execute(
            f"""
            WITH matched AS (
                SELECT m.id, m.chat_id, m.msg_id, m.msg_type, m.sender, m.ts, m.content
                {base_from} {where_sql}
            ),
            ranked AS (
                SELECT *,
                       COUNT(*) OVER (PARTITION BY chat_id) AS hit_count,
                       ROW_NUMBER() OVER (PARTITION BY chat_id ORDER BY ts DESC, id DESC) AS rn
                FROM matched
            )
            SELECT r.id, r.chat_id, r.msg_id, r.msg_type, r.sender, r.ts, r.content, r.hit_count,
                   c.name AS chat_name, c.avatar AS chat_avatar, c.href AS chat_href, c.is_group
            FROM ranked r
            JOIN chats c ON c.id = r.chat_id
            WHERE r.rn = 1
            ORDER BY r.ts DESC, r.id DESC
            LIMIT ? OFFSET ?
            """,
            params + [limit, offset],
        ).fetchall()
        totals = cur.execute(
            f"SELECT COUNT(*) AS total_msgs, COUNT(DISTINCT m.chat_id) AS total_chats {base_from} {where_sql}",
            params,
        ).fetchone()
        conn.close()
        return {
            "total": totals["total_msgs"] if totals else 0,
            "total_chats": totals["total_chats"] if totals else 0,
            "use_fts": use_fts,
            "grouped": True,
            "items": [dict(r) for r in grouped_rows],
        }

    total = cur.execute(f"SELECT COUNT(*) {base_from} {where_sql}", params).fetchone()[0]

    chat_summary = []
    if not chat_id:
        sum_rows = cur.execute(
            f"""
            SELECT c.id, c.name, c.avatar, c.href, c.is_group, COUNT(*) as hit_count
            {base_from} {where_sql}
            GROUP BY c.id
            ORDER BY hit_count DESC
            LIMIT 30
            """,
            params,
        ).fetchall()
        chat_summary = [dict(r) for r in sum_rows]

    rows = cur.execute(
        f"""
        SELECT m.id, m.chat_id, m.msg_id, m.msg_type, m.sender, m.ts, m.content,
               c.name AS chat_name, c.avatar AS chat_avatar, c.href AS chat_href, c.is_group
        {base_from} {where_sql}
        ORDER BY m.ts DESC, m.id DESC
        LIMIT ? OFFSET ?
        """,
        params + [limit, offset],
    ).fetchall()

    conn.close()
    return {
        "total": total,
        "use_fts": use_fts,
        "grouped": False,
        "chat_summary": chat_summary,
        "items": [dict(r) for r in rows],
    }


def _get_decode_lock(key: str) -> threading.Lock:
    with _DECODE_LOCKS_GUARD:
        lk = _DECODE_LOCKS.get(key)
        if lk is None:
            lk = threading.Lock()
            _DECODE_LOCKS[key] = lk
        return lk


def maybe_decode_special_image(file_path: pathlib.Path, cache_dir: pathlib.Path) -> pathlib.Path:
    """Transparently decode WeChat WXGF (HEVC) or HEIC images into cached standard JPEG without touching originals."""
    if not FFMPEG_EXE:
        return file_path
    if file_path.suffix.lower() not in (".jpg", ".jpeg", ".png", ".gif", ".pic", ".heic"):
        return file_path
    try:
        with file_path.open("rb") as f:
            head = f.read(16)
    except OSError:
        return file_path

    is_wxgf = head.startswith(b"wxgf")
    is_heic = len(head) >= 12 and head[4:8] == b"ftyp" and head[8:12] in (b"heic", b"heix", b"mif1", b"msf1")
    if not (is_wxgf or is_heic):
        return file_path

    st = file_path.stat()
    key = hashlib.sha1(f"{file_path}|{st.st_size}|{st.st_mtime_ns}".encode("utf-8")).hexdigest()
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / f"{key}.jpg"
    if cached.is_file() and cached.stat().st_size > 0:
        return cached

    with _get_decode_lock(key):
        if cached.is_file() and cached.stat().st_size > 0:
            return cached
        try:
            if is_wxgf:
                data = file_path.read_bytes()
                pos = data.find(b"\x00\x00\x00\x01\x40\x01")
                if pos == -1:
                    pos = data.find(b"\x00\x00\x00\x01")
                if pos == -1:
                    return file_path
                proc = subprocess.run(
                    [
                        FFMPEG_EXE, "-hide_banner", "-loglevel", "error",
                        "-f", "hevc", "-i", "pipe:0",
                        "-frames:v", "1", "-q:v", "2",
                        "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1",
                    ],
                    input=data[pos:],
                    capture_output=True,
                    timeout=12,
                )
            else:
                proc = subprocess.run(
                    [
                        FFMPEG_EXE, "-hide_banner", "-loglevel", "error",
                        "-i", str(file_path),
                        "-frames:v", "1", "-q:v", "2",
                        "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1",
                    ],
                    capture_output=True,
                    timeout=12,
                )
            if proc.returncode == 0 and proc.stdout.startswith(b"\xff\xd8\xff"):
                tmp = cache_dir / f"{key}.{threading.get_ident()}.tmp"
                tmp.write_bytes(proc.stdout)
                os.replace(tmp, cached)
                return cached
        except Exception:
            pass
    return file_path


def make_handler(ctx: ArchiveContext):
    class WeChatViewerHandler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):
            pass

        def send_json(self, obj, status=200):
            data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def serve_file(self, file_path: pathlib.Path):
            if not file_path.is_file():
                self.send_error(404, "File not found")
                return
            orig_path = file_path
            file_path = maybe_decode_special_image(file_path, ctx.wxgf_cache_dir)
            decoded = file_path != orig_path
            file_size = file_path.stat().st_size
            ctype, _ = mimetypes.guess_type(str(file_path))
            if decoded:
                ctype = "image/jpeg"
            if not ctype:
                ext = file_path.suffix.lower()
                ctype = {".mp3": "audio/mpeg", ".mp4": "video/mp4"}.get(ext, "application/octet-stream")
            if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
                ctype += "; charset=utf-8"

            range_header = self.headers.get("Range")
            start, end, status = 0, file_size - 1, 200

            if range_header and range_header.startswith("bytes="):
                try:
                    spec = range_header[6:].split(",")[0].strip()
                    s_str, e_str = spec.split("-", 1)
                    if s_str:
                        start = int(s_str)
                        end = int(e_str) if e_str else file_size - 1
                    else:
                        suffix_len = int(e_str)
                        start = max(0, file_size - suffix_len)
                        end = file_size - 1
                    if start >= file_size or start > end:
                        self.send_response(416)
                        self.send_header("Content-Range", f"bytes */{file_size}")
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                    end = min(end, file_size - 1)
                    status = 206
                except Exception:
                    start, end, status = 0, file_size - 1, 200

            length = end - start + 1
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Accept-Ranges", "bytes")
            if status == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
            self.send_header("Content-Length", str(length))
            self.end_headers()

            if self.command == "HEAD":
                return

            with file_path.open("rb") as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = f.read(min(65536, remaining))
                    if not chunk:
                        break
                    try:
                        self.wfile.write(chunk)
                    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                        break
                    remaining -= len(chunk)

        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            parsed = urllib.parse.urlsplit(self.path)
            path = parsed.path
            qs = urllib.parse.parse_qs(parsed.query)

            if path in ("/", "/viewer", "/viewer.html"):
                self.serve_file(VIEWER_HTML)
                return

            if path == "/api/status":
                acc = ctx.active_account
                conn = sqlite3.connect(f"file:{ctx.db_path}?mode=ro", uri=True)
                chats_cnt = conn.execute("SELECT COUNT(*) FROM chats WHERE COALESCE(hidden,0)=0").fetchone()[0]
                hidden_cnt = conn.execute("SELECT COUNT(*) FROM chats WHERE COALESCE(hidden,0)=1").fetchone()[0]
                msgs_cnt = conn.execute(
                    "SELECT COALESCE(SUM(msg_count),0) FROM chats WHERE COALESCE(hidden,0)=0"
                ).fetchone()[0]
                conn.close()
                self.send_json({
                    "ok": True,
                    "version": APP_VERSION,
                    "is_demo": ctx.is_demo,
                    "has_ffmpeg": bool(FFMPEG_EXE),
                    "account": {
                        "id": acc["id"],
                        "name": acc["name"],
                        "avatar": ("/archive/" + acc["avatar_rel"]) if acc["avatar_rel"] else "",
                    },
                    "accounts": [{"id": a["id"], "name": a["name"]} for a in ctx.accounts],
                    "chats": chats_cnt,
                    "hidden_chats": hidden_cnt,
                    "messages": msgs_cnt,
                })
                return

            if path == "/api/chats":
                conn = sqlite3.connect(f"file:{ctx.db_path}?mode=ro", uri=True)
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT id, rank, name, wxid, href, avatar, is_group, msg_count, last_time, last_preview, COALESCE(hidden,0) AS hidden FROM chats ORDER BY rank ASC"
                ).fetchall()
                conn.close()
                self.send_json({"chats": [dict(r) for r in rows]})
                return

            if path == "/api/search":
                q = qs.get("q", [""])[0]
                chat_id_raw = qs.get("chat_id", [""])[0]
                chat_id = int(chat_id_raw) if chat_id_raw.isdigit() else None
                msg_type = qs.get("type", ["all"])[0]
                date_from = qs.get("from", [""])[0]
                date_to = qs.get("to", [""])[0]
                grouped = qs.get("grouped", ["0"])[0] == "1"
                max_limit = 500 if grouped else 200
                limit = min(int(qs.get("limit", ["60"])[0]), max_limit)
                offset = max(int(qs.get("offset", ["0"])[0]), 0)
                try:
                    res = query_search(
                        ctx.db_path, q, chat_id, msg_type, date_from, date_to, limit, offset, group_by_chat=grouped
                    )
                    self.send_json(res)
                except Exception as e:
                    self.send_json({"error": str(e), "total": 0, "items": [], "chat_summary": []}, status=500)
                return

            if path.startswith("/archive/"):
                rel = urllib.parse.unquote(path[len("/archive/"):])
                base = ctx.account_dir.resolve()
                target = (base / rel).resolve()
                try:
                    target.relative_to(base)
                except ValueError:
                    self.send_error(403, "Forbidden")
                    return
                self.serve_file(target)
                return

            self.send_error(404, "Not found")

        def _read_json_body(self):
            try:
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length) if length > 0 else b"{}"
                return json.loads(raw.decode("utf-8"))
            except Exception:
                return {}

        def do_POST(self):
            parsed = urllib.parse.urlsplit(self.path)
            path = parsed.path
            body = self._read_json_body()

            if path == "/api/account/switch":
                acc_id = str(body.get("id", ""))
                ok = ctx.switch_account(acc_id)
                self.send_json({"ok": ok}, status=200 if ok else 404)
                return

            ids = [int(x) for x in body.get("ids", []) if str(x).isdigit()]

            if path in ("/api/chats/hide", "/api/chats/restore"):
                if not ids:
                    self.send_json({"ok": False, "error": "未指定会话 ID"}, status=400)
                    return
                flag = 1 if path.endswith("/hide") else 0
                conn = sqlite3.connect(ctx.db_path)
                placeholders = ",".join("?" for _ in ids)
                cur = conn.execute(f"UPDATE chats SET hidden = ? WHERE id IN ({placeholders})", [flag] + ids)
                conn.commit()
                affected = cur.rowcount
                conn.close()
                self.send_json({"ok": True, "affected": affected, "hidden": flag})
                return

            if path == "/api/chats/purge":
                if not ids or not body.get("confirm"):
                    self.send_json({"ok": False, "error": "缺少二次确认参数"}, status=400)
                    return
                conn = sqlite3.connect(ctx.db_path)
                conn.row_factory = sqlite3.Row
                placeholders = ",".join("?" for _ in ids)
                rows = conn.execute(
                    f"SELECT id, filename FROM chats WHERE COALESCE(hidden,0)=1 AND id IN ({placeholders})",
                    ids,
                ).fetchall()
                freed_bytes = 0
                purged_ids = []
                acc_resolved = ctx.account_dir.resolve()
                for r in rows:
                    fn = r["filename"]
                    html_fp = (acc_resolved / fn).resolve()
                    files_dir = (acc_resolved / (pathlib.Path(fn).stem + "_files")).resolve()
                    try:
                        html_fp.relative_to(acc_resolved)
                        if html_fp.is_file():
                            freed_bytes += html_fp.stat().st_size
                            html_fp.unlink()
                    except Exception:
                        pass
                    try:
                        files_dir.relative_to(acc_resolved)
                        if files_dir.is_dir():
                            for p in files_dir.rglob("*"):
                                if p.is_file():
                                    try:
                                        freed_bytes += p.stat().st_size
                                    except OSError:
                                        pass
                            shutil.rmtree(files_dir, ignore_errors=True)
                    except Exception:
                        pass
                    purged_ids.append(r["id"])

                if purged_ids:
                    ph2 = ",".join("?" for _ in purged_ids)
                    conn.execute(f"DELETE FROM messages WHERE chat_id IN ({ph2})", purged_ids)
                    conn.execute(f"DELETE FROM chats WHERE id IN ({ph2})", purged_ids)
                    conn.execute("INSERT INTO messages_fts(messages_fts) VALUES('rebuild')")
                    conn.commit()
                conn.close()
                self.send_json({
                    "ok": True,
                    "purged": len(purged_ids),
                    "freed_mb": round(freed_bytes / (1024 * 1024), 2),
                })
                return

            self.send_json({"ok": False, "error": "Unknown endpoint"}, status=404)

    return WeChatViewerHandler


class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def find_free_port(preferred: int) -> int:
    for p in range(preferred, preferred + 30):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", p)) != 0:
                return p
    return 0


def load_saved_dir() -> pathlib.Path | None:
    if not CONFIG_FILE.is_file():
        return None
    try:
        cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        p = pathlib.Path(cfg.get("archive_dir", ""))
        if p.is_dir() and discover_accounts(p):
            return p
    except Exception:
        pass
    return None


def save_last_dir(path: pathlib.Path):
    try:
        CONFIG_FILE.write_text(
            json.dumps({"archive_dir": str(path.resolve())}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass


def prompt_select_archive_dir() -> pathlib.Path | None:
    """Open native folder picker if Tkinter is available, else prompt in terminal."""
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        chosen = filedialog.askdirectory(
            title="请选择 WechatExporter 导出的 HTML 聊天记录根目录"
        )
        root.destroy()
        if chosen:
            return pathlib.Path(chosen)
    except Exception:
        pass

    print("\n未在当前目录自动检测到 WechatExporter 导出的聊天记录。")
    print("提示：")
    print("  1) 可输入 WechatExporter 导出目录的路径（含 index.html）")
    print("  2) 或直接运行 `python viewer_server.py --demo` 体验内置演示数据")
    try:
        raw = input("\n请输入导出目录路径（留空退出）：").strip().strip('"').strip("'")
    except EOFError:
        return None
    return pathlib.Path(raw) if raw else None


def resolve_archive_dir(args) -> tuple[pathlib.Path, bool]:
    if args.demo:
        sys.path.insert(0, str(PROJECT_DIR / "demo"))
        from generate_demo import generate_demo_export

        print("[演示模式] 正在准备纯虚构中文演示数据集...")
        generate_demo_export(DEMO_DATA_DIR, force=args.rebuild)
        return DEMO_DATA_DIR, True

    candidates = []
    if args.dir:
        candidates.append(pathlib.Path(args.dir))
    env_dir = os.environ.get("WECHAT_ARCHIVE_DIR")
    if env_dir:
        candidates.append(pathlib.Path(env_dir))
    if not args.pick:
        # Auto-detect current working directory, project directory, parent directory, or last saved path
        candidates.extend([pathlib.Path.cwd(), PROJECT_DIR, PROJECT_DIR.parent])
        saved = load_saved_dir()
        if saved:
            candidates.append(saved)

    for cand in candidates:
        if cand and cand.is_dir():
            accs = discover_accounts(cand)
            if accs:
                if not str(cand.resolve()).startswith(str(DEMO_DATA_DIR.resolve())):
                    save_last_dir(cand)
                return cand.resolve(), False

    picked = prompt_select_archive_dir()
    if picked and picked.is_dir() and discover_accounts(picked):
        save_last_dir(picked)
        return picked.resolve(), False

    print("\n[错误] 未在所选目录中检测到有效的 WechatExporter HTML 导出结构（需要包含 index.html）。")
    print("请先使用开源工具 WechatExporter 将聊天记录导出为 HTML 格式，再运行本查看器。")
    print("如果想先预览界面，请运行：python viewer_server.py --demo")
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        prog="WeChat-HTML-Viewer",
        description="高度还原 PC 微信界面的离线 HTML 聊天记录查看器（配合 WechatExporter 使用）",
    )
    parser.add_argument("--dir", "-d", help="WechatExporter 导出的 HTML 根目录或单个账号目录")
    parser.add_argument("--demo", action="store_true", help="启动内置纯虚构中文演示模式（零隐私，3秒预览）")
    parser.add_argument("--pick", action="store_true", help="强制弹出文件夹选择框重新指定导出目录")
    parser.add_argument("--account", help="多账号导出时指定默认打开的账号名")
    parser.add_argument("--port", "-p", type=int, default=DEFAULT_PORT, help=f"本地服务端口（默认 {DEFAULT_PORT}）")
    parser.add_argument("--rebuild", action="store_true", help="强制重建全文检索索引")
    parser.add_argument("--index-only", action="store_true", help="仅构建索引后退出，不启动 HTTP 服务")
    parser.add_argument("--no-browser", action="store_true", help="启动服务但不自动打开浏览器")
    args = parser.parse_args()

    archive_root, is_demo = resolve_archive_dir(args)
    accounts = discover_accounts(archive_root)
    if not accounts:
        print(f"[错误] 在 {archive_root} 中未找到有效会话索引。")
        sys.exit(1)

    active_idx = 0
    if args.account:
        for i, a in enumerate(accounts):
            if a["name"] == args.account:
                active_idx = i
                break

    ctx = ArchiveContext(archive_root, accounts, active_idx=active_idx, is_demo=is_demo)
    ctx.ensure_index(force=args.rebuild)
    if args.index_only:
        return

    port = find_free_port(args.port)
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(ctx))
    url = f"http://127.0.0.1:{port}/"
    print("=" * 60)
    print(f"  WeChat-HTML-Viewer v{APP_VERSION} 已启动: {url}")
    print(f"  当前目录: {archive_root}")
    print(f"  当前账号: {ctx.active_account['name']}（共发现 {len(accounts)} 个账号）")
    print(f"  WXGF/HEIC 自动解码: {'已就绪 (' + FFMPEG_EXE + ')' if FFMPEG_EXE else '未检测到 ffmpeg（可选安装）'}")
    print("  100% 本机离线运行，关闭本窗口即可停止服务")
    print("=" * 60)

    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止查看器服务。")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
