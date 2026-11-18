r"""
desktop.py - Shelfrip as a Windows app: its own window, and an icon by the clock.

  open_window(url)   opens the page in an app window (Edge's app mode: no tabs or address
                     bar; Edge comes with Windows 10 and 11), else Chrome, else the browser.
  Tray(...)          the icon in the notification area. Click it to open Shelfrip;
                     right-click for a menu. Closing the window leaves Shelfrip running there.
  write_icon(path)   writes shelfrip.ico (the tray, the exe and the installer use it).
  hide_console()     hides the black console window once the tray icon is up.

Everything here is standard library (ctypes); on other systems it does nothing, and the page
opens in the browser as before.
"""

from __future__ import annotations

import os
import shutil
import struct
import subprocess
import threading
import webbrowser
from pathlib import Path

import paths

ICON_PATH = paths.DATA_DIR / "shelfrip.ico"


# --------------------------------------------------------------------------- icon

def _pixels(size: int) -> list[list[tuple[int, int, int, int]]]:
    """The Shelfrip mark (three spines on a shelf), drawn on a size x size grid."""
    clear = (0, 0, 0, 0)
    img = [[clear] * size for _ in range(size)]
    k = size / 28.0
    shapes = [  # x, y, w, h on a 28 grid, RGBA
        (3, 4, 5, 18, (0xF2, 0xB3, 0x3D, 255)),
        (10, 7, 5, 15, (0x6C, 0x9B, 0xFF, 255)),
        (17, 5, 5, 17, (0x4C, 0xC3, 0x8A, 255)),
        (2, 23, 24, 2.5, (0xC9, 0xD1, 0xDC, 255)),
    ]
    for x, y, w, h, c in shapes:
        x0, y0 = int(round(x * k)), int(round(y * k))
        x1, y1 = max(x0 + 1, int(round((x + w) * k))), max(y0 + 1, int(round((y + h) * k)))
        for yy in range(y0, min(y1, size)):
            for xx in range(x0, min(x1, size)):
                img[yy][xx] = c
    return img


def write_icon(path: Path = ICON_PATH) -> Path:
    """An .ico with 16, 24, 32, 48 and 256 px images (32-bit, uncompressed)."""
    sizes = (16, 24, 32, 48, 256)
    images = []
    for s in sizes:
        px = _pixels(s)
        data = bytearray()
        for row in reversed(px):  # BMP rows go bottom-up, pixels as BGRA
            for r, g, b, a in row:
                data += bytes((b, g, r, a))
        mask_row = ((s + 31) // 32) * 4
        data += bytes(mask_row * s)  # AND mask: all zero (alpha does the work)
        header = struct.pack("<IiiHHIIiiII", 40, s, s * 2, 1, 32, 0, len(data), 0, 0, 0, 0)
        images.append(header + bytes(data))
    out = struct.pack("<HHH", 0, 1, len(sizes))
    offset = 6 + 16 * len(sizes)
    for s, img in zip(sizes, images):
        out += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(img), offset)
        offset += len(img)
    out += b"".join(images)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(out)
    return path


# --------------------------------------------------------------------------- app window

def _find_browser() -> str | None:
    if os.name != "nt":
        return None
    roots = [os.environ.get(k) for k in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA")]
    names = [r"Microsoft\Edge\Application\msedge.exe", r"Google\Chrome\Application\chrome.exe"]
    for name in names:  # Edge first: it's on every Windows 10/11 PC
        for root in roots:
            if root and Path(root, name).is_file():
                return str(Path(root, name))
    return shutil.which("msedge") or shutil.which("chrome")


def _window_box() -> list[str]:
    """Size and place the window to fit the screen it opens on (inside the taskbar), centred.
    Sizes are in the same scaled units Edge uses, so 125% or 150% display scaling is fine."""
    w, h, x0, y0 = 1320, 900, 0, 0
    try:
        import ctypes

        class RECT(ctypes.Structure):
            _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]
        r = RECT()
        if ctypes.WinDLL("user32").SystemParametersInfoW(0x30, 0, ctypes.byref(r), 0):  # SPI_GETWORKAREA
            aw, ah = r.right - r.left, r.bottom - r.top
            w, h = min(w, int(aw * 0.92)), min(h, int(ah * 0.9))
            x0, y0 = r.left + (aw - w) // 2, r.top + (ah - h) // 2
    except Exception:
        return ["--window-size=1280,760"]
    return [f"--window-size={w},{h}", f"--window-position={x0},{y0}"]


