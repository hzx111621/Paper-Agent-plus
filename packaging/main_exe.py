from __future__ import annotations

import os
import sys
import threading
import webbrowser
from pathlib import Path

import uvicorn

from src.api import create_app
from src.utils import get_logger, setup_logging


def _application_root() -> Path:
    """返回程序运行时使用的根目录。

    中文说明：
    开发环境里，根目录是这个文件所在项目的上一级目录；打成 exe 后，
    根目录改为 exe 文件所在的目录。这样 config、data、logs 和前端页面
    都会放在用户看得见、也可以修改的目录中。
    """

    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def _open_browser() -> None:
    """在服务启动后打开本地网页。"""

    webbrowser.open("http://127.0.0.1:8000")


def main() -> None:
    """启动打包版 Paper-Agent。"""

    # 中文注释：所有相对路径都从 exe 同级目录计算，避免双击启动时使用了错误的工作目录。
    os.chdir(_application_root())
    setup_logging()
    logger = get_logger(__name__)
    app = create_app()

    # 中文注释：浏览器延迟一点打开，给本地服务留出初始化时间；线程设为守护线程，
    # 关闭服务时不会因为这个定时任务把程序继续挂住。
    browser_timer = threading.Timer(1.2, _open_browser)
    browser_timer.daemon = True
    browser_timer.start()

    logger.info("准备启动 Paper-Agent exe", extra={"host": "127.0.0.1", "port": 8000, "reload": False})
    # 中文注释：exe 不需要开发环境的热重载；直接传入 app 对象也能避免
    # uvicorn 再次按字符串导入入口文件，从而减少打包后的导入问题。
    uvicorn.run(app, host="127.0.0.1", port=8000, reload=False, log_config=None)


if __name__ == "__main__":
    main()
