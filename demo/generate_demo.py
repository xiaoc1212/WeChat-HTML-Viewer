#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成 100% 虚构的 WechatExporter 标准格式演示数据集（零依赖纯 Python 标准库）
- 绝不包含任何真实个人信息，专用于 --demo 一键体验与开源项目展示截图
- 生成丰富的程序化风景/插画 PNG 示例图与可选 MP4 测试视频
"""

import datetime
import html
import json
import math
import os
import pathlib
import shutil
import struct
import subprocess
import urllib.parse
import zlib


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    chunk = chunk_type + data
    return struct.pack(">I", len(data)) + chunk + struct.pack(">I", zlib.crc32(chunk) & 0xFFFFFFFF)


def write_rgb_png(path: pathlib.Path, width: int, height: int, pixel_rows: list[bytes]):
    """Write a standard RGB PNG using only Python stdlib zlib/struct."""
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = b"".join(b"\x00" + row for row in pixel_rows)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    png = (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(raw, level=6))
        + _png_chunk(b"IEND", b"")
    )
    path.write_bytes(png)


def _lerp(a: float, b: float, t: float) -> int:
    return max(0, min(255, int(a + (b - a) * t)))


def make_avatar_png(path: pathlib.Path, c1: tuple[int, int, int], c2: tuple[int, int, int], style: int = 0):
    """Generate a clean 84x84 stylized avatar PNG (gradient + geometric silhouette / group 4-grid)."""
    w = h = 84
    rows = []
    if style == 1:
        # WeChat-like 4-tile group avatar
        palette = [
            ((78, 168, 222), (46, 118, 179)),
            ((102, 187, 106), (56, 142, 60)),
            ((255, 167, 38), (230, 115, 20)),
            ((171, 114, 212), (123, 72, 172)),
        ]
        bg = (224, 228, 232)
        for y in range(h):
            row = bytearray()
            for x in range(w):
                # 2x2 grid inside 6..78 with 4px gap
                in_l = 6 <= x < 40
                in_r = 44 <= x < 78
                in_t = 6 <= y < 40
                in_b = 44 <= y < 78
                if (in_l or in_r) and (in_t or in_b):
                    qi = (0 if in_t else 2) + (0 if in_l else 1)
                    lx = (x - (6 if in_l else 44)) / 34.0
                    ly = (y - (6 if in_t else 44)) / 34.0
                    p1, p2 = palette[(qi + c1[0]) % 4]
                    # subtle person icon inside each tile
                    dx, dy = lx - 0.5, ly - 0.36
                    in_head = dx * dx + dy * dy < 0.038
                    in_body = (lx - 0.5) ** 2 / 0.13 + (ly - 0.96) ** 2 / 0.14 < 1.0 and ly > 0.56
                    if in_head or in_body:
                        row.extend((248, 250, 252))
                    else:
                        t = (lx + ly) * 0.5
                        row.extend((_lerp(p1[0], p2[0], t), _lerp(p1[1], p2[1], t), _lerp(p1[2], p2[2], t)))
                else:
                    row.extend(bg)
            rows.append(bytes(row))
    else:
        for y in range(h):
            row = bytearray()
            ny = y / (h - 1)
            for x in range(w):
                nx = x / (w - 1)
                t = 0.65 * ny + 0.35 * nx
                r = _lerp(c1[0], c2[0], t)
                g = _lerp(c1[1], c2[1], t)
                b = _lerp(c1[2], c2[2], t)
                # Minimalist clean avatar silhouette
                dx, dy = nx - 0.5, ny - 0.37
                in_head = dx * dx + dy * dy < 0.032
                in_body = (nx - 0.5) ** 2 / 0.115 + (ny - 0.92) ** 2 / 0.13 < 1.0 and ny > 0.55
                if in_head or in_body:
                    r = _lerp(r, 255, 0.88)
                    g = _lerp(g, 255, 0.88)
                    b = _lerp(b, 255, 0.88)
                row.extend((r, g, b))
            rows.append(bytes(row))
    write_rgb_png(path, w, h, rows)


SCENES = [
    # (sky_top, sky_mid, sky_bot, sun_xy, sun_r, sun_col, mtn1_col, mtn2_col, water_tint, seed, stars)
    ((22, 34, 72), (112, 78, 128), (244, 152, 92), (0.72, 0.34), 0.11, (255, 232, 168), (58, 44, 76), (32, 26, 48), (195, 118, 96), 1.1, False),
    ((28, 98, 168), (104, 178, 226), (218, 240, 252), (0.26, 0.25), 0.09, (255, 252, 224), (54, 108, 94), (34, 76, 62), (82, 146, 178), 2.3, False),
    ((10, 18, 42), (20, 42, 86), (36, 82, 118), (0.76, 0.24), 0.08, (242, 248, 255), (18, 34, 52), (12, 22, 34), (24, 54, 84), 3.7, True),
    ((46, 116, 86), (126, 184, 142), (232, 242, 206), (0.50, 0.28), 0.10, (255, 248, 208), (48, 96, 64), (28, 66, 44), (96, 152, 124), 4.5, False),
    ((128, 52, 48), (218, 114, 62), (252, 198, 112), (0.34, 0.36), 0.12, (255, 242, 186), (114, 48, 34), (72, 28, 24), (196, 118, 68), 5.2, False),
    ((42, 54, 112), (124, 114, 188), (236, 182, 206), (0.64, 0.28), 0.09, (255, 244, 232), (76, 64, 112), (48, 38, 76), (146, 122, 168), 6.8, True),
    ((22, 84, 116), (62, 154, 176), (188, 234, 228), (0.80, 0.22), 0.08, (255, 255, 232), (38, 98, 108), (22, 64, 74), (58, 138, 156), 7.4, False),
    ((64, 46, 36), (156, 114, 72), (242, 204, 144), (0.48, 0.32), 0.11, (255, 246, 204), (118, 78, 46), (82, 52, 30), (168, 132, 86), 8.9, False),
    ((18, 64, 132), (82, 148, 218), (206, 232, 250), (0.20, 0.30), 0.09, (255, 250, 224), (86, 108, 134), (48, 68, 94), (74, 132, 186), 9.6, False),
    ((28, 24, 58), (74, 48, 112), (176, 92, 128), (0.52, 0.40), 0.13, (255, 208, 152), (44, 28, 64), (24, 16, 40), (118, 66, 98), 10.3, True),
    ((52, 112, 146), (148, 192, 208), (246, 236, 218), (0.68, 0.24), 0.09, (255, 246, 218), (94, 116, 128), (58, 76, 86), (132, 168, 184), 11.7, False),
    ((24, 86, 68), (82, 164, 124), (204, 238, 192), (0.36, 0.26), 0.10, (252, 255, 214), (36, 86, 64), (20, 56, 42), (76, 142, 114), 12.4, False),
]


def make_scenic_png(path: pathlib.Path, scene_idx: int, width: int = 320, height: int = 240):
    """Paint a crisp, colorful procedural landscape/skyline/sunset illustration PNG."""
    sky_top, sky_mid, sky_bot, sun_xy, sun_r, sun_col, mtn1, mtn2, water, seed, has_stars = SCENES[scene_idx % len(SCENES)]
    horizon = 0.66
    sx, sy = sun_xy
    rows = []

    # Precompute mountain ridges & stars
    ridge1 = [
        horizon - 0.09 - 0.13 * abs(math.sin(x / width * 4.2 + seed)) - 0.05 * math.sin(x / width * 11.5 + seed * 2.1)
        for x in range(width)
    ]
    ridge2 = [
        horizon - 0.03 - 0.09 * abs(math.cos(x / width * 5.6 + seed * 1.4)) - 0.035 * math.sin(x / width * 15.0 + seed)
        for x in range(width)
    ]
    stars = set()
    if has_stars:
        for k in range(38):
            rx = int(((math.sin(k * 12.9898 + seed * 78.233) * 43758.5453) % 1.0) * width)
            ry = int(((math.sin(k * 93.9898 + seed * 19.13) * 19341.231) % 1.0) * (height * 0.48))
            stars.add((rx, ry))

    for y in range(height):
        ny = y / (height - 1)
        row = bytearray()
        if ny < horizon:
            t_sky = ny / horizon
            if t_sky < 0.55:
                k = t_sky / 0.55
                sr = _lerp(sky_top[0], sky_mid[0], k)
                sg = _lerp(sky_top[1], sky_mid[1], k)
                sb = _lerp(sky_top[2], sky_mid[2], k)
            else:
                k = (t_sky - 0.55) / 0.45
                sr = _lerp(sky_mid[0], sky_bot[0], k)
                sg = _lerp(sky_mid[1], sky_bot[1], k)
                sb = _lerp(sky_mid[2], sky_bot[2], k)

            for x in range(width):
                nx = x / (width - 1)
                r, g, b = sr, sg, sb
                # Sun / moon glow
                dx = (nx - sx) * (width / height)
                dy = ny - sy
                dist = math.sqrt(dx * dx + dy * dy)
                if dist < sun_r:
                    r, g, b = sun_col
                elif dist < sun_r * 2.6:
                    glow = max(0.0, 1.0 - (dist - sun_r) / (sun_r * 1.6)) ** 2 * 0.48
                    r = _lerp(r, sun_col[0], glow)
                    g = _lerp(g, sun_col[1], glow)
                    b = _lerp(b, sun_col[2], glow)
                if has_stars and (x, y) in stars:
                    r, g, b = 248, 250, 255
                # Layered mountains
                if ny >= ridge2[x]:
                    shade = min(1.0, (ny - ridge2[x]) * 6.0)
                    r = _lerp(mtn2[0] + 18, mtn2[0], shade)
                    g = _lerp(mtn2[1] + 18, mtn2[1], shade)
                    b = _lerp(mtn2[2] + 18, mtn2[2], shade)
                elif ny >= ridge1[x]:
                    shade = min(1.0, (ny - ridge1[x]) * 5.0)
                    r = _lerp(mtn1[0] + 22, mtn1[0], shade)
                    g = _lerp(mtn1[1] + 22, mtn1[1], shade)
                    b = _lerp(mtn1[2] + 22, mtn1[2], shade)
                row.extend((r, g, b))
        else:
            # Lake / sea reflection below horizon
            wt = (ny - horizon) / (1.0 - horizon)
            wave = math.sin(wt * 36.0 + seed * 3.0) * 0.5 + 0.5
            for x in range(width):
                nx = x / (width - 1)
                r = _lerp(sky_bot[0], water[0], 0.35 + wt * 0.65)
                g = _lerp(sky_bot[1], water[1], 0.35 + wt * 0.65)
                b = _lerp(sky_bot[2], water[2], 0.35 + wt * 0.65)
                # Shimmering sun reflection path
                shimmer_w = 0.03 + wt * 0.11
                if abs(nx - sx) < shimmer_w and wave > 0.42:
                    s_alpha = (1.0 - abs(nx - sx) / shimmer_w) * 0.55 * wave
                    r = _lerp(r, sun_col[0], s_alpha)
                    g = _lerp(g, sun_col[1], s_alpha)
                    b = _lerp(b, sun_col[2], s_alpha)
                row.extend((r, g, b))
        rows.append(bytes(row))
    write_rgb_png(path, width, height, rows)


def maybe_make_demo_mp4(mp4_path: pathlib.Path, poster_path: pathlib.Path, ffmpeg_exe: str | None):
    """If ffmpeg is installed, generate a tiny 2-second MP4 from the poster image."""
    if not ffmpeg_exe or mp4_path.exists():
        return
    try:
        subprocess.run(
            [
                ffmpeg_exe, "-y", "-hide_banner", "-loglevel", "error",
                "-loop", "1", "-i", str(poster_path),
                "-t", "2", "-vf", "scale=320:240,format=yuv420p",
                "-c:v", "libx264", "-preset", "ultrafast", "-movflags", "+faststart",
                str(mp4_path),
            ],
            capture_output=True,
            timeout=10,
        )
    except Exception:
        pass


CHAT_HTML_HEAD = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
body {{ background:#ebebeb; font-family:-apple-system,"Microsoft YaHei","PingFang SC",sans-serif; font-size:10.5pt; margin:0; }}
.main {{ max-width:720px; margin:0 auto; padding:18px 14px 36px; background:#f5f5f5; min-height:100vh; box-sizing:border-box; }}
.header {{ display:none; }}
.msgs {{ width:100%; }}
div.msg {{ clear:both; padding:8px 0; overflow:hidden; }}
.avatar-box {{ width:40px; height:40px; }}
.msg.left .avatar-box {{ float:left; margin-right:10px; }}
.msg.right .avatar-box {{ float:right; margin-left:10px; }}
.avatar {{ width:40px; height:40px; border-radius:4px; display:block; object-fit:cover; }}
.nt-box {{ font-size:11.5px; color:#999; margin-bottom:4px; }}
.msg.right .nt-box {{ text-align:right; }}
.content-box {{ position:relative; display:inline-block; max-width:68%; padding:9px 12px; border-radius:6px; line-height:1.55; word-break:break-word; }}
.msg.left .content-box {{ background:#fff; color:#181818; }}
.msg.right .content-box {{ float:right; background:#95ec69; color:#181818; }}
.msg.media .content-box {{ background:transparent !important; padding:2px 0; box-shadow:none !important; }}
.content-box pre {{ margin:0; white-space:pre-wrap; font-family:inherit; font-size:13.5px; }}
img.image {{ max-width:240px; max-height:240px; border-radius:6px; display:block; cursor:pointer; box-shadow:0 1px 4px rgba(0,0,0,.1); }}
video {{ max-width:280px; max-height:220px; border-radius:6px; display:block; background:#111; }}
.msg.chat-notice {{ text-align:center; }}
.msg.chat-notice .content-box {{ background:rgba(0,0,0,.06) !important; color:#888; font-size:12px; padding:3px 10px; float:none; }}
</style>
</head>
<body>
<div class="main">
  <div id="msgs-div" class="msgs">
"""


