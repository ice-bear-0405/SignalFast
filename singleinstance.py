# -*- coding: utf-8 -*-
"""Windows 单实例保证：命名互斥锁 + 命名事件唤醒。

- 互斥锁（Local\\ 命名空间，按登录会话隔离）：同一会话同一时刻只有一个主程序
  界面。进程退出或崩溃时句柄由操作系统自动释放，不会残留、不会 PID 复用误判。
- 唤醒事件：重复启动的进程不弹新窗口，而是 SetEvent 通知已运行实例把主窗口
  恢复并带到前台，随后自身静默退出。
- SignalMCP.exe（无界面协议适配器）不受此锁约束，多个 MCP 客户端可并存。
- suffix 参数用于测试隔离（不同后缀 = 不同锁名），生产入口不传。

仅 Windows（项目目标平台）；依赖 kernel32 命名内核对象。
"""
import ctypes
import os
import time
from ctypes import wintypes

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.CreateMutexW.restype = wintypes.HANDLE
_k32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
_k32.CreateEventW.restype = wintypes.HANDLE
_k32.CreateEventW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL,
                              wintypes.LPCWSTR]
_k32.OpenEventW.restype = wintypes.HANDLE
_k32.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
_k32.SetEvent.restype = wintypes.BOOL
_k32.SetEvent.argtypes = [wintypes.HANDLE]
_k32.WaitForSingleObject.restype = wintypes.DWORD
_k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
_k32.CloseHandle.restype = wintypes.BOOL
_k32.CloseHandle.argtypes = [wintypes.HANDLE]

_ERROR_ALREADY_EXISTS = 183
_WAIT_OBJECT_0 = 0
_EVENT_MODIFY_STATE = 0x0002

_MUTEX = "Local\\Signal快传单实例"
_WAKE = "Local\\Signal快传唤醒"

_held_mutex = None      # 进程存活期间保持引用；退出时由系统释放，勿手动 CloseHandle
_wake_handle = None


def _sfx(explicit):
    """锁/事件名后缀：显式参数优先，否则读环境变量（多进程测试隔离用）。"""
    if explicit is not None:
        return explicit
    return os.environ.get("SIGNAL_INSTANCE_SUFFIX", "")


def acquire(suffix=None):
    """获取单实例锁：True=本进程成为唯一实例；False=已有实例在运行。"""
    global _held_mutex
    if _held_mutex is not None:
        return True
    h = _k32.CreateMutexW(None, False, _MUTEX + _sfx(suffix))
    if not h:
        return False            # 句柄创建失败（极罕见）：宁多开勿锁死
    if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
        _k32.CloseHandle(h)     # 仅关本进程的重复句柄，锁归已运行实例
        return False
    _held_mutex = h
    return True


def is_locked(suffix=None):
    """探测锁是否已被持有（含本进程自身；不改变持有状态，供测试/诊断）。"""
    h = _k32.CreateMutexW(None, False, _MUTEX + _sfx(suffix))
    if not h:
        return False
    exists = ctypes.get_last_error() == _ERROR_ALREADY_EXISTS
    _k32.CloseHandle(h)
    return exists


def create_wake_handle(suffix=None):
    """已运行实例创建唤醒事件（自动重置、初始无信号），返回轮询句柄。"""
    global _wake_handle
    if _wake_handle is None:
        _wake_handle = _k32.CreateEventW(None, False, False, _WAKE + _sfx(suffix))
    return _wake_handle


def notify_existing(suffix=None, retries=8, delay=0.12):
    """新进程通知已运行实例唤醒窗口；旧实例尚未建好事件时短暂重试。

    返回是否通知成功（失败时调用方可弹提示兜底）。"""
    for _ in range(retries):
        h = _k32.OpenEventW(_EVENT_MODIFY_STATE, False, _WAKE + _sfx(suffix))
        if h:
            _k32.SetEvent(h)
            _k32.CloseHandle(h)
            return True
        time.sleep(delay)
    return False


def poll_wake(handle):
    """非阻塞轮询唤醒事件：True=收到唤醒请求（自动重置事件随即复位）。"""
    if not handle:
        return False
    return _k32.WaitForSingleObject(handle, 0) == _WAIT_OBJECT_0
