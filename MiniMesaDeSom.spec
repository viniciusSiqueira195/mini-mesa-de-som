from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_dynamic_libs, copy_metadata


datas = collect_data_files("mini_mesa", excludes=["assets/sounds/**"])
datas.append(("README.md", "."))
binaries = []
hiddenimports = ["markdown.extensions.fenced_code", "markdown.extensions.sane_lists", "markdown.extensions.toc"]

package_datas, package_binaries, package_hiddenimports = collect_all("pedalboard")
datas += package_datas
binaries += package_binaries
hiddenimports += package_hiddenimports

binaries += collect_dynamic_libs("pyrnnoise")
datas += copy_metadata("pyrnnoise")

analysis = Analysis(
    ["tools/frozen_entry.py"],
    pathex=["."],
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

executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="MiniMesaDeSom",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
)

bundle = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="MiniMesaDeSom",
)
