# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

datas = [
    ('logo', 'logo'),
    ('fonts', 'fonts'),
    ('sounds', 'sounds'),
    ('modules', 'modules'),
    ('orb.html', '.'),
    ('overlay.html', '.'),
]
datas += collect_data_files('faster_whisper')
datas += collect_data_files('ctranslate2')
datas += collect_data_files('onnxruntime')
datas += collect_data_files('tokenizers')

# Dependency analysis skips cudnn64_9.dll. CPU int8 still ships it with the wheel.
binaries = collect_dynamic_libs('ctranslate2')
binaries += collect_dynamic_libs('onnxruntime')
binaries += collect_dynamic_libs('tokenizers')

hiddenimports = [
    'faster_whisper',
    'ctranslate2',
    'onnxruntime',
    'tokenizers',
    'huggingface_hub',
    'sounddevice',
    'numpy',
    'PIL.Image',
    'websocket',
    'keyboard',
    'mss',
    'certifi',
    'PySide6.QtSvg',
    'PySide6.QtWebEngineCore',
    'PySide6.QtWebEngineWidgets',
    'keyring.backends.Windows',
]
hiddenimports += collect_submodules('keyring.backends')
hiddenimports += collect_submodules('win32ctypes.core.ctypes')


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Yogi',
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
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Yogi',
)
