# -*- coding: utf-8 -*-
"""Signal 快传 - UI 冒烟测试 + 界面截图（离屏渲染）"""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen:fontdir=C:/Windows/Fonts"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import core
import hotspot

import PyQt5
_qt_plugins = os.path.join(os.path.dirname(PyQt5.__file__), "Qt5", "plugins")
os.environ["QT_PLUGIN_PATH"] = _qt_plugins
os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = os.path.join(_qt_plugins, "platforms")

from PyQt5.QtWidgets import QApplication

import ui

print("hotspot.hosted_supported() =", hotspot.hosted_supported())
print("hotspot.status() =", hotspot.status())

app = QApplication([])

# offscreen 平台不加载系统字体：显式注入中文字体用于文字渲染验证
from PyQt5.QtGui import QFont, QFontDatabase
for _f in (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simsun.ttc",
           r"C:\Windows\Fonts\simhei.ttf", r"C:\Windows\Fonts\simfang.ttf"):
    if os.path.exists(_f):
        _fid = QFontDatabase.addApplicationFont(_f)
        _fams = QFontDatabase.applicationFontFamilies(_fid)
        if _fams:
            print("font loaded:", _fams[0], flush=True)
            app.setFont(QFont(_fams[0], 10))
            break

win = ui.MainWindow()
win.resize(980, 660)
win.show()
app.processEvents()

# 塞两个假设备让列表有内容（仅测试渲染）
from core import Device
import time
now = time.time()
with win.discovery.lock:
    win.discovery.devices["fake1"] = Device("fake1", "工位-互联网机", "192.168.1.23", 54546, 54566, now + 999)
    win.discovery.devices["fake2"] = Device("fake2", "工位-内网机", "10.20.30.44", 54547, 54567, now + 999)
win.refresh_devices()
app.processEvents()

# 塞两条传输任务（一条进行中，一条完成）
win._add_task_row("demo1", "↑ 发送", "工位-内网机", "项目方案.pptx；合同扫描件.pdf")
win.progress["demo1"] = {"direction": "send", "sender": "本机", "total": 100 * 1024 * 1024,
                         "sent": 62 * 1024 * 1024, "speed": 112 * 1024 * 1024,
                         "state": "发送中", "files": []}
win._add_task_row("demo2", "↓ 接收", "工位-互联网机", "照片.zip")
win.progress["demo2"] = {"direction": "recv", "sender": "工位-互联网机", "total": 10 * 1024 * 1024,
                         "sent": 10 * 1024 * 1024, "speed": 0.0,
                         "state": "✅ 全部接收完成，共 1 个文件，MD5 校验通过", "files": []}
win.refresh_progress()
app.processEvents()

shot = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui_screenshot.png")
win.grab().save(shot)
print("截图已保存:", shot)

# 对话框实例化冒烟
hs = ui.HotspotDialog(win, lambda: None)
st = ui.SettingsDialog(win)
cf = ui.ConfirmDialog(win, "测试设备", [{"name": "a.txt", "size": 123}])
print("对话框实例化 OK")
win.discovery.stop()
win.server.stop()
app.processEvents()
print("UI 冒烟测试通过 ✅")
