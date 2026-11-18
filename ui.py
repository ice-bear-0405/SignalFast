# -*- coding: utf-8 -*-
"""
Signal 快传 - 主界面（PyQt5）
深色主题 / 拖拽发送 / 实时进度 / 托盘常驻 / 一键热点
"""
import os
import subprocess
import sys
import time
import uuid

from PyQt5.QtCore import Qt, QTimer, QPointF, QSize, pyqtSignal, QObject
from PyQt5.QtGui import (QBrush, QColor, QFont, QIcon, QPainter, QPixmap,
                         QPolygonF)
from PyQt5.QtWidgets import (QAbstractItemView, QApplication, QCheckBox,
                             QDialog, QFileDialog, QFormLayout, QFrame,
                             QHBoxLayout, QLabel, QLineEdit, QListWidget,
                             QListWidgetItem, QMainWindow, QMenu,
                             QMessageBox, QProgressBar, QPushButton,
                             QSystemTrayIcon, QTextBrowser, QTreeWidget, QTreeWidgetItem,
                             QVBoxLayout, QWidget, QAction)

import core
import hotspot
import mcp as _mcp
import web as _web

# ---------------------------------------------------------------- 全局样式

QSS = """
* { font-family: "Microsoft YaHei UI"; font-size: 13px; color: #e6edf7; }
QMainWindow, QDialog { background: #0d1321; }
#card { background: #151f33; border-radius: 12px; }
#title { font-size: 17px; font-weight: bold; color: #7dd3fc; }
#hint { color: #8b9bb8; font-size: 12px; }
#dropzone { border: 2px dashed #31446e; border-radius: 12px; background: #121a2e; color: #8b9bb8; }
#dropzone:hover { border-color: #22d3ee; color: #22d3ee; }
QPushButton { background: #1d2a45; border: 1px solid #2a3a5e; border-radius: 8px;
              padding: 6px 14px; }
QPushButton:hover { border-color: #22d3ee; color: #22d3ee; }
QPushButton:disabled { color: #55688f; border-color: #22304f; }
QPushButton#primary { background: #0891b2; border: none; color: #ffffff; font-weight: bold; }
QPushButton#primary:hover { background: #22d3ee; color: #06222b; }
QLineEdit, QTextEdit { background: #0f1830; border: 1px solid #2a3a5e; border-radius: 8px; padding: 6px 10px; }
QLineEdit:focus, QTextEdit:focus { border-color: #22d3ee; }
QListWidget, QTreeWidget { background: #101828; border: 1px solid #22304f; border-radius: 10px; }
QListWidget::item, QTreeWidget::item { padding: 4px; }
QListWidget::item:selected, QTreeWidget::item:selected { background: #15304a; }
#devList::item { border: 1px solid transparent; border-radius: 10px; margin: 4px 5px; }
#devList::item:hover { background: #16273f; }
#devList::item:selected { background: #163452; border: 1px solid #22d3ee; }
#devName { font-size: 14px; font-weight: bold; color: #e6edf7; }
#devIp { font-size: 11px; color: #8b9bb8; }
#devBadge { background: #0f2f22; color: #22c55e; border-radius: 9px;
            padding: 2px 10px; font-size: 11px; }
#hint2 { color: #7dd3fc; font-size: 12px; }
#target { font-size: 13px; color: #7dd3fc; font-weight: bold; }
#speed { font-size: 15px; font-weight: bold; color: #22d3ee; }
#codeBig { font-size: 26px; font-weight: bold; color: #22d3ee;
           letter-spacing: 8px; qproperty-alignment: AlignCenter; }
QHeaderView::section { background: #16223c; border: none; padding: 6px; color: #8b9bb8; }
QProgressBar { background: #0f1830; border: 1px solid #22304f; border-radius: 7px;
               text-align: center; color: #e6edf7; height: 14px; }
QProgressBar::chunk { background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                      stop:0 #0891b2, stop:1 #22d3ee); border-radius: 6px; }
QMenu { background: #16223c; border: 1px solid #2a3a5e; }
QMenu::item:selected { background: #15304a; }
QLabel#dot { font-size: 12px; }
"""


def make_app_icon(active=False):
    """代码绘制应用图标：深色圆角底 + 青色闪电；active=True 时叠加绿色动态圆点"""
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor("#0891b2"))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(2, 2, 60, 60, 16, 16)
    p.setBrush(QColor("#e6fbff"))
    poly = QPolygonF([QPointF(36, 10), QPointF(20, 36), QPointF(30, 36),
                      QPointF(26, 54), QPointF(44, 28), QPointF(33, 28)])
    p.drawPolygon(poly)
    if active:
        p.setBrush(QColor("#22c55e"))
        p.drawEllipse(QPointF(52, 12), 7, 7)
    p.end()
    return QIcon(pm)


def set_autostart(enable):
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Run",
                             0, winreg.KEY_SET_VALUE)
        if enable:
            exe = sys.executable
            winreg.SetValueEx(key, "Signal快传", 0, winreg.REG_SZ, exe)
        else:
            try:
                winreg.DeleteValue(key, "Signal快传")
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------- 信号桥

class Bridge(QObject):
    incoming_request = pyqtSignal(object)      # _ReplyBox(含 sender/files)
    text_received = pyqtSignal(str, str)       # sender, text
    recv_update = pyqtSignal(str, dict)        # msg_id, info
    recv_done = pyqtSignal(str, bool, str)     # msg_id, ok, note
    need_setup = pyqtSignal()                  # 未设置保存目录，引导设置
    task_started = pyqtSignal(str, str, str, str, bool)   # MCP 发起：mid/direction/peer/content/has_ops


# ---------------------------------------------------------------- 接收确认

class ConfirmDialog(QDialog):
    def __init__(self, parent, sender, files, need_code=False):
        QDialog.__init__(self, parent)
        self.setWindowTitle("收到加密文件" if need_code else "收到文件请求")
        self.need_code = need_code
        self.code = ""
        self.setFixedSize(420, 300 if need_code else 260)
        total = sum(int(f.get("size") or 0) for f in files)
        v = QVBoxLayout(self)
        title = QLabel("%s 想向你加密发送 %d 个文件（%s）\n内容将以 AES-256-GCM 端到端加密"
                       % (sender, len(files), core.fmt_size(total)) if need_code
                       else "%s 想向你发送 %d 个文件（%s）" % (sender, len(files), core.fmt_size(total)))
        title.setWordWrap(True)
        v.addWidget(title)
        lst = QListWidget()
        for f in files[:8]:
            lst.addItem("%s（%s）" % (f.get("name"), core.fmt_size(f.get("size") or 0)))
        if len(files) > 8:
            lst.addItem("…… 共 %d 个文件" % len(files))
        v.addWidget(lst)
        if need_code:
            v.addWidget(QLabel("请让对方告知你 6 位验证码，输入后才能解密接收："))
            self.code_edit = QLineEdit()
            self.code_edit.setPlaceholderText("6 位数字验证码")
            v.addWidget(self.code_edit)
        hint = QLabel("保存到：%s" % (parent.config.save_dir if parent.config.save_dir
                                      else "（未设置，请先在设置中选择）"))
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        v.addWidget(hint)
        row = QHBoxLayout()
        ok = QPushButton("接收" if not need_code else "🔒 解密接收")
        ok.setObjectName("primary")
        no = QPushButton("拒绝")
        ok.clicked.connect(self.accept)
        no.clicked.connect(self.reject)
        row.addStretch(1)
        row.addWidget(no)
        row.addWidget(ok)
        v.addLayout(row)

    def accept(self):
        if self.need_code:
            self.code = self.code_edit.text().strip()
            if len(self.code) < 4:
                QMessageBox.warning(self, "需要验证码", "请输入对方告知的验证码，或点“拒绝”）")
                return
        QDialog.accept(self)


