"""Local Windows hotkeys. No credentials on disk and no unauthenticated control port."""
import asyncio
import ctypes
from ctypes import wintypes
import os
import json
from pathlib import Path
import threading


def parse_binding(value):
    parts = value.upper().split('+')
    if (len(parts) < 3 or len(set(parts)) != len(parts)
            or parts[-1] not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
            or len(parts[-1]) != 1 or 'CTRL' not in parts[:-1]
            or not ({'ALT', 'SHIFT'} & set(parts[:-1]))
            or set(parts[:-1]) - {'CTRL', 'ALT', 'SHIFT'}):
        raise ValueError('全局按键须为 Ctrl 加 Alt 或 Shift，再加一个字母或数字')
    modifiers = sum({'ALT': 1, 'CTRL': 2, 'SHIFT': 4}[p] for p in parts[:-1])
    return modifiers | 0x4000, ord(parts[-1])  # MOD_NOREPEAT


class WindowsHotkeys:
    def __init__(self, callback):
        self.callback = callback
        self.thread = None
        self.stop_event = threading.Event()
        self.ready = threading.Event()
        self.error = ''
        self.thread_id = None

    def start(self, bindings):
        if os.name != 'nt':
            return '当前系统不支持 Windows 全局快捷键'
        self.stop_event.clear()
        self.ready.clear()
        self.error = ''
        self.thread = threading.Thread(target=self._run, args=(bindings,), daemon=True,
                                       name='teacher-global-hotkeys')
        self.thread.start()
        if not self.ready.wait(5):
            self.stop()
            return '全局快捷键注册超时'
        return self.error

    def _run(self, bindings):
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        user32.RegisterHotKey.restype = wintypes.BOOL
        user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                                      wintypes.UINT, wintypes.UINT, wintypes.UINT]
        registered = []
        try:
            self.thread_id = kernel32.GetCurrentThreadId()
            for index, (command, binding) in enumerate(bindings.items(), 1):
                modifiers, key = parse_binding(binding)
                if not user32.RegisterHotKey(None, index, modifiers, key):
                    raise RuntimeError(f'{binding} 注册失败，可能已被其他程序占用，请更换按键')
                registered.append(index)
            commands = list(bindings)
            self.ready.set()
            msg = wintypes.MSG()
            while not self.stop_event.is_set():
                while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
                    if msg.message == 0x0312 and 1 <= msg.wParam <= len(commands):
                        self.callback(commands[msg.wParam - 1])  # WM_HOTKEY
                self.stop_event.wait(.04)
        except Exception as exc:
            self.error = str(exc)
        finally:
            for index in registered:
                user32.UnregisterHotKey(None, index)
            self.ready.set()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=5)
        self.thread = None


