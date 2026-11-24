#!/usr/bin/env python3
"""Relocation test: link every PRG bank pair at a different address (banks B and B^1 at their CPU address -
(B/2+1)*$100: both banks of a pair move together, so branches and instructions across $A000 keep working) and check
that the result differs from the original ROM exactly where the generator put a ROM reference, by exactly the
shift of the bank it believes the target is in.

  python tools/reloc_test.py [--root DIR] [--labels DIR]

Fails on
  - any other changed byte          -> a ROM address is still hard-coded as a number in src/prg/*.asm
  - a reference that did not move   -> the same
  - a reference that moved by the shift of another bank -> ca65 resolved the label in a bank other than the one
                                       the generator assumed (wrong module/segment)
Unresolved $8000-$BFFF references (no bank hint) are numbers by design; they are counted, not failed.
"""
import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import disasm as d  # noqa: E402


def shift(b):
    return ((b >> 1) + 1) * 0x100


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default=ROOT, help='directory with src/ (generated)')
    ap.add_argument('--rom', default=os.path.join(ROOT, d.ROM_NAME))
    ap.add_argument('--cdl', nargs='+', default=None)
    ap.add_argument('--labels', default=os.path.join(HERE, 'labels'))
    a = ap.parse_args()
    tmp_cfg, tmp_o, tmp_nes = (os.path.join(a.root, n) for n in ('config_reloc.cfg', 'src/main_reloc.o', 'reloc.nes'))
    open(tmp_cfg, 'w', encoding='utf-8').write(d.config_text(shift))
    try:
        subprocess.check_call(['ca65', 'src/main.asm', '-o', 'src/main_reloc.o'], cwd=a.root)
        subprocess.check_call(['ld65', '-C', 'config_reloc.cfg', '-o', 'reloc.nes', 'src/main_reloc.o'], cwd=a.root)
        new = open(tmp_nes, 'rb').read()[16:16 + d.SIZE]
    finally:
        for p in (tmp_cfg, tmp_o, tmp_nes):
            if os.path.exists(p):
                os.remove(p)
    D = d.Disasm(a.rom, a.cdl or d.default_cdls(), a.labels)
    D.run()
    old = D.rom
    expect = {}                                     # byte idx -> expected new value
    def word_at(j, t, adj=0):
        v = (old[j] | old[j + 1] << 8) - shift(d.bank_of(t))
        expect[j], expect[j + 1] = v & 0xFF, (v >> 8) & 0xFF
    for i in D.instrs():
        mn, mode, n = D.decode(i)
        if n == 3 and i not in D.user['refs']:
            t = D.operand_target(i)
            if t is not None:
                word_at(i + 1, t)
    rom_label = {name: k for k, name in D.labels.items()}
    for i, (name, _off, _e) in D.user['refs'].items():  # rom.txt `ref LOC Name+-N` to a ROM label moves with it
        if name in rom_label:
            word_at(i + 1, rom_label[name])
    for j in D.word_start:
        t = D.word_target(j)
        if t is not None:
            word_at(j, t)
    pairs = list(D.user['imms'])
    for lo_i, hi_i in pairs:
        t = D.immref[lo_i][1]
        v = ((old[hi_i + 1] << 8) | old[lo_i + 1]) - shift(d.bank_of(t))
        expect[lo_i + 1], expect[hi_i + 1] = v & 0xFF, (v >> 8) & 0xFF
    for lo, hi, n, adj, _p in D.user['splits']:
        for e in range(n):
            if lo + e in D.split:
                _part, t, _adj = D.split[lo + e]
                v = ((old[hi + e] << 8) | old[lo + e]) - shift(d.bank_of(t))
                expect[lo + e], expect[hi + e] = v & 0xFF, (v >> 8) & 0xFF
    bad, moved, wrong = [], 0, []
    for i in range(d.SIZE):
        if i in expect:
            if new[i] == expect[i]:
                moved += 1
            else:
                wrong.append(i)
        elif new[i] != old[i]:
            bad.append(i)
    print('relocation: %d reference byte(s) moved as expected, %d unexpected change(s), %d reference byte(s) wrong, '
          '%d unresolved reference(s) left as numbers' % (moved, len(bad), len(wrong), len(D.unresolved)))
    for i in bad[:40]:
        print('  unexpected change at %s' % d.where(i))
    for i in wrong[:40]:
        print('  reference byte at %s is $%02X, expected $%02X' % (d.where(i), new[i], expect[i]))
    sys.exit(1 if bad or wrong else 0)


if __name__ == '__main__':
    main()
