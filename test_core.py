# -*- coding: utf-8 -*-
"""Signal 快传 - 核心端到端测试（模拟两台电脑）"""
import hashlib
import os
import random
import shutil
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import core

OK = True


def report(name, ok, extra=""):
    global OK
    print(("[PASS] " if ok else "[FAIL] ") + name + ("  " + extra if extra else ""))
    if not ok:
        OK = False


def make_cfg(save_dir, auto_accept=False):
    c = core.Config.__new__(core.Config)
    c.path = os.path.join(core.app_dir(), "config_test.json")
    c.device_name = "测试机"
    c.save_dir = save_dir
    os.makedirs(save_dir, exist_ok=True)
    c.auto_accept = auto_accept
    return c


def wait_clean(dirpath, before, timeout=8):
    """轮询等待清理完成（接收端取消清理有最长约 2 秒延迟）"""
    for _ in range(int(timeout * 2)):
        time.sleep(0.5)
        cur = {f for f in os.listdir(dirpath) if not f.startswith(".")}
        if not (cur - before):
            return True
    return False


class Inst(object):
    def __init__(self, tag, auto_accept=False, no_dir=False, hold=False):
        self.tag = tag
        self.my_id = tag + "-id-" + tag
        self.save_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     "test_recv_" + tag)
        # 清理上一轮残留，避免重名文件干扰 MD5 对照
        if os.path.isdir(self.save_dir):
            shutil.rmtree(self.save_dir, ignore_errors=True)
        self.cfg = make_cfg(self.save_dir, auto_accept)
        if no_dir:
            self.cfg.save_dir = ""          # 模拟首次使用未设置目录
        self.hold = hold
        self.texts = []
        self.dones = []
        self.need_setup = []
        self.done_event = threading.Event()
        self.server = core.TransferServer(self.cfg, {
            "on_request": self._req,
            "on_text": self._text,
            "on_recv_update": self._upd,
            "on_recv_done": self._done,
            "on_need_setup": self._setup,
        })
        self.server.start()
        self.disc = core.DiscoveryService(self.my_id, "电脑-" + tag, self.server.port)
        self.disc.start()

    def _setup(self):
        self.need_setup.append(True)

    def _req(self, sender, files, box):
        if self.hold:
            return            # 模拟用户长时间不响应弹窗（供取消测试）
        box.result = True
        if getattr(box, "enc", False):
            box.code = "123456"          # 测试用固定验证码
        box.event.set()

    def _text(self, sender, text):
        self.texts.append((sender, text))

    def _upd(self, mid, info):
        pass

    def _done(self, mid, ok, note):
        self.dones.append((ok, note))
        self.done_event.set()

    def close(self):
        self.disc.stop()
        self.server.stop()


