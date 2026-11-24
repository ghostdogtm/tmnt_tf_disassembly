#!/usr/bin/env python3
"""Register-clobber scan on the control-flow graph of the generated sources (src/prg/*.asm).

Looks for the pattern that hides a real game bug (docs/ai.md: Casey's second distance check): a caller loads X or Y,
calls a routine that leaves that register changed, and then uses the register again without reloading it.

  1. Per routine: does any path from its entry to an RTS end with X / Y written by something other than a restore?
     A restore is `LDX/LDY` from memory or `PLA` + `TAX/TAY`; `JSR` to a clobbering routine propagates (fixpoint).
  2. Per `JSR` to a clobbering routine: the register was set in the 10 instructions before the call and a path
     (branches followed, up to DEPTH instructions) uses it before any reload.
  3. Routines that return a value in X / Y on purpose show up at most of their call sites; they are listed as
     "intended" when more than 60% of the sites use the register. The rest are the candidates to read.

  python tools/clobber_scan.py [--all] [--depth N]

Jump-table handlers (`JSR JumpTable` followed by .word entries) and indirect jumps end a path: what they run is not
followed. Cross-bank `JSR` and `JMP` use the global labels. Output only, nothing is written.
"""
import argparse
import glob
import os
import re
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTR = re.compile(r'^\s+([A-Z]{3})\b\s*([^;]*?)\s*(?:;.*)?$')
LABEL = re.compile(r'^([A-Za-z_][A-Za-z0-9_]*):')
LOCAL = re.compile(r'^@([A-Za-z0-9_]+):')
OPPOSITE = {'BPL': 'BMI', 'BMI': 'BPL', 'BEQ': 'BNE', 'BNE': 'BEQ', 'BCC': 'BCS', 'BCS': 'BCC', 'BVC': 'BVS', 'BVS': 'BVC'}
BRANCH = {'BCC', 'BCS', 'BEQ', 'BNE', 'BMI', 'BPL', 'BVC', 'BVS'}
REG_X = {'W': {'LDX', 'TAX', 'TSX'}, 'R': ('X',)}


def module_files():
    """the PRG source files in ROM order (the .include lines of src/main.asm)"""
    inc = re.findall(r'^\.include "(prg/[^"]+)"', open(os.path.join(ROOT, 'src', 'main.asm'), encoding='utf-8').read(), re.M)
    return [os.path.join(ROOT, 'src', p) for p in inc]


class Prog:
    def __init__(self):
        self.ins = []                # (mnemonic, operand, file, line)
        self.glabel = {}             # global label -> index
        self.local = {}              # (scope, name) -> index
        self.scope_of = []           # index -> scope (last global label)
        self.label_at = {}           # index -> global label name
        self.routines = set()

    def load(self):
        for path in module_files():
            scope = os.path.basename(path)
            for n, line in enumerate(open(path, encoding='utf-8'), 1):
                line = line.rstrip('\n')
                m = LABEL.match(line)
                if m:
                    scope = m.group(1)
                    self.glabel[scope] = len(self.ins)
                    self.label_at[len(self.ins)] = scope
                    line = line[m.end():]
                m = LOCAL.match(line)
                if m:
                    self.local[(scope, m.group(1))] = len(self.ins)
                    continue
                m = INSTR.match(line)
                if m and not line.lstrip().startswith('.'):
                    self.ins.append((m.group(1), m.group(2), os.path.basename(path), n))
                    self.scope_of.append(scope)

    def target(self, i, operand):
        name = operand.strip()
        if name.startswith('@'):
            return self.local.get((self.scope_of[i], name[1:]))
        return self.glabel.get(name)

    def succ(self, i):
        """successors inside the program: [(index, kind)] kind: 'next' | 'jump' ; empty list = path ends"""
        mn, op, _f, _l = self.ins[i]
        if mn == 'RTS' or mn == 'RTI' or mn == 'BRK':
            return []
        if mn == 'JMP':
            if op.startswith('('):
                return []
            t = self.target(i, op)
            return [t] if t is not None else []
        if mn in BRANCH:
            out = []
            t = self.target(i, op)
            if t is not None:
                out.append(t)
            prev = self.ins[i - 1][0] if i else ''
            always = OPPOSITE.get(prev) == mn or (prev == 'CLC' and mn == 'BCC') or (prev == 'SEC' and mn == 'BCS')
            if i + 1 < len(self.ins) and not always:
                out.append(i + 1)
            return out
        if mn == 'JSR' and op.strip() in ('JumpTable', 'SndJumpTable', 'DispatchTable'):
            return []
        return [i + 1] if i + 1 < len(self.ins) else []


def writes(mn, op, reg):
    """kind of write to X/Y: None, 'restore', 'clobber'"""
    r = reg
    ld, ta = 'LD' + r, 'TA' + r
    if mn == ld:
        return 'restore' if not op.startswith('#') else 'clobber'
    if mn == ta:
        return 'clobber'
    if mn in ('IN' + r, 'DE' + r):
        return 'clobber'
    if mn == 'TSX' and r == 'X':
        return 'clobber'
    return None


def reads(mn, op, reg):
    r = reg
    if mn in ('ST' + r, 'CP' + r, 'T' + r + 'A', 'IN' + r, 'DE' + r):
        return True
    if mn in ('LDX', 'LDY') and mn != 'LD' + r:
        pass
    if re.search(r',\s*' + r + r'\b', op) or re.search(r',\s*' + r + r'\)', op):
        return mn not in ('JMP',) or True
    return False


