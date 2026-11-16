# -*- coding: utf-8 -*-
"""
Signal 快传 - 一键热点模块
优先使用 netsh 承载网络（Win7 可用）；网卡不支持时引导打开系统"移动热点"。
"""
import ctypes
import os
import random
import string
import subprocess

SUGGEST_IP = "192.168.137.1"   # Windows 承载网络默认网关 IP


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _netsh(args):
    try:
        p = subprocess.run(["netsh"] + args, capture_output=True, timeout=20)
        return (p.stdout or b"").decode("gbk", "replace")
    except Exception:
        return ""


def hosted_supported():
    """网卡是否支持承载网络（中英文系统都尝试匹配）"""
    out = _netsh(["wlan", "show", "drivers"])
    if not out:
        return False
    for line in out.splitlines():
        low = line.lower()
        if ("hosted network" in low and ("yes" in low or "是" in line)) \
                or ("承载的网络" in line and "是" in line):
            return True
    return False


def _run_elevated(cmd_args):
    """弹 UAC 执行命令；已具备管理员权限则直接执行"""
    if is_admin():
        try:
            subprocess.run(["cmd", "/c"] + cmd_args, capture_output=True, timeout=30)
            return True
        except Exception:
            return False
    ret = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", "cmd.exe", "/c " + " ".join(cmd_args), None, 0)
    return ret > 32


def start_hotspot(ssid, key):
    """启动承载网络热点，返回 (ok, message)"""
    setup = 'netsh wlan set hostednetwork mode=allow ssid="%s" key="%s"' % (ssid, key)
    start = 'netsh wlan start hostednetwork'
    ok1 = _run_elevated(["/c", setup])
    if not ok1:
        return False, "需要管理员权限，请在弹出的 UAC 窗口点“是”"
    ok2 = _run_elevated(["/c", start])
    if not ok2:
        return False, "启动热点失败，请检查无线网卡是否支持"
    # 轮询确认状态
    for _ in range(6):
        import time
        time.sleep(1)
        st = status()
        if st.get("running"):
            return True, "热点已启动"
    st = status()
    if st.get("running"):
        return True, "热点已启动"
    return False, "热点未就绪（状态：%s）" % st.get("state", "未知")


def status():
    """查询承载网络状态，返回 {"running":bool,"state":str,"ssid":str}"""
    out = _netsh(["wlan", "show", "hostednetwork"])
    state, ssid = "", ""
    for line in out.splitlines():
        if "状态" in line or "State" in line.lower():
            state = line.split(":", 1)[-1].strip()
        if "SSID 名称" in line or "SSID name" in line.lower():
            ssid = line.split(":", 1)[-1].strip().strip('"')
    return {"running": ("已启动" in state or "started" in state.lower()),
            "state": state, "ssid": ssid}


def gen_key():
    """生成 8 位易读密码（无易混淆字符）"""
    chars = "abcdefghjkmnpqrstuvwxyz23456789"
    return "".join(random.choice(chars) for _ in range(8))


def open_system_hotspot():
    """打开系统自带移动热点设置页（Win10/11）"""
    try:
        os.startfile("ms-settings:network-wifihotspot")
        return True
    except Exception:
        return False


def add_firewall_rules():
    """添加入站放行规则：TCP 54546-54565（传输）+ UDP 54545（发现）+ UDP 54544（暂停/取消通知）。
    弹 UAC 提权执行，返回是否成功启动命令。"""
    import sys
    if getattr(sys, "frozen", False):
        prog = sys.executable
        prog_rules = ('netsh advfirewall firewall delete rule name="Signal快传-程序" >nul 2>&1 & '
                      'netsh advfirewall firewall add rule name="Signal快传-程序" '
                      'dir=in action=allow program="%s" enable=yes & ' % prog)
    else:
        prog_rules = ""
    cmd = (prog_rules +
           'netsh advfirewall firewall delete rule name="Signal快传-TCP" >nul 2>&1 & '
           'netsh advfirewall firewall delete rule name="Signal快传-UDP" >nul 2>&1 & '
           'netsh advfirewall firewall delete rule name="Signal快传-UDP2" >nul 2>&1 & '
           'netsh advfirewall firewall add rule name="Signal快传-TCP" '
           'dir=in action=allow protocol=TCP localport=54546-54565 & '
           'netsh advfirewall firewall add rule name="Signal快传-UDP" '
           'dir=in action=allow protocol=UDP localport=54545 & '
           'netsh advfirewall firewall add rule name="Signal快传-UDP2" '
           'dir=in action=allow protocol=UDP localport=54544')
    ok = _run_elevated(["/c", cmd])
    try:
        from core import log
        log.info("防火墙放行命令执行结果：%s", ok)
    except Exception:
        pass
    return ok