def build_msg_block(
    msgid: int,
    side: str,
    sender: str,
    sender_wxid: str,
    avatar_rel: str,
    ts: str,
    mtype: str,
    content: str = "",
    media_thumb: str = "",
    media_full: str = "",
) -> str:
    s_esc = html.escape(sender)
    if mtype == "notice":
        return f"""<div class="msg chat-notice" msgid="{msgid}" msgtype="10000">
  <div class="content-box"><span class="dont-break-out msg-text"><pre>{html.escape(content)}</pre></span></div>
</div>"""

    if mtype == "image":
        raw_attr = f' rawUrl="{media_full}"' if media_full else ""
        cls_extra = " raw-img" if media_full else ""
        return f"""<div class="msg media {side}{cls_extra}" msgid="{msgid}" msgtype="image">
  <div class="avatar-box"><img src="{avatar_rel}" class="avatar" /></div>
  <div class="nt-box"><span class="dspname {side}" wxId="{html.escape(sender_wxid)}">{s_esc}</span> {ts}</div>
  <div class="content-box"><img{raw_attr} src="{media_thumb}" class="image" /><span class="dont-break-out msg-text"></span></div>
</div>"""

    if mtype == "video":
        return f"""<div class="msg media {side}" msgid="{msgid}" msgtype="video">
  <div class="avatar-box"><img src="{avatar_rel}" class="avatar" /></div>
  <div class="nt-box"><span class="dspname {side}" wxId="{html.escape(sender_wxid)}">{s_esc}</span> {ts}</div>
  <div class="content-box"><video controls poster="{media_thumb}"><source src="{media_full}" type="video/mp4"><a href="{media_full}">播放视频</a></video></div>
</div>"""

    return f"""<div class="msg chat {side}" msgid="{msgid}" msgtype="text">
  <div class="avatar-box"><img src="{avatar_rel}" class="avatar" /></div>
  <div class="nt-box"><span class="dspname {side}" wxId="{html.escape(sender_wxid)}">{s_esc}</span> {ts}</div>
  <div class="content-box"><div class="triangle"></div><span class="dont-break-out msg-text"><pre>{html.escape(content)}</pre></span></div>
</div>"""