def summarize(P, depth_limit=4000):
    """fixpoint: clob[(entry_index, reg)] for every routine entry that is the target of a JSR"""
    entries = set()
    for i, (mn, op, _f, _l) in enumerate(P.ins):
        if mn == 'JSR':
            t = P.target(i, op)
            if t is not None:
                entries.add(t)
    clob = {(e, r): False for e in entries for r in 'XY'}
    changed = True
    while changed:
        changed = False
        for e in entries:
            for r in 'XY':
                if clob[(e, r)]:
                    continue
                if path_clobbers(P, e, r, clob, depth_limit):
                    clob[(e, r)] = True
                    changed = True
    return entries, clob


def path_clobbers(P, entry, reg, clob, limit):
    seen = set()
    stack = [(entry, 'orig', False)]
    steps = 0
    while stack:
        i, st, after_pla = stack.pop()
        if (i, st, after_pla) in seen:
            continue
        seen.add((i, st, after_pla))
        steps += 1
        if steps > limit:
            break
        mn, op, _f, _l = P.ins[i]
        if mn == 'RTS':
            if st == 'mod':
                return True
            continue
        nst, npla = st, False
        if mn == 'PLA':
            npla = True
        w = writes(mn, op, reg)
        if w:
            if w == 'restore' or (mn == 'TA' + reg and after_pla):
                nst = 'orig'
            else:
                nst = 'mod'
        elif mn == 'JSR':
            t = P.target(i, op)
            if t is not None and clob.get((t, reg)):
                nst = 'mod'
        for s in P.succ(i):
            stack.append((s, nst, npla))
    return False


def input_use(P, entries, clob, limit=4000):
    """inp[(entry, reg)]: some path from the entry reads reg before writing it (the routine takes reg as input)"""
    inp = {(e, r): False for e in entries for r in 'XY'}
    changed = True
    while changed:
        changed = False
        for e in entries:
            for r in 'XY':
                if inp[(e, r)]:
                    continue
                if reads_first(P, e, r, clob, inp, limit):
                    inp[(e, r)] = True
                    changed = True
    return inp


def reads_first(P, start, reg, clob, inp, limit, depth=None):
    """path from start reaches a read of reg (directly or through a callee that takes it as input) before a write;
    returns the (file, line, text) of the first such use or None"""
    seen = set()
    stack = [(start, 0)]
    steps = 0
    while stack:
        i, d = stack.pop()
        if i in seen or (depth is not None and d > depth):
            continue
        seen.add(i)
        steps += 1
        if steps > limit:
            break
        mn, op, f, l = P.ins[i]
        if mn == 'JSR':
            t = P.target(i, op)
            if t is not None and inp.get((t, reg)):
                return (f, l, 'JSR ' + op.strip() + ' (takes ' + reg + ' as input)')
            if t is not None and clob.get((t, reg)):
                continue                       # the callee rewrites reg: what follows sees the returned value
        elif reads(mn, op, reg) and mn != 'LD' + reg:
            if mn == 'ST' + reg and any(P.ins[k][0] == 'LD' + reg and P.ins[k][1] == op for k in range(i + 1, min(i + 60, len(P.ins)))):
                pass                            # STY var ... LDY var: the routine saves and restores the register
            else:
                return (f, l, mn + ' ' + op)
        w = writes(mn, op, reg)
        if w:
            continue
        for s in P.succ(i):
            stack.append((s, d + 1))
    return None


def defined_before(P, i, reg, window=40):
    for k in range(i - 1, max(i - 1 - window, -1), -1):
        mn, op, _f, _l = P.ins[k]
        if mn in ('RTS', 'JMP', 'RTI'):
            return False
        w = writes(mn, op, reg)
        if w and mn != 'T' + 'A' + reg or (w and mn == 'TA' + reg):
            return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--all', action='store_true', help='also list the routines judged intended')
    ap.add_argument('--depth', type=int, default=25)
    a = ap.parse_args()
    P = Prog()
    P.load()
    entries, clob = summarize(P)
    inp = input_use(P, entries, clob)
    sites = defaultdict(lambda: defaultdict(list))   # (callee, reg) -> list of (call index, use or None)
    for i, (mn, op, f, l) in enumerate(P.ins):
        if mn != 'JSR':
            continue
        t = P.target(i, op)
        if t is None:
            continue
        for r in 'XY':
            if not clob.get((t, r)):
                continue
            if not defined_before(P, i, r):
                sites[(op.strip(), r)]['nodef'].append(i)
                continue
            u = reads_first(P, i + 1, r, clob, inp, 4000, a.depth)
            sites[(op.strip(), r)]['use' if u else 'free'].append((i, u))
    cand = intended = 0
    for (callee, r), d in sorted(sites.items()):
        use, free = d['use'], d['free']
        n = len(use) + len(free)
        if not use:
            continue
        share = len(use) / n
        tag = 'intended' if share > 0.6 and n >= 3 else 'CANDIDATE'
        if tag == 'intended':
            intended += 1
            if not a.all:
                continue
        else:
            cand += 1
        print('%s clobbers %s: %d of %d call sites load %s first and use it again  [%s]' % (callee, r, len(use), n, r, tag))
        for i, u in use:
            f, l = P.ins[i][2], P.ins[i][3]
            print('    %s:%d JSR %s -> %s:%d %s' % (f, l, callee, u[0], u[1], u[2]))
    print('routines clobbering X: %d, Y: %d; callee/register pairs judged intended: %d, candidates: %d' % (
        sum(1 for (e, r), v in clob.items() if v and r == 'X'), sum(1 for (e, r), v in clob.items() if v and r == 'Y'),
        intended, cand))


if __name__ == '__main__':
    main()
