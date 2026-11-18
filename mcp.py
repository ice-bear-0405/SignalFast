# -*- coding: utf-8 -*-
"""
Signal 快传 - MCP 接口（Model Context Protocol）
双角色单文件：
1) CtrlServer：随主程序运行的本地控制服务（仅绑定 127.0.0.1，令牌保护），
   提供 JSON API：状态 / 设备 / 历史 / 共享管理 / 触发发送 / 任务查询
2) MCP stdio 适配器：独立运行（可打包为 SignalMCP.exe），供 TeleAgent 等
   MCP 客户端接入——按行读 JSON-RPC 请求，转发到本地控制服务。
   客户端配置示例（见设置页「复制 MCP 配置」）：
   {"mcpServers": {"signal-fast": {"command": "...\\SignalMCP.exe", "args": []}}}
纯标准库实现。兼容 Python 3.8。
"""
import json
import logging
import os
import re
import secrets
import socket
import sys
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

log = logging.getLogger("signal")

CTRL_PORT_BASE = 54555          # 本地控制端口（54555-54564，仅回环）
MCP_PROTOCOL_VERSION = "2024-11-05"
MAX_SEND_FILES = 50


def mcp_json_path():
    """主程序控制口信息文件（MCP 适配器据此连接）"""
    from core import app_dir
    return os.path.join(app_dir(), "mcp.json")


def _safe_name(name):
    return os.path.basename(name or "").replace('"', "").replace("\r", "").replace("\n", "")


# ---------------------------------------------------------------- 控制服务

class _ExclusiveHTTPServer(ThreadingHTTPServer):
    """确定性独占端口（Windows SO_EXCLUSIVEADDRUSE），同 web.py——
    避免与运行中的其他实例共享端口导致连接投递不确定。"""

    allow_reuse_address = False

    def server_bind(self):
        excl = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if excl is not None:
            try:
                self.socket.setsockopt(socket.SOL_SOCKET, excl, 1)
            except OSError:
                pass
        ThreadingHTTPServer.server_bind(self)


