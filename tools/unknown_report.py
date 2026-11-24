#!/usr/bin/env python3
"""Report the PRG bytes that neither the CDLs nor the tracer classified (not counting $FF fill): docs/unknown.txt
The generator emits them as data marked 'unread' (Disasm.mark_unread); this report is the list to review.

  python tools/unknown_report.py [--min N]

For each unknown run:
  refs   places that point into the run: decoded operands/words (exact), plus a raw search of the ROM for the
         little-endian CPU address of every byte of the run (same 16KB unit, or anywhere for the fixed banks),
         and lo/hi immediates (LDA #<x ... LDA #>x) close together
  code   result of speculative decoding from the first byte: number of instructions and whether it reaches an
         RTS/RTI/JMP without running into data ("code?") or not ("not code")
  look   a rough description of the bytes (text with the game's charmap, fill, small values, ...)
"""
import argparse
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import disasm as d  # noqa: E402

CHAR_A = 0x8B           # game font: 'A' = $8B (seen in the fighter names at $DDB6)


def look(data):
    n = len(data)
    if len(set(data)) == 1:
        return 'fill $%02X' % data[0]
    letters = sum(1 for b in data if CHAR_A <= b < CHAR_A + 26 or b == 0xFF)
    if letters >= 0.7 * n:
        return 'text? "%s"' % ''.join(chr(b - CHAR_A + 65) if CHAR_A <= b < CHAR_A + 26 else ' ' if b == 0xFF else '.'
                                      for b in data[:40])
    if max(data) < 0x40:
        return 'small values (< $40)'
    return ''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--min', type=int, default=1)
    ap.add_argument('--out', default=os.path.join(ROOT, 'docs', 'unknown.txt'))
    a = ap.parse_args()
    D = d.Disasm(os.path.join(ROOT, d.ROM_NAME), d.default_cdls(), os.path.join(HERE, 'labels'))
    D.run()
    rom = D.rom
    # exact references: operands and words
    exact = defaultdict(list)
    for i in D.instrs():
        t = D.operand_target(i)
        if t is not None:
            exact[t].append(i)
    for j in D.word_start:
        t = D.word_target(j)
        if t is not None:
            exact[t].append(j)
    runs, i = [], 0
    while i < d.SIZE:
        if i in D.unread:
            j = i
            while j < d.bank_end(i) and j in D.unread:
                j += 1
            if not all(b == 0xFF for b in rom[i:j]) and j - i >= a.min:
                runs.append((i, j))
            i = j
        else:
            i += 1
    out = ['Unread PRG data (not $FF fill; emitted as data marked unread): %d in %d runs' % (sum(j - i for i, j in runs), len(runs)), '']
    for i, j in sorted(runs, key=lambda r: -(r[1] - r[0])):
        lines = []
        for k in range(i, j):
            for src in exact.get(k, []):
                lines.append('exact %s <- %s' % (d.where(k), d.where(src)))
        lo_cpu, hi_cpu = d.cpu(i), d.cpu(j - 1)
        pat = {}
        for k in range(i, j):
            c = d.cpu(k)
            pat[bytes((c & 0xFF, c >> 8))] = k
        scope = range(0, d.SIZE) if d.bank_of(i) >= 14 else \
            list(range((i >> 14) << 14, ((i >> 14) + 1) << 14)) + list(range(14 * d.BANK, d.SIZE))
        raw = []
        for s in scope:
            k = pat.get(bytes(rom[s:s + 2]))
            if k is not None and not (i <= s < j) and D.kind[s] in (d.K_DATA, d.K_UNK, d.K_WORD):
                raw.append('raw %s <- %s' % (d.where(k), d.where(s)))
        lines += raw[:6] + (['... %d more raw hits' % (len(raw) - 6)] if len(raw) > 6 else [])
        for k in range(i, j):                       # speculate on the bytes as they were before mark_unread
            D.kind[k] = d.K_UNK
        f = D.speculate(i)
        for k in range(i, j):
            D.kind[k] = d.K_DATA
        if f:
            ends = any(D.decode(x)[0] in ('RTS', 'RTI', 'JMP') for x in f)
            code = 'code? %d instructions%s' % (len(f), '' if ends else ', no RTS/JMP')
        else:
            code = 'not code'
        out.append('%s-%04X %5d  %-32s %s' % (d.where(i), d.cpu(j - 1), j - i, code, look(rom[i:j])))
        out.append('    ' + ' '.join('%02X' % b for b in rom[i:min(j, i + 24)]) + (' ...' if j - i > 24 else ''))
        out += ['    ' + x for x in lines]
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    open(a.out, 'w', encoding='utf-8', newline='\n').write('\n'.join(out) + '\n')
    print('%s (%d runs)' % (out[0], len(runs)))


if __name__ == '__main__':
    main()
