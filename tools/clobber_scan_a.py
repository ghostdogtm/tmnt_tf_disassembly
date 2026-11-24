#!/usr/bin/env python3
"""Accumulator clobber scan (companion of clobber_scan.py, which does X / Y).

Pattern: a caller loads A (LDA/TXA/TYA/PLA...), calls a routine that rewrites A on every path to its RTS, and then
reads A again (STA, CMP, AND, TAX ...) without loading it first. Often intended (the callee returns a value in A);
a callee whose call sites mostly keep using their own A is listed as a candidate to read.

  python tools/clobber_scan_a.py [--all] [--depth N]

A PHA ... PLA pair inside a routine counts as a restore. Output only, nothing is written.
"""
import argparse
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from clobber_scan import Prog  # noqa: E402

PURE = {'LDA', 'TXA', 'TYA', 'PLA'}
RMW_A = {'ADC', 'SBC', 'AND', 'ORA', 'EOR'}
SHIFT = {'ASL', 'LSR', 'ROL', 'ROR'}
READ_ONLY = {'STA', 'CMP', 'BIT', 'PHA', 'TAX', 'TAY'}


def a_read(mn, op):
    if mn in READ_ONLY or mn in RMW_A:
        return True
    return mn in SHIFT and op.strip() in ('', 'A')


def a_write(mn, op):
    return mn in PURE or mn in RMW_A or (mn in SHIFT and op.strip() in ('', 'A'))


def summarize(P, limit=4000):
    entries = set()
    for mn, op, _f, _l in P.ins:
        if mn == 'JSR':
            t = P.target_of(op) if hasattr(P, 'target_of') else None
    for i, (mn, op, _f, _l) in enumerate(P.ins):
        if mn == 'JSR':
            t = P.target(i, op)
            if t is not None:
                entries.add(t)
    clob = {e: False for e in entries}
    inp = {e: False for e in entries}
    changed = True
    while changed:
        changed = False
        for e in entries:
            if not clob[e] and path_clobbers(P, e, clob, limit):
                clob[e] = True
                changed = True
            if not inp[e] and reads_first(P, e, clob, inp, limit):
                inp[e] = True
                changed = True
    return entries, clob, inp


def path_clobbers(P, entry, clob, limit):
    seen = set()
    stack = [(entry, False, 0)]          # modified?, pushed A count (0/1)
    n = 0
    while stack:
        i, mod, pushed = stack.pop()
        if (i, mod, pushed) in seen:
            continue
        seen.add((i, mod, pushed))
        n += 1
        if n > limit:
            break
        mn, op, _f, _l = P.ins[i]
        if mn == 'RTS':
            if mod:
                return True
            continue
        if mn == 'PHA':
            pushed = 1
        elif mn == 'PLA':
            mod, pushed = (False, 0) if pushed else (True, 0)
        elif a_write(mn, op):
            mod = True
        elif mn == 'JSR':
            t = P.target(i, op)
            if t is not None and clob.get(t):
                mod = True
        for s in P.succ(i):
            stack.append((s, mod, pushed))
    return False


def reads_first(P, start, clob, inp, limit, depth=None):
    seen = set()
    stack = [(start, 0)]
    n = 0
    while stack:
        i, d = stack.pop()
        if i in seen or (depth is not None and d > depth):
            continue
        seen.add(i)
        n += 1
        if n > limit:
            break
        mn, op, f, l = P.ins[i]
        if mn == 'JSR':
            t = P.target(i, op)
            if t is not None and inp.get(t):
                return (f, l, 'JSR ' + op.strip() + ' (takes A as input)')
            if t is not None and clob.get(t):
                continue
        elif a_read(mn, op):
            return (f, l, mn + ' ' + op)
        if mn in PURE:
            continue
        for s in P.succ(i):
            stack.append((s, d + 1))
    return None


def loaded_before(P, i, window=8):
    for k in range(i - 1, max(i - 1 - window, -1), -1):
        mn, op, _f, _l = P.ins[k]
        if mn in ('RTS', 'JMP', 'RTI', 'JSR') or mn.startswith('B') and mn != 'BIT':
            return False
        if mn in PURE:
            return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--depth', type=int, default=12)
    a = ap.parse_args()
    P = Prog()
    P.load()
    entries, clob, inp = summarize(P)
    sites = defaultdict(lambda: {'use': [], 'free': []})
    for i, (mn, op, f, l) in enumerate(P.ins):
        if mn != 'JSR':
            continue
        t = P.target(i, op)
        if t is None or not clob.get(t) or not loaded_before(P, i):
            continue
        u = reads_first(P, i + 1, clob, inp, 4000, a.depth)
        sites[op.strip()]['use' if u else 'free'].append((i, u))
    cand = intended = 0
    for callee, d in sorted(sites.items()):
        use, free = d['use'], d['free']
        n = len(use) + len(free)
        if not use:
            continue
        tag = 'intended' if len(use) / n > 0.6 and n >= 3 else 'CANDIDATE'
        if tag == 'intended':
            intended += 1
            if not a.all:
                continue
        else:
            cand += 1
        print('%s clobbers A: %d of %d call sites load A first and use it again  [%s]' % (callee, len(use), n, tag))
        for i, u in use:
            print('    %s:%d JSR %s -> %s:%d %s' % (P.ins[i][2], P.ins[i][3], callee, u[0], u[1], u[2]))
    print('routines clobbering A: %d; intended: %d, candidates: %d' % (sum(clob.values()), intended, cand))


if __name__ == '__main__':
    main()
