# -*- mode: python ; coding: utf-8 -*-
# PyInstaller one-folder 打包配置。
# 用法： pyinstaller PromptPop.spec
# 产物： dist/PromptPop/PromptPop.exe
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
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name='PromptPop',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
    version='version_info.py',
)
coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='PromptPop',
)
