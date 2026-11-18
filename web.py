# -*- coding: utf-8 -*-
"""
Signal 快传 - 手机网页互传服务
局域网 HTTP 服务（纯标准库）：手机浏览器扫码访问，
上传文件到电脑接收目录 / 下载电脑共享的文件。
访问令牌（URL 含 8 位随机 token）防止局域网内无关设备访问。
兼容 Python 3.8 / Windows 7+。
"""
import html as _html
import json
import logging
import os
import re
import secrets
import socket
import tempfile
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

log = logging.getLogger("signal")

WEB_PORT_BASE = 54550         # 网页互传端口（落在防火墙放行段 TCP 54546-54565 内）
MAX_UPLOAD = 4 * 1024 * 1024 * 1024   # 单次上传总大小上限 4GB
CHUNK = 1 << 20

_UNSAFE = re.compile(r'[\\/:*?"<>|\r\n\t]')


def local_ips():
    """枚举本机所有 IPv4（排除回环）——多网卡（如网线+热点）逐一列出"""
    out = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip and not ip.startswith("127.") and ip not in out:
                out.append(ip)
    except Exception:
        pass
    return out or [socket.gethostbyname(socket.gethostname())]


def _safe_name(name):
    """清理上传文件名：取 basename、去非法字符，保留中文"""
    name = _UNSAFE.sub("_", os.path.basename(name or "")).strip()
    if not name:
        name = "未命名文件"
    if name.startswith("."):
        name = "_" + name
    return name[:120]


def _find_in_file(f, start, needle, limit):
    """在文件对象 [start, limit) 范围内查找字节串，返回起始位置或 -1（分块 + 跨块窗口）"""
    f.seek(start)
    window = b""
    pos = start
    while pos < limit:
        chunk = f.read(min(CHUNK, limit - pos))
        if not chunk:
            return -1
        window += chunk
        idx = window.find(needle)
        if idx >= 0:
            return start + idx
        keep = max(len(needle) - 1, 0)
        window = window[-keep:] if keep else b""
        pos += len(chunk)
    return -1


def _save_multipart(spool_path, boundary, save_dir, size):
    """把 spool 临时文件里的 multipart 体逐段写盘，返回保存信息列表"""
    saved = []
    delim = b"--" + boundary
    f = open(spool_path, "rb")
    try:
        pos = _find_in_file(f, 0, delim, size)
        while pos >= 0:
            head_start = pos + len(delim)
            f.seek(head_start)
            two = f.read(2)
            if two == b"--":
                break   # 结束分隔符
            head_end = _find_in_file(f, head_start + 2, b"\r\n\r\n", size)
            if head_end < 0:
                break
            f.seek(head_start + 2)
            headers = f.read(head_end - head_start - 2).decode("utf-8", "replace")
            body_start = head_end + 4
            nxt = _find_in_file(f, body_start, b"\r\n" + delim, size)
            if nxt < 0:
                nxt = _find_in_file(f, body_start, delim, size)
                body_end = nxt
            else:
                body_end = nxt
            if nxt < 0:
                break
            fname = ""
            for line in headers.split("\r\n"):
                if line.lower().startswith("content-disposition"):
                    m = re.search(r'filename="([^"]*)"', line)
                    if m:
                        raw = m.group(1)
                        try:
                            fname = _safe_name(raw.encode("latin-1").decode("utf-8"))
                        except Exception:
                            fname = _safe_name(raw)
            if fname:
                from core import unique_path
                dst = unique_path(os.path.join(save_dir, fname))
                try:
                    n = 0
                    with open(dst, "wb") as out:
                        f.seek(body_start)
                        left = body_end - body_start
                        while left > 0:
                            piece = f.read(min(CHUNK, left))
                            if not piece:
                                break
                            out.write(piece)
                            n += len(piece)
                            left -= len(piece)
                    saved.append({"name": os.path.basename(dst), "size": n, "path": dst})
                    log.info("网页上传已保存：%s（%d 字节）", os.path.basename(dst), n)
                except OSError as e:
                    log.warning("网页上传写盘失败 %s：%s", fname, e)
            pos = _find_in_file(f, body_end, delim, size)
    finally:
        f.close()
    return saved