# ---------------------------------------------------------------- 热点对话框

class HotspotDialog(QDialog):
    def __init__(self, parent, on_started):
        QDialog.__init__(self, parent)
        self.setWindowTitle("一键热点")
        self.setFixedWidth(420)
        self.on_started = on_started
        v = QVBoxLayout(self)
        v.addWidget(QLabel("没有路由器？让一台电脑开热点，另一台连上后即可互传（无需互联网）。"))
        form = QFormLayout()
        self.ssid_edit = QLineEdit("Signal-快传")
        self.key_edit = QLineEdit(hotspot.gen_key())
        form.addRow("热点名称", self.ssid_edit)
        form.addRow("连接密码", self.key_edit)
        v.addLayout(form)
        self.status_label = QLabel("")
        self.status_label.setObjectName("hint")
        self.status_label.setWordWrap(True)
        v.addWidget(self.status_label)
        row = QHBoxLayout()
        self.btn_start = QPushButton("启动热点")
        self.btn_start.setObjectName("primary")
        self.btn_sys = QPushButton("打开系统热点设置")
        row.addWidget(self.btn_start)
        row.addWidget(self.btn_sys)
        v.addLayout(row)
        tip = QLabel("提示：新网卡（Win10/11 多数）不支持承载网络时，"
                     "请用「打开系统热点设置」一键开启 Windows 自带移动热点。")
        tip.setObjectName("hint")
        tip.setWordWrap(True)
        v.addWidget(tip)
        self.btn_start.clicked.connect(self.start)
        self.btn_sys.clicked.connect(self.open_sys)

    def start(self):
        ssid = self.ssid_edit.text().strip() or "Signal-快传"
        key = self.key_edit.text().strip() or hotspot.gen_key()
        self.status_label.setText("正在启动热点，如弹出 UAC 窗口请点“是”……")
        QApplication.processEvents()
        ok, msg = hotspot.start_hotspot(ssid, key)
        if ok:
            self.status_label.setText("✅ %s\n热点名：%s  密码：%s\n热点电脑 IP 通常为 %s"
                                      % (msg, ssid, key, hotspot.SUGGEST_IP))
            self.on_started()
        else:
            self.status_label.setText("❌ " + msg)

    def open_sys(self):
        if hotspot.open_system_hotspot():
            self.status_label.setText("已打开系统移动热点设置，开启后对方连上即可互传。")
        else:
            self.status_label.setText("当前系统不支持设置页跳转，请在“设置→网络→移动热点”手动开启。")


# ---------------------------------------------------------------- 设置对话框

class HistoryDialog(QDialog):
    """传输历史（最近 200 条，双击打开文件所在文件夹）"""

    def __init__(self, parent):
        QDialog.__init__(self, parent)
        self.setWindowTitle("传输历史")
        self.resize(560, 420)
        v = QVBoxLayout(self)
        self.lst = QListWidget()
        v.addWidget(self.lst)
        hint = QLabel("双击记录可打开文件所在文件夹（仅接收记录有路径）")
        hint.setObjectName("hint")
        v.addWidget(hint)
        self.lst.itemDoubleClicked.connect(self.open_selected)
        self.reload()

    def reload(self):
        self.lst.clear()
        for h in core.load_history():
            kind = "文字" if h.get("kind") == "text" else "%d 个文件" % h.get("count", 0)
            if h.get("kind") == "text":
                content = h.get("content") or ""
                title = "【%s】%s → %s ｜ %s" % ("发送" if h.get("direction") == "send" else "接收",
                                              kind, h.get("peer", ""), content[:24])
            else:
                names = "、".join(h.get("files") or []) or "-"
                title = "【%s】%s → %s ｜ %s%s" % (
                    "发送" if h.get("direction") == "send" else "接收",
                    kind, h.get("peer", ""), names,
                    "（等 %d 个）" % h.get("count", 0) if (h.get("count") or 0) > 5 else "")
            item = QListWidgetItem("%s  ｜  %s  ｜  %s" % (h.get("time", ""), title, h.get("result", "")))
            paths = h.get("paths") or []
            item.setData(Qt.UserRole, paths[0] if paths else "")
            self.lst.addItem(item)
        if not self.lst.count():
            self.lst.addItem("暂无传输记录")

    def open_selected(self, item):
        p = item.data(Qt.UserRole)
        if p and os.path.exists(p):
            try:
                subprocess.Popen(["explorer", "/select,", os.path.normpath(p)])
            except Exception:
                pass


class WebShareDialog(QDialog):
    """手机网页互传：扫码进入 + 共享文件清单管理"""

    def __init__(self, parent):
        QDialog.__init__(self, parent)
        self.setWindowTitle("📱 手机互传")
        self.resize(640, 660)
        mw = parent
        v = QVBoxLayout(self)
        tip = QLabel("手机连接同一网络（Wi-Fi / 本机热点）后，用相机或浏览器扫码进入。\n"
                     "手机可上传文件到电脑接收目录，也可下载下方共享的文件。")
        tip.setWordWrap(True)
        v.addWidget(tip)
        self.qr_row = QHBoxLayout()
        v.addLayout(self.qr_row)
        self.url_hint = QLabel("")
        self.url_hint.setObjectName("hint")
        self.url_hint.setWordWrap(True)
        v.addWidget(self.url_hint)
        v.addWidget(QLabel("电脑 → 手机：共享给手机的文件（手机页面可下载）"))
        self.shared_list = QListWidget()
        self.shared_list.setObjectName("devList")
        v.addWidget(self.shared_list, 1)
        row = QHBoxLayout()
        btn_add = QPushButton("➕ 添加文件")
        btn_remove = QPushButton("移除所选")
        btn_clear = QPushButton("清空")
        btn_add.clicked.connect(self.add_files)
        btn_remove.clicked.connect(self.remove_sel)
        btn_clear.clicked.connect(self.clear_all)
        row.addWidget(btn_add)
        row.addWidget(btn_remove)
        row.addWidget(btn_clear)
        row.addStretch(1)
        v.addLayout(row)
        hint = QLabel("提示：手机端地址含随机令牌，局域网内其他设备无法访问；\n"
                      "热点互传时请扫热点网卡对应的二维码。")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        v.addWidget(hint)
        self.rebuild_qr()
        self.refresh_list()

    def _qr_pixmap(self, text, cell=4):
        try:
            import qrcode
            qr = qrcode.QRCode(border=2)
            qr.add_data(text)
            qr.make(fit=True)
            m = qr.get_matrix()
            n = len(m)
            pm = QPixmap(n * cell, n * cell)
            pm.fill(QColor("#ffffff"))
            p = QPainter(pm)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#111111"))
            for y in range(n):
                for x in range(n):
                    if m[y][x]:
                        p.drawRect(x * cell, y * cell, cell, cell)
            p.end()
            return pm
        except Exception as e:
            core.log.warning("二维码生成失败：%s", e)
            return None

    def rebuild_qr(self):
        mw = self.parent()
        while self.qr_row.count():
            item = self.qr_row.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        ips = _web.local_ips()
        urls = []
        for ip in ips[:3]:   # 最多画 3 个（多网卡场景逐个给出）
            url = mw.web.url_for(ip)
            urls.append((ip, url))
        if not urls:
            self.url_hint.setText("未获取到本机 IP")
            return
        for ip, url in urls:
            box = QVBoxLayout()
            pm = self._qr_pixmap(url)
            if pm:
                lb = QLabel()
                lb.setPixmap(pm)
                lb.setAlignment(Qt.AlignCenter)
                box.addWidget(lb)
            cap = QLabel(ip)
            cap.setObjectName("hint")
            cap.setAlignment(Qt.AlignCenter)
            box.addWidget(cap)
            holder = QWidget()
            holder.setLayout(box)
            self.qr_row.addWidget(holder)
        self.url_hint.setText("地址：" + "    ".join(u for _, u in urls))

    def refresh_list(self):
        mw = self.parent()
        self.shared_list.clear()
        for i, x in enumerate(mw.web.shared):
            self.shared_list.addItem(QListWidgetItem(
                "%s（%s，%s 添加）" % (x["name"], core.fmt_size(x["size"]), x["added"])))

    def add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "选择要共享给手机的文件")
        if not paths:
            return
        mw = self.parent()
        mw.web.add_shared(paths)
        self.refresh_list()

    def remove_sel(self):
        mw = self.parent()
        for item in self.shared_list.selectedItems():
            mw.web.remove_shared(self.shared_list.row(item))
        self.refresh_list()

    def clear_all(self):
        mw = self.parent()
        mw.web.clear_shared()
        self.refresh_list()