class _CtrlHandler(BaseHTTPRequestHandler):
    server_version = "SignalFastCtrl/1.12"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def _token_ok(self):
        q = urllib.parse.urlparse(self.path)
        args = urllib.parse.parse_qs(q.query)
        t = (self.headers.get("X-Token") or (args.get("t") or [""])[0])
        return t == self.server.ctrl.token

    def _reply(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self._token_ok():
            self._reply({"err": "令牌不符"}, 403); return
        c = self.server.ctrl
        path = urllib.parse.urlparse(self.path).path
        args = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        try:
            if path == "/status":
                self._reply(c.status())
            elif path == "/devices":
                self._reply({"devices": c.devices()})
            elif path == "/history":
                n = min(int((args.get("limit") or ["20"])[0]), 200)
                self._reply({"history": c.history(n)})
            elif path == "/shared":
                self._reply({"shared": c.shared()})
            elif path == "/task":
                self._reply({"task": c.task_status((args.get("mid") or [""])[0])})
            else:
                self._reply({"err": "未知端点"}, 404)
        except Exception as e:
            self._reply({"err": str(e)}, 500)

    def do_POST(self):
        if not self._token_ok():
            self._reply({"err": "令牌不符"}, 403); return
        c = self.server.ctrl
        path = urllib.parse.urlparse(self.path).path
        try:
            n = int(self.headers.get("Content-Length") or 0)
            req = json.loads(self.rfile.read(n).decode("utf-8")) if n else {}
        except Exception:
            self._reply({"err": "请求体无效"}, 400); return
        try:
            if path == "/send":
                self._reply(c.send_file(req))
            elif path == "/shared":
                self._reply(c.shared_op(req))
            else:
                self._reply({"err": "未知端点"}, 404)
        except Exception as e:
            self._reply({"err": str(e)}, 500)


class CtrlServer(threading.Thread):
    """本地控制服务（127.0.0.1）：主程序数据 → JSON API（MCP 适配器的后端）"""

    def __init__(self, refs):
        """
        refs = {"config", "discovery", "web", "progress", "ui_cb"}
        ui_cb["on_send_started"](mid, direction, peer, content)  # bridge 信号，主线程建任务行
        """
        threading.Thread.__init__(self)
        self.daemon = True
        self.refs = refs
        self.token = secrets.token_hex(8)
        self.port = 0
        self.httpd = None
        self._stop = threading.Event()
        self._tasks = {}            # mid -> SendTask
        self._tasks_lock = threading.Lock()

    # ---- 数据接口 ----
    def status(self):
        from core import APP_VERSION
        cfg = self.refs["config"]
        disc = self.refs.get("discovery")
        return {
            "app": "Signal 快传",
            "version": APP_VERSION,
            "device_name": cfg.device_name,
            "save_dir": cfg.save_dir,
            "devices_online": len(disc.alive()) if disc else 0,
            "web_enabled": bool(getattr(cfg, "web_enabled", True)),
            "shared_count": len(self.refs["web"].shared) if self.refs.get("web") else 0,
            "running_tasks": len([t for _, t in self._tasks.items() if t.is_alive()]),
        }

    def devices(self):
        disc = self.refs.get("discovery")
        if not disc:
            return []
        return [{"name": d.name, "ip": d.ip, "tcp": d.tcp, "tls": d.tls}
                for d in disc.alive()]

    def history(self, limit=20):
        from core import load_history
        return load_history()[:max(1, min(limit, 200))]

    def shared(self):
        w = self.refs.get("web")
        return w.list_json() if w else []

    def task_status(self, mid):
        if not mid:
            return {"err": "缺少 mid"}
        with self._tasks_lock:
            t = self._tasks.get(mid)
        if t is None:
            return {"err": "任务不存在或已过期"}
        info = dict(t.progress.get(t.msg_id) or {})
        info.pop("obj", None)          # SendTask 对象引用不可 JSON 序列化
        for f in info.get("files") or []:
            f.pop("obj", None)
        info["mid"] = t.msg_id
        info["alive"] = t.is_alive()
        return info

    def send_file(self, req):
        paths = [p for p in (req.get("paths") or []) if isinstance(p, str) and p]
        text = (req.get("text") or "").strip()
        device = (req.get("device") or "").strip()
        if not device:
            return {"err": "缺少 device（设备名称或 IP）"}
        if not paths and not text:
            return {"err": "缺少 paths（文件路径列表）或 text（文字内容）"}
        if len(paths) > MAX_SEND_FILES:
            return {"err": "一次最多发送 %d 个文件" % MAX_SEND_FILES}
        for p in paths:
            if not os.path.isfile(p):
                return {"err": "文件不存在：%s" % p}
        target = self._find_device(device)
        if not target:
            return {"err": "设备不在线：未发现名称或 IP 为「%s」的设备" % device,
                    "devices": self.devices()}
        ip, port, name, tls_port = target
        from core import SendTask
        kw = {"progress": self.refs["progress"],
              "on_done": lambda mid, ok, note: log.info("MCP 发送[%s] 完成（%s）：%s", mid, ok, note),
              "on_error": lambda e: log.warning("MCP 发送失败：%s", e)}
        task = SendTask(ip, port, self.refs["config"].device_name,
                        paths=paths or None, text=text or None, **kw)
        with self._tasks_lock:
            self._tasks[task.msg_id] = task
            if len(self._tasks) > 50:   # 只保留最近 50 个任务引用
                for k in list(self._tasks.keys())[:-50]:
                    self._tasks.pop(k, None)
        task.start()
        content = ("文字：" + text[:24]) if text else \
            "；".join(_safe_name(p) for p in paths[:2])
        try:
            self.refs["ui_cb"]["on_send_started"](
                task.msg_id, "↑ 发送(MCP)", name, content)
        except Exception:
            pass
        log.info("MCP 发起传输：%s -> %s（%s:%d）",
                 ("文字" if text else "%d 个文件" % len(paths)), name, ip, port)
        return {"ok": True, "mid": task.msg_id, "device": name,
                "note": "接收端会弹出确认框，需对方确认后才开始传输"}

    def shared_op(self, req):
        w = self.refs.get("web")
        if not w:
            return {"err": "网页互传服务未运行"}
        op = req.get("op")
        if op == "add":
            paths = [p for p in (req.get("paths") or []) if isinstance(p, str) and p]
            if not paths:
                return {"err": "缺少 paths"}
            for p in paths:
                if not os.path.isfile(p):
                    return {"err": "文件不存在：%s" % p}
            n = w.add_shared(paths)
            return {"ok": True, "added": n, "total": len(w.shared)}
        if op == "remove":
            idx = req.get("index")
            if not isinstance(idx, int):
                return {"err": "缺少 index（整数）"}
            return {"ok": w.remove_shared(idx)}
        if op == "clear":
            w.clear_shared()
            return {"ok": True}
        return {"err": "op 须为 add/remove/clear"}

    def _find_device(self, key):
        disc = self.refs.get("discovery")
        if not disc:
            return None
        for d in disc.alive():
            if d.ip == key or d.name == key:
                return (d.ip, d.tcp, d.name, d.tls)
        for d in disc.alive():   # 名称模糊匹配
            if key in d.name:
                return (d.ip, d.tcp, d.name, d.tls)
        return None

    # ---- 线程 ----
    def run(self):
        port = CTRL_PORT_BASE
        for p in range(CTRL_PORT_BASE, CTRL_PORT_BASE + 10):
            try:
                self.httpd = _ExclusiveHTTPServer(("127.0.0.1", p), _CtrlHandler)
                port = p
                break
            except OSError:
                continue
        if self.httpd is None:
            log.warning("MCP 控制端口绑定失败（54555-54564），AI 助手接入不可用")
            return
        self.port = port
        self.httpd.ctrl = self
        try:
            from core import APP_VERSION
            info = {"port": port, "token": self.token, "version": APP_VERSION,
                    "updated": time.strftime("%Y-%m-%d %H:%M:%S")}
            with open(mcp_json_path(), "w", encoding="utf-8") as f:
                json.dump(info, f, ensure_ascii=False, indent=2)
            log.info("MCP 本地控制服务：127.0.0.1:%d（仅回环），mcp.json 已更新", port)
        except Exception as e:
            log.warning("mcp.json 写入失败：%s", e)
        try:
            self.httpd.serve_forever(poll_interval=0.5)
        except Exception:
            pass

    def stop(self):
        self._stop.set()
        if self.httpd:
            try:
                self.httpd.shutdown()
                self.httpd.server_close()
            except Exception:
                pass


# ---------------------------------------------------------------- stdio 适配器

TOOLS = [
    {"name": "app_status", "description": "查询 Signal 快传运行状态（版本/设备名/在线设备数/共享数等）",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "list_devices", "description": "列出局域网内当前在线的 Signal 快传设备",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "send_file", "description": "向指定设备发送文件（接收端会弹窗确认后才传输）。paths 必须是本机已存在的文件路径",
     "inputSchema": {"type": "object",
                     "properties": {
                         "device": {"type": "string", "description": "目标设备名称或 IP（可先用 list_devices 查询）"},
                         "paths": {"type": "array", "items": {"type": "string"},
                                   "description": "要发送的本机文件路径列表"},
                         "text": {"type": "string", "description": "可选：随文件一起发送的文字；也可只发文字"}},
                     "required": ["device"]}},
    {"name": "task_status", "description": "查询一次发送任务的进度状态",
     "inputSchema": {"type": "object",
                     "properties": {"mid": {"type": "string", "description": "send_file 返回的任务 ID"}},
                     "required": ["mid"]}},
    {"name": "list_history", "description": "查询传输历史记录（最近 200 条以内）",
     "inputSchema": {"type": "object",
                     "properties": {"limit": {"type": "integer", "description": "返回条数，默认 20"}}}},
    {"name": "list_shared", "description": "查看已共享给手机网页的文件清单",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "add_shared", "description": "把本机文件添加到手机网页下载清单",
     "inputSchema": {"type": "object",
                     "properties": {"paths": {"type": "array", "items": {"type": "string"}}},
                     "required": ["paths"]}},
    {"name": "remove_shared", "description": "从手机网页清单移除一个文件（按索引）",
     "inputSchema": {"type": "object",
                     "properties": {"index": {"type": "integer"}}, "required": ["index"]}},
]


def mcp_handle(msg, api):
    """处理一条 MCP 请求，返回响应 dict（通知返回 None）。api 为 CtrlClient 实例。"""
    method = msg.get("method")
    mid = msg.get("id")
    if mid is None:
        return None   # 通知不响应
    try:
        if method == "initialize":
            return {"jsonrpc": "2.0", "id": mid, "result": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "signal-fast",
                               "version": _ver()}}}
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}}
        if method == "tools/call":
            name = (msg.get("params") or {}).get("name")
            args = (msg.get("params") or {}).get("arguments") or {}
            try:
                data = api.call(name, args)
                ok = not (isinstance(data, dict) and data.get("err"))
                return {"jsonrpc": "2.0", "id": mid, "result": {
                    "content": [{"type": "text",
                                 "text": json.dumps(data, ensure_ascii=False, indent=1)}],
                    "isError": not ok}}
            except Exception as e:
                return {"jsonrpc": "2.0", "id": mid, "result": {
                    "content": [{"type": "text", "text": "工具执行失败：%s" % e}],
                    "isError": True}}
        return {"jsonrpc": "2.0", "id": mid,
                "error": {"code": -32601, "message": "未知方法：%s" % method}}
    except Exception as e:
        return {"jsonrpc": "2.0", "id": mid,
                "error": {"code": -32603, "message": "内部错误：%s" % e}}


