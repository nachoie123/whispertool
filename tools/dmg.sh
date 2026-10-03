#!/bin/bash
# dist/WhisperTool.app -> dist/WhisperTool.dmg: ventana con fondo (arrastrar a Applications + "Open Anyway").
# Después de ./build.sh. Mismo método que Guardados: bounds dos veces o el Finder no guarda el tamaño.
# Colores de la landing (docs/index.html): crema #F4EEDD, tinta #16141a, violeta #5B47E0.
set -e
cd "$(dirname "$0")/.."
ST=build/dmg_stage; VOL=WhisperTool
hdiutil detach "/Volumes/$VOL" -force -quiet 2>/dev/null || true
rm -rf $ST build/rw.dmg; mkdir -p $ST/.background
python3 - <<'EOF'
from PIL import Image, ImageDraw, ImageFont
W, H, S = 660, 520, 2
INK, MUTE, V = "#16141a", "#6b6457", "#5B47E0"
im = Image.new("RGB", (W*S, H*S), "#F4EEDD"); d = ImageDraw.Draw(im)
F = lambda sz, b=False: ImageFont.truetype("/System/Library/Fonts/HelveticaNeue.ttc", sz*S, index=1 if b else 0)
d.line([(255*S, 150*S), (405*S, 150*S)], fill=V, width=6*S)
d.polygon([(405*S, 135*S), (430*S, 150*S), (405*S, 165*S)], fill=V)
d.text((W*S//2, 40*S), "1 · Drag WhisperTool into Applications", font=F(20, True), fill=INK, anchor="mm")
y = 260
d.rounded_rectangle([(30*S, y*S), (630*S, (y+235)*S)], radius=16*S, fill="#FBF8EF", outline=V, width=2*S)
d.text((52*S, (y+22)*S), "2 · The first time, macOS stops it (that's normal)", font=F(18, True), fill=INK)
lines = ["It says Apple could not verify \"WhisperTool\".",
         "The app isn't notarized by Apple ($99/year), like most indie apps.", "",
         "Click \"Done\", then:",
         "System Settings  ›  Privacy & Security  ›",
         "scroll to the bottom  ›  \"Open Anyway\"  ›  confirm.", "",
         "Only once. Then allow Microphone and Accessibility. Apple Silicon only."]
for i, l in enumerate(lines):
    d.text((52*S, (y+58+i*20)*S), l, font=F(14, i in (4, 5)), fill=INK if i in (4, 5) else MUTE)
im.save("build/bg@2x.png"); im.resize((W, H), Image.LANCZOS).save("build/bg.png")
EOF
tiffutil -cathidpicheck build/bg.png build/bg@2x.png -out $ST/.background/bg.tiff >/dev/null
ditto dist/WhisperTool.app $ST/WhisperTool.app
ln -s /Applications $ST/Applications
# tamaño: lo que ocupa la app + margen (pesa ~500 MB)
MB=$(( $(du -sm $ST | cut -f1) + 80 ))
hdiutil create -srcfolder $ST -volname $VOL -fs HFS+ -format UDRW -size ${MB}m build/rw.dmg >/dev/null
hdiutil attach build/rw.dmg -noautoopen -quiet; sleep 2
osascript <<EOF
tell application "Finder"
  tell disk "$VOL"
    open
    delay 1
    set current view of container window to icon view
    set toolbar visible of container window to false
    set statusbar visible of container window to false
    set vo to the icon view options of container window
    set arrangement of vo to not arranged
    set icon size of vo to 96
    set text size of vo to 13
    set background picture of vo to file ".background:bg.tiff"
    set position of item "WhisperTool.app" of container window to {170, 150}
    set position of item "Applications" of container window to {500, 150}
    set the bounds of container window to {200, 120, 860, 700}
    delay 1
    set the bounds of container window to {200, 120, 860, 700}
    update without registering applications
    delay 3
    close
  end tell
end tell
EOF
sleep 2; sync; hdiutil detach "/Volumes/$VOL" -quiet; rm -f dist/WhisperTool.dmg
hdiutil convert build/rw.dmg -format UDZO -imagekey zlib-level=9 -o dist/WhisperTool.dmg >/dev/null; rm build/rw.dmg
ls -la dist/WhisperTool.dmg