class SettingsDialog(QDialog):
    def __init__(self, parent):
        QDialog.__init__(self, parent)
        self.setWindowTitle("设置")
        self.resize(820, 520)
        cfg = parent.config
        outer = QHBoxLayout(self)
        left = QWidget()
        v = QVBoxLayout(left)
        right = QWidget()
        rv = QVBoxLayout(right)
        outer.addWidget(left, 11)
        outer.addWidget(right, 9)
        form = QFormLayout()
        self.name_edit = QLineEdit(cfg.device_name)
        form.addRow("设备名称", self.name_edit)
        dirrow = QHBoxLayout()
        self.dir_edit = QLineEdit(cfg.save_dir)
        self.dir_edit.setPlaceholderText("必填：选择接收文件的保存目录")
        btn = QPushButton("浏览")
        btn.clicked.connect(self.pick_dir)
        dirrow.addWidget(self.dir_edit)
        dirrow.addWidget(btn)
        form.addRow("保存目录", dirrow)
        v.addLayout(form)
        self.auto_chk = QCheckBox("自动接收文件（不再弹窗确认）")
        self.auto_chk.setChecked(cfg.auto_accept)
        v.addWidget(self.auto_chk)
        self.web_chk = QCheckBox("手机网页互传（手机浏览器扫码收发，局域网）")
        self.web_chk.setChecked(cfg.web_enabled)
        v.addWidget(self.web_chk)
        self.startup_chk = QCheckBox("开机自动运行")
        self.startup_chk.setChecked(cfg.autostart)
        v.addWidget(self.startup_chk)
        row2 = QHBoxLayout()
        btn_log = QPushButton("📂 打开日志文件夹")
        btn_log.clicked.connect(self.open_logs)
        btn_fw = QPushButton("🛡 一键放行防火墙")
        btn_fw.clicked.connect(self.fix_firewall)
        btn_hist = QPushButton("📜 传输历史")
        btn_hist.clicked.connect(self.show_history)
        row2.addWidget(btn_log)
        row2.addWidget(btn_fw)
        row2.addWidget(btn_hist)
        row2.addStretch(1)
        v.addLayout(row2)
        fw_hint = QLabel("提示：若对方发送时提示“无法连接”或“等待确认超时”，"
                         "多半是那台电脑的防火墙未放行——请在【对方电脑】上点“一键放行防火墙”。")
        fw_hint.setObjectName("hint")
        fw_hint.setWordWrap(True)
        v.addWidget(fw_hint)
        mcp_sep = QLabel("—")
        mcp_sep.setObjectName("hint")
        v.addWidget(mcp_sep)
        self.mcp_status = QLabel("🤖 MCP 接口：启动中…")
        self.mcp_status.setObjectName("hint")
        self.mcp_status.setWordWrap(True)
        v.addWidget(self.mcp_status)
        mcp_row = QHBoxLayout()
        btn_mcp = QPushButton("📋 复制 MCP 配置")
        btn_mcp.clicked.connect(self.copy_mcp_config)
        mcp_row.addWidget(btn_mcp)
        mcp_row.addStretch(1)
        v.addLayout(mcp_row)
        try:
            if parent.ctrl and parent.ctrl.port:
                self.mcp_status.setText("🤖 MCP 接口：127.0.0.1:%d 运行中（AI 助手可接入，仅限本机）"
                                        % parent.ctrl.port)
        except Exception:
            pass
        rv.addWidget(QLabel("📋 关于 Signal 快传"))
        ver_lb = QLabel("当前版本：v%s" % core.APP_VERSION)
        ver_lb.setObjectName("hint")
        rv.addWidget(ver_lb)
        about = QTextBrowser()
        parts = []
        for ver, items in core.RELEASE_NOTES:
            parts.append("<p><b style='color:#22d3ee'>v%s</b><br>· %s</p>"
                         % (ver, "<br>· ".join(items)))
        about.setHtml("".join(parts))
        rv.addWidget(about, 1)
        row = QHBoxLayout()
        save = QPushButton("保存")
        save.setObjectName("primary")
        row.addStretch(1)
        row.addWidget(save)
        v.addLayout(row)
        save.clicked.connect(self.do_save)

    def pick_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择保存目录", self.dir_edit.text())
        if d:
            self.dir_edit.setText(d)

    def open_logs(self):
        try:
            os.makedirs(core.logs_dir(), exist_ok=True)
            os.startfile(core.logs_dir())
        except Exception as e:
            QMessageBox.warning(self, "失败", "无法打开日志文件夹：%s" % e)

    def fix_firewall(self):
        ok = hotspot.add_firewall_rules()
        if ok:
            QMessageBox.information(self, "完成",
                                    "防火墙放行命令已执行（UAC 弹窗点“是”）：\n"
                                    "· TCP 54546-54565（文件传输）\n"
                                    "· UDP 54545（设备发现）\n"
                                    "· UDP 54544（暂停/取消通知）\n"
                                    "· 本程序自身\n已允许入站连接，请对方电脑也执行一次。")
        else:
            QMessageBox.warning(self, "未执行", "命令未成功启动（可能取消了 UAC）。\n"
                                "也可手动以管理员身份运行命令提示符执行 netsh 命令。")

    def copy_mcp_config(self):
        import json as _json
        mw = self.parent()
        if not (getattr(mw, "ctrl", None) and mw.ctrl.port):
            QMessageBox.warning(self, "未运行", "MCP 接口未就绪，请重启软件后重试。")
            return
        if getattr(sys, "frozen", False):
            cmd = os.path.join(os.path.dirname(sys.executable), "SignalMCP.exe")
            cfg_json = {"mcpServers": {"signal-fast": {"command": cmd, "args": []}}}
        else:
            cmd = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcp.py")
            cfg_json = {"mcpServers": {"signal-fast": {
                "command": sys.executable, "args": [cmd]}}}
        QApplication.clipboard().setText(_json.dumps(cfg_json, ensure_ascii=False, indent=1))
        QMessageBox.information(
            self, "已复制",
            "MCP 配置已复制到剪贴板：\n%s\n\n粘贴到 AI 助手（如 TeleAgent）的 MCP 服务器设置中即可接入。\n"
            "接入后 AI 可查询设备/历史、管理共享，并触发发送（接收端仍需人工确认）。" % _json.dumps(cfg_json, ensure_ascii=False))

    def show_history(self):
        dlg = HistoryDialog(self)
        dlg.exec_()

    def do_save(self):
        mw = self.parent()
        cfg = mw.config
        cfg.device_name = self.name_edit.text().strip() or socket_hostname()
        d = self.dir_edit.text().strip()
        if not d:
            QMessageBox.warning(self, "需要设置", "请先选择文件保存目录（接收的文件将存到这里）")
            return
        if not os.path.isdir(d):
            ret = QMessageBox.question(self, "目录不存在",
                                       "目录不存在：\n%s\n\n是否现在创建该目录？" % d,
                                       QMessageBox.Yes | QMessageBox.No)
            if ret != QMessageBox.Yes:
                return
            try:
                os.makedirs(d)
            except Exception as e:
                QMessageBox.warning(self, "创建失败", "无法创建目录：%s" % e)
                return
        cfg.save_dir = d
        cfg.auto_accept = self.auto_chk.isChecked()
        cfg.autostart = self.startup_chk.isChecked()
        cfg.web_enabled = self.web_chk.isChecked()
        if cfg.web_enabled and not mw.web.is_alive():
            mw.web = _web.WebShareServer(cfg, {
                "on_recv_update": mw._cb_update,
                "on_recv_done": mw._cb_recv_done,
            })
            mw.web.start()
        elif not cfg.web_enabled and mw.web.is_alive():
            mw.web.stop()
        if cfg.autostart and not set_autostart(True):
            QMessageBox.warning(self, "提示", "开机自启设置失败，可忽略继续使用。")
        if not cfg.autostart:
            set_autostart(False)
        cfg.save()
        mw.discovery.set_name(cfg.device_name)
        mw.refresh_header()
        self.accept()


