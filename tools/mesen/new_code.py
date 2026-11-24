#!/usr/bin/env python3
"""List PRG bytes a Mesen run executed or read that the game CDL never saw.

  python tools/mesen/new_code.py RUN_PREFIX [RUN_PREFIX ...]      (RUN_PREFIX = tmp/dir/name, without .exec)

Prints ranges of newly executed code (with the nearest label from the generated sources) and the number of newly
read data bytes; ranges inside 'entry' routines of tools/labels/rom.txt (no known caller) are marked.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
ROOT = os.path.dirname(TOOLS)
sys.path.insert(0, TOOLS)
import disasm as d  # noqa: E402


def main():
    game = d.load_cdl([os.path.join(ROOT, d.CDL_NAME)], d.SIZE, d.CHR_SIZE)
    labels = d.load_rom_labels(os.path.join(TOOLS, 'labels', 'rom.txt'))
    entries = set(labels['entries'])
    for prefix in sys.argv[1:]:
        e = open(prefix + '.exec', 'rb').read()
        r = open(prefix + '.read', 'rb').read() if os.path.exists(prefix + '.read') else bytes(d.SIZE)
        new = [i for i in range(d.SIZE) if e[i] and not game[i] & d.CDL_CODE]
        reads = sum(1 for i in range(1, d.SIZE) if r[i] and not e[i] and not e[i - 1] and not game[i] & 0x83)
        print('%s: %d new code bytes, %d new data bytes' % (prefix, len(new), reads))
        runs = []
        for i in new:
            if runs and i - runs[-1][1] <= 3 and d.bank_of(i) == d.bank_of(runs[-1][0]):
                runs[-1][1] = i
            else:
                runs.append([i, i])
        for lo, hi in runs:
            mark = ' (entry: no known caller)' if any(x in entries for x in range(lo, hi + 1)) else ''
            print('  %s-%04X %4d%s' % (d.where(lo), d.cpu(hi), hi - lo + 1, mark))


if __name__ == '__main__':
    main()
