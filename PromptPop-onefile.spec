# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 单文件（onefile）打包配置：产物就是一个 PromptPop.exe。
# 用法：
#   pyinstaller PromptPop-onefile.spec --noconfirm ^
#       --distpath "C:/Users/y/Desktop" --workpath build_onefile
#
# 说明：onefile 每次启动会先把依赖解压到临时目录（首次/冷启动约 3-8 秒），
# 换来的是「只有一个 exe，可直接放桌面/拷走」。若更在意启动速度，
# 用 PromptPop.spec（one-folder）——那个产物是 dist_v7/PromptPop/PromptPop.exe。
block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        'uiautomation', 'comtypes', 'comtypes.client',
        'pynput.keyboard._win32', 'pynput.mouse._win32',
        'keyring', 'keyring.backends.Windows',
        'jaraco.classes', 'jaraco.functools', 'jaraco.context',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 本机 PyInstaller 会扫进无关重型科学计算库（大脑记忆#198：构建极慢/产物臃肿）
        'sklearn', 'scipy', 'matplotlib', 'sympy', 'PIL', 'pandas', 'numpy',
        'torch', 'torchvision', 'cv2', 'IPython', 'tkinter',
        'PyQt5', 'PyQt6', 'PySide2',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='PromptPop',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,   # UPX 压坏 Qt DLL：窗口首启不渲染/文字发虚（大脑记忆#123）
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
    version='version_info.py',
)