def open_window(url: str, use_window: bool = True) -> None:
    """Open Shelfrip in its own window (falls back to a browser tab)."""
    exe = _find_browser() if use_window else None
    if exe:
        try:
            subprocess.Popen([exe, f"--app={url}", *_window_box(), "--no-first-run",
                              "--no-default-browser-check"],
                             creationflags=getattr(subprocess, "DETACHED_PROCESS", 0) |
                             getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             close_fds=True)
            return
        except OSError:
            pass
    webbrowser.open(url)


# --------------------------------------------------------------------------- console

LOG_PATH = paths.DATA_DIR / "shelfrip.log"


def use_log_file() -> bool:
    """Started without a console window (Shelfrip.exe, pythonw)? Send what would have been
    printed there to shelfrip.log in the data folder instead. Returns True if it did."""
    import sys
    if sys.stdout is not None and sys.stderr is not None:
        return False
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        if LOG_PATH.exists() and LOG_PATH.stat().st_size > 5_000_000:
            LOG_PATH.replace(LOG_PATH.with_suffix(".old.log"))
        f = open(LOG_PATH, "a", encoding="utf-8", buffering=1, errors="replace")
        sys.stdout = sys.stdout or f
        sys.stderr = sys.stderr or f
        return True
    except OSError:
        return False


def message_box(title: str, text: str) -> None:
    """A plain Windows message box (for errors when there's no console to print them to)."""
    if os.name != "nt":
        print(f"{title}: {text}")
        return
    try:
        import ctypes
        u32 = ctypes.WinDLL("user32")
        u32.MessageBoxW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint]
        u32.MessageBoxW(None, text, title, 0x10 | 0x40000)  # MB_ICONERROR | MB_TOPMOST
    except Exception:
        pass


def open_file(path: Path) -> None:
    try:
        os.startfile(str(path))  # type: ignore[attr-defined]
    except Exception:
        pass

def _console():
    import ctypes
    k32 = ctypes.WinDLL("kernel32")
    k32.GetConsoleWindow.restype = ctypes.c_void_p
    return ctypes, k32, k32.GetConsoleWindow()


def owns_console() -> bool:
    """True if the console window is ours alone (not a Command Prompt someone typed into)."""
    if os.name != "nt":
        return False
    try:
        ctypes, k32, hwnd = _console()
        if not hwnd:
            return False
        ids = (ctypes.c_uint32 * 4)()
        import sys
        # a one-file exe runs as two processes (unpacker + app) sharing the console
        return k32.GetConsoleProcessList(ids, 4) <= (2 if getattr(sys, "frozen", False) else 1)
    except Exception:
        return False


def show_console(show: bool) -> None:
    if os.name != "nt":
        return
    try:
        ctypes, _, hwnd = _console()
        if hwnd:
            u32 = ctypes.WinDLL("user32")
            u32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
            u32.ShowWindow(hwnd, 5 if show else 0)  # SW_SHOW / SW_HIDE
            if show:
                u32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
                u32.SetForegroundWindow(hwnd)
    except Exception:
        pass


# --------------------------------------------------------------------------- tray icon

