#!/usr/bin/env python3
"""Draw fighter frames from the ROM (docs/fighters.md).

  python tools/frames_png.py [ROM]   gfx/frames_<set>.png: every frame (objFrame $80+n) of each sprite set
                                     gfx/moves.png: every move script (MovePtrs), one row per move
                                     gfx/anims.png: every animation (AnimOffsets) in play order, one row each

Frame n of a sprite set: SpriteSetPtrs -> Frames<Set> (pair 04) -> metasprite; FrameChrPtrs -> FrameChr<Set>[n]
-> ChrBankPairs entry = the two 1 KB CHR banks of sprite tiles $00-$3F / $40-$7F (8x16 sprites, odd tiles = $1000).
Grey levels instead of the real palette; sprites with an even tile (pattern table $0000) are skipped.
"""
import os
import sys

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
ROM = os.path.join(HERE, '..', 'Teenage Mutant Ninja Turtles - Tournament Fighters (U) [!].nes')
PRG = 0x20000
# name, frame table (pair 04, $8000-$BFFF), FrameChr table (bank 03, $A000-$BFFF), frames
SETS = [('turtles', 0x8001, 0xB17B, 102), ('casey', 0x8E13, 0xB1E1, 89),
        ('hothead', 0x9B52, 0xB23A, 69), ('shredder', 0xAEC5, 0xB27F, 75)]
SET_OF_CHAR = [0, 0, 0, 0, 1, 2, 3]
CHR_PAIRS = 0xB2CA
MOVE_PTRS, MOVES, MOVE_SEL_B, MOVE_SEL_A = 0x9401, 0x2E, 0x9388, 0x93B2   # bank 02
ANIM_OFFSETS, ANIM_DATA = 0xDFE6, 0xE000                                   # fixed banks
# animation id -> (number of pairs, character); the counts are in code (StartAnim callers), not in the data
ANIMS = {4: (10, 0), 5: (15, 1), 6: (9, 2), 7: (9, 3), 8: (6, 4), 9: (19, 5), 0x0A: (5, 6),
         0x0E: (4, 0), 0x0F: (2, 4), 0x10: (4, 5), 0x11: (4, 6),
         0x13: (5, 0), 0x17: (2, 4), 0x18: (3, 5), 0x19: (4, 6)}
GREYS = [(40, 40, 60), (250, 250, 250), (150, 150, 150), (80, 80, 80)]
CW, CH = 72, 96


class Rom:
    def __init__(self, path):
        d = open(path, 'rb').read()
        self.rom, self.chr = d[16:16 + PRG], d[16 + PRG:]

    def p04(self, a):
        return 4 * 0x2000 + a - 0x8000

    def b02(self, a):
        return 2 * 0x2000 + a - 0x8000

    def b03(self, a):
        return 3 * 0x2000 + a - 0xA000

    def word(self, o):
        return self.rom[o] | self.rom[o + 1] << 8

    def draw(self, img, s, f, ox, oy):
        """frame f ($00-$7F) of sprite set s, origin (object X/Y) at ox, oy"""
        rom, sgn = self.rom, lambda v: v - 256 if v & 0x80 else v
        _name, tbl, ctbl, _n = SETS[s]
        o = self.p04(self.word(self.p04(tbl) + 2 * f))
        left, j = rom[o] & 0x7F, o + 1
        ci = rom[self.b03(ctbl) + f]
        banks = rom[self.b03(CHR_PAIRS) + 2 * ci], rom[self.b03(CHR_PAIRS) + 2 * ci + 1]
        while left:
            if rom[j] == 0x80:                      # MSPR_JUMP
                j = self.p04(self.word(j + 1))
                continue
            dy, t, at, dx = rom[j:j + 4]
            j, left = j + 4, left - 1
            if not t & 1:
                continue
            for half in (0, 1):
                tt = (t & 0xFE) + half
                base = banks[tt >> 6] * 1024 + (tt & 0x3F) * 16
                for y in range(8):
                    yy = (1 - half) * 8 + 7 - y if at & 0x80 else half * 8 + y
                    for x in range(8):
                        c = (self.chr[base + y] >> (7 - x) & 1) | (self.chr[base + 8 + y] >> (7 - x) & 1) << 1
                        if c:
                            X, Y = ox + sgn(dx) + (7 - x if at & 0x40 else x), oy + sgn(dy) + yy
                            if 0 <= X < img.width and 0 <= Y < img.height:
                                img.putpixel((X, Y), GREYS[c])


def strips(r, rows, path):
    """rows: [(caption, sprite set, [(frame byte, frames)])] -> one row of cells per entry"""
    cols = max(len(fr) for _c, _s, fr in rows)
    img = Image.new('RGB', (cols * CW, len(rows) * (CH + 10)), GREYS[0])
    dr = ImageDraw.Draw(img)
    for k, (cap, s, frames) in enumerate(rows):
        y = k * (CH + 10)
        dr.text((2, y), cap, fill=(255, 220, 120))
        for i, (f, t) in enumerate(frames):
            r.draw(img, s, f & 0x7F, i * CW + 36, y + 10 + 80)
            dr.text((i * CW + 2, y + CH - 2), '%02X/%d' % (f, t), fill=(160, 200, 255))
    img.resize((img.width * 2, img.height * 2), Image.NEAREST).save(path)
    print(path)


def main():
    r = Rom(sys.argv[1] if len(sys.argv) > 1 else ROM)
    out = os.path.join(HERE, '..', 'gfx')
    os.makedirs(out, exist_ok=True)
    for s, (name, _tbl, _ctbl, n) in enumerate(SETS):
        cols = 12
        img = Image.new('RGB', (cols * CW, (n + cols - 1) // cols * CH), GREYS[0])
        for f in range(n):
            r.draw(img, s, f, f % cols * CW + 36, f // cols * CH + 80)
        path = os.path.join(out, 'frames_%s.png' % name)
        img.resize((img.width * 2, img.height * 2), Image.NEAREST).save(path)
        print(path)
    # moves: the character comes from the selection tables (first user; Move20/Move25 are picked in code)
    owner = {0x20: 5, 0x25: 6}
    for sel in (MOVE_SEL_B, MOVE_SEL_A):
        for i in range(42):
            owner.setdefault(r.rom[r.b02(sel) + i], i % 7)
    rows = []
    for m in range(MOVES):
        j, fr, extra = r.b02(r.word(r.b02(MOVE_PTRS) + 2 * m)), [], []
        while r.rom[j]:
            b, v = r.rom[j], r.rom[j + 1]
            if b == 0xFE:
                extra.append('snd %02X' % v)
            elif b == 0xFF:
                extra.append('hit %02X' % v)
            else:
                fr.append((b, v))
            j += 2
        rows.append(('Move%02X  %s' % (m, ', '.join(extra)), SET_OF_CHAR[owner[m]], fr))
    strips(r, rows, os.path.join(out, 'moves.png'))
    rows = []
    for a, (n, ch) in sorted(ANIMS.items()):
        off = r.rom[0x1C000 + ANIM_OFFSETS - 0xC000 + a]
        pairs = [r.rom[0x1E000 + ANIM_DATA - 0xE000 + off + 2 * k:][:2] for k in range(n)][::-1]  # last pair first
        rows.append(('anim %02X (char %d), play order' % (a, ch), SET_OF_CHAR[ch], [(f, t) for f, t in pairs if f]))
    strips(r, rows, os.path.join(out, 'anims.png'))


if __name__ == '__main__':
    main()
