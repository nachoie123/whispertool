# -*- mode: python -*-
# Receta de WhisperTool.app para PyInstaller (la usa build.sh). Solo Apple Silicon:
# la transcripción va en la GPU con mlx, que no existe para Intel.
from PyInstaller.utils.hooks import collect_all

version = open("VERSION").read().strip()

datas = [("VERSION", ".")]
binaries, hiddenimports = [], []
# mlx: libmlx.dylib + mlx.metallib (los kernels de la GPU); mlx_whisper y faster_whisper: sus assets
# (tokenizer, filtros mel, el VAD de Silero); hf_xet: el descargador de Hugging Face, que se importa a escondidas.
for pkg in ("mlx", "mlx_whisper", "faster_whisper", "ctranslate2", "hf_xet"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    ["main.py"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    # torch solo lo usa mlx_whisper/torch_whisper.py para convertir modelos; la app no lo toca
    excludes=["torch", "matplotlib", "pandas", "IPython", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="WhisperTool",
    console=False,
    target_arch="arm64",
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="WhisperTool", upx=False)
app = BUNDLE(
    coll,
    name="WhisperTool.app",
    icon="build/WhisperTool.icns",
    bundle_identifier="com.nachosanbenito.whispertool",
    version=version,
    info_plist={
        "CFBundleName": "WhisperTool",
        "CFBundleDisplayName": "WhisperTool",
        "CFBundleShortVersionString": version,
        "CFBundleVersion": version,
        "NSHighResolutionCapable": True,
        # Lo que macOS enseña al pedir el micrófono la primera vez
        "NSMicrophoneUsageDescription": (
            "WhisperTool listens only while you hold the hotkey, to turn your speech into text. "
            "Transcription happens on this Mac: your audio never leaves it."
        ),
        # mlx se instala con la rueda de macOS 14 (build.sh): por debajo no arranca
        "LSMinimumSystemVersion": "14.0",
        "LSArchitecturePriority": ["arm64"],
        "LSRequiresNativeExecution": True,
        # Sin LSUIElement: no hay icono en la barra de menús; la app es su propio icono del Dock
        # y su ventana de ajustes. Accesibilidad e Input Monitoring no tienen clave en Info.plist:
        # macOS las pide con su propio diálogo (main.py dice dónde activarlas si faltan).
    },
)