class Tray:
    """The notification-area icon. `menu` is a function returning [(label, callback or None), ...]
    (None = separator), built fresh each time the menu opens so it shows the current state.
    `on_click` runs on a left click. Runs its own thread; start() returns False if it can't."""

    WM_TRAY = 0x8001  # WM_APP + 1

    def __init__(self, tip: str, on_click, menu) -> None:
        self.tip, self.on_click, self.menu = tip, on_click, menu
        self.hwnd = None
        self.taskbar_created = None  # set before the window exists: messages arrive during CreateWindowExW
        self._ready = threading.Event()
        self.ok = False

    def start(self) -> bool:
        if os.name != "nt":
            return False
        threading.Thread(target=self._run, daemon=True, name="tray").start()
        self._ready.wait(5)
        return self.ok

    # -- Win32 plumbing
    def _setup(self):
        import ctypes
        self.c = ctypes
        self.u32 = ctypes.WinDLL("user32", use_last_error=True)
        self.s32 = ctypes.WinDLL("shell32", use_last_error=True)
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        LRESULT, HWND, UINT, WPARAM, LPARAM = ctypes.c_ssize_t, ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t
        self.WNDPROC = ctypes.WINFUNCTYPE(LRESULT, HWND, UINT, WPARAM, LPARAM)

        class WNDCLASSW(ctypes.Structure):
            _fields_ = [("style", UINT), ("lpfnWndProc", self.WNDPROC), ("cbClsExtra", ctypes.c_int),
                        ("cbWndExtra", ctypes.c_int), ("hInstance", ctypes.c_void_p), ("hIcon", ctypes.c_void_p),
                        ("hCursor", ctypes.c_void_p), ("hbrBackground", ctypes.c_void_p),
                        ("lpszMenuName", ctypes.c_wchar_p), ("lpszClassName", ctypes.c_wchar_p)]

        class NOTIFYICONDATAW(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint32), ("hWnd", ctypes.c_void_p), ("uID", UINT), ("uFlags", UINT),
                        ("uCallbackMessage", UINT), ("hIcon", ctypes.c_void_p), ("szTip", ctypes.c_wchar * 128),
                        ("dwState", ctypes.c_uint32), ("dwStateMask", ctypes.c_uint32),
                        ("szInfo", ctypes.c_wchar * 256), ("uVersion", UINT), ("szInfoTitle", ctypes.c_wchar * 64),
                        ("dwInfoFlags", ctypes.c_uint32), ("guidItem", ctypes.c_ubyte * 16),
                        ("hBalloonIcon", ctypes.c_void_p)]

        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        class MSG(ctypes.Structure):
            _fields_ = [("hwnd", ctypes.c_void_p), ("message", UINT), ("wParam", WPARAM), ("lParam", LPARAM),
                        ("time", ctypes.c_uint32), ("pt", POINT), ("lPrivate", ctypes.c_uint32)]

        self.WNDCLASSW, self.NID, self.POINT, self.MSG = WNDCLASSW, NOTIFYICONDATAW, POINT, MSG
        u = self.u32
        u.DefWindowProcW.argtypes = [HWND, UINT, WPARAM, LPARAM]
        u.DefWindowProcW.restype = LRESULT
        u.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
        u.CreateWindowExW.argtypes = [ctypes.c_uint32, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32,
                                      ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                      HWND, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        u.CreateWindowExW.restype = HWND
        u.LoadImageW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, UINT, ctypes.c_int, ctypes.c_int, UINT]
        u.LoadImageW.restype = ctypes.c_void_p
        u.LoadIconW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        u.LoadIconW.restype = ctypes.c_void_p
        u.CreatePopupMenu.restype = ctypes.c_void_p
        u.AppendMenuW.argtypes = [ctypes.c_void_p, UINT, ctypes.c_size_t, ctypes.c_wchar_p]
        u.TrackPopupMenu.argtypes = [ctypes.c_void_p, UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, HWND, ctypes.c_void_p]
        u.DestroyMenu.argtypes = [ctypes.c_void_p]
        u.SetForegroundWindow.argtypes = [HWND]
        u.PostMessageW.argtypes = [HWND, UINT, WPARAM, LPARAM]
        u.GetMessageW.argtypes = [ctypes.POINTER(MSG), HWND, UINT, UINT]
        u.TranslateMessage.argtypes = [ctypes.POINTER(MSG)]
        u.DispatchMessageW.argtypes = [ctypes.POINTER(MSG)]
        u.DispatchMessageW.restype = LRESULT
        u.RegisterWindowMessageW.argtypes = [ctypes.c_wchar_p]
        u.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
        self.s32.Shell_NotifyIconW.argtypes = [ctypes.c_uint32, ctypes.POINTER(NOTIFYICONDATAW)]
        k32.GetModuleHandleW.restype = ctypes.c_void_p
        k32.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
        self.hinst = k32.GetModuleHandleW(None)

    def _nid(self, flags: int) -> "object":
        nid = self.NID()
        nid.cbSize = self.c.sizeof(self.NID)
        nid.hWnd, nid.uID, nid.uFlags = self.hwnd, 1, flags
        return nid

    def _add(self) -> bool:
        nid = self._nid(0x1 | 0x2 | 0x4)  # NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage, nid.hIcon, nid.szTip = self.WM_TRAY, self.hicon, self.tip[:127]
        return bool(self.s32.Shell_NotifyIconW(0, self.c.byref(nid)))  # NIM_ADD

    def set_tip(self, tip: str) -> None:
        self.tip = tip
        if self.hwnd:
            nid = self._nid(0x4)
            nid.szTip = tip[:127]
            self.s32.Shell_NotifyIconW(1, self.c.byref(nid))  # NIM_MODIFY

    def notify(self, title: str, text: str) -> bool:
        """A Windows notification from the tray icon (shown as a toast on Windows 10 and 11)."""
        if not self.hwnd:
            return False
        nid = self._nid(0x10)  # NIF_INFO
        nid.szInfoTitle, nid.szInfo, nid.dwInfoFlags = title[:63], text[:255], 0x4  # NIIF_USER (our icon)
        return bool(self.s32.Shell_NotifyIconW(1, self.c.byref(nid)))

    def remove(self) -> None:
        if self.hwnd:
            self.s32.Shell_NotifyIconW(2, self.c.byref(self._nid(0)))  # NIM_DELETE

    def _show_menu(self) -> None:
        u = self.u32
        items = self.menu()
        h = u.CreatePopupMenu()
        actions = {}
        for n, item in enumerate(items, start=1):
            if item is None:
                u.AppendMenuW(h, 0x800, 0, None)  # MF_SEPARATOR
                continue
            label, fn = item
            u.AppendMenuW(h, 0 if fn else 0x1, n, label)  # MF_STRING, or MF_GRAYED for a heading
            actions[n] = fn
        pt = self.POINT()
        u.GetCursorPos(self.c.byref(pt))
        u.SetForegroundWindow(self.hwnd)
        cmd = u.TrackPopupMenu(h, 0x0100 | 0x0002 | 0x0020, pt.x, pt.y, 0, self.hwnd, None)  # RETURNCMD|RIGHTBUTTON|BOTTOMALIGN
        u.PostMessageW(self.hwnd, 0, 0, 0)
        u.DestroyMenu(h)
        fn = actions.get(cmd)
        if fn:
            threading.Thread(target=fn, daemon=True).start()

    def _proc(self, hwnd, msg, wparam, lparam):
        if msg == self.WM_TRAY:
            ev = lparam & 0xFFFF
            if ev == 0x0202:  # WM_LBUTTONUP
                threading.Thread(target=self.on_click, daemon=True).start()
            elif ev == 0x0205:  # WM_RBUTTONUP
                self._show_menu()
            return 0
        if msg == self.taskbar_created:  # Explorer restarted: put the icon back
            self._add()
            return 0
        return self.u32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _run(self) -> None:
        try:
            self._setup()
            u = self.u32
            self._wndproc = self.WNDPROC(self._proc)  # keep a reference, or it's garbage-collected
            wc = self.WNDCLASSW()
            wc.lpfnWndProc, wc.hInstance, wc.lpszClassName = self._wndproc, self.hinst, "ShelfripTray"
            u.RegisterClassW(self.c.byref(wc))
            self.taskbar_created = u.RegisterWindowMessageW("TaskbarCreated")
            self.hwnd = u.CreateWindowExW(0, "ShelfripTray", "Shelfrip", 0, 0, 0, 0, 0, None, None, self.hinst, None)
            try:
                icon = ICON_PATH if ICON_PATH.exists() else write_icon()
                px = u.GetSystemMetrics(49) or 16  # SM_CXSMICON: the tray's icon size at this display scale
                self.hicon = u.LoadImageW(None, str(icon), 1, px, px, 0x10)  # IMAGE_ICON, LR_LOADFROMFILE
            except OSError:
                self.hicon = None
            if not self.hicon:
                self.hicon = u.LoadIconW(None, self.c.c_void_p(32512))  # IDI_APPLICATION
            self.ok = bool(self.hwnd) and self._add()
        except Exception as exc:
            print(f"(no tray icon: {exc})")
            self.ok = False
        finally:
            self._ready.set()
        if not self.ok:
            return
        msg = self.MSG()
        while u.GetMessageW(self.c.byref(msg), None, 0, 0) > 0:
            u.TranslateMessage(self.c.byref(msg))
            u.DispatchMessageW(self.c.byref(msg))


