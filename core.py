# -*- coding: utf-8 -*-
"""
Signal 快传 - 核心模块
UDP 设备发现 + TCP 全速传输（文件 / 文字消息），纯标准库实现。
兼容 Python 3.8 / Windows 7+。
"""
import base64
import hashlib
import hmac
import json
import logging
import logging.handlers
import os
import queue
import socket
import ssl
import struct
import threading
import time
import uuid

# 加密传输方案：Python 内置 TLS（HTTPS 同款主流加密技术，AES-256-GCM 套件），
# 随 Python 自带，零外部依赖；验证码用于应用层身份校验，不经网络传输。

# 内置传输证书（构建时生成，有效期 10 年；仅用于加密通道的加密，非身份证明）
CERT_B64 = "LS0tLS1CRUdJTiBDRVJUSUZJQ0FURS0tLS0tCk1JSUN6ekNDQWJlZ0F3SUJBZ0lVR3FTQXNnWXI1Mk9yWmF0aUFpbTBYQ0NwSTA4d0RRWUpLb1pJaHZjTkFRRUwKQlFBd0Z6RVZNQk1HQTFVRUF3d01VMmxuYm1GczViK3I1THlnTUI0WERUSTJNVEV4TWpBMk16SXlOVm9YRFRNMgpNVEV4TURBMk16SXlOVm93RnpFVk1CTUdBMVVFQXd3TVUybG5ibUZzNWIrcjVMeWdNSUlCSWpBTkJna3Foa2lHCjl3MEJBUUVGQUFPQ0FROEFNSUlCQ2dLQ0FRRUFzLzZQdFJhaUt2T2pGN00vQUtpVE9ROEVMaHI2dUtkWHoxZkkKT3VyVGNTRVNzMUR0Z3NaaVQzTXdORkZxaVBFcUlzQkRrb3pvSDl2MGo5cTd5YTkxRVlGYndQd1M0cXBnRjBCVQpyQ2JXNjJFL3ppTXUxT3NuVjAvc3BEcndLa081MWNXbkFkWmd2TTdHemZLV2NTa0ZWL2FFOHFaNnhSWHBnbXNVCi9lWHczOXJhamdyUjY0VlgzbERDN3o5QVAyaERSRzNHTnV5ZHNya1hIYXEyV1Fid1dpOVlURXhyUlBxdXM5dkoKMlVRTFBtTzVCeGdLNG5CK0FjR2Q3M2VZWXNQV3l2L1pUcXZ0TlJRWGJEY1RNQTg4OFM4cjBtK3B0ekFDd2lLZwplT0k0dk5nK09YZzRCRW5aNHVFcGkxVEdHa0QzS0owM1lHdmFYQk1xQ1JMYjJkNkN5d0lEQVFBQm94TXdFVEFQCkJnTlZIUk1CQWY4RUJUQURBUUgvTUEwR0NTcUdTSWIzRFFFQkN3VUFBNElCQVFCVkJWNjBmcE1DbVIrTXZwbCsKVHZWMzZIRG5JOUFxN1dLaFRxMGpHOFlEL2J0eWNzY1ZUSCtTdEQ1OXk0a3lEc0UrcHdBSk1DVloxckRmcHpPTwo5Z2dtdEExM09SRmJPOTBtdWZXdTRIbUQ0UU1abC9JSlQvRXhONFNUc3Y0RVhOUWR1NHp6elltSndDTTZHUWNCCnQwbjRlTDhqdEFMK1FkQlg2eHUvb2wvTVNaWm5NRnFjbWRHR0E5T1BOakgvMkUvcitMc1RkeFpWazZkWE4zNXEKd1dTNmF4YkdQVnB5eDJiL1Jsc2RCZXNWQUhabW1HcFlFcHVTaWhGRHdZTGcvaVZTeFkzdXZkQm5UamozWEVWVQpXZGQyTlA1cml3OHNlNEtrZW92Mk1TQkJDUDhpOW1qQVZvNjBRNWFpdVBuWmRRbUp4UFpid2Z0dTNHS0tmc09SCnlrVUEKLS0tLS1FTkQgQ0VSVElGSUNBVEUtLS0tLQo="
KEY_B64 = "LS0tLS1CRUdJTiBSU0EgUFJJVkFURSBLRVktLS0tLQpNSUlFb2dJQkFBS0NBUUVBcy82UHRSYWlLdk9qRjdNL0FLaVRPUThFTGhyNnVLZFh6MWZJT3VyVGNTRVNzMUR0CmdzWmlUM013TkZGcWlQRXFJc0JEa296b0g5djBqOXE3eWE5MUVZRmJ3UHdTNHFwZ0YwQlVyQ2JXNjJFL3ppTXUKMU9zblYwL3NwRHJ3S2tPNTFjV25BZFpndk03R3pmS1djU2tGVi9hRThxWjZ4UlhwZ21zVS9lWHczOXJhamdyUgo2NFZYM2xEQzd6OUFQMmhEUkczR051eWRzcmtYSGFxMldRYndXaTlZVEV4clJQcXVzOXZKMlVRTFBtTzVCeGdLCjRuQitBY0dkNzNlWVlzUFd5di9aVHF2dE5SUVhiRGNUTUE4ODhTOHIwbStwdHpBQ3dpS2dlT0k0dk5nK09YZzQKQkVuWjR1RXBpMVRHR2tEM0tKMDNZR3ZhWEJNcUNSTGIyZDZDeXdJREFRQUJBb0lCQUMzekZnZXlPL3NBRUlvYgoyY0VXeCtMQW1SNFdDQng4cC9lSUh0Y2ZuSlBjVUJSVDNCWlBBOGpwakl4R25vNVFGcVFoZGY2akZ4ME8vMHQ4CkdRVi9VOEVBeDRZb004QUdvNW83ODRHeE5wdUhTNDBad1RwY3Y4SFQ1d0wwQXR5ZlJvRXl3SlJCQUpnaXAzRHEKOVluMDRXYlh5WS9TZlRQMENKVWhOZzR0RmNWbmdWVitJQlNSZjliLzllVjQvYkNVWldhaUphalExQ3didzBVRQpaTjlzVlR1TERWRWs3Y1luTjlpWFpoeXFWbnIwdWUxWUZTRjBIMkgwR28rRnlPUUtLMnZsc3Zjd1JZK0oyUGVKCmZ2Wnk1R2xDaE9mQnc1QWtleGU3MWJ0VDF3elc4RGhMb3dPZFg0eTBMQmpkZWg3bmEyUUVnZDBEZWhaem54aUgKR0Vxa2VqVUNnWUVBMnhnTzZCTm9PMFlwZWllY25nb1NMUDNXY28zYk1WVnlGSXhYTE5XOTY0QStKUHI0RndJVQpvWGxMVmk3VUVhYUFQaFdrLzJNb3hUcjV0OGlDQnNGeXFsYmFMMGVXOXREL0plbDdEaUIxcUFkUFRDVWdZbDZECkdTbzVaVDFONHpEQ1hDWUs3MkFGZzJZVGprR0lSdnVwOUx3Tk0yL29pb09mVkF1amxqNGdUVmNDZ1lFQTBsQnIKYzYwYm9QMWNKUUdWV1hyUG1uVFd2eUZlS1BSOG5OanRPOVNYL0xDZndzdStsVkpVaVJEZFBSOTZnZnhISTlpMgo3QnNYSkhHUFdFaUtZRkwzSWhmNFBJWml5Qk9YR05SU2NxS1VaNEVkVkVyWHRXMFNUNnhpcStNRGkrejFjMjJMCjhXbUd6Kzc2a0swYWpvMkNVenRSQzFoVjJaTVFxclVyditheFdhMENnWUF0VUsyTW5LNzdTNGk2cGtURGYwdkIKR0lOcFVDUGM4VkpXSTZ6SUxqRkk2MDV2TWFWc2hOYWxpMFBrd0d6R2RjeWlpckdFelFxYXVKYjd4ekgxbWI5UQpzZ1FRc1ZydEU4OGlGVWVKWlhkUVdLcXpFaDYvbWRLOXVya0NVb3F3aWQ0NVZ2aitCN3M4TVRtc082dW5HdGhOCk1UUDl4cEN2VFlmL3h5Ui9wN3Znb3dLQmdDZVZpVlBoWGhUait1YmdNR3NDQ1hjSnpLMTJxMUZNQ3ZRK2hCQkIKeUVXQVBPR2VGWVhuVkEva1E2L1FiKzl0T3pxTS9JamQ1SEl3aVlsVlJlNHhUMkIwWUgyTDBhWFV3aGlqUmMxYgp1bERzNVVkTE91UmozaEZ1NGJkMlorRjdQUXQzcitKRk9XR0RtbGVHclR2dGVIMFA2Z1lYbnpqdlREREZIckhrCnlyYVZBb0dBUnpiSnE1SWlxazFlYmhEZXBwcWhQdjMzL2ZrODF3U0daZzZOR3Bha2F3WVl0ZmZNRlcxYnpXcm0KY2lSbTRmcEhQdG0zbHFoaW1pTzAxT1dIcUk5eThEaS8vQzY5d05GbjR5dXQ5QkFYTEVOeEJFOWJlOFRMdnBCbQpvcnovUEtBdUsxbHROQ25va093cjZSS2ZLdGJNM0hGUmhUYlRDWHRKVi9EeDkzWE5lYVk9Ci0tLS0tRU5EIFJTQSBQUklWQVRFIEtFWS0tLS0tCg=="

APP_NAME = "Signal快传"
APP_VERSION = "1.12.0"

