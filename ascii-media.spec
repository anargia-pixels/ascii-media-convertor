# PyInstaller build for the standalone ascii-media binary.
# Run: uv run pyinstaller ascii-media.spec
# The imageio-ffmpeg hook bundles the ffmpeg binary.

from PyInstaller.utils.hooks import copy_metadata

a = Analysis(
    ["src/ascii_media/__main__.py"],
    pathex=["src"],
    datas=[
        ("src/ascii_media/assets", "ascii_media/assets"),
        *copy_metadata("ascii-media"),  # --version reads the package metadata
    ],
    excludes=["tkinter"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    name="ascii-media",
    console=True,
    upx=False,
)
