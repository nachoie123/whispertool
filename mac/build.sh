#!/bin/bash
# Compila build/WhisperTool.app (sin Xcode) con Sparkle dentro, para que se actualice sola.
#   ./build.sh            solo compila y firma
#   ./build.sh instalar   además la copia a /Applications (cierra la que esté abierta)
# Firma con Developer ID + runtime endurecido (desde 11/10/2026): la identidad es estable, recompilar no borra permisos.
set -e
cd "$(dirname "$0")"
VERSION=2.4; BUILD=7    # las sube el trabajo semanal de actualizaciones
APP=build/WhisperTool.app
SPARKLE=build/sparkle   # Sparkle 2.10.1 oficial; se descarga la primera vez
[ -d "$SPARKLE/Sparkle.framework" ] || { mkdir -p "$SPARKLE"
  curl -fsSL https://github.com/sparkle-project/Sparkle/releases/download/2.10.1/Sparkle-2.10.1.tar.xz | tar -xJ -C "$SPARKLE"; }
rm -rf "$APP"; mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources" "$APP/Contents/Frameworks"
ditto "$SPARKLE/Sparkle.framework" "$APP/Contents/Frameworks/Sparkle.framework"
# -target fija el macOS mínimo real del binario (sin él sale el del Mac que compila: macOS 26). Debe coincidir con LSMinimumSystemVersion.
swiftc -O -swift-version 5 -parse-as-library -target arm64-apple-macos14.0 -F "$SPARKLE" -framework Sparkle \
  -Xlinker -rpath -Xlinker @executable_path/../Frameworks -o "$APP/Contents/MacOS/WhisperTool" WhisperTool.swift
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
<key>CFBundleShortVersionString</key><string>$VERSION</string>
<key>CFBundleVersion</key><string>$BUILD</string>
<key>LSMinimumSystemVersion</key><string>14.0</string>
<key>LSUIElement</key><true/>
<key>NSHighResolutionCapable</key><true/>
<key>NSMicrophoneUsageDescription</key><string>WhisperTool escucha solo mientras mantienes ⌃⌥.</string>
<key>NSSpeechRecognitionUsageDescription</key><string>Para enseñarte el texto en vivo mientras dictas, en tu Mac.</string>
<key>SUFeedURL</key><string>https://nachosanbenito.com/whispertool/appcast.xml</string>
<key>SUPublicEDKey</key><string>P4duSfYCtrpopwAjL9zcxrrLn7DYaDk3ws38jqC6Ehs=</string>
<key>SUEnableAutomaticChecks</key><true/>
<key>SUAutomaticallyUpdate</key><true/>
<key>SUScheduledCheckInterval</key><integer>86400</integer>
</dict></plist>
PL
cp icono/WhisperTool.icns sonidos/*.wav "$APP/Contents/Resources/"
ID="${SIGN_ID:-Developer ID Application: Ignacio San Benito (4HBV76K3X6)}"; security find-identity -v -p codesigning | grep -q "$ID" || ID=-   # sin ese certificado: firma ad-hoc
# Sparkle por dentro primero (sus XPC, Autoupdate y Updater.app), como dice su guía; luego el framework y la app
FW="$APP/Contents/Frameworks/Sparkle.framework"
for x in "$FW/Versions/B/XPCServices/Installer.xpc" "$FW/Versions/B/XPCServices/Downloader.xpc" \
         "$FW/Versions/B/Autoupdate" "$FW/Versions/B/Updater.app" "$FW"; do
  codesign --force --options runtime --timestamp --preserve-metadata=entitlements -s "$ID" "$x"
done
codesign --force --options runtime --timestamp --entitlements WhisperTool.entitlements -s "$ID" --identifier com.nacho.whispertool "$APP"
codesign --verify --deep --strict "$APP"
if [ "$1" = instalar ]; then
  pkill -x WhisperTool 2>/dev/null || true
  ditto "$APP" /Applications/WhisperTool.app
  echo "✅ /Applications/WhisperTool.app"
else
  echo "✅ $APP $VERSION ($BUILD)"
fi