def socket_hostname():
    import socket as _s
    return _s.gethostname()


# ---------------------------------------------------------------- 设备条目

class DeviceItemWidget(QWidget):
    """卡片式设备条目：绿点 + 名称 + IP + 右侧“在线”徽章"""
    def __init__(self, name, ip):
        QWidget.__init__(self)
        h = QHBoxLayout(self)
        h.setContentsMargins(10, 6, 10, 6)
        h.setSpacing(10)
        dot = QLabel("●")
        dot.setObjectName("dot")
        dot.setStyleSheet("color:#22c55e; font-size:15px; border:none;")
        box = QVBoxLayout()
        box.setSpacing(1)
        name_lb = QLabel(name)
        name_lb.setObjectName("devName")
        ip_lb = QLabel(ip)
        ip_lb.setObjectName("devIp")
        box.addWidget(name_lb)
        box.addWidget(ip_lb)
        badge = QLabel("在线")
        badge.setObjectName("devBadge")
        badge.setAlignment(Qt.AlignCenter)
        h.addWidget(dot, 0, Qt.AlignVCenter)
        h.addLayout(box, 1)
        h.addWidget(badge, 0, Qt.AlignVCenter)
        h.setSizeConstraint(QHBoxLayout.SetMinimumSize)


# ---------------------------------------------------------------- 主窗口