def generate_demo_export(target_dir: pathlib.Path, force: bool = False) -> pathlib.Path:
    """Create a complete synthetic WechatExporter-format archive in target_dir."""
    acc_name = "林致远"
    acc_wxid = "wxid_demo_linzhiyuan"
    acc_dir = target_dir / acc_name
    marker = target_dir / ".demo_version_v1"
    if marker.exists() and (acc_dir / "index.html").exists() and not force:
        return target_dir

    if target_dir.exists():
        shutil.rmtree(target_dir, ignore_errors=True)
    portrait_dir = acc_dir / "Portrait"
    portrait_dir.mkdir(parents=True, exist_ok=True)

    ffmpeg_exe = shutil.which("ffmpeg") or (
        r"C:\ffmpeg\bin\ffmpeg.exe" if os.path.isfile(r"C:\ffmpeg\bin\ffmpeg.exe") else None
    )

    # 1. Generate clean avatars for fictional owner & contacts
    avatars = {
        acc_wxid: ((45, 168, 120), (24, 118, 86), 0),
        "chenhao_dev": ((66, 133, 244), (38, 92, 196), 0),
        "suwanqing_art": ((236, 112, 146), (192, 68, 108), 0),
        "zhangmingyu_cam": ((245, 158, 66), (206, 112, 32), 0),
        "linxiaomei": ((166, 118, 228), (118, 72, 186), 0),
        "zhouyifan": ((58, 174, 196), (32, 122, 146), 0),
        "camping@chatroom": ((78, 168, 222), (46, 118, 179), 1),
        "product_team@chatroom": ((102, 187, 106), (56, 142, 60), 1),
        "photo_club@chatroom": ((255, 167, 38), (230, 115, 20), 1),
        "family_home@chatroom": ((238, 118, 116), (198, 74, 72), 1),
        "frontend_dev@chatroom": ((124, 114, 212), (76, 68, 168), 1),
        "notifymessage": ((245, 176, 52), (218, 134, 24), 0),
        "gh_demo_geekweekly": ((56, 142, 214), (32, 96, 164), 0),
        "demo_cloud@openim": ((44, 164, 152), (24, 116, 108), 0),
    }
    for uid, (c1, c2, st) in avatars.items():
        make_avatar_png(portrait_dir / f"{uid}.jpg", c1, c2, st)

    now_year = datetime.date.today().year
    base_dt = datetime.datetime(now_year, 10, 18, 9, 15, 0)

    def ts_of(day_offset: int, hour: int, minute: int, sec: int = 12) -> str:
        d = base_dt + datetime.timedelta(days=day_offset)
        return d.replace(hour=hour, minute=minute, second=sec).strftime("%Y-%m-%d %H:%M:%S")

    # 2. Define 12 realistic fictional chats
    chats_spec = [
        {
            "name": "周末露营小分队",
            "wxid": "",
            "avatar_id": "camping@chatroom",
            "is_group": True,
            "msgs": [
                ("left", "陈浩", "chenhao_dev", ts_of(-14, 19, 20), "text", "大家这周六去莫干山露营的方案定下来了吗？天气预报说全天晴，非常适合看日落！"),
                ("right", acc_name, acc_wxid, ts_of(-14, 19, 24), "text", "我刚整理好新版露营方案，天幕、蛋卷桌、卡式炉我车上都能装下。"),
                ("left", "苏婉清", "suwanqing_art", ts_of(-14, 19, 28), "text", "太棒了！我负责带手冲咖啡器具、氛围灯串和水果甜点，晚上拍星空肯定好看。"),
                ("left", "张明宇", "zhangmingyu_cam", ts_of(-14, 19, 33), "text", "我带三脚架和广角镜头，上回在湖边拍的几张露营参考图先发群里大家感受下："),
                ("left", "张明宇", "zhangmingyu_cam", ts_of(-14, 19, 34), "image", "0"),
                ("left", "张明宇", "zhangmingyu_cam", ts_of(-14, 19, 34, 28), "image", "2"),
                ("left", "周亦凡", "zhouyifan", ts_of(-14, 19, 41), "text", "哇这星空也太绝了！顺路我在山脚超市买点炭和烤肉食材。"),
                ("right", acc_name, acc_wxid, ts_of(-7, 10, 12), "text", "出发！高速一路畅通，预计 11 点半到达山谷营地。"),
                ("left", "苏婉清", "suwanqing_art", ts_of(-7, 12, 48), "image", "1"),
                ("left", "苏婉清", "suwanqing_art", ts_of(-7, 12, 49), "image", "3"),
                ("left", "苏婉清", "suwanqing_art", ts_of(-7, 12, 50), "text", "营地草坪太舒服了，微风吹着一点都不晒，咖啡已经冲好啦！"),
                ("right", acc_name, acc_wxid, ts_of(-7, 17, 42), "image", "4"),
                ("right", acc_name, acc_wxid, ts_of(-7, 17, 43), "image", "5"),
                ("right", acc_name, acc_wxid, ts_of(-7, 17, 45), "text", "今天的晚霞直接封神！大家快看西边山脊，颜色美得像油画一样。"),
                ("left", "张明宇", "zhangmingyu_cam", ts_of(-7, 18, 5), "video", "0"),
                ("left", "张明宇", "zhangmingyu_cam", ts_of(-7, 21, 16), "image", "9"),
                ("left", "陈浩", "chenhao_dev", ts_of(-7, 21, 20), "text", "这次露营体验满分！下个月红叶季咱们再约一次秋日山谷露营方案。"),
                ("right", acc_name, acc_wxid, ts_of(-2, 14, 18), "image", "6"),
                ("left", "周亦凡", "zhouyifan", ts_of(-2, 14, 22), "image", "7"),
                ("left", "苏婉清", "suwanqing_art", ts_of(-1, 20, 10), "text", "我把这批露营原图都汇总好了，发在群里大家直接右键保存就行～"),
                ("left", "苏婉清", "suwanqing_art", ts_of(-1, 20, 11), "image", "8"),
                ("left", "苏婉清", "suwanqing_art", ts_of(-1, 20, 12), "image", "10"),
                ("left", "苏婉清", "suwanqing_art", ts_of(-1, 20, 12, 40), "image", "11"),
                ("right", acc_name, acc_wxid, ts_of(0, 9, 42), "text", "收到！用离线查看器的图片网格翻原图超方便，右键还能直接定位回当天聊天。"),
                ("left", "陈浩", "chenhao_dev", ts_of(0, 9, 45), "text", "我也把最近五年的微信记录都导出来用这个看了，搜关键词秒出结果，还按会话分组显示。"),
                ("left", "张明宇", "zhangmingyu_cam", ts_of(0, 9, 48), "text", "关键是纯本地离线运行，不联网也不改原文件，几千张摄影原图点开就是文件夹网格！"),
                ("right", acc_name, acc_wxid, ts_of(0, 9, 51), "text", "嗯！而且装上 ffmpeg 连微信的 WXGF 原图都能自动解码，下个月红叶季露营再多拍点～"),
            ],
        },
        {
            "name": "陈浩",
            "wxid": "chenhao_dev",
            "avatar_id": "chenhao_dev",
            "is_group": False,
            "msgs": [
                ("left", "陈浩", "chenhao_dev", ts_of(-10, 10, 15), "text", "老林，昨晚你分享的离线微信聊天记录查看器方案我跑起来了，速度真快！"),
                ("right", acc_name, acc_wxid, ts_of(-10, 10, 18), "text", "哈哈我也觉得顺手多了，之前翻几万条记录的原始 HTML 要往下划半天。"),
                ("left", "陈浩", "chenhao_dev", ts_of(-10, 10, 22), "text", "最赞的是搜索栏，现在搜关键字上面显示联系人/群聊，下面按会话汇总相关聊天记录，跟原版 PC 微信一模一样。"),
                ("right", acc_name, acc_wxid, ts_of(-6, 15, 30), "text", "对了，周末露营咱们几点在北口集合？我顺路接你。"),
                ("left", "陈浩", "chenhao_dev", ts_of(-6, 15, 34), "text", "上午 9 点整在地铁口见，我把露营装备提前装进收纳箱。"),
                ("left", "陈浩", "chenhao_dev", ts_of(-3, 18, 45), "image", "1"),
                ("right", acc_name, acc_wxid, ts_of(-1, 11, 20), "text", "把新版本的图片网格和右键定位聊天处也加上了，有空帮你也升级一下。"),
                ("left", "陈浩", "chenhao_dev", ts_of(0, 9, 15), "text", "太给力了！开源发到 GitHub 肯定很多人需要。"),
            ],
        },
        {
            "name": "摄影与风景相册群",
            "wxid": "",
            "avatar_id": "photo_club@chatroom",
            "is_group": True,
            "msgs": (
                [
                    ("left", "张明宇", "zhangmingyu_cam", ts_of(-20, 8, 30), "text", "本周主题「山海与日落」，欢迎大家把近期拍的风景原图发上来交流构图和调色！"),
                ]
                + [
                    (
                        "left" if i % 3 != 0 else "right",
                        ["张明宇", "苏婉清", acc_name][i % 3],
                        ["zhangmingyu_cam", "suwanqing_art", acc_wxid][i % 3],
                        ts_of(-18 + (i // 2), 9 + (i % 10), (i * 7) % 58),
                        "image",
                        str(i % 12),
                    )
                    for i in range(24)
                ]
                + [
                    ("left", "张明宇", "zhangmingyu_cam", ts_of(-3, 19, 10), "video", "1"),
                    ("left", "苏婉清", "suwanqing_art", ts_of(-2, 20, 22), "video", "2"),
                    ("right", acc_name, acc_wxid, ts_of(-1, 18, 45), "video", "3"),
                    ("right", acc_name, acc_wxid, ts_of(-1, 18, 50), "text", "刚试了下点右上角「图片」网格浏览这 24 张风景图，像文件夹一样清爽，右键任意一张就能秒跳回原聊天位置！"),
                ]
            ),
        },
        {
            "name": "产品研发讨论群",
            "wxid": "",
            "avatar_id": "product_team@chatroom",
            "is_group": True,
            "msgs": [
                ("left", "周亦凡", "zhouyifan", ts_of(-8, 14, 10), "text", "同步一下本周评审结论：离线归档工具的核心竞争力是纯本地零依赖和搜索精准度。"),
                ("left", "陈浩", "chenhao_dev", ts_of(-8, 14, 15), "text", "SQLite FTS5 trigram 索引已经测过，50 万条中文聊天记录毫秒级响应，不漏字也不串发言人名字。"),
                ("right", acc_name, acc_wxid, ts_of(-5, 16, 40), "text", "方案定稿！开源前再补一套纯虚构 Demo 数据，既方便展示界面又能零隐私风险一键试玩。"),
                ("left", "苏婉清", "suwanqing_art", ts_of(-2, 11, 5), "text", "UI 细节已经对齐 PC 微信：绿气泡 #95ec69、高亮绿 #07c160、右侧网格视图支持小/中/大图切换。"),
                ("right", acc_name, acc_wxid, ts_of(0, 8, 55), "text", "今天可以把 README 和开源仓库打包整理好了，大家辛苦！"),
            ],
        },
        {
            "name": "苏婉清",
            "wxid": "suwanqing_art",
            "avatar_id": "suwanqing_art",
            "is_group": False,
            "msgs": [
                ("left", "苏婉清", "suwanqing_art", ts_of(-9, 13, 12), "text", "上次露营拍的日落照片你修完啦？发我两张当桌面壁纸呀～"),
                ("right", acc_name, acc_wxid, ts_of(-9, 13, 18), "image", "0"),
                ("right", acc_name, acc_wxid, ts_of(-9, 13, 19), "image", "5"),
                ("left", "苏婉清", "suwanqing_art", ts_of(-4, 16, 5), "text", "周末去西湖边新开的咖啡馆坐坐吗？顺便聊聊下个月去川西的行程方案。"),
                ("right", acc_name, acc_wxid, ts_of(-1, 21, 30), "text", "好呀，周日下午两点半见，我把川西露营路线图带上。"),
            ],
        },
        {
            "name": "幸福一家人",
            "wxid": "",
            "avatar_id": "family_home@chatroom",
            "is_group": True,
            "msgs": [
                ("left", "林小妹", "linxiaomei", ts_of(-12, 18, 5), "text", "哥，这周回家吃饭吗？妈说炖了排骨藕汤！"),
                ("right", acc_name, acc_wxid, ts_of(-12, 18, 9), "text", "回！周六露营回来周日中午就回家吃饭。"),
                ("left", "林小妹", "linxiaomei", ts_of(-5, 12, 30), "image", "3"),
                ("right", acc_name, acc_wxid, ts_of(-2, 19, 15), "text", "给家里的老照片和聊天记录都做了本地离线备份，随时能在电脑上翻看。"),
            ],
        },
        {
            "name": "张明宇",
            "wxid": "zhangmingyu_cam",
            "avatar_id": "zhangmingyu_cam",
            "is_group": False,
            "msgs": [
                ("left", "张明宇", "zhangmingyu_cam", ts_of(-11, 20, 40), "text", "新镜头到了！周末露营刚好拿去拍星空延时。"),
                ("right", acc_name, acc_wxid, ts_of(-11, 20, 45), "text", "太棒了，记得多带两块备用电池。"),
                ("left", "张明宇", "zhangmingyu_cam", ts_of(-4, 10, 18), "image", "2"),
            ],
        },
        {
            "name": "前端技术交流群",
            "wxid": "",
            "avatar_id": "frontend_dev@chatroom",
            "is_group": True,
            "msgs": [
                ("left", "陈浩", "chenhao_dev", ts_of(-15, 11, 20), "text", "原生 CSS Grid 配合外层独立滚动容器和 padding-top:100%，几千张图也不会挤扁。"),
                ("right", acc_name, acc_wxid, ts_of(-6, 17, 10), "text", "再配合每批 120 张的滚动分批加载，打开超大相册几乎零卡顿。"),
            ],
        },
        {
            "name": "林小妹",
            "wxid": "linxiaomei",
            "avatar_id": "linxiaomei",
            "is_group": False,
            "msgs": [
                ("left", "林小妹", "linxiaomei", ts_of(-8, 21, 10), "text", "哥，你拍的那张日落海面发我一下原图呗！"),
                ("right", acc_name, acc_wxid, ts_of(-8, 21, 14), "image", "4"),
            ],
        },
        {
            "name": "微信支付",
            "wxid": "",
            "avatar_id": "notifymessage",
            "is_group": False,
            "msgs": [
                ("left", "微信支付", "notifymessage", ts_of(-1, 12, 30), "text", "微信支付凭证：山谷露营咖啡馆 消费 ¥68.00"),
                ("left", "微信支付", "notifymessage", ts_of(-5, 19, 12), "text", "微信支付凭证：户外装备旗舰店 消费 ¥299.00"),
            ],
        },
        {
            "name": "极客科技周刊",
            "wxid": "gh_demo_geekweekly",
            "avatar_id": "gh_demo_geekweekly",
            "is_group": False,
            "msgs": [
                ("left", "极客科技周刊", "gh_demo_geekweekly", ts_of(-3, 8, 0), "text", "[文章] 2026 年度值得收藏的本地离线效率工具精选"),
            ],
        },
        {
            "name": "云协作客服",
            "wxid": "demo_cloud@openim",
            "avatar_id": "demo_cloud@openim",
            "is_group": False,
            "msgs": [
                ("left", "云协作客服", "demo_cloud@openim", ts_of(-6, 9, 30), "text", "您好，您的云文档备份方案咨询工单已受理，祝工作顺利！"),
            ],
        },
    ]

    # 3. Render each chat HTML & media assets
    index_rows = []
    for spec in chats_spec:
        cname = spec["name"]
        wxid = spec["wxid"]
        avatar_id = spec["avatar_id"]
        files_dir = acc_dir / f"{cname}_files"
        files_dir.mkdir(parents=True, exist_ok=True)
        files_rel = urllib.parse.quote(f"{cname}_files")
        chat_href = urllib.parse.quote(f"{cname}.html")

        blocks = []
        for idx, (side, sender, swxid, ts, mtype, payload) in enumerate(spec["msgs"], start=1):
            av_rel = f"Portrait/{urllib.parse.quote(swxid)}.jpg"
            if mtype == "image":
                sc_i = int(payload)
                thumb_p = files_dir / f"{idx}_thumb.jpg"
                full_p = files_dir / f"{idx}.jpg"
                make_scenic_png(thumb_p, sc_i, 240, 240)
                make_scenic_png(full_p, sc_i, 640, 480)
                blocks.append(
                    build_msg_block(
                        idx, side, sender, swxid, av_rel, ts, "image",
                        media_thumb=f"{files_rel}/{idx}_thumb.jpg",
                        media_full=f"{files_rel}/{idx}.jpg",
                    )
                )
            elif mtype == "video":
                sc_i = int(payload) + 3
                poster_p = files_dir / f"{idx}_thum.jpg"
                mp4_p = files_dir / f"{idx}.mp4"
                make_scenic_png(poster_p, sc_i, 320, 240)
                maybe_make_demo_mp4(mp4_p, poster_p, ffmpeg_exe)
                blocks.append(
                    build_msg_block(
                        idx, side, sender, swxid, av_rel, ts, "video",
                        media_thumb=f"{files_rel}/{idx}_thum.jpg",
                        media_full=f"{files_rel}/{idx}.mp4",
                    )
                )
            else:
                blocks.append(build_msg_block(idx, side, sender, swxid, av_rel, ts, mtype, content=payload))

        # Put last 4 messages of 摄影与风景相册群 in Data/msg-1.js to exercise real pagination too
        js_footer = ""
        if cname == "摄影与风景相册群" and len(blocks) > 10:
            data_dir = files_dir / "Data"
            data_dir.mkdir(parents=True, exist_ok=True)
            head_blocks = blocks[:-4]
            tail_blocks = blocks[-4:]
            (data_dir / "msg-1.js").write_text(
                "var msgArray = " + json.dumps(tail_blocks, ensure_ascii=False) + ";\n",
                encoding="utf-8",
            )
            blocks = head_blocks
            js_footer = f"""
<script>
window.wechatMsgsIndexes = [1];
window.loadingMoreMsgs = false;
window.addEventListener('load', function() {{
  window.loadingMoreMsgs = true;
  var s = document.createElement('script');
  s.src = "{files_rel}/Data/msg-1.js";
  s.onload = function() {{
    if (window.msgArray) {{
      var box = document.getElementById('msgs-div');
      box.insertAdjacentHTML('beforeend', window.msgArray.join('\\n'));
    }}
    window.wechatMsgsIndexes = [];
    window.loadingMoreMsgs = false;
  }};
  document.body.appendChild(s);
}});
</script>"""

        chat_html = (
            CHAT_HTML_HEAD.format(title=html.escape(cname))
            + "\n".join(blocks)
            + '\n  </div>\n  <div id="footer" class="footer"></div>\n</div>'
            + js_footer
            + "\n</body>\n</html>\n"
        )
        (acc_dir / f"{cname}.html").write_text(chat_html, encoding="utf-8")

        label = f"{cname}（微信号：{wxid}）" if wxid else cname
        index_rows.append(
            f"""<tr height="56">
  <td width="64" align="center"><img src="Portrait/{urllib.parse.quote(avatar_id, safe='@')}.jpg" style="max-width:48px;max-height:48px" /></td>
  <td><a href="{chat_href}">{html.escape(label)}</a></td>
</tr>"""
        )

    # 4. Write Account index.html and Root index.html (standard WechatExporter format)
    (acc_dir / "index.html").write_text(
        f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{html.escape(acc_name)} - 聊天记录索引</title></head>
<body><table width="500" align="center">
{"".join(index_rows)}
</table></body></html>
""",
        encoding="utf-8",
    )

    acc_q = urllib.parse.quote(acc_name)
    (target_dir / "index.html").write_text(
        f"""<!doctype html>
<html><head><meta charset="utf-8"><title>WechatExporter 演示归档</title></head>
<body><table width="400" align="center">
  <tr height="60">
    <td width="100" align="center"><img src="{acc_q}/Portrait/{acc_wxid}.jpg" style="float:left;max-width:60px;max-height:60px" /></td>
    <td><a href="{acc_q}/index.html">{html.escape(acc_name)}</a></td>
  </tr>
</table></body></html>
""",
        encoding="utf-8",
    )

    marker.write_text("v1\n", encoding="utf-8")
    return target_dir


if __name__ == "__main__":
    out = pathlib.Path(__file__).resolve().parent.parent / "_demo_data"
    generate_demo_export(out, force=True)
    print(f"演示数据已生成至: {out}")