class TeacherShortcuts:
    def __init__(self, preferences_path=None):
        self.native = WindowsHotkeys(self._dispatch)
        self.lock = asyncio.Lock()
        self.config_lock = asyncio.Lock()
        self.token = None
        self.loop = None
        self.bindings = {'hide': 'Ctrl+Alt+Shift+H', 'restore': 'Ctrl+Alt+Shift+R'}
        self.auto_enable = True
        self.preferences_path = Path(preferences_path) if preferences_path else None
        if self.preferences_path and self.preferences_path.exists():
            try:
                saved = json.loads(self.preferences_path.read_text('utf-8'))
                bindings = saved['bindings']
                if (type(saved['enabled']) is not bool or set(bindings) != {'hide', 'restore'}
                        or parse_binding(bindings['hide']) == parse_binding(bindings['restore'])):
                    raise ValueError('Invalid saved hotkeys')
                self.bindings = bindings
                self.auto_enable = saved['enabled']
            except (OSError, ValueError, TypeError, KeyError, AttributeError):
                pass
        self.error = ''
        self.result = ''
        self.revision = 0
        self.pending = set()
        self.queued_command = None
        self.feedback = set()
        self.watcher = None

    def online(self, token):
        from app import state
        return token in state.admin_tokens and any(
            ws.query_params.get('admin_token') == token
            and state.manager._session_role.get(state.manager._ws_session.get(id(ws))) == 'host'
            for sockets in state.manager.connections.values() for ws in sockets)

    def status(self):
        from app import state
        enabled = bool(self.token and self.token in state.admin_tokens and self.native.thread
                       and self.native.thread.is_alive() and not self.native.error)
        return dict(enabled=enabled, online=bool(enabled and self.online(self.token)),
                    auto_enable=self.auto_enable,
                    supported=os.name == 'nt', bindings=self.bindings,
                    error=self.error or self.native.error, result=self.result,
                    revision=self.revision, private_mode=state.private_mode)

    async def configure(self, token, enabled, bindings=None):
        async with self.config_lock:
            if enabled:
                proposed = bindings or self.bindings
                if set(proposed) != {'hide', 'restore'}:
                    raise ValueError('必须分别设置隐藏与恢复按键')
                parsed = [parse_binding(v) for v in proposed.values()]
                if parsed[0] == parsed[1]:
                    raise ValueError('隐藏与恢复不能使用同一按键')
                if not self.online(token):
                    raise ValueError('教师页面离线，请先恢复连接')
            if self.preferences_path:
                self.preferences_path.parent.mkdir(parents=True, exist_ok=True)
                temporary = self.preferences_path.with_suffix('.tmp')
                temporary.write_text(json.dumps({'enabled': enabled,
                    'bindings': proposed if enabled else self.bindings}, indent=2), 'utf-8')
                temporary.replace(self.preferences_path)
            self.auto_enable = enabled
            self.token = None
            await asyncio.to_thread(self.native.stop)
            self.error = ''
            if enabled:
                self.bindings = dict(proposed)
                self.loop = asyncio.get_running_loop()
                self.error = await asyncio.to_thread(self.native.start, self.bindings)
                if not self.error:
                    self.token = token
                    if not self.watcher or self.watcher.done():
                        self.watcher = asyncio.create_task(self._watch_login())
            return self.status()

    async def _watch_login(self):
        from app import state
        while self.token:
            await asyncio.sleep(.5)
            if self.token and self.token not in state.admin_tokens:
                self.token = None
                await asyncio.to_thread(self.native.stop)

    def _dispatch(self, command):
        if self.loop and not self.loop.is_closed():
            self.loop.call_soon_threadsafe(self._schedule, command)

    def _schedule(self, command):
        # Keep the latest requested state while the previous privacy operation finishes.
        self.queued_command = command
        if any(not task.done() for task in self.pending):
            return
        task = asyncio.create_task(self._drain())
        self.pending.add(task)
        task.add_done_callback(self.pending.discard)

    async def _drain(self):
        while self.queued_command:
            command, self.queued_command = self.queued_command, None
            await self._execute(command)

    async def _execute(self, command):
        try:
            if not self.online(self.token):
                raise ValueError('教师登录失效或页面离线，请先恢复连接')
            await self.set_private(self.token, command == 'hide', require_online=True)
            self.result = '学生画面已隐藏' if command == 'hide' else '已恢复共享（保留原屏幕权限）'
        except Exception as exc:
            self.result = str(exc)
        self.revision += 1
        # Non-blocking native feedback remains visible over PPT / IDE.
        task = asyncio.create_task(asyncio.to_thread(notify, self.result))
        self.feedback.add(task)
        task.add_done_callback(self.feedback.discard)

    async def set_private(self, token, enabled, require_online=False):
        from app import state, database
        from app.routers.api import _enforce_private_mode
        async with self.lock:
            if token not in state.admin_tokens:
                raise PermissionError('教师登录已失效，请重新登录')
            if require_online and not self.online(token):
                raise ValueError('教师页面离线，请先恢复连接')
            if require_online and not database.get_active_session():
                raise ValueError('请先创建课堂')
            state.private_mode = enabled
            if enabled:
                await _enforce_private_mode()
            return dict(ok=True, private_mode=state.private_mode)

    async def shutdown(self):
        self.token = None
        if self.watcher:
            self.watcher.cancel()
            await asyncio.gather(self.watcher, return_exceptions=True)
        await asyncio.to_thread(self.native.stop)
        await asyncio.gather(*list(self.pending), return_exceptions=True)
        await asyncio.gather(*list(self.feedback), return_exceptions=True)


def notify(message):
    """Non-activating native status window, including on embedded Python installs."""
    if os.name != 'nt':
        return
    import time
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
        wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.DestroyWindow.argtypes = [wintypes.HWND]
    user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                                   wintypes.UINT, wintypes.UINT, wintypes.UINT]
    user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
    width = min(760, max(360, len(message) * 22 + 48))
    hwnd = user32.CreateWindowExW(0x08000088, 'STATIC', message, 0x80800201,
        max(0, user32.GetSystemMetrics(0) - width - 32), 48, width, 64,
        None, None, None, None)
    if not hwnd:
        print('Teacher shortcut: ' + message, flush=True)
        return
    try:
        user32.ShowWindow(hwnd, 4)  # SW_SHOWNOACTIVATE
        deadline = time.monotonic() + 2.2
        msg = wintypes.MSG()
        while time.monotonic() < deadline:
            while user32.PeekMessageW(ctypes.byref(msg), hwnd, 0, 0, 1):
                user32.DispatchMessageW(ctypes.byref(msg))
            time.sleep(.04)
    finally:
        user32.DestroyWindow(hwnd)
