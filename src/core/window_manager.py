from __future__ import annotations

import time
from typing import List, NamedTuple

import win32con
import win32gui


class WindowInfo(NamedTuple):
    hwnd: int
    title: str


def is_window_valid(hwnd: int) -> bool:
    try:
        return bool(win32gui.IsWindow(hwnd) and win32gui.IsWindowVisible(hwnd))
    except Exception:
        return False


def get_window_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    if not is_window_valid(hwnd):
        return None
    try:
        return win32gui.GetWindowRect(hwnd)
    except Exception:
        return None


def find_all_windows(title_keyword: str) -> List[WindowInfo]:
    matches: List[WindowInfo] = []
    keyword = title_keyword.lower()

    def _enum_handler(hwnd: int, _context: object) -> bool:
        if not win32gui.IsWindowVisible(hwnd):
            return True
        title = win32gui.GetWindowText(hwnd)
        if not title:
            return True
        if keyword in title.lower():
            matches.append(WindowInfo(hwnd=hwnd, title=title))
        return True

    win32gui.EnumWindows(_enum_handler, None)
    return matches


def filter_windows(hwnd_list: List[int] | List[WindowInfo]) -> List[WindowInfo]:
    filtered: List[WindowInfo] = []
    for entry in hwnd_list:
        hwnd = entry.hwnd if isinstance(entry, WindowInfo) else int(entry)
        if not is_window_valid(hwnd):
            continue
        try:
            title = win32gui.GetWindowText(hwnd)
        except Exception:
            continue
        if not title:
            continue
        filtered.append(WindowInfo(hwnd=hwnd, title=title))
    return filtered


def bring_to_front(hwnd: int, wait_timeout: float = 1.0) -> bool:
    if not is_window_valid(hwnd):
        return False

    try:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
        win32gui.SetForegroundWindow(hwnd)
        win32gui.BringWindowToTop(hwnd)
    except Exception:
        return False

    deadline = time.time() + wait_timeout
    while time.time() < deadline:
        try:
            if win32gui.GetForegroundWindow() == hwnd:
                return True
        except Exception:
            break
        time.sleep(0.05)
    return False
