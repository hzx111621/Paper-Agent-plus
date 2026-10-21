from __future__ import annotations

import asyncio
import base64
import ctypes
import multiprocessing
import os
import shutil
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pystray
import uvicorn
import webview
from PIL import Image


# 中文说明：首次运行时，Windows 可能需要先检查 EXE、解压资源并建立本地数据库。
# 较慢电脑上这段准备时间可能超过一分钟，因此给它留出更充足但仍有限的等待时间。
_SERVICE_STARTUP_TIMEOUT_SECONDS = 180


def _user_data_root(frozen: bool, project_root: Path) -> Path:
    """返回安装版可长期写入的本机数据目录。"""

    if not frozen:
        # 中文说明：开发时继续把数据放在项目目录，便于调试；只有发布版才使用用户目录。
        return project_root
    local_app_data = os.environ.get("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return base / "Paper-Agent"


def _service_is_ready(url: str) -> bool:
    """请求一个很轻量的接口，确认本地服务真的已经能够接收页面请求。"""

    try:
        # 中文说明：不能只看后台线程是否存在。只有这个请求成功，才说明页面可以正常连接服务。
        with urllib.request.urlopen(f"{url}/webui/bootstrap", timeout=2) as response:
            return 200 <= response.status < 300
    except (OSError, TimeoutError, urllib.error.URLError):
        return False


def _read_recent_log_hint(log_dir: Path) -> str:
    """从日志末尾摘取最关键的几行，方便其他电脑直接看到启动失败原因。"""

    try:
        lines = (log_dir / "app.log").read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""

    # 中文说明：优先显示错误行；如果还没有错误行，就显示最后的启动记录。
    error_lines = [line for line in lines[-120:] if "ERROR" in line or "CRITICAL" in line]
    selected_lines = error_lines[-3:] or lines[-8:]
    return "\n".join(selected_lines)[-1200:]


class DesktopApi:
    """提供给内置页面的少量桌面能力，目前只负责可靠保存导出文件。"""

    def __init__(self) -> None:
        # 中文说明：pywebview 会递归扫描 API 对象的公开属性并暴露给页面。
        # 窗口对象必须用下划线保存，否则它的原生无障碍对象会被无限递归扫描，导致界面卡死。
        self._window: webview.Window | None = None

    def save_export(self, filename: str, content_base64: str) -> dict[str, object]:
        """弹出 Windows 保存对话框，并把页面准备好的文件写入用户选定位置。"""

        if self._window is None:
            return {"saved": False, "error": "桌面窗口尚未准备完成"}
        safe_name = Path(str(filename or "导出文件")).name or "导出文件"
        try:
            content = base64.b64decode(str(content_base64 or ""), validate=True)
        except (ValueError, TypeError):
            return {"saved": False, "error": "导出文件内容无效"}
        downloads = Path.home() / "Downloads"
        selected = self._window.create_file_dialog(
            webview.FileDialog.SAVE,
            directory=str(downloads if downloads.exists() else Path.home()),
            save_filename=safe_name,
        )
        if not selected:
            return {"saved": False, "cancelled": True}
        target = Path(selected[0])
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        except OSError as exc:
            return {"saved": False, "error": f"无法保存文件：{exc}"}
        return {"saved": True}


def main() -> None:
    """启动网页服务，并在 Windows 右下角显示打开、退出菜单。"""
    frozen = getattr(sys, "frozen", False)
    root = Path(sys.executable).resolve().parent if frozen else Path(__file__).resolve().parents[1]
    resources = Path(sys._MEIPASS) if frozen else root
    data_root = _user_data_root(frozen, root)
    # 页面和图片会临时解压；用户填写的密钥和论文数据需要长期保存。
    # 因此安装版放到当前 Windows 用户目录，避免装到 Program Files 后没有写入权限。
    data_root.mkdir(parents=True, exist_ok=True)
    os.chdir(data_root)
    for directory in ("config", "data", "logs"):
        (data_root / directory).mkdir(parents=True, exist_ok=True)
    for filename in ("model.json", "system.yaml"):
        target = data_root / "config" / filename
        if not target.exists():
            shutil.copyfile(resources / "packaging" / "defaults" / filename, target)

    # 无黑色窗口时没有控制台可写，日志仍会正常写入 logs 文件夹。
    os.environ["PAPERS_LOG_ENABLE_CONSOLE"] = "false"
    os.environ["PAPERS_LOG_DIR"] = str(data_root / "logs")
    from src.api import create_app
    from src.utils import get_logger, setup_logging

    setup_logging()
    logger = get_logger(__name__)
    # 本机已有旧版运行时，使用空闲端口，避免新 EXE 打开旧版网页。
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.bind(("127.0.0.1", 8000))
    except OSError:
        listener.bind(("127.0.0.1", 0))
    url = f"http://127.0.0.1:{listener.getsockname()[1]}"
    # 中文说明：loop="none" 禁止 Uvicorn 自己重新指定 Proactor 模式，
    # 这样 serve 函数中为 Windows 设置的 Selector 模式才会真正生效。
    server = uvicorn.Server(
        uvicorn.Config(create_app(), log_config=None, loop="none", timeout_graceful_shutdown=5)
    )

    window_holder: list[webview.Window] = []
    exiting = threading.Event()
    startup_error: list[str] = []

    def show_window(_icon: pystray.Icon | None = None, _item: pystray.MenuItem | None = None) -> None:
        """双击托盘图标或点击菜单时，恢复软件主窗口。"""
        if not window_holder:
            return
        window_holder[0].show()
        window_holder[0].restore()

    def quit_app(icon: pystray.Icon, _item: pystray.MenuItem | None = None) -> None:
        """从托盘退出时，同时关闭桌面窗口和本地服务。"""
        if exiting.is_set():
            return
        exiting.set()
        server.should_exit = True
        icon.stop()
        if window_holder:
            window_holder[0].destroy()

    icon = pystray.Icon(
        "Paper-Agent",
        Image.open(resources / "front" / "dist" / "hohai-app-icon.png"),
        "Paper-Agent · 河海大学",
        menu=pystray.Menu(
            pystray.MenuItem("打开 Paper-Agent", show_window, default=True),
            pystray.MenuItem("退出", quit_app),
        ),
    )

    def serve() -> None:
        """网页服务在后台运行，让托盘菜单始终可以点击。"""
        try:
            if sys.platform == "win32":
                # 中文说明：部分 Windows 电脑的默认 Proactor 模式会卡在本地监听端口的初始化阶段。
                # 本软件只使用普通 HTTP 本地服务，改用 Selector 模式更稳定，不影响内置页面和托盘功能。
                asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
            logger.info("开始启动本地网页服务", extra={"url": url})
            server.run(sockets=[listener])
            if not server.started and not exiting.is_set():
                # 中文说明：正常退出前服务一定会设置 started；没有设置就退出代表启动过程被中断。
                startup_error.append("本地服务在完成启动前退出")
                logger.error("本地网页服务在完成启动前退出")
        except BaseException as exc:
            startup_error.append(f"{type(exc).__name__}: {exc}")
            logger.exception("网页服务启动失败")
        finally:
            if not exiting.is_set():
                exiting.set()
                icon.stop()
                if window_holder:
                    window_holder[0].destroy()

    worker = threading.Thread(target=serve, daemon=True)
    worker.start()
    deadline = time.monotonic() + _SERVICE_STARTUP_TIMEOUT_SECONDS
    service_ready = False
    while worker.is_alive() and time.monotonic() < deadline:
        if _service_is_ready(url):
            service_ready = True
            break
        time.sleep(0.2)
    if not service_ready:
        # 中文说明：服务启动失败时先通知后台线程停止，避免进程退出前残留一个无响应服务。
        exiting.set()
        server.should_exit = True
        worker.join(timeout=3)
        listener.close()
        detail = startup_error[-1] if startup_error else _read_recent_log_hint(data_root / "logs")
        detail_text = f"\n\n启动记录：\n{detail}" if detail else ""
        raise RuntimeError(
            f"本地服务未能在 {_SERVICE_STARTUP_TIMEOUT_SECONDS} 秒内启动，请查看 {data_root / 'logs'}。{detail_text}"
        )
    logger.info("本地网页服务已就绪", extra={"url": url})

    desktop_api = DesktopApi()
    window = webview.create_window(
        "Paper-Agent · 河海大学",
        url,
        width=1440,
        height=900,
        min_size=(1050, 680),
        background_color="#f4f7fb",
        text_select=True,
        js_api=desktop_api,
    )
    window_holder.append(window)
    desktop_api._window = window

    def on_closing() -> bool:
        """点击关闭时，让用户选择最小化到托盘、退出或取消。"""
        if exiting.is_set():
            return True
        choice = ctypes.windll.user32.MessageBoxW(
            None,
            "是否最小化到系统托盘？\n\n是：最小化到托盘\n否：退出软件\n取消：返回软件",
            "关闭 Paper-Agent",
            0x23,
        )
        if choice == 6:
            window.hide()
            return False
        if choice == 7:
            exiting.set()
            server.should_exit = True
            icon.stop()
            return True
        return False

    def on_closed() -> None:
        """窗口确认退出后，停止仍在后台运行的服务。"""
        exiting.set()
        server.should_exit = True
        icon.stop()

    window.events.closing += on_closing
    window.events.closed += on_closed

    try:
        # pywebview 在主线程运行桌面窗口，托盘菜单由它启动的后台线程处理。
        webview.start(
            icon.run,
            debug=False,
            private_mode=False,
            storage_path=str(data_root / "data" / "webview"),
        )
    finally:
        exiting.set()
        server.should_exit = True
        icon.stop()
        if worker.ident is not None:
            worker.join(timeout=8)
        listener.close()


if __name__ == "__main__":
    # 正确识别依赖库启动的子进程，避免子进程重复打开软件。
    multiprocessing.freeze_support()
    try:
        main()
    except Exception as exc:
        ctypes.windll.user32.MessageBoxW(None, f"无法启动 Paper-Agent：{exc}", "Paper-Agent", 0x10)
        raise
