#!/usr/bin/env python3
"""Run tools/mesen/explore.lua headless (Mesen 2 --testrunner), one emulator at a time.

  python tools/mesen/run_mesen.py --out DIR [--rom ROM] [--frames N] [--runs NAME:SEED ...] [--shot-every N]
                                  [--light] [--reads] [--start-every N] [--p2] [--cfg "lua fields"] [--extra FILE ...]

The Mesen folder (default: ./mesen, the project's own copy) is run in place; its settings.json is patched to allow Lua
IO and zero the RAM at power on. Never point --mesen at an installed Mesen you use for playing. The fixed-bank sites with $8000-$BFFF operands are taken from tools/disasm.py.
Results: DIR/<name>.{exec,read,hints,pairs,acc,vals,progress} + screenshots (see explore.lua).
Then: python tools/mesen/merge_runs.py DIR   (bank hints -> tools/labels/banks.txt, coverage -> tools/mesen/cdl/)
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
ROOT = os.path.dirname(TOOLS)
sys.path.insert(0, TOOLS)
import disasm as d  # noqa: E402


def setup(work):
    """Patch settings.json of the project's own mesen/ copy in place (it is a private copy, not the user's installed one)."""
    p = os.path.join(work, 'settings.json')
    s = open(p, encoding='utf-8').read()
    s = s.replace('"AllowIoOsAccess": false', '"AllowIoOsAccess": true')
    s = re.sub(r'"ScriptTimeout": \d+', '"ScriptTimeout": 100', s)
    s = s.replace('"RamPowerOnState": "Random"', '"RamPowerOnState": "AllZeros"')
    # Two plain NES pads on ports 1/2 and nothing on the expansion port: with a Famicom + four-player adapter setup,
    # emu.setInput(..., 1) lands on the expansion port, which the game ORs into player 1 ($4016 bit 1).
    cfg = json.loads(s.lstrip('﻿'))
    nes = cfg.get('Nes', {})
    nes['ConsoleType'] = 'Nes001'
    for port, kind in (('Port1', 'NesController'), ('Port2', 'NesController'), ('ExpPort', 'None')):
        if isinstance(nes.get(port), dict):
            nes[port]['Type'] = kind
    s = json.dumps(cfg, indent=2)
    open(p, 'w', encoding='utf-8').write(s)


def lua_str(p):
    return '[[' + os.path.abspath(p) + ']]'


def fixed_sites():
    D = d.Disasm(os.path.join(ROOT, d.ROM_NAME), d.default_cdls(), os.path.join(TOOLS, 'labels'))
    D.run()
    sites = set()
    for i in D.instrs():
        if d.bank_of(i) < 14:
            continue
        mn, mode, n = D.decode(i)
        if n == 3 and mode in ('abs', 'abx', 'aby', 'ind'):
            a = D.operand(i, n)
            if 0x8000 <= a < 0xC000 and not D.is_mmc3_write(mn, mode, a):
                sites.add(d.cpu(i))
    return sorted(sites)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--mesen', default=os.path.join(ROOT, 'mesen'))
    ap.add_argument('--out', required=True)
    ap.add_argument('--rom', default=os.path.join(ROOT, d.ROM_NAME))
    ap.add_argument('--frames', type=int, default=18000)
    ap.add_argument('--runs', nargs='*', default=['r1:1'])
    ap.add_argument('--shot-every', type=int, default=0)
    ap.add_argument('--start-every', type=int, default=0)
    ap.add_argument('--light', action='store_true')
    ap.add_argument('--reads', action='store_true')
    ap.add_argument('--p2', action='store_true', help='random input on controller 2 too')
    ap.add_argument('--cfg', default='', help='extra Lua table fields, e.g. "bot = \\"idle\\", script = { {60, \\"start\\"} }"')
    ap.add_argument('--extra', nargs='*', default=[], help='Lua files appended to explore.lua')
    ap.add_argument('--timeout', type=int, default=3000)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    work = a.mesen
    setup(work)
    sites = fixed_sites()
    rc = 0
    for spec in a.runs:                                  # sequential: only one emulator instance at a time
        name, seed = (spec.split(':') + ['1'])[:2]
        prefix = os.path.join(a.out, name)
        cfg = ('CFG = { out = %s, frames = %d, seed = %s, shotEvery = %d, startEvery = %d, light = %s, reads = %s, p2 = %s,'
               ' sites = { %s }%s }\n') % (lua_str(prefix), a.frames, seed, a.shot_every, a.start_every,
                                           'true' if a.light else 'false', 'true' if a.reads else 'false',
                                           'true' if a.p2 else 'false',
                                           ', '.join('0x%04X' % s for s in sites), (', ' + a.cfg) if a.cfg else '')
        script = prefix + '.lua'
        open(script, 'w').write(cfg + open(os.path.join(HERE, 'explore.lua')).read()
                                + ''.join('\n' + open(x).read() for x in a.extra))
        for f in ('.progress', '.exec'):
            if os.path.exists(prefix + f):
                os.remove(prefix + f)
        t0 = time.time()
        proc = subprocess.Popen([os.path.join(work, 'Mesen.exe'), '--testrunner', os.path.abspath(a.rom), script,
                                 '--timeout=%d' % a.timeout], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        try:                                             # a Lua error leaves Mesen waiting for its timeout
            for _ in range(60):
                if os.path.exists(prefix + '.progress') or proc.poll() is not None:
                    break
                time.sleep(1)
            else:
                proc.kill()
                print('%s: no %s.progress after 60 s (Lua error?), Mesen killed' % (name, name))
            out = proc.communicate()[0].decode(errors='replace')
        except KeyboardInterrupt:
            proc.kill()
            raise
        ok = os.path.exists(prefix + '.exec')
        print('%s: exit %s, %.0f s%s' % (name, proc.returncode, time.time() - t0, '' if ok else ' (no output)'))
        if not ok:
            print(out[-2000:])
            rc = 1
    return rc


if __name__ == '__main__':
    sys.exit(main())