# --------------------------------------------------------------------------- pickers

def pick(kind: str = "folder", start: str = "", title: str = "") -> str | None:
    """Windows' own folder (or .exe file) picker, for the Settings page. '' if cancelled,
    None if there's no picker on this system."""
    if os.name != "nt":
        return None
    esc = lambda x: str(x or "").replace("'", "''")
    if kind == "file":
        ps = ("Add-Type -AssemblyName System.Windows.Forms;"
              "$d = New-Object System.Windows.Forms.OpenFileDialog;"
              f"$d.Title = '{esc(title) or 'Choose the program'}'; $d.Filter = 'Programs (*.exe)|*.exe';"
              f"if ('{esc(start)}') {{ $d.InitialDirectory = Split-Path -Parent '{esc(start)}' }};")
    else:
        ps = ("Add-Type -AssemblyName System.Windows.Forms;"
              "$d = New-Object System.Windows.Forms.FolderBrowserDialog;"
              f"$d.Description = '{esc(title) or 'Choose a folder'}'; $d.ShowNewFolderButton = $true;"
              f"if ('{esc(start)}') {{ $d.SelectedPath = '{esc(start)}' }};")
    ps += ("$o = New-Object System.Windows.Forms.Form; $o.TopMost = $true;"
           "if ($d.ShowDialog($o) -eq 'OK') { [Console]::OutputEncoding = [Text.Encoding]::UTF8;"
           + ("$d.FileName" if kind == "file" else "$d.SelectedPath") + " }")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", ps], capture_output=True,
                           timeout=600, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return r.stdout.decode("utf-8", "replace").strip()
    except Exception:
        return None