RELEASE_NOTES = [
    ("1.12.0", [
        "新增 MCP 接口：AI 助手可接入，查询设备/历史、管理共享、触发发送（接收端仍需人工确认）",
        "设置页新增 MCP 区块：状态查看与一键复制接入配置",
        "网页/控制服务改用确定性独占端口（同机多开自动避让）",
    ]),
    ("1.11.0", [
        "手机网页互传：电脑内置网页服务，手机扫码即可互传文件（无需安装 APP）",
        "手机上传文件自动存入接收目录，电脑可将文件共享给手机下载",
        "访问令牌保护：二维码内含随机令牌，局域网内其他设备无法访问",
        "多网卡多二维码：网线+热点同时开时，每个网段一个二维码任扫",
    ]),
    ("1.10.0", [
        "设备发现互通：双网卡电脑（如有线+热点同时开）也能被对方自动发现，多数场景无需再手动添加",
        "修复接收确认弹窗出现约 250ms 后必闪退的问题（v1.9 引入，弹窗自动关闭轮询的类型错误）",
        "新增全局异常钩子：界面层未捕获异常写入日志且不再导致闪退",
    ]),
    ("1.9.0", [
        "断点续传：网络中断后保留半成品，重新发送同名文件自动续传",
        "单个大文件自动分段多连接并行，速度再提速",
        "暂停不再受 5 分钟超时限制（暂停/取消通知对方，可长时间暂停）",
        "对方取消时接收端弹窗自动关闭",
        "接收端多连接进度合并显示（不再跳动）",
        "新增传输历史记录（最近 200 条，可在设置中查看）",
        "进度显示文件序号（如 3/8）",
        "传输中托盘图标动态提示",
    ]),
    ("1.8.0", [
        "新增传输暂停/继续与主动终止（发送端和接收端均可操作）",
        "传输记录保存文件路径，点击任务行可打开文件所在文件夹",
        "多连接并行发送 + 磁盘预读流水线（速度优化）",
        "设置窗口新增【关于】页（版本历史，最新置顶）",
    ]),
    ("1.7.1", [
        "修复加密传输按钮无法点亮的遗漏（拖入文件后正常可点）",
        "标题栏显示版本号",
    ]),
    ("1.7.0", [
        "加密传输改用 Python 内置 TLS 加密通道（HTTPS 同款技术），任意电脑 100% 可用",
        "验证码 HMAC 校验，验证码全程不经网络",
    ]),
    ("1.6.0", [
        "TCP 收发缓冲加大至 4MB（跨 AP WiFi 链路提速）",
        "设置新增【一键放行防火墙】【打开日志文件夹】",
    ]),
    ("1.5.0", [
        "新增加密传输按钮（验证码验证接收）",
        "实时速度条：当前速度 / 百分比 / 剩余时间",
    ]),
    ("1.4.0", [
        "传输日志系统（按天记录，保留 14 天）",
        "错误按阶段提示（连接/握手/传输）",
    ]),
    ("1.3.0", [
        "新增发送文件按钮，修复文件无发送入口的遗漏",
        "设备列表卡片化、目标提示联动",
    ]),
    ("1.2.0", [
        "首次使用引导设置保存目录",
        "拒绝原因直接显示在发送端",
    ]),
    ("1.1.0", [
        "任务状态分阶段显示，接收确认弹窗置顶",
    ]),
    ("1.0.0", [
        "首个版本：自动发现设备、全速传输、文字同步、一键热点",
    ]),
]
DISCOVER_PORT = 54545          # UDP 发现端口
UDP_CTRL_PORT = 54544          # UDP 控制信令端口（暂停/取消通知，防火墙需放行）
TCP_BASE_PORT = 54546          # TCP 传输起始端口（被占用自动 +1）
MAGIC = "SGNL01"               # UDP 包魔数，用于过滤无关广播
CHUNK = 1 << 20                # 明文分块 1MB
KDF_ITER = 200000              # PBKDF2 迭代次数
SOCK_BUF = 4 * 1024 * 1024     # TCP 收发缓冲 4MB（高延迟 WiFi 链路提速关键）
TCP_BASE_PORT = 54546          # 普通传输 TCP 起始端口
TLS_PORT_BASE = 54566          # 加密(TLS)传输 TCP 起始端口
SEND_PIECE = 256 * 1024        # 非阻塞发送小片（暂停检查点粒度）
SPLIT_MIN = 64 * 1024 * 1024   # 单文件超过 64MB 自动分段并行
RESUME_SYNC_EVERY = 32 * 1024 * 1024   # 续传清单同步间隔（崩溃最多丢 32MB 进度）


def derive_key(code, salt, kdf_iter=KDF_ITER):
    """由验证码派生密钥（PBKDF2-HMAC-SHA256，市面主流口令派生）。
    验证码本身不经网络传输，两端各自派生。"""
    return hashlib.pbkdf2_hmac("sha256", code.encode("utf-8"),
                               salt, kdf_iter, dklen=32)


def _cert_files():
    """把内置证书写到配置目录（TLS 服务器加载需要文件路径）"""
    cert_p = os.path.join(app_dir(), "transport_cert.pem")
    key_p = os.path.join(app_dir(), "transport_key.pem")
    if not os.path.exists(cert_p) or not os.path.exists(key_p):
        with open(cert_p, "wb") as f:
            f.write(base64.b64decode(CERT_B64))
        with open(key_p, "wb") as f:
            f.write(base64.b64decode(KEY_B64))
    return cert_p, key_p


_tls_server_ctx = None


def server_tls_ctx():
    global _tls_server_ctx
    if _tls_server_ctx is None:
        c, k = _cert_files()
        _tls_server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        _tls_server_ctx.load_cert_chain(c, k)
    return _tls_server_ctx


_tls_client_ctx = None


def client_tls_ctx():
    global _tls_client_ctx
    if _tls_client_ctx is None:
        c, _k = _cert_files()
        with open(c, "r", encoding="ascii") as f:
            pem = f.read()
        _tls_client_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        _tls_client_ctx.check_hostname = False
        _tls_client_ctx.verify_mode = ssl.CERT_REQUIRED
        _tls_client_ctx.load_verify_locations(cadata=pem)
    return _tls_client_ctx


# ---------------------------------------------------------------- 基础工具

