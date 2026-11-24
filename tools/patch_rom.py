#!/usr/bin/env python3
"""Apply the optional bug-fix patches (tools/patches.py) to a copy of the ROM.

  python tools/patch_rom.py --list
  python tools/patch_rom.py --all                      # every patch
  python tools/patch_rom.py --only 1,3,casey-dy-gap    # chosen patches (numbers or names)
  python tools/patch_rom.py --except 6                 # all but these
  python tools/patch_rom.py --all --src game.nes --out tmp/patched.nes

The source is never changed. Every edit checks the original bytes first, so a patch cannot be applied twice or to the
wrong ROM. The default source is the ROM built from src/ (game.nes); it is byte-identical to the original.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from patches import PATCHES  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def offset(bank, addr):
    return 0x10 + bank * 0x2000 + (addr & 0x1FFF)


def pick(spec):
    out = []
    for tok in spec.split(','):
        tok = tok.strip()
        if not tok:
            continue
        for p in PATCHES:
            if tok == str(p['id']) or tok == p['name']:
                out.append(p)
                break
        else:
            sys.exit('unknown patch: %s (see --list)' % tok)
    return out


def apply(rom, patches):
    for p in patches:
        for bank, addr, old, new in p['edits']:
            o = offset(bank, addr)
            if bytes(rom[o:o + len(old)]) != old:
                sys.exit('patch %d (%s): %02X:%04X holds %s, expected %s (already applied, or another ROM?)'
                         % (p['id'], p['name'], bank, addr, bytes(rom[o:o + len(old)]).hex(), old.hex()))
            assert len(old) == len(new)
            rom[o:o + len(new)] = new
        # a stub shared by two patches is written twice: the second write sees the first one's bytes
    return rom


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--list', action='store_true')
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--only', default='')
    ap.add_argument('--except', dest='skip', default='')
    ap.add_argument('--src', default=os.path.join(ROOT, 'game.nes'))
    ap.add_argument('--out', default=os.path.join(ROOT, 'game_fixed.nes'))
    a = ap.parse_args()
    if a.list:
        for p in PATCHES:
            print('%d  %-20s %s' % (p['id'], p['name'], p['title']))
            print('     ' + p['text'])
        return
    if a.only:
        chosen = pick(a.only)
    elif a.all or a.skip:
        skip = {p['id'] for p in pick(a.skip)}
        chosen = [p for p in PATCHES if p['id'] not in skip]
    else:
        sys.exit('choose --all, --only LIST or --except LIST (or --list)')
    rom = bytearray(open(a.src, 'rb').read())
    apply(rom, chosen)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    open(a.out, 'wb').write(rom)
    print('patched %s: %s' % (a.out, ', '.join('%d %s' % (p['id'], p['name']) for p in chosen)))


if __name__ == '__main__':
    main()
