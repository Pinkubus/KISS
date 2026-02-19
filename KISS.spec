# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for KISS (Spreeder) application.
Builds a standalone Windows executable that runs in the background.
"""

import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# Collect all customtkinter data files (themes, assets)
ctk_datas = collect_data_files('customtkinter')

a = Analysis(
    ['KISS.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('.env', '.'),  # Include .env file for API key
        ('settings.json', '.'),  # Include settings
    ] + ctk_datas,
    hiddenimports=[
        'customtkinter',
        'tkinter',
        'tkinter.ttk',
        'PIL',
        'PIL._tkinter_finder',
        'pyperclip',
        'keyboard',
        'openai',
        'httpx',
        'httpcore',
        'anyio',
        'certifi',
        'dotenv',
        'pystray',
        'PIL.Image',
    ] + collect_submodules('openai'),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib',
        'numpy',
        'pandas',
        'scipy',
        'pytest',
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
    name='KISS',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # No console window - runs in background
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # Add icon path here if you have one: icon='icon.ico'
    version=None,
    uac_admin=False,  # Don't require admin - keyboard hook works without it
)