def get_local_ip():
    """获取本机主出口 IP（不开流量，仅路由探测）"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("223.5.5.5", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def app_dir():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    d = os.path.join(base, APP_NAME)
    if not os.path.isdir(d):
        os.makedirs(d)
    return d


# ---------------------------------------------------------------- 传输历史

_HISTORY_MAX = 200
_hist_lock = threading.Lock()


def record_history(entry):
    """追加一条传输历史（最近 200 条，json 存储；失败不影响传输）"""
    try:
        with _hist_lock:
            path = os.path.join(app_dir(), "history.json")
            items = []
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        items = json.load(f)
                except Exception:
                    items = []
            entry["time"] = time.strftime("%Y-%m-%d %H:%M:%S")
            items.insert(0, entry)
            del items[_HISTORY_MAX:]
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(items, f, ensure_ascii=False, indent=1)
            os.replace(tmp, path)
    except Exception:
        log.debug("历史记录写入失败", exc_info=True)


def load_history():
    try:
        path = os.path.join(app_dir(), "history.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return []


# ------------------------------------------------- 接收端未完成清单（断点续传）
#
# 意外断线（网络中断/软件崩溃）时保留半成品并记录已收字节，
# 下次对方发送同名同大小文件时自动从断点续传；
# 用户主动取消 / 拒收仍然清理半成品（.signal_resume.json 同步移除）。

_resume_lock = threading.Lock()


def _resume_path(save_dir):
    """续传清单存放在接收目录下（点开头，随目录自清理；避免污染全局配置）"""
    return os.path.join(save_dir, ".signal_resume.json")


def load_resume(save_dir):
    try:
        with open(_resume_path(save_dir), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_resume(save_dir, data):
    """原子写入续传清单；data 为空时删除清单文件"""
    try:
        p = _resume_path(save_dir)
        if not data:
            if os.path.exists(p):
                os.remove(p)
            return
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, p)
    except Exception:
        log.debug("续传清单写入失败", exc_info=True)


def logs_dir():
    d = os.path.join(app_dir(), "logs")
    if not os.path.isdir(d):
        os.makedirs(d)
    return d


def get_logger():
    """按天轮转的日志：logs/signal.log（保留 14 天）"""
    logger = logging.getLogger("signal")
    if not logger.handlers:
        logger.setLevel(logging.DEBUG)
        fh = logging.handlers.TimedRotatingFileHandler(
            os.path.join(logs_dir(), "signal.log"),
            when="midnight", backupCount=14, encoding="utf-8")
        fh.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S"))
        logger.addHandler(fh)
    return logger


log = get_logger()
log.info("加密通道：Python 内置 TLS（AES-256-GCM 套件），始终可用")


def fmt_size(n):
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return ("%.1f %s" % (n, unit)) if unit != "B" else ("%d B" % n)
        n /= 1024.0


def unique_path(path):
    """保存冲突时自动改名: file.txt -> file (1).txt"""
    if not os.path.exists(path):
        return path
    root, ext = os.path.splitext(path)
    i = 1
    while True:
        cand = "%s (%d)%s" % (root, i, ext)
        if not os.path.exists(cand):
            return cand
        i += 1


def _recv_exact(sock, n):
    buf = bytearray()
    while len(buf) < n:
        try:
            piece = sock.recv(min(1 << 20, n - len(buf)))
        except socket.timeout:
            raise
        except ConnectionError:
            raise
        except OSError as e:
            raise ConnectionError(str(e))   # socket 被关闭（取消）等场景
        if not piece:
            raise ConnectionError("连接中断")
        buf += piece
    return bytes(buf)


def _send_json(sock, obj):
    raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    try:
        sock.sendall(struct.pack(">I", len(raw)) + raw)
    except ConnectionError:
        raise
    except OSError as e:
        raise ConnectionError(str(e))
    except ConnectionError:
        raise
    except OSError as e:
        raise ConnectionError(str(e))


def _tune_sock(sock):
    """加大 TCP 收发缓冲：跨 AP WiFi 链路延迟高，小窗口会严重限速"""
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, SOCK_BUF)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, SOCK_BUF)
    except Exception:
        pass


def _recv_json(sock):
    raw_len = struct.unpack(">I", _recv_exact(sock, 4))[0]
    if raw_len > 4 * 1024 * 1024:
        raise ValueError("协议头过大")
    return json.loads(_recv_exact(sock, raw_len).decode("utf-8"))


# ---------------------------------------------------------------- 配置

class Config(object):
    DEFAULTS = {
        "device_name": "",
        "save_dir": "",
        "auto_accept": False,
        "autostart": False,
        "web_enabled": True,
    }

    def __init__(self):
        self.path = os.path.join(app_dir(), "config.json")
        data = dict(self.DEFAULTS)
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data.update(json.load(f))
        except Exception:
            pass
        self.device_name = data["device_name"] or socket.gethostname()
        # 保存目录默认为空：不自动创建任何文件夹，首次使用由用户在设置中选择
        self.save_dir = data["save_dir"] or ""
        self.auto_accept = bool(data["auto_accept"])
        self.autostart = bool(data["autostart"])
        self.web_enabled = bool(data["web_enabled"])

    def save_dir_ok(self):
        """保存目录是否已设置且真实存在"""
        return bool(self.save_dir) and os.path.isdir(self.save_dir)

    def save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({
                "device_name": self.device_name,
                "save_dir": self.save_dir,
                "auto_accept": self.auto_accept,
                "autostart": self.autostart,
                "web_enabled": self.web_enabled,
            }, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------- 设备发现

class Device(object):
    __slots__ = ("id", "name", "ip", "tcp", "tls", "last_seen")

    def __init__(self, did, name, ip, tcp, tls, last_seen):
        self.id = did
        self.name = name
        self.ip = ip
        self.tcp = tcp
        self.tls = tls          # 加密传输端口；0 = 对方是旧版，不支持加密
        self.last_seen = last_seen


class DiscoveryService(threading.Thread):
    """UDP 广播发现：每 2.5s 广播一次，同时监听其他设备的广播。"""

    def __init__(self, my_id, my_name, my_tcp, my_tls=0, port=None):
        threading.Thread.__init__(self)
        self.daemon = True
        self.my_id = my_id
        self.my_name = my_name
        self.my_tcp = my_tcp
        self.my_tls = my_tls
        self._port = port or DISCOVER_PORT
        self.devices = {}            # id -> Device（GIL 下读写安全）
        self.lock = threading.Lock()
        self._stop = threading.Event()
        self._sock = None

    def set_name(self, name):
        self.my_name = name

    def stop(self):
        self._stop.set()

    def _payload(self, t="d"):
        return (MAGIC + json.dumps({
            "id": self.my_id, "name": self.my_name,
            "tcp": self.my_tcp, "tls": self.my_tls, "ip": get_local_ip(),
            "t": t,
        }, ensure_ascii=False)).encode("utf-8")

    def _reply(self, addr):
        """广播回执：收到对方发现包后向其单播回发自己的信息。
        不绑定源地址，由系统按目标路由自动选网卡——双网卡主机（如
        有线+移动热点同时开启）的广播只会从默认路由网卡发出，热点
        网段的对端收不到；有了回执，对方广播一次即可反向发现本机，
        无需手动添加。回执包仅几百字节且随广播周期（2.5s）出现，
        流量可忽略，不做节流以保证发现速度。"""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.sendto(self._payload("r"), addr)
            s.close()
        except Exception:
            pass

    def run(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock = sock
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("", self._port))
        except Exception:
            sock.close()
            return
        last_send = 0.0
        while not self._stop.is_set():
            now = time.time()
            if now - last_send >= 2.5:
                last_send = now
                pkt = self._payload()
                try:
                    try:
                        # 绑定本机主 IP，从正确网卡发广播
                        s2 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                        s2.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                        s2.bind((get_local_ip(), 0))
                        s2.sendto(pkt, ("255.255.255.255", self._port))
                        s2.close()
                    except Exception:
                        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                        sock.sendto(pkt, ("255.255.255.255", self._port))
                except Exception:
                    pass
            sock.settimeout(1.0)
            try:
                data, addr = sock.recvfrom(65535)
            except socket.timeout:
                continue
            except Exception:
                continue
            try:
                if not data.startswith(MAGIC.encode()):
                    continue
                info = json.loads(data[len(MAGIC):].decode("utf-8"))
                did = info.get("id")
                if not did or did == self.my_id:
                    continue
                ptype = info.get("t", "d")   # 旧版本报文无类型字段，视为发现广播
                with self.lock:
                    old = self.devices.get(did)
                    if old is None:
                        self.devices[did] = Device(
                            did, info.get("name") or "未知设备",
                            addr[0], int(info.get("tcp") or TCP_BASE_PORT),
                            int(info.get("tls") or 0), now)
                        log.info("发现设备：%s（%s:%d，加密端口:%d）",
                                 self.devices[did].name, self.devices[did].ip,
                                 self.devices[did].tcp, self.devices[did].tls)
                    else:
                        old.name = info.get("name") or old.name
                        old.tcp = int(info.get("tcp") or old.tcp)
                        old.tls = int(info.get("tls") or 0)
                        old.last_seen = now
                if ptype == "d":
                    # 只对发现包回执；回执包（t=r）不再回执，避免乒乓风暴
                    self._reply(addr)
            except Exception:
                continue

    def alive(self, timeout=9.0):
        """返回当前在线设备快照（剔除超时设备）"""
        now = time.time()
        dead = []
        out = []
        with self.lock:
            for did, d in self.devices.items():
                if now - d.last_seen <= timeout:
                    out.append(d)
                else:
                    dead.append((did, d))
            for did, d in dead:
                self.devices.pop(did, None)
                log.info("设备离线：%s（%s）", d.name, d.ip)
        out.sort(key=lambda x: x.name)
        return out

    def poke(self, ip, times=3):
        """手动添加：向指定 IP 单播发现包，对方在线即出现在列表"""
        def _poke():
            pkt = self._payload()
            for _ in range(times):
                try:
                    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    s.sendto(pkt, (ip, DISCOVER_PORT))
                    s.close()
                except Exception:
                    pass
                time.sleep(0.5)
        threading.Thread(target=_poke, daemon=True).start()


# ---------------------------------------------------------------- 接收端

class TaskCancelled(Exception):
    """用户主动终止传输"""
    pass


class TransferControl(object):
    """传输控制句柄：暂停 / 继续 / 取消（发送端与接收端通用）"""

    def __init__(self):
        self.pause_ev = threading.Event()
        self.pause_ev.set()          # 默认运行中
        self.cancel_ev = threading.Event()
        self._socks = []             # 关联的 socket，取消时强制关闭以打断阻塞 IO
        self._lock = threading.Lock()

    def attach(self, sock):
        """关联 socket：取消时 shutdown，打断阻塞中的 recv/sendall"""
        with self._lock:
            self._socks.append(sock)

    def pause(self):
        self.pause_ev.clear()

    def resume(self):
        self.pause_ev.set()

    def cancel(self):
        self.cancel_ev.set()
        with self._lock:
            socks = list(self._socks)
        for s in socks:
            try:
                s.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                s.close()   # Windows 上 shutdown 无法唤醒阻塞 recv，需 close 才能打断
            except Exception:
                pass

    @property
    def paused(self):
        return not self.pause_ev.is_set()

    def wait_run(self, poll=0.1):
        """阻塞直到恢复运行或被取消；返回 False 表示已取消。
        替代无限期 pause_ev.wait()，保证取消可打断暂停等待。"""
        while not self.pause_ev.wait(poll):
            if self.cancel_ev.is_set():
                return False
        return not self.cancel_ev.is_set()


class _ReplyBox(object):
    """跨线程确认结果容器"""
    def __init__(self):
        self.event = threading.Event()
        self.result = False
        self.enc = False          # 是否加密传输（需验证码）
        self.code = ""            # 用户输入的验证码


class TransferServer(threading.Thread):
    """TCP 传输服务。协议（统一帧：4 字节大端长度 + JSON）：
      1) 客户端发 header {"v":1,"type":"text"|"files","id":...,"name":发送者,...}
      2) 服务端回 {"type":"accept"} 或 {"type":"reject"}
      3) text：正文（UTF-8）
         files：按 header.files 顺序流式传 1MB 块，最后发 {"type":"done","md5s":[...]}
      4) 服务端逐文件校验后回 {"type":"received","ok":bool}
    """

    def __init__(self, config, ui_cb):
        """ui_cb 回调（均在子线程触发，UI 层负责转到主线程）：
            on_request(sender, files, box)   box.event / box.result  ← 文件确认
            on_text(sender, text)
            on_recv_update(msg_id, info)     接收进度
            on_recv_done(msg_id, ok, note)   接收完成
            on_need_setup()                  未设置保存目录，引导用户设置
        """
        threading.Thread.__init__(self)
        self.daemon = True
        self.config = config
        self.cb = ui_cb
        self.port = 0
        self.tls_port = 0
        self._listeners = []      # [(use_tls, srv)]，构造时同步绑定，端口立即可用
        self._bind()
        self._stop = threading.Event()
        self._approved = {}       # 主任务id -> 已确认的验证码（并行子连接复用）
        self._recv_ctrl = {}      # msg_id -> TransferControl（接收任务暂停/取消）
        self._task_prog = {}      # msg_id -> 合并进度（多连接接收进度不跳动）
        self._prog_lock = threading.Lock()
        # UDP 控制信令：接收发送方发来的暂停/继续/取消事件
        self._udp_port = 0
        self._udp_sock = None
        self._bind_udp()

    def _bind_udp(self):
        # SO_EXCLUSIVEADDRUSE：确定性占用端口，同机多实例（测试/双开）时
        # 自动递增避让，保证信令单播投递确定；真实双机无感知。
        excl = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        for p in range(UDP_CTRL_PORT, UDP_CTRL_PORT + 10):
            if p == DISCOVER_PORT:
                continue   # 避开发现广播端口
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                if excl is not None:
                    s.setsockopt(socket.SOL_SOCKET, excl, 1)
                s.bind(("0.0.0.0", p))
                s.settimeout(0.5)
                self._udp_sock = s
                self._udp_port = p
                log.info("UDP 控制信令端口：%d" % p)
                return
            except OSError:
                continue
        log.warning("UDP 控制信令端口绑定失败，暂停通知不可用（不影响传输）")

    def udp_port(self):
        return self._udp_port

    def _udp_loop(self):
        """处理发送方发来的暂停/继续/取消信令（幂等，重复收到无副作用）"""
        while not self._stop.is_set():
            try:
                data, addr = self._udp_sock.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                msg = json.loads(data.decode("utf-8"))
                mid = msg.get("id") or ""
                ev = msg.get("ev") or ""
                ctrl = self._recv_ctrl.get(mid)
                if not ctrl:
                    continue
                if ev == "pause":
                    ctrl.pause()
                elif ev == "resume":
                    ctrl.resume()
                elif ev == "cancel":
                    ctrl.cancel()
                    log.info("接收[%s] 收到发送方取消信令" % mid)
            except Exception:
                continue

    def _bind(self):
        for use_tls, base in ((False, TCP_BASE_PORT), (True, TLS_PORT_BASE)):
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            for p in range(base, base + 20):
                try:
                    srv.bind(("0.0.0.0", p))
                    break
                except OSError:
                    continue
            else:
                srv.close()
                continue
            if use_tls:
                self.tls_port = srv.getsockname()[1]
            else:
                self.port = srv.getsockname()[1]
            self._listeners.append((use_tls, srv))
        log.info("普通端口：%d，加密(TLS)端口：%d" % (self.port, self.tls_port) if self.port and self.tls_port
                 else "端口绑定异常：plain=%s tls=%s" % (self.port, self.tls_port))

    def stop(self):
        self._stop.set()
        if self._udp_sock:
            try:
                self._udp_sock.close()
            except Exception:
                pass
        for p in (self.port, self.tls_port):
            if p:
                try:
                    socket.create_connection(("127.0.0.1", p), 1).close()
                except Exception:
                    pass

    def cancel_recv(self, msg_id=None):
        """取消接收任务（msg_id 为空则取消全部进行中的接收）"""
        with threading.Lock():
            if msg_id is None:
                for c in list(self._recv_ctrl.values()):   # 拷贝快照，避免并发修改
                    c.cancel()
            else:
                c = self._recv_ctrl.get(msg_id)
                if c:
                    c.cancel()

    def pause_recv(self, msg_id, pause=True):
        """暂停/继续接收任务"""
        c = self._recv_ctrl.get(msg_id)
        if c:
            c.resume() if not pause else c.pause()

    def run(self):
        threads = []
        for use_tls, srv in self._listeners:
            _tune_sock(srv)
            srv.listen(8)
            t = threading.Thread(target=self._accept_loop, args=(use_tls, srv), daemon=True)
            t.start()
            threads.append(t)
        if self._udp_sock:
            tu = threading.Thread(target=self._udp_loop, daemon=True)
            tu.start()
            threads.append(tu)
        while any(t.is_alive() for t in threads) and not self._stop.is_set():
            time.sleep(0.2)

    def _accept_loop(self, use_tls, srv):
        while not self._stop.is_set():
            try:
                conn, addr = srv.accept()
            except OSError:
                break
            t = threading.Thread(target=self._accept, args=(conn, addr, use_tls), daemon=True)
            t.start()

    def _accept(self, conn, addr, use_tls):
        if use_tls:
            try:
                conn = server_tls_ctx().wrap_socket(conn, server_side=True)
            except Exception as e:
                log.error("TLS 握手失败（%s）：%s", addr[0], e)
                try:
                    conn.close()
                except Exception:
                    pass
                return
        self._handle_conn(conn, addr)   # 明文与 TLS 统一进入连接处理

    def _handle_conn(self, conn, addr):
        """单连接处理（方法名避开 3.13 threading.Thread 内部新增的 _handle 句柄属性）"""
        tmp_key = uuid.uuid4().hex[:8]
        ctrl = TransferControl()
        ctrl.attach(conn)
        self._recv_ctrl[tmp_key] = ctrl
        own_key = tmp_key            # finally 按实际注册键清理，避免字典泄漏
        msg_id = tmp_key
        is_follow = False
        conn_slot = uuid.uuid4().hex[:6]
        task = None
        target_map = {}
        received_holder = {"list": [], "cur": None}
        try:
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            _tune_sock(conn)
            conn.settimeout(300)   # 防止僵尸连接，文件流间隙超 5 分钟视为中断
            header = _recv_json(conn)
            msg_id = header.get("id") or msg_id
            follow_id = header.get("follow") or ""
            is_follow = bool(follow_id)
            main_ctrl = self._recv_ctrl.get(follow_id) if follow_id else None
            if main_ctrl is not None:
                # 并行子连接：共享主任务 ctrl，取消/暂停主任务时子连接同步生效
                ctrl = main_ctrl
                ctrl.attach(conn)
            elif msg_id != tmp_key:
                # 接收任务的 ctrl 必须挂在发送方的 msg_id 下，否则 UI 按任务取消/暂停查不到
                self._recv_ctrl.pop(tmp_key, None)
                own_key = msg_id
                self._recv_ctrl[msg_id] = ctrl
            sender = header.get("name") or "未知设备"
            mtype = header.get("type")
            log.info("接收[%s] 来自 %s 的%s请求（发送者：%s）",
                     msg_id, addr[0], mtype, sender)
            if mtype == "text":
                size = int(header.get("size") or 0)
                _send_json(conn, {"type": "accept"})   # 与文件传输统一：先确认再收正文
                text = _recv_exact(conn, size).decode("utf-8", "replace")
                _send_json(conn, {"type": "received", "ok": True})
                log.info("接收[%s] 文字消息已收到（%d 字节）", msg_id, size)
                self.cb["on_text"](sender, text)
            elif mtype == "files":
                files = header.get("files") or []
                show_files = header.get("plan") or files
                approved_code = self._approved.get(follow_id) if follow_id else None
                if not self.config.save_dir_ok():
                    # 首次使用未设置保存目录：拒收并把原因传给发送端，引导用户去设置
                    log.warning("接收[%s] 拒绝：未设置保存目录", msg_id)
                    _send_json(conn, {"type": "reject",
                                      "reason": "对方未设置文件保存目录"})
                    self.cb["on_recv_done"](msg_id, False,
                                            "未设置文件保存目录，请先在【设置】中选择")
                    try:
                        self.cb["on_need_setup"]()
                    except Exception:
                        pass
                    return
                enc = bool(header.get("enc"))
                box = _ReplyBox()
                box.enc = enc
                box.cancel_ev = ctrl        # UI 弹窗轮询：发送方取消时自动关闭
                if follow_id and approved_code is not None:
                    # 并行子连接：主连接已确认过，直接复用验证码，不重复弹窗
                    box.result = True
                    box.code = approved_code
                    box.event.set()
                    log.info("接收[%s] 复用主任务 %s 的确认（并行子连接）", msg_id, follow_id)
                elif self.config.auto_accept and not enc:
                    box.result = True
                    box.event.set()
                    log.info("接收[%s] 自动接收已开启，直接确认", msg_id)
                else:
                    self.cb["on_request"](sender, show_files, box)
                    log.info("接收[%s] 已弹窗（%s），等待用户确认…",
                             msg_id, "加密：需验证码" if enc else "普通")
                    # 轮询等待用户决定或发送方取消/断开（弹窗可被自动关闭）
                    is_tls = use_tls_conn = hasattr(conn, "version")   # SSLSocket
                    while not box.event.wait(0.25):
                        if ctrl.cancel_ev.is_set():
                            raise TaskCancelled()
                        if not is_tls:
                            # 明文连接：探测发送方 cancel 帧/断开（对方取消时主动告知）
                            try:
                                conn.setblocking(False)
                                data = conn.recv(1, socket.MSG_PEEK)
                            except (BlockingIOError, ssl.SSLWantReadError,
                                    ssl.SSLWantWriteError):
                                try:
                                    conn.setblocking(True)
                                except Exception:
                                    pass
                                continue
                            except (ConnectionError, OSError):
                                try:
                                    conn.setblocking(True)
                                except Exception:
                                    pass
                                raise ConnectionError("发送方已断开")
                            conn.setblocking(True)
                            if not data:
                                log.info("接收[%s] 探测到对方断开", msg_id)
                                raise ConnectionError("发送方已断开")
                            # 有数据：读完整帧（弹窗阶段只会是 cancel 通知）
                            frame = _recv_json(conn)
                            log.info("接收[%s] 探测读到帧：%s", msg_id, frame)
                            if isinstance(frame, dict) and frame.get("type") == "cancel":
                                raise TaskCancelled()
                log.info("接收[%s] 用户决定：%s%s", msg_id,
                         "接收" if box.result else "拒绝",
                         "（已输入验证码）" if (enc and box.result and box.code) else "")
                if not box.result:
                    reason = "对方手动拒绝接收" if not enc else "对方拒绝（未输入验证码或取消）"
                    _send_json(conn, {"type": "reject", "reason": reason})
                    self.cb["on_recv_done"](msg_id, False, "已拒绝来自 %s 的文件" % sender)
                    return
                if enc:
                    if not box.code:
                        _send_json(conn, {"type": "reject", "reason": "对方未输入验证码"})
                        self.cb["on_recv_done"](msg_id, False, "未输入验证码，已拒绝")
                        return
                    # 应用层验证码校验：服务端发随机 challenge，客户端用验证码派生密钥回 HMAC
                    data = os.urandom(32)
                    _send_json(conn, {"type": "challenge",
                                      "data": base64.b64encode(data).decode("ascii")})
                    resp = _recv_json(conn)
                    mac = base64.b64decode(resp.get("mac") or "")
                    expect = hmac.new(derive_key(box.code, data[:16]),
                                      data, hashlib.sha256).digest()
                    if not hmac.compare_digest(mac, expect):
                        log.warning("接收[%s] 验证码错误，拒绝传输", msg_id)
                        _send_json(conn, {"type": "reject",
                                          "reason": "验证码错误，请核对后重试"})
                        self.cb["on_recv_done"](msg_id, False,
                                                 "验证码错误，已拒绝传输")
                        return
                    log.info("接收[%s] 验证码校验通过，开始接收", msg_id)
                    if enc:
                        self._approved[msg_id] = box.code
                self._approved[msg_id] = ""

                # ---- v1.9：断点续传协商 → 任务注册 → 目标路径映射 ----
                plan = header.get("plan") or []
                save_dir = self.config.save_dir
                resume_map = {}      # "fi:name" -> 偏移
                resume_paths = {}    # "fi:name" -> 清单里的半成品路径
                if not is_follow:
                    resume_data = load_resume(save_dir)
                    for meta in files:
                        st = meta.get("start")
                        nm = os.path.basename(meta.get("name") or "")
                        fi = int(meta.get("fi") or 0)
                        rec = resume_data.get("%d:%s" % (fi, nm))
                        if (st is None and rec
                                and int(rec.get("size") or 0) == int(meta.get("size") or 0)):
                            off = int(rec.get("offset") or 0)
                            rp = rec.get("path") or ""
                            if (0 < off < int(meta.get("size") or 0)
                                    and os.path.exists(rp)):
                                resume_map["%d:%s" % (fi, nm)] = off
                                resume_paths["%d:%s" % (fi, nm)] = rp
                    if resume_map:
                        log.info("接收[%s] 断点续传：%s", msg_id,
                                 {k: fmt_size(v) for k, v in resume_map.items()})
                if is_follow:
                    task = self._task_prog.get(msg_id)
                    if task is None:
                        # 主任务已结束（取消/完成）：迟到连接直接拒绝，避免它再创建文件且无人清理
                        try:
                            _send_json(conn, {"type": "reject",
                                              "reason": "主任务已结束"})
                        except Exception:
                            pass
                        return
                    with self._prog_lock:
                        task["left"] += 1
                        task["slots"][conn_slot] = {"sent": 0}
                        task["holders"].append(received_holder)
                    target_map = task.get("targets") or {}
                else:
                    total_all = sum(int(f.get("size") or 0) for f in (plan or files))
                    with self._prog_lock:
                        task = self._task_prog.setdefault(msg_id, {
                            "sender": sender, "total": total_all,
                            "slots": {}, "left": 1, "segs": {},
                            "paths": [], "targets": {}, "plan": plan or files,
                            "ok": True, "note": "", "last_cb": 0.0,
                            "last_sent": 0, "last_t": time.time(), "speed": 0.0,
                            "cancel": False, "holders": [received_holder],
                        })
                        task["slots"][conn_slot] = {"sent": 0}
                    # 为计划内每个文件预分配目标路径（续传项直接用清单里的半成品路径）
                    target_map = task["targets"]
                    for fmeta in (plan or files):
                        nm = os.path.basename(fmeta.get("name") or "")
                        fi = int(fmeta.get("fi") or 0)
                        if not nm:
                            continue
                        rkey = "%d:%s" % (fi, nm)
                        if rkey in resume_paths:
                            target_map[str(fi)] = resume_paths[rkey]
                        elif str(fi) not in target_map:
                            target_map[str(fi)] = unique_path(os.path.join(save_dir, nm))
                        if fmeta.get("segs"):
                            task["segs"][str(fi)] = {"need": int(fmeta["segs"]), "done": 0,
                                                     "size": int(fmeta.get("size") or 0)}
                            # 分段文件预分配（只在主连接做一次，避免并行连接 wb 截断竞态）
                            tpath = target_map[str(fi)]
                            if not os.path.exists(tpath):
                                try:
                                    with open(tpath, "wb") as t:
                                        t.truncate(int(fmeta.get("size") or 0))
                                except OSError:
                                    pass
                    task["targets"] = target_map

                resp = {"type": "accept", "v": 2, "udp": self._udp_port}
                if resume_map:
                    resp["resume"] = resume_map
                _send_json(conn, resp)
                self._recv_files(conn, msg_id, sender, files, ctrl, received_holder,
                                 conn_slot, task, target_map, resume_map, is_follow)
            else:
                _send_json(conn, {"type": "reject", "reason": "不支持的传输类型"})
        except TaskCancelled:
            log.info("接收[%s] 已被用户取消，清理未完成文件", msg_id)
            if task is not None:
                with self._prog_lock:
                    task["cancel"] = True
            self._finish_task(msg_id, task, False, "已取消，未完成文件已清理",
                              conn_slot, is_follow)
        except ConnectionError as e:
            log.warning("接收[%s] 连接中断：%s", msg_id, e)
            if task is not None:
                if not ctrl.cancel_ev.is_set():
                    time.sleep(1.0)   # 宽限：等 UDP 取消信令（重发 3 帧覆盖 0.6s）
                if ctrl.cancel_ev.is_set():
                    if task is not None:
                        with self._prog_lock:
                            task["cancel"] = True
                    self._finish_task(msg_id, task, False, "已取消传输，未完成文件已清理",
                                      conn_slot, is_follow)
                else:
                    # 断点续传：保留半成品并记录偏移，下次同名重发自动续传
                    self._keep_partial(task, received_holder)
                    self._finish_task(msg_id, task, False,
                                      "连接中断，已保留半成品；对方重新发送可自动续传",
                                      conn_slot, is_follow)
            else:
                # 确认/弹窗阶段对方断开 = 对方取消（无半成品，直接回调）
                self._finish_task(msg_id, None, False,
                                  "对方已取消发送或连接中断", conn_slot, is_follow)
        except Exception as e:
            log.exception("接收[%s] 异常：%s", msg_id, e)
            # 异常同样保留半成品（可续传），统一在最后一个连接结束时回调
            self._keep_partial(task, received_holder)
            self._finish_task(msg_id, task, False, "接收失败：%s" % e,
                              conn_slot, is_follow)
        finally:
            self._recv_ctrl.pop(own_key, None)
            try:
                conn.close()
            except Exception:
                pass

    # ---------- v1.9 接收端辅助：清理 / 保留半成品 / 合并进度 ----------

    def _cleanup_task(self, task, received_holder):
        """用户取消/异常：删除本任务已创建的所有半成品与文件，并移除续传清单"""
        paths = set()
        for r in received_holder.get("list") or []:
            paths.add(r["path"])
        if received_holder.get("cur"):
            paths.add(received_holder["cur"])
        targets = (task or {}).get("targets") or {}
        paths.update(p for p in targets.values() if p)
        for p in paths:
            try:
                if p and os.path.exists(p):
                    os.remove(p)
            except OSError:
                pass
        if targets:
            with _resume_lock:
                data = load_resume(self.config.save_dir)
                changed = False
                for nm in list(data.keys()):
                    if nm in targets:
                        data.pop(nm)
                        changed = True
                if changed:
                    save_resume(self.config.save_dir, data)

    def _cleanup_all(self, task):
        """最后一个连接退出后的统一清理（单连接也走此处）"""
        paths = set()
        for h in task.get("holders") or []:
            for r in h.get("list") or []:
                paths.add(r.get("path"))
            if h.get("cur"):
                paths.add(h["cur"])
        targets = task.get("targets") or {}
        paths.update(p for p in targets.values() if p)
        for p in paths:
            try:
                if p and os.path.exists(p):
                    os.remove(p)
            except OSError:
                pass
        # 清理清单内属于本任务的条目（key 为 "fi:name"，从 plan 还原）
        with _resume_lock:
            data = load_resume(self.config.save_dir)
            changed = False
            for fmeta in task.get("plan") or []:
                key = "%d:%s" % (int(fmeta.get("fi") or 0),
                                 os.path.basename(fmeta.get("name") or ""))
                if key in data:
                    data.pop(key)
                    changed = True
            if changed:
                save_resume(self.config.save_dir, data)

    def _keep_partial(self, task, received_holder):
        """意外断线：保留半成品，更新续传清单（分段文件不记录——重新发送即整文件重传）"""
        save_dir = self.config.save_dir
        targets = (task or {}).get("targets") or {}
        if not targets:
            return
        seg_names = set((task or {}).get("segs") or {})
        done_paths = set(r["path"] for r in received_holder.get("list") or [])
        with _resume_lock:
            data = load_resume(save_dir)
            for nm, p in targets.items():
                if nm in seg_names or p in done_paths or not p:
                    continue
                try:
                    if os.path.exists(p):
                        sz = os.path.getsize(p)
                        data[nm] = {"path": p, "size": sz, "offset": sz,
                                    "ts": time.time()}
                except OSError:
                    pass
            # 已完整收到的文件从清单移除
            for r in received_holder.get("list") or []:
                nm = os.path.basename(r["path"])
                if nm in data:
                    data.pop(nm)
            save_resume(save_dir, data)

    def _merged_update(self, msg_id, task):
        """多连接合并进度：汇总各连接已收字节，节流 0.2s 回调 UI"""
        now = time.time()
        with self._prog_lock:
            if now - task["last_cb"] < 0.2:
                return
            task["last_cb"] = now
            sent = sum(s.get("sent") or 0 for s in task["slots"].values())
            dt = now - task["last_t"]
            if dt > 0:
                inst = (sent - task["last_sent"]) / dt
                task["speed"] = 0.7 * task["speed"] + 0.3 * inst
            task["last_sent"] = sent
            task["last_t"] = now
            info = {"direction": "recv", "sender": task["sender"],
                    "files": task.get("plan") or [], "total": task["total"],
                    "sent": sent, "speed": task["speed"], "state": "接收中",
                    "file_idx": len(task.get("paths") or []),
                    "file_cnt": len(task.get("plan") or [])}
        try:
            self.cb["on_recv_update"](msg_id, dict(info))
        except Exception:
            pass

    def _finish_task(self, msg_id, task, ok, note, conn_slot, is_follow):
        """连接结束：递减计数，最后一个连接结束时统一回调 on_recv_done"""
        if task is None:
            try:
                self.cb["on_recv_done"](msg_id, ok, note)
            except Exception:
                pass
            return
        last = False
        with self._prog_lock:
            task["ok"] = task["ok"] and ok
            if not ok or not task["note"]:
                task["note"] = note
            task["left"] = max(task.get("left", 1) - 1, 0)
            task["slots"].pop(conn_slot, None)
            last = task["left"] == 0
        if last:
            if task.get("cancel"):
                # 所有连接都已退出：统一清理（避免先退连接删除时其他连接句柄未释放）
                self._cleanup_all(task)
            paths = list(task.get("paths") or [])
            info = {"direction": "recv", "sender": task["sender"],
                    "files": task.get("plan") or [], "total": task["total"],
                    "sent": task["total"], "speed": 0.0,
                    "state": "✅ 全部接收完成" if task["ok"] else "❌ 未完成",
                    "paths": paths,
                    "file_idx": len(paths), "file_cnt": len(task.get("plan") or [])}
            try:
                self.cb["on_recv_update"](msg_id, dict(info))
            except Exception:
                pass
            try:
                self.cb["on_recv_done"](msg_id, task["ok"], task["note"])
            except Exception:
                pass
            try:
                record_history({"direction": "recv", "peer": task["sender"],
                                "kind": "files",
                                "files": [os.path.basename(p) for p in paths[:5]],
                                "count": len(paths), "result": task["note"]})
            except Exception:
                pass
            with self._prog_lock:
                self._task_prog.pop(msg_id, None)

    def _recv_files(self, conn, msg_id, sender, files, ctrl, received_holder,
                    conn_slot, task, target_map, resume_map, is_follow):
        save_dir = self.config.save_dir
        received = received_holder["list"]
        cur_target = received_holder["cur"] = None
        slot = (task or {}).get("slots", {}).get(conn_slot)
        inflight = []      # [(fi, name, target, size, is_seg)] 对应本连接 files 顺序
        mds = []           # 对应每项的 md5 hex（done 校验用）
        for idx, meta in enumerate(files):
            fi = int(meta.get("fi") or idx)
            name = os.path.basename(meta.get("name") or "file_%d" % idx)
            size = int(meta.get("size") or 0)
            start = int(meta.get("start") or 0)
            ftotal = int(meta.get("ftotal") or size)
            is_seg = bool(meta.get("seg"))
            offset = int(resume_map.get("%d:%s" % (fi, name)) or 0)
            # 目标路径：跨连接映射优先（主连接已预分配）
            if task is not None:
                tkey = str(fi)
                target = target_map.get(tkey)
                if not target:
                    target = target_map[tkey] = unique_path(os.path.join(save_dir, name))
            else:
                target = unique_path(os.path.join(save_dir, name))
            md5 = hashlib.md5()
            left = size - offset   # 续传时发送端只发剩余部分（offset 已在半成品里）
            cur_target = received_holder["cur"] = target
            # 打开方式：段/续传 → r+b 定位写（分段文件已由主连接预分配；清单文件已存在）
            if is_seg or offset:
                if not os.path.exists(target):
                    # 兜底：预分配缺失时补建（正常时序下主连接已建）
                    with open(target, "wb") as t:
                        t.truncate(ftotal if is_seg else offset + size)
                fp = open(target, "r+b")
                fp.seek(start + offset)
            else:
                fp = open(target, "wb")
            last_t = time.time()
            last_sync = 0.0
            done_local = 0
            try:
                while left > 0:
                    if ctrl.cancel_ev.is_set():
                        raise TaskCancelled()
                    if not ctrl.pause_ev.is_set() and not ctrl.wait_run():
                        raise TaskCancelled()
                    try:
                        piece = conn.recv(min(CHUNK, left))
                    except socket.timeout:
                        raise
                    except ConnectionError:
                        raise
                    except OSError as e:
                        raise ConnectionError(str(e))   # 连接被关闭（取消/断开）等
                    if not piece:
                        raise ConnectionError("连接中断")
                    fp.write(piece)
                    md5.update(piece)
                    left -= len(piece)
                    done_local += len(piece)
                    if slot is not None:
                        slot["sent"] = slot.get("sent", 0) + len(piece)
                    now = time.time()
                    if task is not None:
                        self._merged_update(msg_id, task)
                    # 续传清单周期同步（每 10 秒且已收超过阈值时记录断点）
                    if (not is_seg and offset == 0 and task is not None
                            and now - last_sync >= 10 and fp.tell() >= RESUME_SYNC_EVERY):
                        last_sync = now
                        self._sync_resume(save_dir, fi, name, target, fp.tell(), size)
            finally:
                fp.close()
            inflight.append((fi, name, target, size, is_seg, start))
            mds.append(md5.hexdigest())
            log.info("接收[%s] 分片落盘： %s（%s%s）", msg_id, name, fmt_size(size),
                     ("，续传自 %s" % fmt_size(offset)) if offset else "")
        # 尾部 done 帧：逐项校验 MD5
        try:
            tail = _recv_json(conn)
        except (TaskCancelled, ConnectionError):
            raise      # 统一由 _handle 标记后清理/保留（最后一个连接退出时执行）
        md5s = tail.get("md5s") or []
        ok = len(md5s) == len(inflight)
        resume_note = []
        if ok:
            for (fi, name, target, size, is_seg, start), want in zip(inflight, md5s):
                m = hashlib.md5()
                if is_seg:
                    # 分段项：校验该段的字节范围
                    with open(target, "rb") as f:
                        f.seek(start)
                        left_s = size
                        while left_s > 0:
                            piece = f.read(min(1 << 20, left_s))
                            if not piece:
                                break
                            m.update(piece)
                            left_s -= len(piece)
                else:
                    with open(target, "rb") as f:
                        for piece in iter(lambda: f.read(1 << 20), b""):
                            m.update(piece)
                if m.hexdigest() != want:
                    ok = False
                    log.warning("接收[%s] MD5 不一致：%s", msg_id, name)
                    break
        if ok:
            for (fi, name, target, size, is_seg, start) in inflight:
                if is_seg:
                    # 分段文件：所有段校验通过才算完整
                    seg = (task or {}).get("segs", {}).get(str(fi))
                    if seg is not None:
                        seg["done"] += 1
                        if seg["done"] >= seg["need"]:
                            received.append({"name": name, "size": seg["size"], "path": target})
                            if task is not None:
                                task["paths"].append(target)
                            self._clear_resume(save_dir, fi, name)
                            log.info("接收[%s] 分段文件已完整： %s（%s，%d 段）",
                                     msg_id, name, fmt_size(seg["size"]), seg["need"])
                else:
                    received.append({"name": name, "size": size, "path": target})
                    if task is not None:
                        task["paths"].append(target)
                    self._clear_resume(save_dir, fi, name)
                    if "%d:%s" % (fi, name) in (resume_map or {}):
                        resume_note.append(name)
                    log.info("接收[%s] 已保存： %s（%s）", msg_id, name, fmt_size(size))
        note = ""
        if ok:
            n_files = len(task.get("paths") or []) if task is not None else len(received)
            extra = ("，续传 %d 个" % len(resume_note)) if resume_note else ""
            seg_n = sum(1 for (_, _, _, _, sg, _st) in inflight if sg)
            extra2 = ("，%d 段并行" % seg_n) if seg_n else ""
            note = ("全部接收完成，共 %d 个文件，MD5 校验通过%s%s" % (n_files, extra, extra2))
        else:
            note = "已完成，但 MD5 校验不一致，请重传"
        # 先回发接收结果，解除发送端等待；再走统一完成回调
        try:
            _send_json(conn, {"type": "received", "ok": ok})
        except Exception:
            pass
        log.info("接收[%s] 连接完成，MD5 校验：%s（%d 项）",
                 msg_id, "通过" if ok else "不一致", len(inflight))
        self._finish_task(msg_id, task, ok, note, conn_slot, is_follow)

    def _sync_resume(self, save_dir, fi, name, target, offset, size):
        """传输中周期记录断点（崩溃最多损失 RESUME_SYNC_EVERY 进度）"""
        with _resume_lock:
            data = load_resume(save_dir)
            data["%d:%s" % (fi, name)] = {"path": target, "size": size,
                                          "offset": offset, "name": name,
                                          "ts": time.time()}
            save_resume(save_dir, data)

    def _clear_resume(self, save_dir, fi, name):
        with _resume_lock:
            data = load_resume(save_dir)
            key = "%d:%s" % (fi, name)
            if key in data:
                data.pop(key)
                save_resume(save_dir, data)


# ---------------------------------------------------------------- 发送端

class SendTask(threading.Thread):
    """发送任务：多连接并行（文件夹自动拆分）+ 磁盘预读流水线。
    加密模式：主连接完成验证码校验后，并行子连接复用同一验证码。"""

    PARALLEL = 3                 # 并行连接数（文件夹多文件时生效）

    def __init__(self, target_ip, target_port, sender_name, text=None,
                 paths=None, progress=None, on_done=None, on_error=None,
                 encrypted=False, code="", tls_port=0):
        threading.Thread.__init__(self)
        self.daemon = True
        self.ip = target_ip
        self.port = target_port
        self.tls_port = tls_port
        self.sender_name = sender_name
        self.text = text
        self.paths = paths or []
        self.msg_id = uuid.uuid4().hex[:8]
        self.progress = progress if progress is not None else {}
        self.on_done = on_done
        self.on_error = on_error
        self.encrypted = bool(encrypted)
        self.code = code
        self.ctrl = TransferControl()
        self._stage = "连接"
        self._lock = threading.Lock()
        self._done = 0
        self._last_t = time.time()
        self._last_bytes = 0
        self._error = None
        self._peer_udp = 0          # 接收方 UDP 信令端口（accept 响应携带）
        self._file_done = 0         # 已完成文件数（进度序号显示）
        # 构造即写入占位状态，UI 立即可见"连接中…"而不是"准备中"
        self._info = self.progress.setdefault(self.msg_id, {
            "direction": "send", "sender": sender_name, "state": "连接中…",
            "speed": 0.0, "sent": 0, "total": 0, "files": [],
            "paths": list(self.paths), "obj": self})
        self._info["state"] = "连接中…"

    def pause(self):
        self.ctrl.pause()
        self._notify_peer("pause")

    def resume(self):
        self.ctrl.resume()
        self._notify_peer("resume")

    def cancel(self):
        # 同步先发一帧取消信令：确保对方在连接 shutdown 断开前收到（否则对方走“保留半成品”分支）
        self._notify_once("cancel")
        # 弹窗/等待确认阶段：通过 TCP 发 cancel 帧，接收端弹窗轮询读到后立即关闭
        if getattr(self, "_stage", "") == "等待确认" and getattr(self, "_main_sock", None):
            try:
                _send_json(self._main_sock, {"v": 2, "type": "cancel"})
                log.info("发送[%s] TCP cancel 帧已发送", self.msg_id)
            except Exception:
                log.info("发送[%s] TCP cancel 帧发送失败", self.msg_id)
        self.ctrl.cancel()
        self._notify_peer("cancel")

    def _notify_once(self, ev):
        port = getattr(self, "_peer_udp", 0)
        if not port or not self.ip:
            log.info("发送[%s] 取消信令跳过（对方 UDP 端口未知）", self.msg_id)
            return
        try:
            pkt = json.dumps({"v": 2, "ev": ev, "id": self.msg_id}).encode("utf-8")
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                s.sendto(pkt, (self.ip, port))
                log.info("发送[%s] 信令 %s -> %s:%d", self.msg_id, ev, self.ip, port)
            finally:
                s.close()
        except Exception:
            log.debug("发送[%s] 信令发送失败", self.msg_id, exc_info=True)

    def set_peer_udp(self, udp_port):
        """记录接收方的 UDP 信令端口（accept 响应携带；旧版无此字段则不通知）"""
        self._peer_udp = int(udp_port or 0)

    def _notify_peer(self, ev):
        """UDP 信令通知对方暂停/继续/取消（幂等，重发 3 次抗丢包）"""
        port = getattr(self, "_peer_udp", 0)
        if not port or not self.ip:
            return
        pkt = json.dumps({"v": 2, "ev": ev, "id": self.msg_id}).encode("utf-8")

        def _send():
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                for _ in range(3):
                    if self.ctrl.cancel_ev.is_set() and ev != "cancel":
                        return
                    try:
                        s.sendto(pkt, (self.ip, port))
                    except OSError:
                        return
                    time.sleep(0.2)
            finally:
                try:
                    s.close()
                except Exception:
                    pass

        threading.Thread(target=_send, daemon=True).start()

    @property
    def paused(self):
        return self.ctrl.paused

    def run(self):
        ok = False
        note = ""
        try:
            self._run()
            ok = True
        except TaskCancelled:
            info = self.progress.get(self.msg_id)
            if info is None:
                info = self._info
            info["state"] = "⏹ 已取消"
            info["speed"] = 0.0
            note = "已取消"
            log.info("发送[%s] 已被用户取消", self.msg_id)
        except Exception as e:
            info = self.progress.get(self.msg_id)
            if info is None:
                info = self._info
            if self.ctrl.cancel_ev.is_set():
                # 取消触发的连接中断等异常统一视为用户取消
                info["state"] = "⏹ 已取消"
                info["speed"] = 0.0
                note = "已取消"
                log.info("发送[%s] 已被用户取消（%s）", self.msg_id, e)
            else:
                info["state"] = "❌ 失败：%s" % e
                info["speed"] = 0.0
                note = "失败：%s" % e
                log.error("发送[%s] 失败：%s", self.msg_id, e)
                if self.on_error:
                    self.on_error(str(e))
        finally:
            try:
                if self.text is not None:
                    record_history({"direction": "send", "peer": self.ip,
                                    "kind": "text", "content": (self.text or "")[:60],
                                    "result": note or "已送达"})
                else:
                    names = [os.path.basename(p) for p in self.paths][:5]
                    record_history({"direction": "send", "peer": self.ip,
                                    "kind": "files", "files": names,
                                    "count": len(self.paths), "result": note or "已发送"})
            except Exception:
                pass

    def _add_done(self, n):
        with self._lock:
            self._done += n
            now = time.time()
            if now - self._last_t >= 0.2:
                dt = now - self._last_t
                inst = (self._done - self._last_bytes) / dt if dt else 0
                self._info["speed"] = 0.7 * self._info["speed"] + 0.3 * inst
                self._last_bytes = self._done
                self._last_t = now
            self._info["sent"] = self._done

    @staticmethod
    def _pump(sock, path, on_chunk, ctrl, start=0, end=None):
        """磁盘预读流水线 + 非阻塞分片发送。
        非阻塞小片（256KB）+ 50ms 轮询：暂停/取消检查点不受 TCP 背压阻塞，
        接收端长时间暂停时发送端可安全暂停而不会触发超时。"""
        q = queue.Queue(maxsize=4)
        stop_ev = threading.Event()   # 主循环退出（含异常）时通知 reader 停止，释放文件句柄

        def reader():
            try:
                with open(path, "rb") as fp:
                    if start:
                        fp.seek(start)
                    remaining = None if end is None else (end - start)
                    while True:
                        want = CHUNK if remaining is None else min(CHUNK, remaining)
                        piece = fp.read(want)
                        while True:
                            try:
                                q.put(piece, timeout=0.2)
                                break
                            except queue.Full:
                                if ctrl.cancel_ev.is_set() or stop_ev.is_set():
                                    return    # 已取消/主循环已退出：释放文件句柄
                        if remaining is not None:
                            remaining -= len(piece)
                        if not piece:
                            break
            except Exception as e:
                try:
                    q.put(e, timeout=0.2)
                except Exception:
                    pass

        rt = threading.Thread(target=reader, daemon=True)
        rt.start()
        try:
            sock.setblocking(False)
        except Exception:
            pass
        buf = b""
        eof = False
        try:
            while True:
                if ctrl.cancel_ev.is_set():
                    raise TaskCancelled()
                if not ctrl.pause_ev.is_set() and not ctrl.wait_run():
                    raise TaskCancelled()
                while not eof and len(buf) < SEND_PIECE:
                    try:
                        item = q.get(timeout=0.05)
                    except queue.Empty:
                        break
                    if isinstance(item, Exception):
                        raise item
                    if not item:
                        eof = True
                        break
                    buf += item
                if not buf:
                    if eof:
                        break
                    continue
                try:
                    piece_out = buf[:SEND_PIECE]
                    n = sock.send(piece_out)
                except (BlockingIOError, ssl.SSLWantWriteError, ssl.SSLWantReadError):
                    time.sleep(0.05)   # 缓冲满：稍后再试，保持暂停/取消响应
                    continue
                except ConnectionError:
                    raise
                except OSError as e:
                    raise ConnectionError(str(e))
                on_chunk(piece_out[:n])
                buf = buf[n:]
        finally:
            stop_ev.set()
            try:
                sock.setblocking(True)
            except Exception:
                pass
            try:
                rt.join(timeout=2)
            except Exception:
                pass

    @staticmethod
    def _split_files(files, k):
        if k <= 1 or len(files) <= 1:
            return [files]
        arr = sorted(files, key=lambda f: -f["size"])
        groups = [[] for _ in range(k)]
        sizes = [0] * k
        for f in arr:
            i = sizes.index(min(sizes))
            groups[i].append(f)
            sizes[i] += f["size"]
        return [g for g in groups if g]

    @staticmethod
    def _wire_item(f):
        """把传输单元转成协议字段（v2：带原始序号/分段信息）"""
        d = {"name": f["name"], "size": f["size"], "fi": f["fi"]}
        if f.get("seg"):
            d["seg"] = True
            d["start"] = f["start"]
            d["ftotal"] = f["ftotal"]
        return d

    def _tls_wrap(self, sock):
        try:
            return client_tls_ctx().wrap_socket(sock, server_hostname="signal")
        except Exception as e:
            log.error("发送[%s] TLS 握手失败：%s", self.msg_id, e)
            raise ValueError("加密通道建立失败：%s" % e)

    def _do_challenge(self, sock):
        """服务端随机挑战 + 验证码 HMAC 应答"""
        ch = _recv_json(sock)
        if ch.get("type") == "challenge":
            data = base64.b64decode(ch.get("data") or "")
            mac = hmac.new(derive_key(self.code, data[:16]),
                           data, hashlib.sha256).digest()
            _send_json(sock, {"type": "verify",
                              "mac": base64.b64encode(mac).decode("ascii")})

    def _connect(self, use_tls):
        target_port = self.tls_port if use_tls else self.port
        try:
            sock = socket.create_connection((self.ip, target_port), timeout=5)
            _tune_sock(sock)
        except Exception as e:
            log.error("发送[%s] 连接 %s:%d 失败：%s", self.msg_id, self.ip, target_port, e)
            raise ValueError("无法连接对方 %s:%d —— 请确认对方软件已打开，"
                             "并在对方电脑上点【设置→一键放行防火墙】" % (self.ip, target_port))
        if use_tls:
            sock = self._tls_wrap(sock)
        sock.settimeout(180)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        return sock

    def _send_files_on(self, sock, grp_files, follow_id="", send_header=True,
                       resume=None, plan=None):
        if send_header:
            hdr = {"v": 2, "type": "files", "id": self.msg_id,
                   "name": self.sender_name,
                   "files": [self._wire_item(f) for f in grp_files]}
            if plan is not None:
                hdr["plan"] = plan
            if follow_id:
                hdr["follow"] = follow_id
            if self.encrypted:
                hdr["enc"] = True
            _send_json(sock, hdr)
            if self.encrypted:
                self._do_challenge(sock)
            resp = self._wait_accept(sock)
            self.set_peer_udp((resp or {}).get("udp"))
            resume = (resp or {}).get("resume") or resume or {}
        md5s = []
        for f in grp_files:
            fi = int(f["fi"])
            start = int(f.get("start") or 0)
            is_seg = bool(f.get("seg"))
            offset = int((resume or {}).get("%d:%s" % (fi, f["name"])) or 0)
            log.info("发送[%s] 开始： %s（%s%s）", self.msg_id, f["name"], fmt_size(f["size"]),
                     ("，%s段" % ("第%d" % (start // max(SPLIT_MIN // self.PARALLEL, 1) + 1)) if is_seg else "")
                     + ("，续传自 %s" % fmt_size(offset)) if offset else "")
            t0 = time.time()

            md5 = hashlib.md5()
            if offset:
                # 断点续传：done 帧需要完整文件 MD5 → 预计算源文件全量 MD5
                with open(f["path"], "rb") as fp0:
                    for piece in iter(lambda: fp0.read(1 << 20), b""):
                        md5.update(piece)

                def on_chunk(piece):
                    # 全量 MD5 已预计算，本次发送的字节不再累计（否则污染全量值）
                    self._add_done(len(piece))
            else:
                def on_chunk(piece):
                    md5.update(piece)
                    self._add_done(len(piece))

            self._pump(sock, f["path"], on_chunk, self.ctrl,
                       start=start + offset,
                       end=(start + f["size"]) if is_seg else None)
            with self._lock:
                self._file_done += 1
                self._info["file_idx"] = self._file_done
            dt = max(time.time() - t0, 0.001)
            log.info("发送[%s] 完成： %s（%s，平均 %s/s）",
                     self.msg_id, f["name"], fmt_size(f["size"]), fmt_size(f["size"] / dt))
            md5s.append(md5.hexdigest())
        _send_json(sock, {"type": "done", "md5s": md5s})
        self._wait_received(sock)

    def _run(self):
        self._stage = "连接"
        try:
            sock = self._connect(self.encrypted)
        except ValueError:
            raise
        self.ctrl.attach(sock)   # 取消时 shutdown/close，打断阻塞中的 sendall/recv
        self._main_sock = sock   # 弹窗阶段取消时可通过它发送 cancel 帧
        if self.encrypted:
            log.info("发送[%s] TLS 加密通道已建立 %s:%d", self.msg_id, self.ip, self.tls_port)
        else:
            log.info("发送[%s] 已连接 %s:%d", self.msg_id, self.ip, self.port)
        self._stage = "等待确认"
        try:
            self._info["state"] = "已连接，等待对方确认…"
            if self.text is not None:
                body = self.text.encode("utf-8")
                _send_json(sock, {"v": 1, "type": "text", "id": self.msg_id,
                                  "name": self.sender_name, "size": len(body)})
                self._wait_accept(sock)
                self._stage = "传输"
                self._info["state"] = "发送中…"
                self._info["total"] = len(body)
                sock.sendall(body)
                self._wait_received(sock)
                short = self.text[:20] + ("…" if len(self.text) > 20 else "")
                self._info["state"] = "✅ 文字已送达"
                self._info["speed"] = 0.0
                self._info["sent"] = 1
                self._info["total"] = 1
                self._info["files"] = [{"name": short, "size": len(body)}]
                log.info("发送[%s] 文字已送达 %s", self.msg_id, self.ip)
                if self.on_done:
                    self.on_done(self.msg_id, True, "文字已送达 %s" % self.ip)
                return
            files = []
            for p in self.paths:
                if os.path.isdir(p):
                    for root, _dirs, names in os.walk(p):
                        for n in names:
                            fp = os.path.join(root, n)
                            files.append({"path": fp,
                                          "name": os.path.basename(fp),
                                          "size": os.path.getsize(fp)})
                else:
                    files.append({"path": p, "name": os.path.basename(p),
                                  "size": os.path.getsize(p)})
            if not files:
                raise ValueError("没有可发送的文件")
            total = sum(f["size"] for f in files)
            for i, f in enumerate(files):
                f["fi"] = i
            # 单大文件自动分段并行（>64MB 即使单文件也拆成 PARALLEL 段）
            has_big = any(f["size"] >= SPLIT_MIN for f in files)
            k = min(self.PARALLEL, max(1, self.PARALLEL if has_big else len(files)))
            plan = []
            work = []
            for f in files:
                if f["size"] >= SPLIT_MIN and k >= 2:
                    nseg = k
                    seg_sz = -(-f["size"] // nseg)   # ceil
                    f["segs"] = nseg
                    for s in range(nseg):
                        st = s * seg_sz
                        sz = min(seg_sz, f["size"] - st)
                        work.append({"path": f["path"], "name": f["name"],
                                     "size": sz, "fi": f["fi"], "start": st,
                                     "seg": True, "ftotal": f["size"]})
                else:
                    work.append({"path": f["path"], "name": f["name"],
                                 "size": f["size"], "fi": f["fi"]})
                plan.append({"name": f["name"], "size": f["size"],
                             "fi": f["fi"], "segs": f.get("segs") or 0})
            log.info("发送[%s] 文件：%d 个，共 %s -> %s（%s，并行连接 %d%s）",
                     self.msg_id, len(files), fmt_size(total), self.ip,
                     "TLS 加密 + 验证码" if self.encrypted else "明文", k,
                     "，含分段" if any(f.get("segs") for f in files) else "")
            self._info["files"] = [{"name": f["name"], "size": f["size"]} for f in files]
            self._info["total"] = total
            self._info["file_cnt"] = len(files)
            self._info["file_idx"] = 0
            groups = self._split_files(work, k)
            hdr = {"v": 2, "type": "files", "id": self.msg_id,
                   "name": self.sender_name,
                   "files": [self._wire_item(f) for f in groups[0]],
                   "plan": plan}
            if self.encrypted:
                hdr["enc"] = True
            _send_json(sock, hdr)
            if self.encrypted:
                self._do_challenge(sock)
            resp = self._wait_accept(sock)
            self.set_peer_udp((resp or {}).get("udp"))
            resume = (resp or {}).get("resume") or {}
            if resume:
                log.info("发送[%s] 对方请求续传 %d 个文件", self.msg_id, len(resume))
            log.info("发送[%s] 对方已确认，开始传输", self.msg_id)
            self._stage = "传输"
            self._info["state"] = "发送中"
            t_start = time.time()
            def _main_worker():
                try:
                    self._send_files_on(sock, groups[0], "", False,
                                        resume=resume, plan=plan)
                except TaskCancelled:
                    pass
                except Exception as e:
                    # 主 worker 异常必须记入 _error，否则主线程会误报“发送完成”
                    if self._error is None:
                        with self._lock:
                            self._error = e

            workers = [threading.Thread(target=_main_worker, daemon=True)]
            workers[0].start()
            for gi in range(1, len(groups)):
                w = threading.Thread(target=self._follow_worker,
                                     args=(gi, groups[gi]), daemon=True)
                workers.append(w)
                w.start()
            for w in workers:
                w.join()
            if self.ctrl.cancel_ev.is_set():
                raise TaskCancelled()
            if self._error:
                raise self._error
            info = self._info
            info["state"] = "✅ 发送完成，MD5 校验通过"
            info["speed"] = 0.0
            info["sent"] = total
            elapsed = max(time.time() - t_start, 0.001)
            log.info("发送[%s] 传输汇总：总 %s，耗时 %.1f 秒，平均 %s/s（模式：%s，连接 x%d）",
                     self.msg_id, fmt_size(total), elapsed, fmt_size(total / elapsed),
                     "TLS 加密 + 验证码" if self.encrypted else "明文", len(groups))
            if self.on_done:
                self.on_done(self.msg_id, True,
                             "已发送 %d 个文件（%s）到 %s" % (len(files), fmt_size(total), self.ip))
        except socket.timeout:
            log.exception("发送[%s] 超时（阶段：%s）", self.msg_id, self._stage)
            if self._stage == "等待确认":
                raise ValueError("等待对方确认超时（180 秒无响应）："
                                 "请看对方电脑上是否有弹窗未处理；若没有弹窗，"
                                 "请在对方电脑上点【设置→一键放行防火墙】后重试")
            raise ValueError("传输超时（%s 阶段）：网络中断或对方无响应" % self._stage)
        except ConnectionError as e:
            log.exception("发送[%s] 连接被断开（阶段：%s）", self.msg_id, self._stage)
            raise ValueError("连接被对方断开（%s 阶段）：%s" % (self._stage, e))
        finally:
            try:
                sock.close()
            except Exception:
                pass

    def _follow_worker(self, wid, grp_files):
        try:
            sock = self._connect(self.encrypted)
            self.ctrl.attach(sock)
            self._send_files_on(sock, grp_files, follow_id=self.msg_id)
            try:
                sock.close()
            except Exception:
                pass
        except TaskCancelled:
            log.info("发送[%s] 并行连接 %d 已取消", self.msg_id, wid)
        except Exception as e:
            if self._error is None:
                with self._lock:
                    self._error = e

    @staticmethod
    def _wait_accept(sock):
        """等待对方确认；返回响应（含 v2 的 udp 端口/续传表）"""
        resp = _recv_json(sock)
        if resp.get("type") == "reject":
            reason = resp.get("reason") or "未说明原因"
            raise ValueError("对方拒绝接收（%s）" % reason)
        return resp

    @staticmethod
    def _wait_received(sock):
        resp = _recv_json(sock)
        if not resp.get("ok"):
            raise ValueError("对方接收数据校验失败，请重传")
