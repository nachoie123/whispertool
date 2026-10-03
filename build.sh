#!/bin/bash
# Empaqueta WhisperTool.app en dist/ y pasa el chequeo de seguridad (tools/seguridad.py).
# Solo Apple Silicon (arm64): la transcripción va en la GPU con mlx, que no existe para Intel.
# Después: tools/dmg.sh -> dist/WhisperTool.dmg
set -e
cd "$(dirname "$0")"
[ "$(uname -m)" = arm64 ] || { echo "Hay que construirla en un Mac con Apple Silicon (mlx es solo arm64)"; exit 1; }

# Nada sin commitear entra en el paquete. WT_ALLOW_DIRTY=1 solo para probar cambios aún sin commit.
SUCIO=$(git status --porcelain)
if [ -n "$SUCIO" ]; then
  echo "$SUCIO"
  [ "$WT_ALLOW_DIRTY" = 1 ] || { echo "Hay ficheros sin commitear: commitea o bórralos antes de empaquetar."; exit 1; }
  echo "AVISO: WT_ALLOW_DIRTY=1 -> se empaqueta con esos cambios sin commitear"
fi

PY=/Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12
[ -x .venv/bin/python ] || { $PY -m venv .venv && .venv/bin/pip install -q pip==26.2.1; }
# mlx: la rueda de macOS 14. pip cogería la de la versión del Mac que construye (p. ej. macOS 26)
# y la app no abriría en Macs más antiguos.
if ! grep -q macosx_14_0 .venv/lib/python3.12/site-packages/mlx-0.32.3.dist-info/WHEEL 2>/dev/null; then
  mkdir -p build/wheels
  .venv/bin/pip download -q --no-deps --only-binary=:all: --platform macosx_14_0_arm64 --python-version 3.12 \
    --implementation cp -d build/wheels mlx==0.32.3 mlx-metal==0.32.3
  .venv/bin/pip install -q --no-deps --force-reinstall build/wheels/mlx-0.32.3-*.whl build/wheels/mlx_metal-0.32.3-*.whl
  # direct_url.json guarda la ruta absoluta de la rueda (/Users/<usuario>/…) y acabaría dentro del .app
  rm -f .venv/lib/python3.12/site-packages/mlx*-0.32.3.dist-info/direct_url.json
fi
# Todo fijado, también lo indirecto (--no-deps). Sin torch: mlx-whisper lo pide, pero solo para convertir modelos.
.venv/bin/pip install -q --no-deps \
  altgraph==0.17.5 anyio==4.15.1 av==19.0.1 certifi==2026.7.22 cffi==2.1.1 charset-normalizer==3.5.2 click==8.5.0 \
  ctranslate2==4.8.2 faster-whisper==1.2.1 filelock==4.0.9 flatbuffers==25.12.19 fsspec==2026.9.0 h11==0.16.0 \
  hf-xet==1.6.0 httpcore==1.0.9 httpx==0.28.1 huggingface_hub==1.33.0 idna==3.20 llvmlite==0.50.0 macholib==1.16.4 \
  mlx-whisper==0.4.3 more-itertools==11.1.0 MouseInfo==0.1.3 numba==0.68.0 numpy==2.5.3 onnxruntime==1.30.0 \
  packaging==26.3 protobuf==7.36.2 PyAutoGUI==0.9.54 pycparser==3.0 PyGetWindow==0.0.9 pyinstaller==6.22.3 \
  pyinstaller-hooks-contrib==2026.8 PyMsgBox==2.0.1 pynput==1.8.2 pyobjc-core==12.2.2 \
  pyobjc-framework-ApplicationServices==12.2.2 pyobjc-framework-AVFoundation==12.2.2 pyobjc-framework-Cocoa==12.2.2 \
  pyobjc-framework-CoreAudio==12.2.2 pyobjc-framework-CoreMedia==12.2.2 pyobjc-framework-CoreText==12.2.2 \
  pyobjc-framework-Quartz==12.2.2 pyperclip==1.11.0 PyRect==0.2.0 PyScreeze==1.0.1 pytweening==1.2.0 PyYAML==6.0.3 \
  regex==2026.9.29 requests==2.34.2 rubicon-objc==0.5.7 scipy==1.18.1 setuptools==84.0.0 six==1.17.0 \
  sounddevice==0.5.6 tiktoken==0.14.0 tokenizers==0.23.2 tqdm==4.70.1 typing_extensions==4.16.0 urllib3==2.8.0

# Icono: icon.png (1024 px) -> .icns
rm -rf build/WhisperTool.iconset && mkdir -p build/WhisperTool.iconset
for s in 16 32 128 256 512; do
  sips -z $s $s icon.png --out build/WhisperTool.iconset/icon_${s}x${s}.png >/dev/null
  sips -z $((s * 2)) $((s * 2)) icon.png --out build/WhisperTool.iconset/icon_${s}x${s}@2x.png >/dev/null
done
iconutil -c icns build/WhisperTool.iconset -o build/WhisperTool.icns

rm -rf build/WhisperTool dist/WhisperTool dist/WhisperTool.app
# caché propia de PyInstaller: la común (~/Library/Application Support/pyinstaller) la borra --clean
# y choca si otra app se está empaquetando a la vez
PYINSTALLER_CONFIG_DIR="$PWD/build/pyinstaller-cache" .venv/bin/pyinstaller --noconfirm --clean WhisperTool.spec > build/pyinstaller.log 2>&1 || { tail -30 build/pyinstaller.log; exit 1; }
tail -2 build/pyinstaller.log
du -sh dist/WhisperTool.app

# El macOS mínimo del Info.plist tiene que cubrir el que pide cada binario (minos de LC_BUILD_VERSION):
# si es más bajo, la app se deja instalar en un Mac viejo y se cae al abrir.
MIN_PLIST=$(plutil -extract LSMinimumSystemVersion raw dist/WhisperTool.app/Contents/Info.plist)
MIN_REAL=$(find dist/WhisperTool.app -type f \( -name "*.so" -o -name "*.dylib" -o -perm +111 \) -exec otool -l {} + 2>/dev/null \
  | awk '/LC_BUILD_VERSION/{b=1} b&&/ minos /{print $2; b=0} /LC_VERSION_MIN_MACOSX/{v=1} v&&/ version /{print $2; v=0}' \
  | sort -V | tail -1)
echo "macOS mínimo: Info.plist $MIN_PLIST, binarios $MIN_REAL"
if [ "$(printf '%s\n' "$MIN_REAL" "$MIN_PLIST" | sort -V | tail -1)" != "$MIN_PLIST" ]; then
  echo "FALLA: algún binario pide macOS $MIN_REAL y el Info.plist dice $MIN_PLIST: sube LSMinimumSystemVersion en WhisperTool.spec"
  exit 1
fi
.venv/bin/python tools/seguridad.py dist/WhisperTool.app