def _ver():
    try:
        from core import APP_VERSION
        return APP_VERSION
    except Exception:
        return "unknown"


class CtrlClient(object):
    """MCP 适配器 → 主程序控制口的 HTTP 客户端"""

    def __init__(self):
        from core import app_dir
        path = os.path.join(app_dir(), "mcp.json")
        with open(path, "r", encoding="utf-8") as f:
            info = json.load(f)
        self.port = info["port"]
        self.token = info["token"]

    def call(self, name, args):
        api_map = {
            "app_status": ("GET", "/status", None),
            "list_devices": ("GET", "/devices", None),
            "send_file": ("POST", "/send", {"device": args.get("device"),
                                            "paths": args.get("paths") or [],
                                            "text": args.get("text") or ""}),
            "task_status": ("GET", "/task?mid=%s" % urllib.parse.quote(str(args.get("mid") or "")), None),
            "list_history": ("GET", "/history?limit=%d" % int(args.get("limit") or 20), None),
            "list_shared": ("GET", "/shared", None),
            "add_shared": ("POST", "/shared", {"op": "add", "paths": args.get("paths") or []}),
            "remove_shared": ("POST", "/shared", {"op": "remove", "index": int(args.get("index", -1))}),
        }
        if name not in api_map:
            raise ValueError("未知工具：%s" % name)
        method, path, payload = api_map[name]
        url = "http://127.0.0.1:%d%s" % (self.port, path)
        headers = {"X-Token": self.token}
        data = None
        if method == "POST":
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode("utf-8"))


def mcp_stdio_main():
    """适配器入口：逐行读 JSON-RPC，逐行写响应"""
    try:
        api = CtrlClient()
    except Exception as e:
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": 1, "result": {
            "content": [{"type": "text",
                         "text": "Signal 快传未运行或未安装（%s）。请先启动 Signal 快传主程序。" % e}],
            "isError": True}}) + "\n")
        sys.stdout.flush()
        return
    log.info("MCP 适配器已连接主程序控制口 127.0.0.1:%d", api.port)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            continue
        resp = mcp_handle(msg, api)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()



if __name__ == "__main__":
    mcp_stdio_main()
