# -*- coding: utf-8 -*-
"""双实例 UI 集成测试：加密按钮状态机 + 完整加密传输流程（模拟用户操作）"""
import os
import shutil
import sys
import time
import hashlib

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["QT_QPA_PLATFORM"] = "offscreen:fontdir=C:/Windows/Fonts"
sys.path.insert(0, HERE)

import core
import ui
import PyQt5
_plugins = os.path.join(os.path.dirname(PyQt5.__file__), "Qt5", "plugins")
os.environ["QT_PLUGIN_PATH"] = _plugins
os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = os.path.join(_plugins, "platforms")

from PyQt5.QtWidgets import QApplication, QDialog
from PyQt5.QtCore import Qt

OK = True


def report(name, ok, extra=""):
    global OK
    print(("[PASS] " if ok else "[FAIL] ") + name + ("  " + extra if extra else ""), flush=True)
    if not ok:
        OK = False


app = QApplication([])
from PyQt5.QtGui import QFont, QFontDatabase
for _f in (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simsun.ttc"):
    if os.path.exists(_f):
        _fid = QFontDatabase.addApplicationFont(_f)
        _fams = QFontDatabase.applicationFontFamilies(_fid)
        if _fams:
            app.setFont(QFont(_fams[0], 10))
            break


# 自动应答所有模态对话框（模拟真人点击）
def fake_exec(self):
    if hasattr(self, "code_edit"):
        self.code_edit.setText(win_a.last_enc_code)   # 接收端输入发送端生成的验证码
    self.accept()
    return QDialog.Accepted


QDialog.exec_ = fake_exec

win_a = ui.MainWindow()
win_b = ui.MainWindow()
win_a.config.device_name = "测试A"
win_a.discovery.set_name("测试A")
win_b.config.device_name = "测试B"
win_b.discovery.set_name("测试B")
win_a.refresh_header()
win_b.refresh_header()
recv_dir_b = os.path.join(HERE, "ui_recv_B")
# 清理上一轮残留，避免 dst 存在性检查出现假阳性
if os.path.isdir(recv_dir_b):
    shutil.rmtree(recv_dir_b, ignore_errors=True)
os.makedirs(recv_dir_b)
win_b.config.save_dir = recv_dir_b
app.processEvents()

report("版本号显示在标题栏", "v%s" % core.APP_VERSION in win_a.windowTitle(),
       win_a.windowTitle())

# 等 A 发现 B（同机广播环回）
deadline = time.time() + 12
found = False
while time.time() < deadline and not found:
    app.processEvents()
    for d in win_a.discovery.alive():
        if d.name == "测试B":
            found = True
    if not found:
        time.sleep(0.3)
report("A 发现设备 B", found)

# 模拟用户点击设备列表中的 B
picked = False
for i in range(win_a.device_list.count()):
    it = win_a.device_list.item(i)
    if it.data(Qt.UserRole + 2) == "测试B":
        win_a.device_list.setCurrentItem(it)
        win_a.on_device_clicked(win_a.device_list.currentIndex())
        picked = True
        break
app.processEvents()
report("B 已选中为发送目标", picked and "测试B" in win_a.target_label.text(),
       win_a.target_label.text())

# 模拟拖入文件
src = os.path.join(HERE, "ui_test_src.txt")
with open(src, "w", encoding="utf-8") as f:
    f.write("加密UI链路测试 SIGNAL-TLS-VERIFY " * 8000)
win_a.selected_paths = [src]
win_a.update_path_hint()
app.processEvents()

# ★ 用户问题的直接答案：拖入文件后加密按钮是否可点
report("【关键】发送文件按钮可点", win_a.btn_send_files.isEnabled())
report("【关键】加密传输按钮可点", win_a.btn_send_enc.isEnabled(),
       "文本=%s" % win_a.btn_send_enc.text())

# 执行加密发送（对话框已被自动应答）
win_a.send_encrypted()
app.processEvents()

# 等 B 端收到文件（TLS + 验证码全链路）
dst = os.path.join(recv_dir_b, os.path.basename(src))
deadline = time.time() + 40
dst_ok = False
while time.time() < deadline and not dst_ok:
    app.processEvents()
    if os.path.exists(dst):
        if os.path.getsize(dst) == os.path.getsize(src):
            dst_ok = True
    time.sleep(0.3)
report("B 端通过 TLS+验证码收到文件", dst_ok, dst)
if dst_ok:
    got = hashlib.md5(open(dst, "rb").read()).hexdigest()
    want = hashlib.md5(open(src, "rb").read()).hexdigest()
    report("内容 MD5 一致", got == want)
    # 给 A 端留出接收 ok 回发与状态更新的时间（B 落盘 ≠ A 已完成）
    time.sleep(0.8)
    app.processEvents()

states = [str(v.get("state")) for v in win_a.progress.values()]
report("A 侧任务完成状态", any("✅" in s for s in states), str(states))

# 拖入后未选设备时点加密按钮 → 应有明确提示（弹窗被自动应答）
win_a.selected_paths = []
win_a.update_path_hint()
app.processEvents()
report("清空后加密按钮复位（灰）", not win_a.btn_send_enc.isEnabled())

win_a.discovery.stop()
win_a.server.stop()
win_b.discovery.stop()
win_b.server.stop()
app.processEvents()
print("\n===== 双实例 UI 测试：%s =====" % ("全部通过 ✅" if OK else "存在失败 ❌"))
sys.exit(0 if OK else 1)
