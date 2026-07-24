#!/bin/bash
echo "============================================"
echo "  Building WisprTool executable..."
echo "============================================"
echo

pip3 install pyinstaller >/dev/null 2>&1

pyinstaller --onefile --noconsole --name WisprTool \
    --add-data "VERSION:." \
    --hidden-import=pynput.keyboard._darwin \
    --hidden-import=pynput.mouse._darwin \
    --collect-all ctranslate2 \
    --collect-all faster_whisper \
    --collect-all onnxruntime \
    --exclude-module torch \
    --exclude-module torchaudio \
    --exclude-module torchvision \
    --exclude-module matplotlib \
    --exclude-module pandas \
    --exclude-module numba \
    --exclude-module llvmlite \
    --exclude-module scipy \
    --exclude-module tensorflow \
    --exclude-module tensorboard \
    --exclude-module openpyxl \
    --exclude-module PIL \
    --exclude-module cv2 \
    --exclude-module sklearn \
    --exclude-module jupyter \
    --exclude-module notebook \
    --exclude-module pytest \
    main.py

echo
if [ -f "dist/WisprTool" ]; then
    echo "============================================"
    echo "  SUCCESS! Find your app at:"
    echo "  dist/WisprTool"
    echo "============================================"
    echo
    echo "  On Mac: grant Accessibility permissions"
    echo "  System Settings > Privacy > Accessibility"
else
    echo "  BUILD FAILED - check errors above."
fi
