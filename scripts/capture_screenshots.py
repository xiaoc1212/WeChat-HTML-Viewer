#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自动化截取 WeChat-HTML-Viewer 演示模式高清展示图（零第三方依赖）
- 启动 --demo 纯虚构演示服务器（100% 零隐私数据）
- 通过本地 Chrome / Edge 无头模式 + CDP 协议自动交互并截取 4 张 1440x900 展示图
- 输出到 docs/images/ 供 README.md 展示
"""

import base64
import hashlib
import json
import os
import pathlib
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request

PROJECT_DIR = pathlib.Path(__file__).resolve().parent.parent
OUT_DIR = PROJECT_DIR / "docs" / "images"
DEMO_PORT = 18799
CDP_PORT = 19222


def find_browser() -> str:
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    raise FileNotFoundError("未找到 Chrome 或 Edge 浏览器，无法自动截图。")


class SimpleCDP:
    """Minimal RFC 6455 WebSocket client for Chrome DevTools Protocol (stdlib only)."""

    def __init__(self, ws_url: str):
        assert ws_url.startswith("ws://")
        rest = ws_url[5:]
        host_port, path = rest.split("/", 1)
        host, port_s = host_port.split(":")
        self.sock = socket.create_connection((host, int(port_s)), timeout=15)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        req = (
            f"GET /{path} HTTP/1.1\r\n"
            f"Host: {host_port}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(req.encode("ascii"))
        resp = b""
        while b"\r\n\r\n" not in resp:
            resp += self.sock.recv(4096)
        assert b"101" in resp.split(b"\r\n", 1)[0], f"WS handshake failed: {resp[:200]}"
        self._buf = resp.split(b"\r\n\r\n", 1)[1]
        self._id = 0

    def _recv_exact(self, n: int) -> bytes:
        while len(self._buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise EOFError("WebSocket closed")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def _send_text(self, text: str):
        payload = text.encode("utf-8")
        mask = os.urandom(4)
        header = bytearray([0x81])
        n = len(payload)
        if n < 126:
            header.append(0x80 | n)
        elif n < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack(">H", n))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack(">Q", n))
        header.extend(mask)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(bytes(header) + masked)

    def _recv_frame(self) -> str:
        while True:
            b1, b2 = self._recv_exact(2)
            opcode = b1 & 0x0F
            length = b2 & 0x7F
            if length == 126:
                length = struct.unpack(">H", self._recv_exact(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self._recv_exact(8))[0]
            data = self._recv_exact(length)
            if opcode == 1:
                return data.decode("utf-8", errors="replace")
            if opcode == 8:
                raise EOFError("WS closed by server")
            if opcode == 9:
                # Pong
                self.sock.sendall(b"\x8a\x80\x00\x00\x00\x00")

    def call(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        cid = self._id
        self._send_text(json.dumps({"id": cid, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(self._recv_frame())
            if msg.get("id") == cid:
                if "error" in msg:
                    raise RuntimeError(f"CDP error in {method}: {msg['error']}")
                return msg.get("result", {})

    def eval_js(self, expr: str):
        res = self.call("Runtime.evaluate", {"expression": expr, "awaitPromise": True, "returnByValue": True})
        return res.get("result", {}).get("value")

    def screenshot(self, path: pathlib.Path):
        res = self.call("Page.captureScreenshot", {"format": "png", "fromSurface": True})
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(base64.b64decode(res["data"]))
        print(f"  [OK] 已保存截图: {path.name} ({path.stat().st_size // 1024} KB)")

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass


def wait_http(url: str, timeout: float = 15.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    return
        except Exception:
            time.sleep(0.25)
    raise TimeoutError(f"Timed out waiting for {url}")


def main():
    browser_exe = find_browser()
    print(f"[1/4] 启动 --demo 演示服务 (端口 {DEMO_PORT})...")
    srv = subprocess.Popen(
        [sys.executable, str(PROJECT_DIR / "viewer_server.py"), "--demo", "--rebuild", "--no-browser", "--port", str(DEMO_PORT)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    user_data_dir = pathlib.Path(tempfile.mkdtemp(prefix="wx_viewer_cdp_"))
    browser = None
    cdp = None
    try:
        wait_http(f"http://127.0.0.1:{DEMO_PORT}/api/status", timeout=20.0)
        print(f"[2/4] 启动无头浏览器: {browser_exe}")
        browser = subprocess.Popen(
            [
                browser_exe,
                "--headless=new",
                f"--remote-debugging-port={CDP_PORT}",
                f"--user-data-dir={user_data_dir}",
                "--window-size=1440,900",
                "--disable-gpu",
                "--no-first-run",
                "--no-default-browser-check",
                f"http://127.0.0.1:{DEMO_PORT}/",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        wait_http(f"http://127.0.0.1:{CDP_PORT}/json", timeout=15.0)
        pages = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json").read().decode("utf-8"))
        target = next(p for p in pages if p.get("type") == "page" and "webSocketDebuggerUrl" in p)
        cdp = SimpleCDP(target["webSocketDebuggerUrl"])
        cdp.call("Emulation.setDeviceMetricsOverride", {
            "width": 1440, "height": 900, "deviceScaleFactor": 1.5, "mobile": False
        })
        time.sleep(1.2)

        print("[3/4] 依次交互并截取 4 张高清演示图...")

        # Shot 1: Main Chat View — open 周末露营小分队
        cdp.eval_js("""(() => {
            const c = allChats.find(x => x.name.includes('周末露营小分队'));
            if (c) openChat(c, null);
        })()""")
        time.sleep(1.3)
        cdp.screenshot(OUT_DIR / "01-main-chat.png")

        # Shot 2: Native PC-WeChat Search — search "露营" & click first message match to show highlight
        cdp.eval_js("""(() => {
            const inp = document.getElementById('contactQuery');
            inp.value = '露营';
            renderChatList(true);
        })()""")
        time.sleep(1.0)
        cdp.eval_js("""(() => {
            const c = allChats.find(x => x.name.includes('周末露营小分队'));
            if (c) openChat(c, '17');
        })()""")
        time.sleep(0.9)
        cdp.screenshot(OUT_DIR / "02-wechat-search.png")

        # Shot 3: Folder-style Media Grid + Right-Click Context Menu on 摄影与风景相册群
        cdp.eval_js("""(() => {
            document.getElementById('contactQuery').value = '';
            renderChatList(false);
            const c = allChats.find(x => x.name.includes('摄影与风景相册群'));
            if (c) openChat(c, null);
        })()""")
        time.sleep(1.2)
        cdp.eval_js("""(() => {
            applyMediaFilterToFrame('image');
        })()""")
        time.sleep(1.0)
        # Trigger right-click context menu on the 4th card so the "定位到聊天处" menu shows clearly!
        cdp.eval_js("""(() => {
            const card = document.querySelectorAll('#mediaGridBody .mgrid-card')[3];
            if (card) {
                const r = card.getBoundingClientRect();
                const ev = new MouseEvent('contextmenu', {
                    bubbles: true, cancelable: true,
                    clientX: Math.round(r.left + r.width * 0.65),
                    clientY: Math.round(r.top + r.height * 0.55)
                });
                card.dispatchEvent(ev);
            }
        })()""")
        time.sleep(0.4)
        cdp.screenshot(OUT_DIR / "03-media-grid.png")

        # Shot 4: Full-screen Lightbox Preview with "定位到聊天处"
        cdp.eval_js("""(() => {
            hideAllCtxMenus();
            openMediaLightbox(0);
        })()""")
        time.sleep(0.7)
        cdp.screenshot(OUT_DIR / "04-lightbox.png")

        print("[4/4] 全部 4 张高清无隐私展示图生成完成！")
    finally:
        if cdp:
            cdp.close()
        if browser:
            browser.terminate()
            try:
                browser.wait(timeout=5)
            except Exception:
                browser.kill()
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except Exception:
            srv.kill()
        import shutil
        shutil.rmtree(user_data_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
