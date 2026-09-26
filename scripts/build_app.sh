#!/bin/bash
# Rebuild IHCQ.app (icon + bundle) and copy it to the Desktop.
set -e
cd "$(dirname "$0")/.."
python3 - <<'PY'
from PIL import Image, ImageDraw
import math, random, os
S = 1024; im = Image.new("RGBA", (S, S), (0, 0, 0, 0)); d = ImageDraw.Draw(im); m = 60
d.rounded_rectangle([m, m, S - m, S - m], radius=220, fill=(244, 240, 232, 255))
random.seed(7); pts, tries = [], 0
while len(pts) < 22 and tries < 20000:
    tries += 1; x, y = random.uniform(175, S - 175), random.uniform(175, S - 175)
    if all(math.hypot(x - a, y - b) > 118 for a, b in pts): pts.append((x, y))
for i, (x, y) in enumerate(pts):
    r = random.uniform(44, 58); brown = i in (3, 8, 12, 17, 20)
    d.ellipse([x - r, y - r * .85, x + r, y + r * .85], fill=(110, 58, 22, 255) if brown else (92, 110, 190, 255))
    if not brown: d.ellipse([x - r * .55, y - r * .45, x + r * .55, y + r * .45], fill=(122, 138, 210, 255))
im.save("app_icon.png"); os.makedirs("IHCQ.iconset", exist_ok=True)
for sz in (16, 32, 128, 256, 512):
    im.resize((sz, sz), Image.LANCZOS).save(f"IHCQ.iconset/icon_{sz}x{sz}.png")
    im.resize((sz * 2, sz * 2), Image.LANCZOS).save(f"IHCQ.iconset/icon_{sz}x{sz}@2x.png")
PY
iconutil -c icns IHCQ.iconset -o IHCQ.icns && rm -rf IHCQ.iconset
mkdir -p IHCQ.app/Contents/MacOS IHCQ.app/Contents/Resources
cp IHCQ.icns IHCQ.app/Contents/Resources/IHCQ.icns
cp scripts/Info.plist IHCQ.app/Contents/Info.plist
cp scripts/launcher.sh IHCQ.app/Contents/MacOS/IHCQ && chmod +x IHCQ.app/Contents/MacOS/IHCQ
rm -rf "$HOME/Desktop/IHCQ.app" && cp -R IHCQ.app "$HOME/Desktop/IHCQ.app" && touch "$HOME/Desktop/IHCQ.app"
echo "IHCQ.app rebuilt and copied to the Desktop"