def main():
    a = Inst("甲", auto_accept=True)
    b = Inst("乙")
    time.sleep(1.0)
    report("两个实例启动，端口分配", a.server.port != b.server.port,
           "A=%d B=%d" % (a.server.port, b.server.port))

    # 1. 广播发现（同机环回，真实双机必然可用；本机不环回则以单播为准）
    time.sleep(4.0)
    a_sees_b = any(d.id == b.my_id for d in a.disc.alive())
    b_sees_a = any(d.id == a.my_id for d in b.disc.alive())
    if a_sees_b and b_sees_a:
        report("UDP 广播互相发现（本机环回）", True)

    # 2. 单播 poke 发现（手动添加路径，跨机场景主路径之一）
    a.disc.poke("127.0.0.1")
    b.disc.poke("127.0.0.1")
    time.sleep(2.5)
    b_sees_a = any(d.id == a.my_id for d in b.disc.alive())
    a_sees_b = any(d.id == b.my_id for d in a.disc.alive())
    report("单播 poke 发现", a_sees_b and b_sees_a)

    # 3. 文字消息 乙 -> 甲
    b_target_ip, b_target_port = "127.0.0.1", a.server.port
    t = core.SendTask(b_target_ip, b_target_port, "电脑-乙", text="你好，这是工位消息同步测试✓")
    t.start()
    t.join(10)
    report("发送线程正常结束（无卡死）", not t.is_alive())
    time.sleep(0.5)
    report("文字消息送达", a.texts and a.texts[0][1] == "你好，这是工位消息同步测试✓",
           str(a.texts))

    # 4. 文件传输 乙 -> 甲（8MB 随机 + 小文本），MD5 校验
    src_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_src")
    if os.path.isdir(src_dir):
        shutil.rmtree(src_dir, ignore_errors=True)
    os.makedirs(src_dir, exist_ok=True)
    big = os.path.join(src_dir, "大数据.bin")
    with open(big, "wb") as f:
        f.write(bytes(random.getrandbits(8) for _ in range(8 * 1024 * 1024)))
    small = os.path.join(src_dir, "报表.txt")
    with open(small, "w", encoding="utf-8") as f:
        f.write("网格打分数据 ABC123 " * 100)
    src_md5 = {os.path.basename(big): hashlib.md5(open(big, "rb").read()).hexdigest(),
               os.path.basename(small): hashlib.md5(open(small, "rb").read()).hexdigest()}

    t = core.SendTask(b_target_ip, b_target_port, "电脑-乙", paths=[big, small])
    t.start()
    t.join(60)
    report("发送线程正常结束（ack 回发已修复）", not t.is_alive())
    a.done_event.wait(30)
    time.sleep(0.5)
    ok_md5 = True
    for name, want in src_md5.items():
        dst = os.path.join(a.save_dir, name)
        if not os.path.exists(dst):
            ok_md5 = False
            break
        got = hashlib.md5(open(dst, "rb").read()).hexdigest()
        if got != want:
            ok_md5 = False
    report("文件传输 + MD5 校验", ok_md5,
           "接收目录: %s" % sorted(os.listdir(a.save_dir)))
    report("接收完成回调", a.dones and a.dones[-1][0], str(a.dones[-1]) if a.dones else "")

    # 5. 发送端状态分阶段（构造即写入，不出现“准备中”）
    t2 = core.SendTask("127.0.0.1", a.server.port, "电脑-乙", text="状态检查")
    st = t2.progress.get(t2.msg_id, {}).get("state")
    report("构造后立即有状态（非准备中）", st == "连接中…", str(st))

    # 6. 未设置保存目录：文件传输拒收并触发设置引导（文字消息不落盘，不受影响）
    c = Inst("丙", no_dir=True)
    time.sleep(0.5)
    t3 = core.SendTask("127.0.0.1", c.server.port, "电脑-乙", paths=[small])
    t3.start()
    t3.join(10)
    time.sleep(0.5)
    st3 = t3.progress.get(t3.msg_id, {}).get("state") or ""
    report("未设目录时发送端收到拒绝", (not t3.is_alive()) and ("拒绝" in st3), st3)
    report("接收端提示引导设置", c.need_setup == [True]
           and c.dones and not c.dones[-1][0], str(c.dones))
    c.close()

    # 7. 加密传输：正确验证码 → 成功且内容一致
    t4 = core.SendTask(b_target_ip, b_target_port, "电脑-乙", paths=[big],
                       encrypted=True, code="123456", tls_port=a.server.tls_port)
    t4.start()
    t4.join(120)
    report("加密传输线程正常结束", not t4.is_alive())
    report("加密传输接收端校验通过", a.dones and a.dones[-1][0],
           str(a.dones[-1]) if a.dones else "")

    # 8. 加密传输：错误验证码 → 服务端 HMAC 校验失败拒绝
    t5 = core.SendTask(b_target_ip, b_target_port, "电脑-乙", paths=[small],
                       encrypted=True, code="999999", tls_port=a.server.tls_port)
    t5.start()
    t5.join(30)
    st5 = t5.progress.get(t5.msg_id, {}).get("state") or ""
    report("错误验证码导致传输中止", (not t5.is_alive()) and ("❌" in st5), st5)
    report("接收端提示验证码错误", a.dones and ("验证码错误" in a.dones[-1][1]),
           str(a.dones[-1]) if a.dones else "")

    # 4b. 多文件并行传输：3 个文件应并行收到且内容一致
    f3 = os.path.join(src_dir, "并行测试.dat")
    with open(f3, "wb") as f:
        f.write(bytes(random.getrandbits(8) for _ in range(2 * 1024 * 1024)))
    before = set(os.listdir(a.save_dir))
    t6 = core.SendTask(b_target_ip, b_target_port, "电脑-乙", paths=[big, small, f3])
    t6.start()
    t6.join(120)
    report("并行传输线程正常结束", not t6.is_alive())
    report("并行传输接收端校验通过", a.dones and a.dones[-1][0],
           str(a.dones[-1]) if a.dones else "")
    md5_src = hashlib.md5(open(f3, "rb").read()).hexdigest()
    dst3 = os.path.join(a.save_dir, "并行测试.dat")
    report("并行传输文件落盘且 MD5 一致", os.path.exists(dst3)
           and hashlib.md5(open(dst3, "rb").read()).hexdigest() == md5_src)

    # 8b. 发送端暂停后取消：接收端清理半成品（1GB 保证取消落在传输中）
    big2 = os.path.join(src_dir, "取消测试.bin")
    with open(big2, "wb") as f:
        f.write(os.urandom(1024 * 1024 * 1024))
    before_files = set(os.listdir(a.save_dir))
    t7 = core.SendTask(b_target_ip, b_target_port, "电脑-乙", paths=[big2])
    t7.start()
    # 等传输真正开始（accept 已返回、UDP 信令端口已交换、数据已在流动）
    # ——避免取消落在“等待确认”阶段导致信令未达、接收端走保留分支
    for _ in range(100):
        if (t7.progress.get(t7.msg_id, {}).get("sent") or 0) > 0:
            break
        time.sleep(0.1)
    time.sleep(0.3)          # 让并行子连接也建立
    t7.pause()
    time.sleep(0.5)
    t7.cancel()
    t7.join(30)
    report("取消后线程结束", not t7.is_alive())
    st7 = t7.progress.get(t7.msg_id, {}).get("state") or ""
    report("取消任务状态显示", ("⏹" in st7) or ("取消" in st7), st7)
    after_files = set(os.listdir(a.save_dir))
    after_files = {f for f in after_files if not f.startswith(".")}   # 排除续传清单等隐藏文件
    report("发送端取消后接收端无残留", wait_clean(a.save_dir, before_files),
           "残留: %s" % (after_files - before_files))

    # 8c. 接收端主动取消：发送端中止，无残留
    t8 = core.SendTask(b_target_ip, b_target_port, "电脑-乙", paths=[big2])
    t8.start()
    for _ in range(100):
        if (t8.progress.get(t8.msg_id, {}).get("sent") or 0) > 0:
            break
        time.sleep(0.1)
    time.sleep(0.2)
    a.server.cancel_recv()
    t8.join(30)
    st8 = t8.progress.get(t8.msg_id, {}).get("state") or ""
    report("接收端取消后发送端中止", (not t8.is_alive()) and ("❌" in st8), st8)
    after2 = set(os.listdir(a.save_dir))
    after2 = {f for f in after2 if not f.startswith(".")}
    report("接收端取消无残留", wait_clean(a.save_dir, before_files),
           "残留: %s" % (after2 - before_files))
    os.remove(big2)

    # 9a. 长时间暂停不中断（UDP 暂停/继续信令 + 暂停期无超时）
    big3 = os.path.join(src_dir, "暂停测试.bin")
    with open(big3, "wb") as f:
        f.write(os.urandom(300 * 1024 * 1024))
    md5_3 = hashlib.md5(open(big3, "rb").read()).hexdigest()
    before3 = set(os.listdir(a.save_dir))
    t9 = core.SendTask(b_target_ip, b_target_port, "电脑-乙", paths=[big3])
    t9.start()
    time.sleep(0.4)
    t9.pause()
    time.sleep(5.0)          # 暂停 5 秒（远超旧版无信令时的担心；验证链路不中断）
    t9.resume()
    t9.join(120)
    report("暂停 5 秒后继续传输完成", not t9.is_alive())
    dst3 = os.path.join(a.save_dir, "暂停测试.bin")
    report("暂停恢复后内容一致", os.path.exists(dst3)
           and hashlib.md5(open(dst3, "rb").read()).hexdigest() == md5_3)
    report("暂停恢复回调正常", a.dones and a.dones[-1][0],
           str(a.dones[-1]) if a.dones else "")
    os.remove(big3)

    # 9b. 单大文件分段并行（128MB → 3 连接 3 段）
    big4 = os.path.join(src_dir, "分段测试.bin")
    with open(big4, "wb") as f:
        f.write(os.urandom(128 * 1024 * 1024))
    md5_4 = hashlib.md5(open(big4, "rb").read()).hexdigest()
    t10 = core.SendTask(b_target_ip, b_target_port, "电脑-乙", paths=[big4])
    t10.start()
    t10.join(120)
    report("分段传输线程正常结束", not t10.is_alive())
    dst4 = os.path.join(a.save_dir, "分段测试.bin")
    report("分段传输文件完整且 MD5 一致", os.path.exists(dst4)
           and hashlib.md5(open(dst4, "rb").read()).hexdigest() == md5_4)
    report("分段传输回调含并行标记", a.dones and a.dones[-1][0] and ("并行" in a.dones[-1][1]),
           str(a.dones[-1]) if a.dones else "")
    os.remove(big4)

    # 9c. 断点续传（预置半成品 + 清单 → 自动续传到完整）
    rn = "续传测试.bin"
    total_len = 32 * 1024 * 1024
    cut = 12 * 1024 * 1024
    src_full = os.path.join(src_dir, rn)
    full_data = os.urandom(total_len)
    with open(src_full, "wb") as f:
        f.write(full_data)
    md5_5 = hashlib.md5(full_data).hexdigest()
    part = os.path.join(a.save_dir, rn)
    with open(part, "wb") as f:
        f.write(full_data[:cut])
    core.save_resume(a.save_dir, {"0:%s" % rn: {"path": part, "size": total_len,
                                                "offset": cut, "ts": time.time()}})
    t11 = core.SendTask(b_target_ip, b_target_port, "电脑-乙", paths=[src_full])
    t11.start()
    t11.join(120)
    report("续传传输线程正常结束", not t11.is_alive())
    report("续传文件 MD5 一致", os.path.exists(part)
           and hashlib.md5(open(part, "rb").read()).hexdigest() == md5_5)
    note5 = a.dones[-1][1] if a.dones else ""
    report("续传回调提示续传", a.dones and a.dones[-1][0] and ("续传" in note5), note5)
    report("续传后清单已清空", not core.load_resume(a.save_dir))
    os.remove(src_full)

    # 9d. 发送方取消时接收方弹窗自动结束（hold 实例不响应确认）
    h = Inst("己", hold=True)
    time.sleep(0.5)
    small2 = os.path.join(src_dir, "弹窗取消测试.txt")
    with open(small2, "w", encoding="utf-8") as f:
        f.write("cancel test " * 100)
    t12 = core.SendTask("127.0.0.1", h.server.port, "电脑-乙", paths=[small2])
    t12.start()
    time.sleep(0.8)          # 弹窗已出，用户未响应
    t12.cancel()
    t12.join(20)
    report("弹窗期取消发送端结束", not t12.is_alive())
    st12 = t12.progress.get(t12.msg_id, {}).get("state") or ""
    report("弹窗期取消发送端状态", ("⏹" in st12) or ("取消" in st12), st12)
    if not h.dones:
        time.sleep(3)
    if not h.dones:
        import faulthandler
        print("==== 9d 接收端无回调，线程栈 ====")
        faulthandler.dump_traceback()
    report("弹窗期取消接收端已中止", h.dones and ("已取消" in h.dones[-1][1]),
           str(h.dones[-1]) if h.dones else "")
    h.close()

    # 9e. 传输历史记录
    hist = core.load_history()
    report("传输历史已记录", len(hist) > 0 and ("direction" in hist[0]) and ("result" in hist[0]),
           "共 %d 条，最新: %s" % (len(hist), hist[0].get("direction") if hist else ""))

    # 9f. 广播回执：对端发现包到达本机时回单播，对端据此反向发现本机
    #     （模拟双网卡主机场景：其广播走默认路由网卡到不了对端热点网段，
    #      只能被动收到对端广播，回执让双方互认）
    #     使用独立端口实例，避开同机多实例 54545 单播投递竞争（测试环境特有）
    import json as _json
    import socket as _sockmod
    c9 = core.DiscoveryService("id-replier", "电脑-回执", 54599, 0,
                               port=core.DISCOVER_PORT + 50)
    c9.start()
    time.sleep(0.5)
    rep = _sockmod.socket(_sockmod.AF_INET, _sockmod.SOCK_DGRAM)
    rep.settimeout(4.0)
    rep.bind(("127.0.0.1", 0))
    disc_pkt = core.MAGIC + _json.dumps(
        {"id": "id-prober", "name": "探测者", "tcp": 54601, "tls": 0,
         "ip": "127.0.0.1", "t": "d"}, ensure_ascii=False)
    rep.sendto(disc_pkt.encode("utf-8"), ("127.0.0.1", core.DISCOVER_PORT + 50))
    info = {}
    got_reply = False
    reply_ok = False
    try:
        data, raddr = rep.recvfrom(65535)
        got_reply = True
        info = _json.loads(data[len(core.MAGIC):].decode("utf-8"))
        reply_ok = (info.get("id") == "id-replier" and info.get("t") == "r"
                    and int(info.get("tcp") or 0) == 54599)
    except _sockmod.timeout:
        pass
    rep.close()
    report("收到广播回执（单播互通）", got_reply and reply_ok,
           "" if reply_ok else (str(info) if got_reply else "未收到回执"))
    report("发现包正常入表", any(d.id == "id-prober" for d in c9.alive()))

    # 回执不应再触发回执（防乒乓）：发送 t=r 报文后短窗口内应无任何回包
    rep2 = _sockmod.socket(_sockmod.AF_INET, _sockmod.SOCK_DGRAM)
    rep2.settimeout(1.2)
    rep2.bind(("127.0.0.1", 0))
    r_pkt = core.MAGIC + _json.dumps(
        {"id": "id-prober", "name": "探测者", "tcp": 54601, "tls": 0,
         "ip": "127.0.0.1", "t": "r"}, ensure_ascii=False)
    rep2.sendto(r_pkt.encode("utf-8"), ("127.0.0.1", core.DISCOVER_PORT + 50))
    no_pingpong = False
    try:
        rep2.recvfrom(65535)
    except _sockmod.timeout:
        no_pingpong = True
    rep2.close()
    c9.stop()
    report("回执不触发回执（无乒乓）", no_pingpong)

    # 9g. 手机网页互传：token 校验 / 上传落盘 / 共享下载
    import json as _j2
    import urllib.request as _u2
    import web as core_web
    web_upds = []
    ws = core_web.WebShareServer(a.cfg, {
        "on_recv_update": lambda mid, info: web_upds.append(("update", mid, info)),
        "on_recv_done": lambda mid, ok, note: web_upds.append(("done", mid, ok, note)),
    })
    ws.start()
    for _ in range(50):        # 等待线程内绑定完成（实测约 0.5~1s）
        if ws.port > 0:
            break
        time.sleep(0.1)
    time.sleep(0.2)
    base = "http://127.0.0.1:%d" % ws.port

    def _get(path):
        try:
            r = _u2.urlopen(base + path, timeout=5)
            return r.getcode(), r.read()
        except Exception as e:
            code = getattr(e, "code", None)
            return code, (e.read() if hasattr(e, "read") else str(e).encode())

    c_no, _ = _get("/?t=wrongtoken")
    c_bad, _ = _get("/list")
    c_ok, page = _get("/?t=" + ws.token)
    report("网页服务 token 校验", c_no == 403 and c_bad == 403 and c_ok == 200
           and "手机互传".encode() in page,
           "no=%s bad=%s ok=%s" % (c_no, c_bad, c_ok))

    # 上传两个文件（含中文文件名），MD5 对照
    d1 = os.urandom(256 * 1024)
    d2 = "网页上传中文内容测试 ✓\n".encode("utf-8") * 100
    mp = (b"--BNDBND\r\n"
          b'Content-Disposition: form-data; name="file"; filename="web A.bin"\r\n'
          b"Content-Type: application/octet-stream\r\n\r\n") + d1 + \
         (b"\r\n--BNDBND\r\n"
          b'Content-Disposition: form-data; name="file"; filename="\xe4\xb8\xad\xe6\x96\x87 \xe4\xb8\x8a\xe4\xbc\xa0.txt"\r\n\r\n') + d2 + \
         b"\r\n--BNDBND--\r\n"
    req = _u2.Request(base + "/up?t=" + ws.token, data=mp, method="POST")
    req.add_header("Content-Type", "multipart/form-data; boundary=BNDBND")
    r = _u2.urlopen(req, timeout=10)
    resp = _j2.loads(r.read().decode("utf-8"))
    f1 = os.path.join(a.save_dir, "web A.bin")
    f2 = os.path.join(a.save_dir, "中文 上传.txt")
    ok_up = (resp.get("ok") and len(resp.get("files") or []) == 2
             and os.path.isfile(f1) and os.path.isfile(f2)
             and hashlib.md5(open(f1, "rb").read()).hexdigest() == hashlib.md5(d1).hexdigest()
             and open(f2, "rb").read() == d2)
    report("网页上传落盘 + MD5（含中文文件名）", ok_up,
           str(resp.get("files"))[:120])
    report("网页上传回调到任务列表", any(x[0] == "done" and x[2] for x in web_upds),
           str(web_upds)[:120])

    # 重名再次上传 → 自动改名 (1)
    req2 = _u2.Request(base + "/up?t=" + ws.token, data=mp, method="POST")
    req2.add_header("Content-Type", "multipart/form-data; boundary=BNDBND")
    _u2.urlopen(req2, timeout=10)
    f1b = os.path.join(a.save_dir, "web A (1).bin")
    report("网页上传重名自动改名", os.path.isfile(f1b))

    # 共享 + 下载
    ws.add_shared([f1, f2])
    c_l, lb = _get("/list?t=" + ws.token)
    lst = _j2.loads(lb.decode("utf-8"))
    c_d, db = _get("/dl?t=" + ws.token + "&i=0")
    ok_dl = (c_l == 200 and len(lst.get("files")) == 2
             and c_d == 200 and db == d1)
    report("网页共享清单 + 下载内容一致", ok_dl,
           "list=%s dl=%s len=%d" % (c_l, c_d, len(db)))
    c_x, _ = _get("/dl?t=" + ws.token + "&i=99")
    report("越界下载返回 404", c_x == 404)

    ws.stop()
    time.sleep(0.3)

    # 10. 大小格式化
    report("fmt_size", core.fmt_size(110 * 1024 * 1024) == "110.0 MB",
           core.fmt_size(110 * 1024 * 1024))

    a.close()
    b.close()
    print("\n===== 测试结果：%s =====" % ("全部通过 ✅" if OK else "存在失败 ❌"))
    sys.exit(0 if OK else 1)


if __name__ == "__main__":
    main()
