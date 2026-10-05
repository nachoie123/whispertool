#!/bin/bash
# Compila WhisperTool.app (sin Xcode) y lo instala en /Applications.
# Firma con el certificado de desarrollo (identificador estable): recompilar NO borra los permisos de micro/accesibilidad.
set -e
cd "$(dirname "$0")"
APP=build/WhisperTool.app
rm -rf "$APP"; mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
swiftc -O -swift-version 5 -parse-as-library -o "$APP/Contents/MacOS/WhisperTool" WhisperTool.swift
cat > "$APP/Contents/Info.plist" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleName</key><string>WhisperTool</string>
<key>CFBundleDisplayName</key><string>WhisperTool</string>
<key>CFBundleIdentifier</key><string>com.nacho.whispertool</string>
<key>CFBundleExecutable</key><string>WhisperTool</string>
<key>CFBundleIconFile</key><string>WhisperTool</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleShortVersionString</key><string>2.0</string>
<key>CFBundleVersion</key><string>2</string>
<key>LSMinimumSystemVersion</key><string>14.0</string>
<key>LSUIElement</key><true/>
<key>NSHighResolutionCapable</key><true/>
<key>NSMicrophoneUsageDescription</key><string>WhisperTool escucha solo mientras mantienes ⌃⌥.</string>
<key>NSSpeechRecognitionUsageDescription</key><string>Para enseñarte el texto en vivo mientras dictas, en tu Mac.</string>
</dict></plist>
PL
cp icono/WhisperTool.icns sonidos/*.wav "$APP/Contents/Resources/"
ID="${SIGN_ID:-Apple Development: nsanbenitop@icloud.com (9X6V6UWR7F)}"; security find-identity -v -p codesigning | grep -q "$ID" || ID=-   # sin ese certificado: firma ad-hoc
codesign --force -s "$ID" --identifier com.nacho.whispertool "$APP"
pkill -x WhisperTool 2>/dev/null || true
ditto "$APP" /Applications/WhisperTool.app
echo "✅ /Applications/WhisperTool.app"
