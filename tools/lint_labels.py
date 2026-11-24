#!/usr/bin/env python3
"""Lint tools/labels/rom.txt, banks.txt, ram.txt and const.txt.

Checks:
  - every line parses (addresses BB:AAAA in their bank's window, plain AAAA only in $C000-$FFFF)
  - the same name used for two different places, one place named twice, ROM names that are also RAM names
  - code ranges overlapping data/words/table/text ranges (the later one silently wins in the generator)
  - module lines: lower-case names, duplicates, each start (other than a bank start) on a labelled address
  - bank hints in rom.txt that contradict tools/labels/banks.txt (the generated file from the Mesen logs)
  - ram.txt: duplicate names / addresses, addresses outside $0000-$07FF
Exit status 1 if any problem is found.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import disasm as d  # noqa: E402

RANGE_KINDS = ('code', 'data', 'words', 'rtswords', 'table', 'text', 'screens', 'metasprites', 'movescripts', 'aiscripts', 'sound', 'dbyt', 'numwords')
OTHER = ('split', 'imm', 'note', 'bitskip', 'entry', 'module', 'ref', 'alias', 'bank', 'rawsym', 'bankcall', 'dispatch', 'soundptrs', 'framenames')


def lint_rom(path, errs):
    names, places, ranges, modules = {}, {}, [], {}
    if not os.path.exists(path):
        return set()
    for ln, line in enumerate(open(path, encoding='utf-8'), 1):
        parts = line.partition(';')[0].split()
        if not parts:
            continue
        w = parts[0]
        try:
            if w in RANGE_KINDS:
                lo, hi = d.parse_range(parts[1])
                for lo2, hi2, w2, ln2 in ranges:
                    if lo <= hi2 and lo2 <= hi and (w == 'code') != (w2 == 'code'):
                        errs.append('%s:%d: %s %s overlaps %s at line %d (code vs data)' % (path, ln, w, parts[1], w2, ln2))
                ranges.append((lo, hi, w, ln))
            elif w == 'module':
                i, n = d.loc(parts[1]), parts[2]
                if not re.match(r'^[a-z][a-z0-9_]*$', n):
                    errs.append('%s:%d: module name %s must be lower case' % (path, ln, n))
                if (d.bank_of(i), n) in modules or i in modules.values():
                    errs.append('%s:%d: module %s / %s defined twice' % (path, ln, n, parts[1]))
                modules[(d.bank_of(i), n)] = i
            elif w == 'charmap':
                d.parse_charmap(parts[2:])
            elif w == 'rawsym':
                d.parse_addr(parts[1])
            elif w in ('bank', 'alias', 'bankcall', 'screentext'):
                d.parse_range(parts[1])
            elif w in OTHER:
                for p in parts[1:3 if w in ('split', 'imm') else 2]:
                    d.loc(p)
            else:
                i, n = d.loc(w), parts[1]
                if n in names and names[n][0] != i:
                    errs.append('%s:%d: name %s used for %s and %s (line %d)' % (path, ln, n, d.where(i), d.where(names[n][0]), names[n][1]))
                if i in places and places[i][0] != n:
                    errs.append('%s:%d: %s named %s and %s (line %d)' % (path, ln, d.where(i), places[i][0], n, places[i][1]))
                if not n.startswith('@'):
                    names.setdefault(n, (i, ln))
                places.setdefault(i, (n, ln))
        except (ValueError, IndexError) as e:
            errs.append('%s:%d: cannot parse %r (%s)' % (path, ln, line.strip(), e))
    for (b, n), i in modules.items():
        if i % d.BANK and i not in places:
            errs.append('%s: module %s starts at %s, which has no label' % (path, n, d.where(i)))
    return set(names)


def lint_hints(labels, errs):
    gen = d.load_rom_labels(os.path.join(labels, 'banks.txt'))['hints']
    own = d.load_rom_labels(os.path.join(labels, 'rom.txt'))['hints']
    for i, tt in sorted(own.items()):
        if i in gen and gen[i] != tt:
            errs.append('rom.txt: bank hint %s -> %s contradicts banks.txt (%s, seen in Mesen)'
                        % (d.where(i), tt, gen[i]))


def lint_ram(path, rom_names, errs):
    names, addrs = {}, {}
    if not os.path.exists(path):
        return
    for ln, line in enumerate(open(path, encoding='utf-8'), 1):
        parts = line.partition(';')[0].split()
        if not parts:
            continue
        if len(parts) < 2 or not re.match(r'^\$?[0-9A-Fa-f]{1,4}$', parts[0]):
            errs.append('%s:%d: cannot parse %r' % (path, ln, line.strip()))
            continue
        a, n = d.parse_addr(parts[0]), parts[1]
        if a > 0x7FF:
            errs.append('%s:%d: $%04X is outside internal RAM' % (path, ln, a))
        if n in names and names[n][0] != a:
            errs.append('%s:%d: name %s used for $%04X and $%04X (line %d)' % (path, ln, n, a, names[n][0], names[n][1]))
        if a in addrs and addrs[a][0] != n:
            errs.append('%s:%d: $%04X named %s and %s (line %d)' % (path, ln, a, addrs[a][0], n, addrs[a][1]))
        if n in rom_names:
            errs.append('%s:%d: name %s is also a ROM label' % (path, ln, n))
        names.setdefault(n, (a, ln))
        addrs.setdefault(a, (n, ln))


def main():
    labels = os.path.join(HERE, 'labels')
    errs = []
    rom_names = lint_rom(os.path.join(labels, 'rom.txt'), errs)
    lint_rom(os.path.join(labels, 'banks.txt'), errs)
    lint_hints(labels, errs)
    lint_ram(os.path.join(labels, 'ram.txt'), rom_names, errs)
    d.load_consts(os.path.join(labels, 'const.txt'))        # exits with a message on a syntax error
    for e in errs:
        print(e)
    print('%d problem(s)' % len(errs))
    return 1 if errs else 0


if __name__ == '__main__':
    sys.exit(main())
