#!/usr/bin/env python3
"""Contact sheet of Mesen screenshots: python tools/mesen/montage.py OUT.png PNG... [--cols 8] [--scale 0.5]
Each tile is labelled with the number after the last '_f' in its file name (the frame)."""
import argparse
import re
from PIL import Image, ImageDraw

ap = argparse.ArgumentParser()
ap.add_argument('out')
ap.add_argument('pngs', nargs='+')
ap.add_argument('--cols', type=int, default=8)
ap.add_argument('--scale', type=float, default=0.5)
a = ap.parse_args()
w, h = int(256 * a.scale), int(240 * a.scale)
im = Image.new('RGB', (a.cols * w, ((len(a.pngs) + a.cols - 1) // a.cols) * h), (40, 40, 40))
dr = ImageDraw.Draw(im)
ok = []
for f in a.pngs:
    try:
        Image.open(f).verify()
        ok.append(f)
    except Exception:
        print('skipped (not an image): ' + f)
a.pngs = ok
im = Image.new('RGB', (a.cols * w, ((len(a.pngs) + a.cols - 1) // a.cols) * h), (40, 40, 40))
dr = ImageDraw.Draw(im)
for k, f in enumerate(a.pngs):
    x, y = (k % a.cols) * w, (k // a.cols) * h
    im.paste(Image.open(f).convert('RGB').resize((w - 2, h - 2)), (x, y))
    m = re.findall(r'_(w[0-9A-F]{4})?_?f(\d+)', f)
    dr.text((x + 2, y + h - 12), (m[-1][0] + ' ' + m[-1][1]) if m else '', fill=(255, 255, 0))
im.save(a.out)
print('%d tiles -> %s' % (len(a.pngs), a.out))
