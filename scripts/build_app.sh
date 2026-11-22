#!/bin/bash
# Rebuild IHCq.app (icon + bundle) and copy it to the Desktop.
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
im.save("app_icon.png"); os.makedirs("IHCq.iconset", exist_ok=True)
for sz in (16, 32, 128, 256, 512):
    im.resize((sz, sz), Image.LANCZOS).save(f"IHCq.iconset/icon_{sz}x{sz}.png")
    im.resize((sz * 2, sz * 2), Image.LANCZOS).save(f"IHCq.iconset/icon_{sz}x{sz}@2x.png")
PY
iconutil -c icns IHCq.iconset -o IHCq.icns && rm -rf IHCq.iconset
mkdir -p IHCq.app/Contents/MacOS IHCq.app/Contents/Resources
cp IHCq.icns IHCq.app/Contents/Resources/IHCq.icns
VERSION=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' ihcq/__init__.py)
sed "s#@VERSION@#$VERSION#g" scripts/Info.plist > IHCq.app/Contents/Info.plist
sed "s#@PROJECT@#$PWD#" scripts/launcher.sh > IHCq.app/Contents/MacOS/IHCq && chmod +x IHCq.app/Contents/MacOS/IHCq
mkdir -p "$HOME/Desktop/Toolbox" && rm -rf "$HOME/Desktop/Toolbox/IHCq.app" && cp -R IHCq.app "$HOME/Desktop/Toolbox/IHCq.app" && touch "$HOME/Desktop/Toolbox/IHCq.app"
echo "IHCq.app rebuilt and copied to ~/Desktop/Toolbox"