_WEB_PAGE = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<title>Signal 快传 · 手机互传</title>
<style>
*{box-sizing:border-box;margin:0;padding:0;font-family:system-ui,-apple-system,"Microsoft YaHei",sans-serif}
body{background:#f2f5f9;color:#17324d;padding:16px;max-width:640px;margin:0 auto}
h1{font-size:20px;margin-bottom:4px}
.sub{color:#6b7f93;font-size:13px;margin-bottom:16px}
.card{background:#fff;border-radius:14px;padding:16px;margin-bottom:14px;box-shadow:0 2px 10px rgba(23,50,77,.08)}
.card h2{font-size:16px;margin-bottom:10px}
#pick{display:none}
.pickbtn{display:block;width:100%;padding:14px;border:2px dashed #2b6cb0;border-radius:12px;
 text-align:center;color:#2b6cb0;font-size:15px;background:#eef4fb;cursor:pointer}
.pickbtn:active{background:#dce9f7}
#bar{height:8px;background:#e3eaf2;border-radius:4px;margin-top:12px;overflow:hidden;display:none}
#fill{height:100%;width:0;background:linear-gradient(90deg,#2b6cb0,#4aa3df);transition:width .2s}
#uptip{font-size:13px;color:#6b7f93;margin-top:8px;min-height:18px;word-break:break-all}
ul{list-style:none}
li{display:flex;justify-content:space-between;align-items:center;padding:10px 4px;border-bottom:1px solid #edf1f5;font-size:14px}
li:last-child{border-bottom:none}
a.dl{color:#2b6cb0;text-decoration:none;font-weight:600;white-space:nowrap;padding:6px 12px;
 background:#eef4fb;border-radius:8px}
.size{color:#6b7f93;font-size:12px;margin-left:6px}
.name{word-break:break-all;flex:1;margin-right:8px}
.empty{color:#9aaaba;font-size:13px;text-align:center;padding:12px}
</style></head><body>
<h1>📱 Signal 快传 · 手机互传</h1>
<div class="sub">与电脑「__DEVICE__」直连传输 · 数据不出局域网</div>
<div class="card"><h2>⬆️ 手机 → 电脑</h2>
<label class="pickbtn" for="pick">点此选择文件（可多选）</label>
<input id="pick" type="file" multiple onchange="doUpload()">
<div id="bar"><div id="fill"></div></div>
<div id="uptip">文件将保存到电脑的接收目录</div>
</div>
<div class="card"><h2>⬇️ 电脑 → 手机（电脑端共享的文件）</h2>
<ul id="list"><li class="empty">加载中…</li></ul>
</div>
<script>
var T='__TOKEN__';
function fmt(n){if(n>1048576)return (n/1048576).toFixed(1)+' MB';if(n>1024)return (n/1024).toFixed(1)+' KB';return n+' B'}
function doUpload(){
 var fs=document.getElementById('pick').files;
 if(!fs.length)return;
 var fd=new FormData();
 for(var i=0;i<fs.length;i++)fd.append('file',fs[i]);
 var xhr=new XMLHttpRequest();var bar=document.getElementById('bar'),fill=document.getElementById('fill'),tip=document.getElementById('uptip');
 bar.style.display='block';fill.style.width='0%';
 tip.textContent='正在上传 '+fs.length+' 个文件（共 '+fmt(fs[0].size+(fs.length>1?fs[fs.length-1].size:0))+'）…';
 xhr.open('POST','/up?t='+T);
 xhr.upload.onprogress=function(e){if(e.lengthComputable){fill.style.width=Math.round(e.loaded/e.total*100)+'%'}};
 xhr.onload=function(){
  try{var r=JSON.parse(xhr.responseText);
   if(r.ok){tip.textContent='✅ 已保存到电脑：'+r.files.map(function(f){return f.name}).join('、');document.getElementById('pick').value=''}
   else{tip.textContent='❌ 失败：'+(r.err||'未知错误')}
  }catch(e){tip.textContent='❌ 响应异常'}
  bar.style.display='none';};
 xhr.onerror=function(){tip.textContent='❌ 网络错误，请确认与电脑在同一网络'};
 xhr.send(fd);
}
function loadList(){
 fetch('/list?t='+T).then(function(r){return r.json()}).then(function(r){
  var ul=document.getElementById('list');ul.innerHTML='';
  if(!r.files.length){ul.innerHTML='<li class="empty">暂无共享文件：在电脑上点【手机互传】添加</li>';return}
  r.files.forEach(function(f){
   var li=document.createElement('li');
   li.innerHTML='<span class="name">'+f.name+'<span class="size">'+fmt(f.size)+'</span></span>'+
    '<a class="dl" href="/dl?t='+T+'&i='+f.i+'" download="'+f.name+'">下载</a>';
   ul.appendChild(li);
  });
 }).catch(function(){document.getElementById('list').innerHTML='<li class="empty">连接失败</li>'});
}
loadList();setInterval(loadList,5000);
</script></body></html>"""


class _ExclusiveHTTPServer(ThreadingHTTPServer):
    """确定性独占端口（Windows SO_EXCLUSIVEADDRUSE）：
    禁用 http.server 默认的 SO_REUSEADDR，避免与运行中的其他实例
    共享端口导致连接投递不确定（多实例场景测试/双开都会踩）。
    端口被占时构造抛 OSError，调用方递增重试。"""

    allow_reuse_address = False

    def server_bind(self):
        excl = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if excl is not None:
            try:
                self.socket.setsockopt(socket.SOL_SOCKET, excl, 1)
            except OSError:
                pass
        ThreadingHTTPServer.server_bind(self)


class _Handler(BaseHTTPRequestHandler):
    server_version = "SignalFastWeb/1.11"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass   # 静默默认访问日志（关键事件业务层自行记录）

    def _token_ok(self):
        q = urllib.parse.urlparse(self.path)
        args = urllib.parse.parse_qs(q.query)
        return (args.get("t") or [""])[0] == self.server.share.token

    def _deny(self):
        body = "请从电脑上的【手机互传】二维码进入（令牌不符）".encode("utf-8")
        self.send_response(403)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        sh = self.server.share
        q = urllib.parse.urlparse(self.path)
        path = q.path
        if path == "/favicon.ico":
            self.send_response(404); self.send_header("Content-Length", "0"); self.end_headers(); return
        if not self._token_ok():
            self._deny(); return
        if path == "/":
            body = sh.page().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/list":
            body = json.dumps({"files": sh.list_json()}, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/dl":
            args = urllib.parse.parse_qs(q.query)
            try:
                idx = int((args.get("i") or ["-1"])[0])
            except ValueError:
                idx = -1
            f = sh.file_at(idx)
            if not f or not os.path.isfile(f["path"]):
                body = "文件不存在或已被移除".encode("utf-8")
                self.send_response(404)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            size = os.path.getsize(f["path"])
            fname = os.path.basename(f["path"])
            quoted = urllib.parse.quote(fname)
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(size))
            self.send_header("Content-Disposition",
                             "attachment; filename*=UTF-8''%s" % quoted)
            self.end_headers()
            try:
                with open(f["path"], "rb") as fp:
                    while True:
                        piece = fp.read(CHUNK)
                        if not piece:
                            break
                        self.wfile.write(piece)
                log.info("网页下载：%s（%d 字节）→ %s", fname, size, self.client_address[0])
            except (ConnectionError, OSError):
                pass   # 手机中途取消下载属正常
        else:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()

    def do_POST(self):
        sh = self.server.share
        q = urllib.parse.urlparse(self.path)
        if q.path != "/up":
            self.send_response(404); self.send_header("Content-Length", "0"); self.end_headers(); return
        if not self._token_ok():
            self._deny(); return
        if not sh.save_dir_ok():
            body = json.dumps({"ok": False, "err": "电脑尚未设置接收目录"}, ensure_ascii=False).encode("utf-8")
            self.send_response(400)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        cl = int(self.headers.get("Content-Length") or 0)
        ct = self.headers.get("Content-Type") or ""
        m = re.search(r'boundary=([^;]+)', ct)
        if cl <= 0 or cl > MAX_UPLOAD or not m:
            body = json.dumps({"ok": False, "err": "请求无效"}, ensure_ascii=False).encode("utf-8")
            self.send_response(400)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        boundary = m.group(1).strip('"').encode("latin-1")
        sh.on_upload_start()
        spool = tempfile.NamedTemporaryFile(delete=False, suffix=".spool")
        try:
            left = cl
            while left > 0:
                piece = self.rfile.read(min(CHUNK, left))
                if not piece:
                    break
                spool.write(piece)
                left -= len(piece)
            spool.close()
            size_on_disk = cl - left
            saved = _save_multipart(spool.name, boundary, sh.save_dir(), size_on_disk)
        except Exception as e:
            log.warning("网页上传处理异常：%s", e)
            saved = []
        finally:
            try:
                os.remove(spool.name)
            except OSError:
                pass
        sh.on_upload_done(saved, self.client_address[0])
        body = json.dumps({"ok": bool(saved), "files": saved,
                           "err": "" if saved else "未包含有效文件"},
                          ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class WebShareServer(threading.Thread):
    """手机网页互传服务：持有共享清单与令牌；线程内跑 ThreadingHTTPServer"""

    def __init__(self, config, callbacks):
        threading.Thread.__init__(self)
        self.daemon = True
        self.config = config
        self.cb = callbacks or {}
        self.token = secrets.token_hex(4)
        self.shared = []            # [{"path", "name", "size", "added"}]
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self.httpd = None
        self.port = 0
        self._up_seq = 0

    # --- 供 UI 调用 ---
    def url_for(self, ip):
        return "http://%s:%d/?t=%s" % (ip, self.port, self.token)

    def add_shared(self, paths):
        added = 0
        with self._lock:
            for p in paths:
                if os.path.isfile(p) and p not in [x["path"] for x in self.shared]:
                    self.shared.append({"path": p, "name": os.path.basename(p),
                                        "size": os.path.getsize(p),
                                        "added": time.strftime("%H:%M")})
                    added += 1
            log.info("网页共享清单更新：共 %d 个文件", len(self.shared))
        return added

    def remove_shared(self, index):
        with self._lock:
            if 0 <= index < len(self.shared):
                removed = self.shared.pop(index)
                log.info("网页共享移除：%s", removed["name"])
                return True
        return False

    def clear_shared(self):
        with self._lock:
            self.shared = []

    def list_json(self):
        with self._lock:
            return [{"i": i, "name": x["name"], "size": x["size"]}
                    for i, x in enumerate(self.shared)]

    def file_at(self, index):
        with self._lock:
            if 0 <= index < len(self.shared):
                return self.shared[index]
        return None

    def save_dir(self):
        return self.config.save_dir

    def save_dir_ok(self):
        return self.config.save_dir_ok()

    def page(self):
        return (_WEB_PAGE.replace("__TOKEN__", self.token)
                .replace("__DEVICE__", _html.escape(self.config.device_name or "电脑")))

    # --- 上传回调到 UI/历史 ---
    def on_upload_start(self):
        with self._lock:
            self._up_seq += 1
        self._mid = "web%06d" % self._up_seq

    def on_upload_done(self, files, peer_ip):
        if not files:
            return
        total = sum(f["size"] for f in files)
        log.info("网页上传完成：%d 个文件（%d 字节）来自 %s", len(files), total, peer_ip)
        mid = getattr(self, "_mid", "web")
        try:
            self.cb["on_recv_update"](mid, {
                "sender": "📱 手机网页", "files": files,
                "total": total, "sent": total, "speed": 0.0,
                "state": "✅ 已保存到接收目录",
                "paths": [f["path"] for f in files]})
        except Exception:
            pass
        try:
            self.cb["on_recv_done"](mid, True,
                                    "✅ 网页上传完成，共 %d 个文件已保存" % len(files))
        except Exception:
            pass
        try:
            from core import record_history
            record_history({"direction": "recv", "peer": "📱 手机网页", "kind": "files",
                            "files": [f["name"] for f in files[:5]],
                            "count": len(files), "result": "网页上传已保存"})
        except Exception:
            pass

    # --- 线程 ---
    def run(self):
        port = WEB_PORT_BASE
        for p in range(WEB_PORT_BASE, WEB_PORT_BASE + 10):
            try:
                self.httpd = _ExclusiveHTTPServer(("0.0.0.0", p), _Handler)
                port = p
                break
            except OSError:
                continue
        if self.httpd is None:
            log.warning("网页互传端口绑定失败（54550-54559 全被占用），手机互传不可用")
            return
        self.port = port
        self.httpd.share = self
        log.info("手机网页互传：http://<本机IP>:%d/?t=%s（令牌已生成）", port, self.token)
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
