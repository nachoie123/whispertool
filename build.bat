@echo off
echo ============================================
echo   Building WisprTool executable...
echo ============================================
echo.

pip install pyinstaller >nul 2>&1

pyinstaller --onefile --noconsole --name WisprTool ^
    --add-data "VERSION;." ^
    --hidden-import=pynput.keyboard._win32 ^
    --hidden-import=pynput.mouse._win32 ^
    --collect-all ctranslate2 ^
    --collect-all faster_whisper ^
    --collect-all onnxruntime ^
    --exclude-module torch ^
    --exclude-module torchaudio ^
    --exclude-module torchvision ^
    --exclude-module matplotlib ^
    --exclude-module pandas ^
    --exclude-module numba ^
    --exclude-module llvmlite ^
    --exclude-module scipy ^
    --exclude-module tensorflow ^
    --exclude-module tensorboard ^
    --exclude-module openpyxl ^
    --exclude-module PIL ^
    --exclude-module cv2 ^
    --exclude-module sklearn ^
    --exclude-module jupyter ^
    --exclude-module notebook ^
    --exclude-module pytest ^
    main.py

echo.
if exist "dist\WisprTool.exe" (
    echo ============================================
    echo   SUCCESS! Find your app at:
    echo   dist\WisprTool.exe
    echo ============================================
    echo.
    echo   Share this single file with anyone.
    echo   First run will download the Whisper model.
) else (
    echo   BUILD FAILED - check errors above.
)
echo.
pause