class MainWindow(QMainWindow):
    def __init__(self):
        QMainWindow.__init__(self)
        self.config = core.Config()
        self.my_id = uuid.uuid4().hex[:12]
        core.log.info("=" * 40)
        core.log.info("Signal 快传启动：设备=%s IP=%s 保存目录=%s（已设=%s）",
                      self.config.device_name, core.get_local_ip(),
                      self.config.save_dir or "（未设）", self.config.save_dir_ok())
        self.bridge = Bridge(self)
        self.progress = {}                 # msg_id -> info
        self._task_btns = {}               # msg_id -> (pause_btn, cancel_btn)
        self.selected_paths = []
        self._tray_hint_shown = False
        self._tray_active = False   # 托盘图标活动态（传输中绿点）

        self.server = core.TransferServer(self.config, {
            "on_request": self._cb_request,
            "on_text": self._cb_text,
            "on_recv_update": self._cb_update,
            "on_recv_done": self._cb_recv_done,
            "on_need_setup": self._cb_need_setup,
        })
        self.server.start()
        self.discovery = core.DiscoveryService(self.my_id, self.config.device_name,
                                               self.server.port, self.server.tls_port)
        self.discovery.start()
        self.web = _web.WebShareServer(self.config, {
            "on_recv_update": self._cb_update,
            "on_recv_done": self._cb_recv_done,
        })
        if self.config.web_enabled:
            self.web.start()
        self.ctrl = _mcp.CtrlServer({
            "config": self.config, "discovery": self.discovery,
            "web": self.web, "progress": self.progress,
            "ui_cb": {"on_send_started":
                      lambda mid, d, p, c: self.bridge.task_started.emit(
                          mid, d, p, c, True)},
        })
        self.ctrl.start()
        self.ctrl = _mcp.CtrlServer({
            "config": self.config, "discovery": self.discovery,
            "web": self.web, "progress": self.progress,
            "ui_cb": {"on_send_started":
                      lambda mid, d, p, c: self.bridge.task_started.emit(
                          mid, d, p, c, True)},
        })
        self.ctrl.start()

        self._build_ui()
        self._build_tray()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_devices)
        self.timer.timeout.connect(self.refresh_progress)
        self.timer.start(400)

        self.bridge.incoming_request.connect(self._ui_request)
        self.bridge.text_received.connect(self._ui_text)
        self.bridge.recv_update.connect(self._ui_recv_update)
        self.bridge.recv_done.connect(self._ui_recv_done)
        self.bridge.need_setup.connect(self._ui_need_setup)
        self.bridge.task_started.connect(self._ui_task_started)
        self.bridge.task_started.connect(self._ui_task_started)

        # 首次使用：未设置保存目录则自动弹出设置窗口引导用户选择
        if not self.config.save_dir_ok():
            self.status_bar_msg("首次使用：请在设置中选择文件保存目录")
            QTimer.singleShot(800, self.open_settings)

    # ---------- UI 构建

    def _build_ui(self):
        self.setWindowTitle("Signal 快传")
        self.setWindowIcon(make_app_icon())
        self.resize(960, 640)
        self.setStyleSheet(QSS)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        # 顶栏
        top = QFrame()
        top.setObjectName("card")
        th = QHBoxLayout(top)
        th.setContentsMargins(14, 10, 14, 10)
        logo = QLabel("⚡ Signal 快传")
        logo.setObjectName("title")
        th.addWidget(logo)
        self.header_info = QLabel("")
        self.header_info.setObjectName("hint")
        th.addWidget(self.header_info)
        th.addStretch(1)
        btn_web = QPushButton("📱 手机互传")
        btn_web.clicked.connect(self.open_web_share)
        btn_hotspot = QPushButton("📶 一键热点")
        btn_hotspot.clicked.connect(self.open_hotspot)
        btn_set = QPushButton("⚙ 设置")
        btn_set.clicked.connect(self.open_settings)
        th.addWidget(btn_web)
        th.addWidget(btn_hotspot)
        th.addWidget(btn_set)
        root.addWidget(top)

        body = QHBoxLayout()
        body.setSpacing(10)

        # 左：设备
        left = QFrame()
        left.setObjectName("card")
        lv = QVBoxLayout(left)
        lv.setContentsMargins(10, 10, 10, 10)
        lv.addWidget(QLabel("在线设备"))
        self.dev_hint = QLabel("正在搜索附近设备…")
        self.dev_hint.setObjectName("hint")
        lv.addWidget(self.dev_hint)
        self.device_list = QListWidget()
        self.device_list.setObjectName("devList")
        self.device_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.device_list.clicked.connect(self.on_device_clicked)
        lv.addWidget(self.device_list, 1)
        iprow = QHBoxLayout()
        self.ip_edit = QLineEdit()
        self.ip_edit.setPlaceholderText("对方 IP，如 192.168.1.23")
        btn_add = QPushButton("手动添加")
        btn_add.clicked.connect(self.add_by_ip)
        iprow.addWidget(self.ip_edit, 1)
        iprow.addWidget(btn_add)
        lv.addLayout(iprow)
        self.save_hint = QLabel("")
        self.save_hint.setObjectName("hint")
        self.save_hint.setWordWrap(True)
        lv.addWidget(self.save_hint)
        body.addWidget(left, 32)

        # 右：发送
        right = QFrame()
        right.setObjectName("card")
        rv = QVBoxLayout(right)
        rv.setContentsMargins(10, 10, 10, 10)
        trow = QHBoxLayout()
        self.target_label = QLabel("目标：未选择（请在左侧点击设备）")
        self.target_label.setObjectName("target")
        self.target_label.setWordWrap(True)
        self.speed_label = QLabel("")
        self.speed_label.setObjectName("speed")
        trow.addWidget(self.target_label, 1)
        trow.addWidget(self.speed_label, 0, Qt.AlignTop)
        rv.addLayout(trow)
        self.dropzone = QLabel("⇩ 把文件 / 文件夹拖到这里\n\n或点击下方按钮选择")
        self.dropzone.setObjectName("dropzone")
        self.dropzone.setAlignment(Qt.AlignCenter)
        self.dropzone.setFixedHeight(150)
        self.dropzone.setAcceptDrops(True)
        self.dropzone.dragEnterEvent = self._drag_enter
        self.dropzone.dropEvent = self._drop
        rv.addWidget(self.dropzone)
        selrow = QHBoxLayout()
        btn_pick = QPushButton("选择文件")
        btn_pick.clicked.connect(self.pick_files)
        btn_pickdir = QPushButton("选择文件夹")
        btn_pickdir.clicked.connect(self.pick_dir)
        btn_clear = QPushButton("清空")
        btn_clear.clicked.connect(self.clear_paths)
        selrow.addWidget(btn_pick)
        selrow.addWidget(btn_pickdir)
        selrow.addWidget(btn_clear)
        selrow.addStretch(1)
        rv.addLayout(selrow)
        self.btn_send_files = QPushButton("📤 发送文件")
        self.btn_send_files.setObjectName("primary")
        self.btn_send_files.setEnabled(False)
        self.btn_send_files.setToolTip("先拖入或选择文件后可点击")
        self.btn_send_files.clicked.connect(self.send_selected)
        self.btn_send_enc = QPushButton("🔒 加密传输")
        self.btn_send_enc.setObjectName("primary")
        self.btn_send_enc.setEnabled(False)
        self.btn_send_enc.setToolTip("先拖入或选择文件；需对方输入 6 位验证码才能解密接收")
        self.btn_send_enc.clicked.connect(self.send_encrypted)
        sendrow = QHBoxLayout()
        sendrow.addWidget(self.btn_send_files, 1)
        sendrow.addWidget(self.btn_send_enc, 1)
        rv.addLayout(sendrow)
        self.text_edit = QLineEdit()
        self.text_edit.setPlaceholderText("输入文字消息，回车或点按钮发送（剪贴板同步）")
        self.text_edit.returnPressed.connect(self.send_text)
        rv.addWidget(self.text_edit)
        self.btn_send_text = QPushButton("发送文字")
        self.btn_send_text.setObjectName("primary")
        self.btn_send_text.clicked.connect(self.send_text)
        rv.addWidget(self.btn_send_text)
        self.path_hint = QLabel("未选择文件")
        self.path_hint.setObjectName("hint")
        rv.addWidget(self.path_hint)
        rv.addStretch(1)
        body.addWidget(right, 68)

        root.addLayout(body, 2)

        # 底：传输记录
        bottom = QFrame()
        bottom.setObjectName("card")
        bv = QVBoxLayout(bottom)
        bv.setContentsMargins(10, 8, 10, 8)
        bv.addWidget(QLabel("传输任务"))
        self.task_tree = QTreeWidget()
        self.task_tree.setColumnCount(7)
        self.task_tree.setHeaderLabels(["时间", "方向", "对方", "内容", "进度", "状态", "操作"])
        self.task_tree.setRootIsDecorated(False)
        self.task_tree.setColumnWidth(0, 80)
        self.task_tree.setColumnWidth(1, 60)
        self.task_tree.setColumnWidth(2, 110)
        self.task_tree.setColumnWidth(3, 230)
        self.task_tree.setColumnWidth(4, 190)
        self.task_tree.setAlternatingRowColors(False)
        self.task_tree.setColumnWidth(0, 80)
        self.task_tree.setColumnWidth(1, 60)
        self.task_tree.setColumnWidth(2, 110)
        self.task_tree.setColumnWidth(3, 220)
        self.task_tree.setColumnWidth(4, 160)
        self.task_tree.setColumnWidth(5, 210)
        self.task_tree.setColumnWidth(6, 70)
        self.task_tree.itemClicked.connect(self._open_task_path)
        self.task_tree.itemDoubleClicked.connect(self._open_task_path)
        bv.addWidget(self.task_tree, 1)
        root.addWidget(bottom, 1)

        self.refresh_header()
        self.refresh_devices()

    def _build_tray(self):
        self.tray = QSystemTrayIcon(make_app_icon(), self)
        menu = QMenu()
        act_show = QAction("显示主窗口", self)
        act_show.triggered.connect(self.show_up)
        act_exit = QAction("退出", self)
        act_exit.triggered.connect(self.real_exit)
        menu.addAction(act_show)
        menu.addAction(act_exit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()

    # ---------- 顶栏/设备

    def refresh_header(self):
        self.header_info.setText("%s  |  本机 IP：%s  |  端口：%d"
                                 % (self.config.device_name, core.get_local_ip(), self.server.port))
        if self.config.save_dir_ok():
            self.save_hint.setText("接收的文件保存到：%s" % self.config.save_dir)
        else:
            self.save_hint.setText("⚠ 未设置文件保存目录——请点右上角【⚙ 设置】选择")
        self.setWindowTitle("Signal 快传 v%s - %s"
                                 % (core.APP_VERSION, self.config.device_name))

    def refresh_devices(self):
        devs = self.discovery.alive()
        selected_ip = None
        it = self.device_list.currentItem()
        if it is not None:
            selected_ip = it.data(Qt.UserRole)
        self.device_list.blockSignals(True)
        self.device_list.clear()
        for d in devs:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, d.ip)
            item.setData(Qt.UserRole + 1, d.tcp)
            item.setData(Qt.UserRole + 2, d.name)
            item.setData(Qt.UserRole + 3, d.tls)
            w = DeviceItemWidget(d.name, d.ip)
            item.setSizeHint(QSize(0, 56))
            self.device_list.addItem(item)
            self.device_list.setItemWidget(item, w)
            if d.ip == selected_ip:
                self.device_list.setCurrentItem(item)
        self.device_list.blockSignals(False)
        n = len(devs)
        if n == 0:
            self.dev_hint.setText("未发现设备，正在搜索…\n（对方需打开本软件；也可手动添加 IP）")
        else:
            self.dev_hint.setText("发现 %d 台在线设备，点击选中后即可发送" % n)
        cur = self.device_list.currentItem()
        if cur is not None:
            self.target_label.setText("目标：%s（%s）"
                                      % (cur.data(Qt.UserRole + 2), cur.data(Qt.UserRole)))
            self.target_label.setStyleSheet("")
            self.btn_send_text.setEnabled(True)
        else:
            self.target_label.setText("目标：未选择（请在左侧点击设备）")
            self.target_label.setStyleSheet("color:#fbbf24; font-weight:bold;")
            self.btn_send_text.setEnabled(False)

    def on_device_clicked(self, index):
        it = self.device_list.currentItem()
        if it is not None:
            self.target_label.setText("目标：%s（%s）"
                                      % (it.data(Qt.UserRole + 2), it.data(Qt.UserRole)))
            self.target_label.setStyleSheet("")
        self.btn_send_text.setEnabled(True)

    def add_by_ip(self):
        ip = self.ip_edit.text().strip()
        if ip:
            self.discovery.poke(ip)
            self.status_bar_msg("正在探测 %s，对方在线的话几秒内会出现" % ip)

    def status_bar_msg(self, text):
        self.save_hint.setText(text)

    # ---------- 拖拽/选择

    def _drag_enter(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def _drop(self, event):
        for url in event.mimeData().urls():
            p = url.toLocalFile()
            if p and p not in self.selected_paths:
                self.selected_paths.append(p)
        self.update_path_hint()

    def pick_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "选择文件")
        for p in files:
            if p not in self.selected_paths:
                self.selected_paths.append(p)
        self.update_path_hint()

    def pick_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if d and d not in self.selected_paths:
            self.selected_paths.append(d)
        self.update_path_hint()

    def clear_paths(self):
        self.selected_paths = []
        self.update_path_hint()

    def update_path_hint(self):
        if not self.selected_paths:
            self.btn_send_files.setText("📤 发送文件")
            self.btn_send_files.setEnabled(False)
            self.btn_send_enc.setText("🔒 加密传输")
            self.btn_send_enc.setEnabled(False)
            self.path_hint.setText("未选择文件")
            self.dropzone.setText("⇩ 把文件 / 文件夹拖到这里\n\n或点击下方按钮选择")
            return
        total = 0
        count = 0
        for p in self.selected_paths:
            if os.path.isdir(p):
                for root, _d, names in os.walk(p):
                    count += len(names)
                    for n in names:
                        try:
                            total += os.path.getsize(os.path.join(root, n))
                        except OSError:
                            pass
            else:
                count += 1
                try:
                    total += os.path.getsize(p)
                except OSError:
                    pass
        self.btn_send_files.setText("📤 发送文件（%d 项，%s）" % (len(self.selected_paths), core.fmt_size(total)))
        self.btn_send_files.setEnabled(True)
        self.btn_send_enc.setText("🔒 加密传输（%d 项）" % len(self.selected_paths))
        self.btn_send_enc.setEnabled(True)
        self.dropzone.setText("⇩ 已选 %d 项，共 %s\n点击下方按钮即发送（加密传输需对方输验证码）"
                              % (len(self.selected_paths), core.fmt_size(total)))
        self.path_hint.setText("待发送：%s" % "；".join(
            os.path.basename(p) for p in self.selected_paths[:3]) +
            (" 等 %d 项" % len(self.selected_paths) if len(self.selected_paths) > 3 else ""))

    # ---------- 发送

    def current_target(self):
        it = self.device_list.currentItem()
        if it is None:
            return None
        return (it.data(Qt.UserRole), it.data(Qt.UserRole + 1),
                it.data(Qt.UserRole + 2) or "对方", it.data(Qt.UserRole + 3) or 0)

    def send_selected(self):
        """发送已拖入/选择的文件（发送后自动清空选择）"""
        if not self.selected_paths:
            QMessageBox.information(self, "提示", "请先拖入或选择要发送的文件")
            return
        self.send_files(list(self.selected_paths))
        self.clear_paths()

    def send_encrypted(self):
        """TLS 加密通道（内置证书，HTTPS 同款）+ 验证码 HMAC 校验，验证码不经网络"""
        if not self.selected_paths:
            QMessageBox.information(self, "提示", "请先拖入或选择要发送的文件")
            return
        code = "%06d" % (int(time.time() * 1000) % 1000000)
        self.last_enc_code = code   # 记录本次验证码（测试与展示共用）
        dlg = QDialog(self)
        dlg.setWindowTitle("加密传输")
        dlg.setFixedWidth(420)
        v = QVBoxLayout(dlg)
        v.addWidget(QLabel("已生成一次性验证码，请当面或用电话告知对方（\n对方接收时需输入此码才能解密；验证码不经过网络传输）："))
        code_lb = QLabel(code)
        code_lb.setObjectName("codeBig")
        v.addWidget(code_lb)
        v.addWidget(QLabel("🔒 文件将通过 TLS 加密通道（AES-256-GCM 套件）传输，\n对方输入正确验证码后才能接收。"))
        row = QHBoxLayout()
        go = QPushButton("开始加密传输")
        go.setObjectName("primary")
        cancel = QPushButton("取消")
        go.clicked.connect(dlg.accept)
        cancel.clicked.connect(dlg.reject)
        row.addStretch(1)
        row.addWidget(cancel)
        row.addWidget(go)
        v.addLayout(row)
        if dlg.exec_() != QDialog.Accepted:
            return
        paths = list(self.selected_paths)
        t = self.current_target()
        if not t:
            self.target_label.setText("⚠ 目标未选择：请先在左侧点击一台设备再发送")
            self.target_label.setStyleSheet("color:#fbbf24; font-weight:bold;")
            QMessageBox.information(self, "提示", "请先在左侧点击选择目标设备")
            return
        ip, _tcp, name, tls_port = t
        if not tls_port:
            QMessageBox.warning(self, "无法加密传输",
                                "对方运行的软件版本过旧，不支持加密传输。\n请先在对方电脑上更新 Signal 快传。")
            return
        task = core.SendTask(ip, _tcp, self.config.device_name, paths=paths,
                             progress=self.progress,
                             on_done=lambda mid, ok, note: self._send_finished(mid, ok, note),
                             on_error=lambda e: self.status_bar_msg("❌ 发送失败：%s" % e),
                             encrypted=True, code=code, tls_port=tls_port)
        self._add_task_row(task.msg_id, "🔒 加密发送", name,
                           "；".join(os.path.basename(p) for p in paths[:2]))
        task.start()
        core.log.info("发起加密传输：%d 项 -> %s（%s，TLS:%d）", len(paths), name, ip, tls_port)
        self.status_bar_msg("正在加密发送到 %s …" % name)
        self.clear_paths()

    def send_files(self, paths):
        t = self.current_target()
        if not t:
            self.target_label.setText("⚠ 目标未选择：请先在左侧点击一台设备再发送")
            self.target_label.setStyleSheet("color:#fbbf24; font-weight:bold;")
            QMessageBox.information(self, "提示", "请先在左侧点击选择目标设备")
            return
        ip, port, name, _tls = t
        task = core.SendTask(ip, port, self.config.device_name, paths=paths,
                             progress=self.progress,
                             on_done=lambda mid, ok, note: self._send_finished(mid, ok, note),
                             on_error=lambda e: self.status_bar_msg("❌ 发送失败：%s" % e))
        self._add_task_row(task.msg_id, "↑ 发送", name,
                           "；".join(os.path.basename(p) for p in paths[:2]))
        task.start()
        core.log.info("发起文件发送：%d 项 -> %s（%s:%d）", len(paths), name, ip, port)
        self.status_bar_msg("正在发送到 %s …" % name)

    def send_text(self):
        text = self.text_edit.text().strip()
        if not text:
            return
        t = self.current_target()
        if not t:
            QMessageBox.information(self, "提示", "请先在左侧选择目标设备")
            return
        ip, port, name = t
        task = core.SendTask(ip, port, self.config.device_name, text=text,
                             progress=self.progress,
                             on_done=lambda mid, ok, note: self._send_finished(mid, ok, note))
        self._add_task_row(task.msg_id, "↑ 发送", name, "文字：" + text[:24], has_ops=False)
        task.start()
        self.text_edit.clear()

    def _send_finished(self, msg_id, ok, note):
        self.tray.showMessage("Signal 快传", note, QSystemTrayIcon.Information, 3000)

    # ---------- 任务表

    def _add_task_row(self, msg_id, direction, peer, content, has_ops=True):
        item = QTreeWidgetItem()
        item.setData(0, Qt.UserRole, msg_id)
        item.setText(0, time.strftime("%H:%M:%S"))
        item.setText(1, direction)
        item.setText(2, peer)
        item.setText(3, content)
        item.setText(5, "准备中")
        item.setToolTip(3, "点击任务行可打开文件所在文件夹")
        self.task_tree.insertTopLevelItem(0, item)
        bar = QProgressBar()
        bar.setRange(0, 1000)
        bar.setValue(0)
        self.task_tree.setItemWidget(item, 4, bar)
        item.setSizeHint(0, bar.sizeHint())
        if has_ops:
            boxw = QWidget()
            h = QHBoxLayout(boxw)
            h.setContentsMargins(2, 0, 2, 0)
            h.setSpacing(2)
            btn_p = QPushButton("⏸")
            btn_p.setFixedSize(24, 20)
            btn_x = QPushButton("✕")
            btn_x.setFixedSize(24, 20)
            btn_p.setToolTip("暂停 / 继续本任务")
            btn_x.setToolTip("终止本任务（接收端会清理未完成文件）")

            def _toggle(mid=msg_id, b=btn_p):
                info = self.progress.get(mid)
                obj = info.get("obj") if info else None
                if not obj:
                    return
                if obj.paused:
                    obj.resume()
                    b.setText("⏸")
                else:
                    obj.pause()
                    b.setText("▶")

            def _cancel(mid=msg_id):
                info = self.progress.get(mid)
                obj = info.get("obj") if info else None
                if obj:
                    obj.cancel()

            btn_p.clicked.connect(_toggle)
            btn_x.clicked.connect(_cancel)
            h.addWidget(btn_p)
            h.addWidget(btn_c if False else btn_x)
            self.task_tree.setItemWidget(item, 6, boxw)
            self._task_btns[msg_id] = (btn_p, btn_x)

    def refresh_progress(self):
        active = None
        any_busy = False
        for i in range(self.task_tree.topLevelItemCount()):
            item = self.task_tree.topLevelItem(i)
            mid = item.data(0, Qt.UserRole)
            info = self.progress.get(mid)
            if not info:
                continue
            bar = self.task_tree.itemWidget(item, 4)
            total = info.get("total") or 0
            sent = info.get("sent") or 0
            if total > 0:
                bar.setValue(int(1000.0 * sent / total))
            speed = info.get("speed") or 0.0
            state = info.get("state") or ""
            # 文件序号（如 3/8）：传输中显示当前进度位置
            if speed > 0:
                fcnt = info.get("file_cnt") or 0
                fidx = info.get("file_idx")
                seq = ""
                if fcnt and fidx is not None and ("发送中" in state or "接收中" in state):
                    seq = "（%d/%d） " % (min(int(fidx) + 1, int(fcnt)), int(fcnt))
                item.setText(5, "%s%s  %s/s" % (seq, state, core.fmt_size(speed)))
            else:
                item.setText(5, state)
            btns = self._task_btns.get(mid)
            if btns and ("✅" in state or "❌" in state or "⏹" in state):
                btns[0].setEnabled(False)
                btns[1].setEnabled(False)
            st = info.get("state") or ""
            if ("发送中" in st or "接收中" in st or "解密" in st) and (info.get("speed") or 0) > 0:
                active = info
                any_busy = True
            elif ("发送中" in st or "接收中" in st):
                any_busy = True
        # 实时速度条：当前活跃任务的速度 / 百分比 / 剩余时间
        if active:
            speed = active["speed"]
            total = active.get("total") or 0
            sent = active.get("sent") or 0
            remain = (total - sent) / speed if speed > 0 and total > sent else 0
            eta_s = ("%d 秒" % int(remain)) if remain < 60 else ("%d 分 %02d 秒" % (int(remain) // 60, int(remain) % 60))
            pct = int(100.0 * sent / total) if total else 0
            self.speed_label.setText("⚡ %s/s ｜ %d%% ｜ 剩余 %s"
                                     % (core.fmt_size(speed), pct, eta_s))
        else:
            self.speed_label.setText("")
        # 托盘图标传输中动态提示（有活动任务时叠加绿点）
        want_icon = make_app_icon(active=any_busy)
        if self._tray_active != any_busy:
            self._tray_active = any_busy
            self.tray.setIcon(want_icon)

    def _open_task_path(self, item, col):
        mid = item.data(0, Qt.UserRole)
        info = self.progress.get(mid) or {}
        paths = info.get("paths") or []
        if not paths:
            self.status_bar_msg("任务完成后可点击打开文件所在文件夹")
            return
        p = paths[0]
        if not os.path.exists(p):
            self.status_bar_msg("文件已不存在：%s" % p)
            return
        try:
            subprocess.Popen(["explorer", "/select,", os.path.normpath(p)])
        except Exception:
            try:
                os.startfile(os.path.dirname(p))
            except Exception:
                pass

    # ---------- 接收回调（子线程 → 信号 → 主线程）

    def _cb_request(self, sender, files, box):
        box.sender = sender
        box.files = files
        self.bridge.incoming_request.emit(box)

    def _cb_text(self, sender, text):
        self.bridge.text_received.emit(sender, text)

    def _cb_update(self, msg_id, info):
        self.bridge.recv_update.emit(msg_id, info)

    def _cb_recv_done(self, msg_id, ok, note):
        self.bridge.recv_done.emit(msg_id, ok, note)

    def _cb_need_setup(self):
        self.bridge.need_setup.emit()

    def _ui_request(self, box):
        # 托盘气泡提醒 + 置顶弹窗，避免确认框藏在其他窗口后面被忽略
        kind = "加密文件（需验证码）" if getattr(box, "enc", False) else "文件"
        self.tray.showMessage("收到文件请求",
                              "%s 想向你发送 %d 个%s" % (box.sender, len(box.files), kind),
                              QSystemTrayIcon.Information, 4000)
        dlg = ConfirmDialog(self, box.sender, box.files,
                            need_code=getattr(box, "enc", False))
        dlg.setWindowFlags(dlg.windowFlags() | Qt.WindowStaysOnTopHint)
        # 发送方取消/中断时自动关闭弹窗（轮询 ctrl 取消事件）
        poll = QTimer(dlg)
        poll.setInterval(250)

        def _check_cancel():
            # v1.10 修复：box.cancel_ev 是 TransferControl（其 .cancel_ev 才是 Event），
            # 此前误按 Event 调 .is_set() 抛 AttributeError，弹窗出现 250ms 后即闪退
            cev = getattr(box, "cancel_ev", None)
            ev = getattr(cev, "cancel_ev", cev)   # TransferControl → 内部 Event；Event → 自身
            if ev is not None and ev.is_set():
                dlg.reject()

        poll.timeout.connect(_check_cancel)
        poll.start()
        ok = dlg.exec_() == QDialog.Accepted
        poll.stop()
        box.result = ok
        if ok and dlg.need_code:
            box.code = dlg.code
        box.event.set()
        if ok:
            self.status_bar_msg("正在接收来自 %s 的文件 …" % box.sender)

    def _ui_text(self, sender, text):
        QApplication.clipboard().setText(text)
        mid = uuid.uuid4().hex[:8]
        self._add_task_row(mid, "↓ 接收", sender, "文字：" + text[:24], has_ops=False)
        # 修复：收到的文字立即标记完成，不再停留在“准备中”
        self.progress[mid] = {"state": "✅ 已收到文字（已自动复制）",
                              "total": 1, "sent": 1, "speed": 0.0}
        self.refresh_progress()
        self.tray.showMessage("收到 %s 的文字（已复制）" % sender, text,
                              QSystemTrayIcon.Information, 4000)
        self.show_up()

    def _ui_recv_update(self, msg_id, info):
        prev = self.progress.get(msg_id)
        if prev is None:
            self._add_task_row(msg_id, "↓ 接收", info.get("sender") or "",
                               "；".join(f.get("name", "") for f in info.get("files", [])[:2]))
        self.progress[msg_id] = info
        self.refresh_progress()

    def _ui_recv_done(self, msg_id, ok, note):
        info = self.progress.get(msg_id)
        if info:
            info["state"] = ("✅ " if ok else "❌ ") + note
            info["speed"] = 0.0
        else:
            self._add_task_row(msg_id, "↓ 接收", "", note)
            self.progress[msg_id] = {"state": ("✅ " if ok else "❌ ") + note,
                                     "total": 1, "sent": 1, "speed": 0.0}
        self.refresh_progress()
        self.tray.showMessage("Signal 快传", note,
                              QSystemTrayIcon.Information if ok else QSystemTrayIcon.Warning, 4000)

    def _ui_task_started(self, mid, direction, peer, content, has_ops):
        """MCP 触发的发送：在任务表中建行（与手动发送一致）"""
        self._add_task_row(mid, direction, peer, content, has_ops=has_ops)

    def _ui_need_setup(self):
        """对方发文件过来但本地未设置保存目录：提示并自动打开设置"""
        self.tray.showMessage("Signal 快传", "请先在设置中选择文件保存目录，再接收文件",
                              QSystemTrayIcon.Warning, 5000)
        self.show_up()
        self.open_settings()

    # ---------- 热点/设置

    def open_hotspot(self):
        dlg = HotspotDialog(self, self.refresh_header)
        dlg.exec_()

    def open_web_share(self):
        if not self.config.web_enabled:
            QMessageBox.information(self, "未开启",
                                    "手机网页互传已在设置中关闭。\n可在【设置】中重新开启。")
            return
        if not self.web.is_alive():
            self.web = _web.WebShareServer(self.config, {
                "on_recv_update": self._cb_update,
                "on_recv_done": self._cb_recv_done,
            })
            self.web.start()
        WebShareDialog(self).exec_()

    def open_settings(self):
        SettingsDialog(self).exec_()

    # ---------- 托盘/关闭

    def _tray_activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            self.show_up()

    def show_up(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        if not self._tray_hint_shown:
            self.tray.showMessage("Signal 快传", "已最小化到托盘，双击托盘图标可再次打开；右键→退出。",
                                  QSystemTrayIcon.Information, 4000)
            self._tray_hint_shown = True
            self.hide()
            event.ignore()
        else:
            self.hide()
            event.ignore()

    def real_exit(self):
        self.discovery.stop()
        self.server.stop()
        try:
            self.web.stop()
        except Exception:
            pass
        self.tray.hide()
        QApplication.quit()


# ---------------------------------------------------------------- 入口

def _fix_qt_plugin_path():
    """显式指定 Qt 插件路径（PyQt5 wheel 在部分环境下无法自动定位，
    否则报 "no Qt platform plugin could be initialized"）。
    PyInstaller 打包后由其 hook 自动配置路径，无需干预。"""
    if getattr(sys, "frozen", False):
        return
    try:
        import PyQt5 as _p
        plugins = os.path.join(os.path.dirname(_p.__file__), "Qt5", "plugins")
        os.environ.setdefault("QT_PLUGIN_PATH", plugins)
        os.environ.setdefault("QT_QPA_PLATFORM_PLUGIN_PATH",
                              os.path.join(plugins, "platforms"))
    except Exception:
        pass


def main():
    if hasattr(Qt, "AA_EnableHighDpiScaling"):
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    _fix_qt_plugin_path()

    # 全局异常钩子：UI 槽/回调中未捕获的 Python 异常写入日志且不再 abort。
    # PyQt5 默认行为是打印 stderr 后 qFatal 闪退（排查时日志里毫无痕迹），
    # 覆盖 excepthook 后异常可追溯，进程继续运行。
    import threading
    import traceback as _tb

    def _ui_excepthook(tp, val, tb):
        try:
            core.log.error("UI 未捕获异常：\n%s", "".join(_tb.format_exception(tp, val, tb)))
        except Exception:
            pass

    sys.excepthook = _ui_excepthook
    threading.excepthook = lambda a: _ui_excepthook(a.exc_type, a.exc_value, a.exc_traceback)

    app = QApplication(sys.argv)
    app.setApplicationName("Signal快传")
    app.setWindowIcon(make_app_icon())
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
