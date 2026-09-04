# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules


PACKAGING_DIR = Path(SPECPATH)
PROJECT_ROOT = PACKAGING_DIR.parent

# 中文说明：项目中的 Agent、路由和工作流有一部分是间接导入的，
# 因此把 src 下的 Python 子模块显式收集，避免 exe 运行到某个功能时才发现模块缺失。
hiddenimports = collect_submodules("src")
datas = []
binaries = []

# 中文说明：这些依赖包含动态加载的子模块或运行时资源。收集它们的完整运行文件，
# 可以让检索、全文阅读、向量库和模型调用在 exe 中保持与开发环境一致。
for package_name in ("chromadb", "langgraph", "fastapi", "uvicorn", "openai", "anthropic", "pypdf"):
    package_datas, package_binaries, package_hiddenimports = collect_all(package_name)
    datas.extend(package_datas)
    binaries.extend(package_binaries)
    hiddenimports.extend(package_hiddenimports)

analysis = Analysis(
    [str(PACKAGING_DIR / "main_exe.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(analysis.pure)

# 中文说明：EXE 只负责生成启动文件，真正的依赖文件由 COLLECT 放到同一个目录，
# 这样 config、data、logs 和前端静态文件可以清楚地放在 exe 旁边。
exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="Paper-Agent",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)

coll = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="Paper-Agent",
)
