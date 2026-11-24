#!/usr/bin/env python3
"""Merge the outputs of tools/mesen/run_mesen.py runs.

  python tools/mesen/merge_runs.py DIR [DIR ...] [--cdl tools/mesen/cdl/bot.cdl] [--banks tools/labels/banks.txt]

* every <run>.exec / <run>.read in the directories -> a Mesen2 'CDLv2' file (exec bytes = code: Mesen marks opcode
  and operand bytes; read bytes = data, except
  the byte after an executed byte: the 6502 dummy-fetches it after branches, implied ops and RTS). tools/disasm.py merges tools/mesen/cdl/*.cdl with the game CDL.
  An existing --cdl file is merged too (union), so runs can be added one directory at a time.
* every <run>.hints -> tools/labels/banks.txt: 'bank LOC TT' for each fixed-bank site that always ran with the same
  bank pair; sites seen with several pairs are listed as comments (they read whatever pair is mapped).
  Existing lines of banks.txt are kept unless a run contradicts them.
* <run>.pairs: prints every PRG pair the game wrote to the MMC3 (must be even banks n, n+1).
"""
import argparse
import glob
import os
import sys
import zlib
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
ROOT = os.path.dirname(TOOLS)
sys.path.insert(0, TOOLS)
import disasm as d  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('dirs', nargs='+')
    ap.add_argument('--cdl', default=os.path.join(HERE, 'cdl', 'bot.cdl'))
    ap.add_argument('--banks', default=os.path.join(TOOLS, 'labels', 'banks.txt'))
    a = ap.parse_args()
    rom = open(os.path.join(ROOT, d.ROM_NAME), 'rb').read()
    prg = rom[16:16 + d.SIZE]
    flags = bytearray(d.SIZE)
    if os.path.exists(a.cdl):
        old = open(a.cdl, 'rb').read()[9:9 + d.SIZE]
        flags[:] = old
    hints = defaultdict(lambda: defaultdict(int))
    pairs = defaultdict(int)
    nruns = 0
    for dr in a.dirs:
        for ex in sorted(glob.glob(os.path.join(dr, '*.exec'))):
            base = ex[:-5]
            nruns += 1
            e = open(ex, 'rb').read()
            r = open(base + '.read', 'rb').read() if os.path.exists(base + '.read') else bytes(d.SIZE)
            for i in range(d.SIZE):
                if e[i]:                     # Mesen counts operand fetches as executions too
                    flags[i] |= d.CDL_CODE
                elif r[i] and not (i % d.BANK and e[i - 1]):
                    flags[i] |= d.CDL_DATA   # a read right after an executed byte is the 6502 dummy fetch of the
                                             # next opcode (taken branch, implied ops, RTS): not data
            if os.path.exists(base + '.hints'):
                for line in open(base + '.hints'):
                    pc, b, n = line.split()
                    hints[int(pc, 16)][int(b, 16)] += int(n)
            if os.path.exists(base + '.pairs'):
                for line in open(base + '.pairs'):
                    r6, r7, n = line.split()
                    pairs[(int(r6, 16), int(r7, 16))] += int(n)
    for i in range(d.SIZE):                  # read bytes inside code: the operand fetches are not data
        if flags[i] & d.CDL_CODE:
            flags[i] &= ~d.CDL_DATA & 0xFF
    os.makedirs(os.path.dirname(a.cdl), exist_ok=True)
    crc = zlib.crc32(prg) & 0xFFFFFFFF
    open(a.cdl, 'wb').write(b'CDLv2' + crc.to_bytes(4, 'little') + bytes(flags) + bytes(d.CHR_SIZE))
    print('%d run(s): %d code bytes, %d data bytes -> %s' % (nruns, sum(1 for f in flags if f & d.CDL_CODE),
                                                            sum(1 for f in flags if f & d.CDL_DATA), a.cdl))
    print('PRG pairs written: ' + ', '.join('%02X/%02X' % k for k in sorted(pairs)))
    bad = [k for k in pairs if k[0] % 2 or k[1] != k[0] + 1]
    if bad:
        print('WARNING: pairs that are not (even, even+1): %s' % bad)
    # banks.txt
    keep = {}
    if os.path.exists(a.banks):
        for line in open(a.banks, encoding='utf-8'):
            p = line.partition(';')[0].split()
            if len(p) == 3 and p[0] == 'bank':
                keep[d.parse_addr(p[1])] = (int(p[2], 16), line.partition(';')[2].strip())
    lines = ['; Bank pairs of $8000-$BFFF operands in the fixed banks, seen in Mesen runs (tools/mesen/merge_runs.py).',
             '; Generated - hand-written hints belong in rom.txt (they override these).', '']
    out = {}
    for pc, seen in sorted(hints.items()):
        if len(seen) == 1:
            b = next(iter(seen))
            out[pc] = 'bank %04X %02X ; %d run(s) of the instruction' % (pc, b & ~1, seen[b])
        else:
            out[pc] = '; %04X runs with several pairs: %s' % (pc, ', '.join('%02X x%d' % (b, n) for b, n in sorted(seen.items())))
    for pc, (b, c) in keep.items():
        if pc not in out:
            out[pc] = 'bank %04X %02X ; %s' % (pc, b, c)
        elif out[pc].startswith('bank') and int(out[pc].split()[2], 16) != b:
            print('NOTE: %04X was pair %02X in banks.txt, the runs say %s' % (pc, b, out[pc]))
    open(a.banks, 'w', encoding='utf-8', newline='\n').write('\n'.join(lines + [out[k] for k in sorted(out)]) + '\n')
    print('%d site(s) -> %s' % (len(out), a.banks))


if __name__ == '__main__':
    main()
