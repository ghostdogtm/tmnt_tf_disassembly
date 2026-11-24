#!/usr/bin/env python3
"""TMNT Tournament Fighters (U) - CDL driven disassembler producing ca65 sources (MMC3, banked).

  python tools/disasm.py [--rom ROM] [--cdl CDL ...] [--out DIR] [--labels DIR] [--build] [--no-chr]

ROM: iNES header + 128KB PRG (16 banks of 8KB) + 128KB CHR, mapper 4 (MMC3), PRG mode 0. The game always maps the
switchable banks in pairs (R6 = n, R7 = n + 1, n even), so every bank has one CPU address:
    even banks 00-0C -> $8000-$9FFF, odd banks 01-0D -> $A000-$BFFF, bank 0E -> $C000 (fixed), 0F -> $E000 (fixed).
A byte is identified by its index into the PRG (= file offset - 16). Label files write it as BB:AAAA (bank:CPU
address); for the fixed banks a plain AAAA ($C000-$FFFF) is enough.

An operand $8000-$BFFF refers to the bank pair the code runs in; from the fixed banks it needs a hint: a
'bank' line in rom.txt or tools/labels/banks.txt (generated from Mesen runs by tools/mesen/merge_runs.py).
Without a hint it stays a number (listed in docs/coverage.txt as unresolved).

Inputs : ROM (.nes), CDL (Mesen2 'CDLv2' or FCEUX; several are merged), tools/labels/{ram,rom,const,banks}.txt
Outputs: src/prg/BB_name.asm (one file per module), src/main.asm, src/chr.asm, src/defines.inc, src/ram.inc,
         src/const.inc, config.cfg, header.bin, assemble.bat, compare.bat, docs/coverage.txt, game.mlb (Mesen labels)
**Overwrites src/** - after editing src/*.asm by hand run it only with --out DIR.
"""
import argparse
import bisect
import glob
import os
import re
import subprocess
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from opcodes import OPS, BRANCHES  # noqa: E402

BANK = 0x2000           # PRG bank size (MMC3 8KB banks)
NBANKS = 16
SIZE = BANK * NBANKS    # 128KB PRG
CHR_SIZE = 0x20000      # 128KB CHR
FIXED = {14: 0xC000, 15: 0xE000}
AUTO_IMM_PAIRS = False  # guess #<label/#>label pairs (declare them with 'imm' instead)
UNREF_MIN = 6           # unreferenced word tables need at least this many words pointing at code
FILL_MIN = 8            # identical-byte runs of at least this length become .res
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ROM_NAME = 'Teenage Mutant Ninja Turtles - Tournament Fighters (U) [!].nes'
CDL_NAME = 'Teenage Mutant Ninja Turtles - Tournament Fighters (U) [!].cdl'
OUT_NAME = 'game'
GAME = 'TMNT Tournament Fighters (U)'

CDL_CODE, CDL_DATA, CDL_JUMP, CDL_SUB, CDL_PCM = 1, 2, 4, 8, 0x80     # Mesen2 NES CDL flags (PCM = DMC sample read)
K_UNK, K_OP, K_ARG, K_DATA, K_WORD = 0, 1, 2, 3, 4      # byte kinds

HW_REGS = {0x2000: 'PPUCTRL', 0x2001: 'PPUMASK', 0x2002: 'PPUSTATUS', 0x2003: 'OAMADDR',
           0x2004: 'OAMDATA', 0x2005: 'PPUSCROLL', 0x2006: 'PPUADDR', 0x2007: 'PPUDATA',
           0x4000: 'SQ1_VOL', 0x4001: 'SQ1_SWEEP', 0x4002: 'SQ1_LO', 0x4003: 'SQ1_HI',
           0x4004: 'SQ2_VOL', 0x4005: 'SQ2_SWEEP', 0x4006: 'SQ2_LO', 0x4007: 'SQ2_HI',
           0x4008: 'TRI_LINEAR', 0x4009: 'APU_UNUSED1', 0x400A: 'TRI_LO', 0x400B: 'TRI_HI',
           0x400C: 'NOISE_VOL', 0x400D: 'APU_UNUSED2', 0x400E: 'NOISE_LO', 0x400F: 'NOISE_HI',
           0x4010: 'DMC_FREQ', 0x4011: 'DMC_RAW', 0x4012: 'DMC_START', 0x4013: 'DMC_LEN',
           0x4014: 'OAMDMA', 0x4015: 'SNDCHN', 0x4016: 'JOY1', 0x4017: 'JOY2'}
MMC3_REGS = {0x8000: 'MMC3_BANK_SELECT', 0x8001: 'MMC3_BANK_DATA', 0xA000: 'MMC3_MIRRORING',
             0xA001: 'MMC3_PRG_RAM', 0xC000: 'MMC3_IRQ_LATCH', 0xC001: 'MMC3_IRQ_RELOAD',
             0xE000: 'MMC3_IRQ_DISABLE', 0xE001: 'MMC3_IRQ_ENABLE'}
WRITES = {'STA', 'STX', 'STY'}
RESERVED = {o[0].lower() for o in OPS.values()} | {'a', 'x', 'y', 's', 'z'}
NAME_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')


# ----------------------------------------------------------------------------- addresses
def base_of(b):
    return FIXED.get(b, 0x8000 if b % 2 == 0 else 0xA000)


def bank_of(i):
    return i >> 13


def cpu(i):
    return base_of(i >> 13) + (i & 0x1FFF)


def bank_end(i):
    """index of the first byte after the bank of i"""
    return (i | 0x1FFF) + 1


def unit_end(i):
    """index of the first byte after the 16KB unit of i: a bank pair n/n+1 ($8000-$BFFF, always mapped together)
    or the fixed banks 0E/0F ($C000-$FFFF). Code, branches and inline tables may run across the bank boundary
    inside a unit."""
    return (i | 0x3FFF) + 1


def fixed_idx(a):
    """$C000-$FFFF -> index into the PRG (fixed banks 0E/0F)"""
    return ((14 if a < 0xE000 else 15) * BANK + (a & 0x1FFF)) if 0xC000 <= a <= 0xFFFF else None


def where(i):
    """'BB:AAAA' for the switchable banks, '$AAAA' for the fixed ones"""
    return '%02X:%04X' % (i >> 13, cpu(i)) if i >> 13 < 14 else '$%04X' % cpu(i)


def parse_addr(s):
    return int(s.replace('$', '').replace('0x', ''), 16)


def loc(s, bank=None):
    """'BB:AAAA' or 'AAAA' ($C000-$FFFF, or any address when bank is given) -> PRG index"""
    if ':' in s:
        bs, s = s.split(':')
        bank = int(bs, 16)
    a = parse_addr(s)
    if bank is None:
        i = fixed_idx(a)
        if i is None:
            raise ValueError('%s: $8000-$BFFF needs a bank (BB:AAAA)' % s)
        return i
    if not 0 <= bank < NBANKS or not base_of(bank) <= a < base_of(bank) + BANK:
        raise ValueError('$%04X is not in bank %02X ($%04X-$%04X)' % (a, bank, base_of(bank), base_of(bank) + BANK - 1))
    return bank * BANK + a - base_of(bank)


def parse_range(spec):
    """'BB:LO-HI' / 'LO-HI' -> (lo idx, hi idx) inside one bank"""
    lo, _, hi = spec.partition('-')
    i = loc(lo)
    j = loc(hi, bank_of(i)) if hi else i
    if j < i:
        raise ValueError('range %r is reversed' % spec)
    return i, j


# ----------------------------------------------------------------------------- label files
def check_name(name, at, local_ok=False):
    if local_ok and name.startswith('@'):
        name = name[1:]                                 # ca65 cheap local label
    if name.lower() in RESERVED or not NAME_RE.match(name):
        sys.exit('%s: bad name %r' % (at, name))


def load_consts(path):
    """NAME = EXPR [@var ...] [; comment]   constant (src/const.inc); @var (RAM/register name, may be name+N): used
                                           automatically where the value is stored into var (LDx #v / STx var) or
                                           tested against it (LDx var / CMP|CPx|AND|ORA|EOR #v, also later CMPs of
                                           the same LDx when only branches lie between)
       use LOC [LOC ...] EXPR               the immediate of these instructions is EXPR (checked against the byte)
       data LOC EXPR[, EXPR ...] [; c]      data bytes from LOC on are printed as these expressions (checked);
                                           the comment goes to the end of the line
       an indented comment-only line right after NAME = ... continues that constant's comment
       struct Name field[:size] ... [; c]   .struct in src/const.inc (fields are bytes unless :size)
       array var Name                       RAM var is an array of struct Name: var+N is printed as
                                           var+(N - field offset)+Name::field
       enum [; c] ... endenum               the NAME = ... lines between are printed as an anonymous .enum
       LOC = BB:AAAA, or AAAA in the fixed banks"""
    r = dict(defs=[], auto=[], uses={}, data={}, datacomment={}, blocks=[], structs={}, arrays={})
    if not os.path.exists(path):
        return r
    prev_def = None
    for ln, line in enumerate(open(path, encoding='utf-8'), 1):
        code = re.sub(r"'.'", lambda m: m.group(0).replace(';', '\0'), line)
        code, _, comment = code.partition(';')
        code = code.replace('\0', ';').strip()
        if not code:
            if line[:1] in ' \t' and comment.strip() and prev_def == ln - 1:     # indented: comment continuation
                n, e, c, w = r['defs'][-1]
                r['defs'][-1] = (n, e, c + '\n' + comment.strip(), w)
                prev_def = ln
            continue
        at = '%s:%d' % (path, ln)
        parts = code.split()
        try:
            if parts[0] == 'struct':
                if len(parts) < 3:
                    sys.exit('%s: struct Name field[:size] ...' % at)
                fields, off = [], 0
                for f in parts[2:]:
                    fn, _, size = f.partition(':')
                    fields.append((fn, off, int(size or '1', 0)))
                    off += int(size or '1', 0)
                r['structs'][parts[1]] = fields
                r['blocks'].append((len(r['defs']), 'struct', parts[1], comment.strip()))
                continue
            if parts[0] == 'array':
                if len(parts) != 3 or parts[2] not in r['structs']:
                    sys.exit('%s: array var StructName (struct defined above)' % at)
                r['arrays'][parts[1]] = parts[2]
                continue
            if parts[0] in ('enum', 'endenum'):
                r['blocks'].append((len(r['defs']), parts[0], None, comment.strip()))
                continue
            if parts[0] == 'data':
                m = re.match(r'data\s+(\S+)\s+(.+)$', code)
                if not m:
                    sys.exit('%s: data LOC EXPR[, EXPR ...]' % at)
                i = loc(m.group(1))
                if comment.strip():
                    r['datacomment'][i] = comment.strip()
                for k, e in enumerate(x.strip() for x in m.group(2).split(',')):
                    if i + k in r['data']:
                        sys.exit('%s: %s already has a data expression' % (at, where(i + k)))
                    r['data'][i + k] = (e, at)
                continue
            if parts[0] == 'use':
                if len(parts) < 3:
                    sys.exit('%s: use LOC [LOC ...] EXPR' % at)
                for a in parts[1:-1]:
                    i = loc(a)
                    if i in r['uses']:
                        sys.exit('%s: %s already has a constant' % (at, a))
                    r['uses'][i] = (parts[-1], at)
                continue
        except ValueError as e:
            sys.exit('%s: %s' % (at, e))
        name, eq, rest = code.partition('=')
        name = name.strip()
        if not eq:
            sys.exit('%s: expected NAME = EXPR or use ...' % at)
        check_name(name, at)
        words = rest.split()
        expr = ' '.join(w for w in words if not w.startswith('@'))
        r['defs'].append((name, expr, comment.strip(), at))
        prev_def = ln
        r['auto'].extend((name, w[1:], at) for w in words if w.startswith('@'))
    return r


def eval_expr(expr, names, at):
    """value of a ca65 constant expression: $hex %bin 'c' numbers, names, + - * / & | ^ ~ << >> ( ),
    a leading < or > takes the low or high byte"""
    part = None
    e = expr.strip()
    if e[:1] in '<>' and e[1:2] not in '<>':
        part, e = e[0], e[1:]
    py = re.sub(r"'(.)'", lambda m: str(ord(m.group(1))), e)
    py = re.sub(r'\$([0-9A-Fa-f]+)', r'0x\1', py)
    py = re.sub(r'%([01]+)', r'0b\1', py).replace('/', '//')
    py = re.sub(r'(\w+)::(\w+)', r'\1__\2', py)
    try:
        v = eval(py, {'__builtins__': {}}, dict(names))
    except Exception as ex:
        sys.exit('%s: cannot evaluate %r (%s)' % (at, expr, ex))
    return v & 0xFF if part == '<' else (v >> 8) & 0xFF if part == '>' else v


def load_ram_labels(path):
    """ADDR NAME [SIZE] ; comment"""
    names = {}                      # addr -> (name, size, comment)
    if not os.path.exists(path):
        return names
    for ln, line in enumerate(open(path, encoding='utf-8'), 1):
        code, _, comment = line.partition(';')
        parts = code.split()
        if not parts:
            continue
        check_name(parts[1], '%s:%d' % (path, ln))
        size = int(parts[2], 0) if len(parts) > 2 else 1
        names[parse_addr(parts[0])] = (parts[1], size, comment.strip())
    return names


# text formats (rom.txt `text RANGE CHARMAP FORMAT`): (address word at the start of a record: None, 'word' or
# 'dbyt'; {control byte: (constant, number of argument bytes, effect)}); effect 'addr' = an address word follows,
# 'end' = the record ends (the next one starts with an address word), 'line' = the source line ends there.
# The constants are defined in tools/labels/const.txt.
TEXT_FORMATS = {
    'plain': (None, {0xFF: ('TEXT_END', 0, 'line')}),
    'bit7': (None, {}),
    'ppu': ('word', {0xFE: ('TEXT_NEXT', 0, 'addr'), 0xFF: ('TEXT_END', 0, 'end')}),
    'credits': ('dbyt', {0xFE: ('CREDITS_ERASE', 0, 'addr'), 0xFF: ('TEXT_END', 0, 'end'),
                         0xFD: ('CREDITS_END', 0, 'line')}),
    'story': (None, {0xBB: ('STORY_WAIT', 1, 'line'), 0xBC: ('STORY_CLEAR', 0, 'line'),
                     0xBD: ('STORY_NEWLINE', 0, 'line'), 0xBE: ('STORY_EASY_ONLY', 0, 'line'),
                     0xBF: ('STORY_FADE_MUSIC', 0, 'line'), 0xFF: ('STORY_END', 0, 'line')}),
}


def parse_charmap(tokens):
    """['A-Z=$8B', "'.'=$A5", 'SPACE=$00', 'Copyright=$A6'] -> {byte: "'c'" or name}"""
    m = {}
    for t in tokens:
        k, _, v = t.partition('=')
        b = int(v.replace('$', '0x'), 0)
        if re.match(r"^'.'$", k):
            chars = [k[1]]
        elif k == 'SPACE':
            chars = [' ']
        elif re.match(r'^.-.$', k):
            chars = [chr(c) for c in range(ord(k[0]), ord(k[2]) + 1)]
        elif re.match(r'^[A-Za-z_][A-Za-z0-9_]+$', k):
            m[b] = k
            continue
        else:
            raise ValueError('bad charmap token %s' % t)
        for n, c in enumerate(chars):
            if c == '"' or not ' ' <= c <= '~':
                raise ValueError('charmap character %r cannot go into a string' % c)
            if b + n in m:
                raise ValueError('charmap byte $%02X mapped twice' % (b + n))
            m[b + n] = "'%s'" % c
    return m


def load_rom_labels(path, r=None):
    """LOC name ; comment                     label (LOC = BB:AAAA, or AAAA in the fixed banks $C000-$FFFF)
       code|data|words|rtswords RANGE        force classification (RANGE = BB:LO-HI or LO-HI; rtswords: target-1)
       table RANGE N [header]                data table, N bytes per row; references into it become name+offset
       text RANGE [CHARMAP [FORMAT]]         string, emitted as .byte "..." (plain ASCII without CHARMAP).
                                             FORMAT (TEXT_FORMATS): plain (TEXT_END = $FF ends a string), bit7
                                             (the last byte of a string has bit 7 set, written 'c'|$80), ppu
                                             (PPU address word, tiles, TEXT_NEXT + address .. TEXT_END), credits
                                             (big-endian address, tiles, TEXT_END; CREDITS_ERASE + address +
                                             TEXT_END; CREDITS_END), story (tiles and STORY_* control bytes)
       screens RANGE                         LoadScreen data: streams of a PPU address word and SCR_* commands
                                             (RUN, SEQUENCE, LITERAL, NEXT + address, END), one after another
       metasprites RANGE                     metasprite frames: count, then count sprites of 4 bytes (Y offset,
                                             tile, OAM attributes, X offset); MSPR_JUMP + word = the rest of
                                             the frame is at that address
       movescripts RANGE                     move (attack) scripts: (frame, frames) pairs, MOVE_SOUND + sound id,
                                             MOVE_HIT + attack id (spawns the hit object), MOVE_END
       aiscripts RANGE                       CPU AI action scripts (docs/ai.md): pad bytes (BTN_*), AI_* control bytes
                                             (AI_WAIT + AIC_* condition, AI_GOTO + action, ...), AI_END ends one
       sound RANGE                           sound driver data (docs/sound.md): music and SFX streams, walked from the
                                             soundptrs tables; bytes no stream reaches stay plain data
       framenames LOC N PREFIX [FIRST]       the word table at LOC (N entries): entry k's target (a metasprite frame)
                                             that has no user label is named PREFIX + hex(FIRST + k), 2+ digits
       soundptrs LOC N songs|sfx|env         the pointer table at LOC: N songs of 4 channel words (SQ1, SQ2, TRI,
                                             drums), N SFX words (each points at an SFX header byte) or N envelope
                                             words (steps time<<4|value, ENV_LOOP, ENV_REPEAT + count, ENV_HOLD)
       screentext RANGE CHARMAP              inside a screens block: SCR_LITERAL runs whose tiles all map are
                                             written as CHARMAP strings
       charmap NAME TOKEN=$NN ...            a font for text lines: A-Z=$8B (a range of characters from $8B),
                                             'c'=$NN (one character), SPACE=$NN, Name=$NN (a tile with no
                                             character: written as the constant Name); src/charmap.inc gets
                                             the macro CHARMAP_NAME (set) and CHARMAP_ASCII (restore)
       split LOC LOC N [adj] [prefix]        lo/hi address tables of N entries (adj 1 = RTS trick)
       imm LOC LOC                           immediates at these two instructions are #<target / #>target
       note LOC ; text                       comment line printed before the line at LOC
       bitskip LOC                           BIT abs ($2C) used to skip a 2-byte instruction
       entry LOC [; comment]                 code that nothing known calls (dead code, or a caller not found yet):
                                             trace from LOC; the source gets a note
       module LOC name ; description         source file src/prg/BB_name.asm starts at LOC (every bank also
                                             starts a module, default name 'bank')
       dbyt RANGE / numwords RANGE           16-bit numbers, big-endian / little-endian, not addresses
       ref LOC Name[+-N]                     absolute operand of the instruction at LOC written as Name+-N (checked)
       alias RANGE RAM[/N] name ; c          inside this code range the N bytes at RAM are written as name, name+1..
       bank LOC|RANGE TT                     $8000-$BFFF operands / table words at these places refer to the bank
                                             pair TT (an even bank, mapped at $8000 with TT+1 at $A000); '-' = none
       rawsym AAAA name                      unresolved operand $AAAA is written as name (name = $AAAA in
                                             src/defines.inc), e.g. a read of the bank number byte at $8000
       bankcall LOC TT                       the routine at LOC maps bank pair TT: in the fixed banks, $8000-$BFFF
                                             operands of the instructions that follow a JSR LOC (straight line, up
                                             to the next RTS/JMP/bankcall) refer to pair TT
       dispatch LOC                          the routine at LOC pops its return address and jumps through the
                                             inline .word table that follows the JSR (A = index); the JSR does not
                                             return, the words are read until code / a word not pointing at code"""
    if r is None:
        r = dict(labels={}, force=[], notes=defaultdict(list), tables={}, texts={}, textfmt={}, charmaps={}, screens={}, screentext={}, msprites={}, mscripts={}, aiscripts={}, sound=[], soundptrs=[], framenames=[], splits=[], imms=[], bitskip=[], entries=[],
                 modules={}, num16={}, refs={}, aliases=[], hints={}, rawsyms={}, bankcalls={}, dispatch=set())
    if not os.path.exists(path):
        return r
    for ln, line in enumerate(open(path, encoding='utf-8'), 1):
        code, _, comment = line.partition(';')
        parts = code.split()
        comment = comment.strip()
        if not parts:
            continue
        at = '%s:%d' % (path, ln)
        try:
            cmd = parts[0]
            if cmd in ('code', 'data', 'words', 'rtswords'):
                r['force'].append((cmd,) + parse_range(parts[1]))
            elif cmd == 'table':
                lo, hi = parse_range(parts[1])
                r['tables'][lo] = (int(parts[2], 0), hi, ' '.join(parts[3:]) or comment)
                r['force'].append(('data', lo, hi))
            elif cmd == 'text':
                lo, hi = parse_range(parts[1])
                r['texts'][lo] = hi
                r['force'].append(('data', lo, hi))
                if len(parts) > 2:
                    fmt = parts[3] if len(parts) > 3 else None
                    if fmt not in (None,) + tuple(TEXT_FORMATS):
                        raise ValueError('text format must be one of ' + ', '.join(TEXT_FORMATS))
                    r['textfmt'][lo] = (parts[2], fmt)
            elif cmd == 'screens':
                lo, hi = parse_range(parts[1])
                r['screens'][lo] = hi
                r['force'].append(('data', lo, hi))
            elif cmd == 'metasprites':
                lo, hi = parse_range(parts[1])
                r['msprites'][lo] = hi
                r['force'].append(('data', lo, hi))
            elif cmd == 'movescripts':
                lo, hi = parse_range(parts[1])
                r['mscripts'][lo] = hi
                r['force'].append(('data', lo, hi))
            elif cmd == 'aiscripts':
                lo, hi = parse_range(parts[1])
                r['aiscripts'][lo] = hi
                r['force'].append(('data', lo, hi))
            elif cmd == 'sound':
                lo, hi = parse_range(parts[1])
                r['sound'].append((lo, hi))
                r['force'].append(('data', lo, hi))
            elif cmd == 'framenames':
                r['framenames'].append((loc(parts[1]), int(parts[2], 0), parts[3], int(parts[4], 0) if len(parts) > 4 else 0))
            elif cmd == 'soundptrs':
                if parts[3] not in ('songs', 'sfx', 'env'):
                    raise ValueError('soundptrs kind must be songs, sfx or env')
                r['soundptrs'].append((loc(parts[1]), int(parts[2], 0), parts[3]))
            elif cmd == 'screentext':
                lo, hi = parse_range(parts[1])
                if parts[2] not in r['charmaps']:
                    raise ValueError('%s: screentext charmap %s is not defined (yet)' % (parts[1], parts[2]))
                r['screentext'][lo] = (hi, parts[2])
            elif cmd == 'charmap':
                r['charmaps'][parts[1]] = parse_charmap(parts[2:])
            elif cmd == 'split':
                lo, hi, n = loc(parts[1]), loc(parts[2]), int(parts[3], 0)
                adj = int(parts[4], 0) if len(parts) > 4 else 0
                r['splits'].append((lo, hi, n, adj, parts[5] if len(parts) > 5 else None))
            elif cmd == 'imm':
                r['imms'].append((loc(parts[1]), loc(parts[2])))
            elif cmd in ('dbyt', 'numwords'):
                lo, hi = parse_range(parts[1])
                if (hi - lo + 1) % 2:
                    raise ValueError('odd number of bytes')
                r['force'].append(('data', lo, hi))
                for k in range(lo, hi, 2):
                    r['num16'][k] = cmd
            elif cmd == 'module':
                i = loc(parts[1])
                if not re.match(r'[a-z][a-z0-9_]*$', parts[2]):
                    raise ValueError('module LOC name (lower case)')
                r['modules'][i] = (parts[2], comment)
            elif cmd == 'bitskip':
                r['bitskip'].append(loc(parts[1]))
            elif cmd == 'entry':
                i = loc(parts[1])
                r['entries'].append(i)
                r['notes'][i].append('No caller found (rom.txt entry)' + ((': ' + comment) if comment else ''))
            elif cmd == 'ref':
                m = re.match(r'([A-Za-z_]\w*)(?:([+-])(\$[0-9A-Fa-f]+|\d+))?$', parts[2])
                if not m:
                    raise ValueError('ref LOC Name[+-N]')
                off = int(m.group(3).replace('$', '0x'), 0) if m.group(3) else 0
                r['refs'][loc(parts[1])] = (m.group(1), -off if m.group(2) == '-' else off, parts[2])
            elif cmd == 'alias':
                lo, hi = parse_range(parts[1])
                check_name(parts[3], at)
                ram, _, size = parts[2].partition('/')
                r['aliases'].append((lo, hi, int(ram.lstrip('$'), 16), int(size or 1), parts[3], comment))
            elif cmd == 'bank':
                lo, hi = parse_range(parts[1])
                tt = None if parts[2] == '-' else int(parts[2], 16)
                if tt is not None and (tt % 2 or tt >= 14):
                    raise ValueError('bank pair must be an even bank 00-0C')
                for k in range(lo, hi + 1):
                    r['hints'][k] = tt
            elif cmd == 'bankcall':
                r['bankcalls'][loc(parts[1])] = int(parts[2], 16)
            elif cmd == 'dispatch':
                r['dispatch'].add(loc(parts[1]))
            elif cmd == 'rawsym':
                check_name(parts[2], at)
                r['rawsyms'][parse_addr(parts[1])] = parts[2]
            elif cmd == 'note':
                r['notes'][loc(parts[1])].append(comment)
            else:
                i = loc(cmd)
                check_name(parts[1], at, local_ok=True)
                r['labels'][i] = (parts[1], comment)
        except (ValueError, IndexError) as e:
            sys.exit('%s cannot parse %r (%s)' % (at, line.strip(), e))
    return r


# ----------------------------------------------------------------------------- ROM files
def load_rom(path):
    return open(path, 'rb').read()


def compare_roms(built, original):
    """(ok, message): the assembled ROM against the original dump"""
    a, b = open(built, 'rb').read(), open(original, 'rb').read()
    if a == b:
        return True, 'IDENTICAL'
    diff = [k for k in range(min(len(a), len(b))) if a[k] != b[k]]
    first = diff[0] if diff else min(len(a), len(b))
    at = ''
    if 16 <= first < 16 + SIZE:
        at = ' = PRG %s' % where(first - 16)
    return False, 'DIFFERENT (sizes %d/%d, %d bytes differ, first at file offset $%X%s)' % (
        len(a), len(b), len(diff), first, at)


def load_cdl(paths, prg_size, chr_size):
    """Mesen2 'CDLv2' (9-byte header) or FCEUX (no header; bit 0 code, bit 1 data) -> PRG flags in Mesen2 bits.
    Several files are merged (union of the flags)."""
    out = bytearray(prg_size)
    for p in paths:
        c = open(p, 'rb').read()
        if c[:5] == b'CDLv2':
            c = c[9:]
            mesen = True
        elif len(c) == prg_size + chr_size:
            mesen = False
        else:
            sys.exit('%s: unknown CDL format (%d bytes)' % (p, len(c)))
        if len(c) < prg_size:
            sys.exit('%s: too short for %d bytes of PRG' % (p, prg_size))
        for k in range(prg_size):
            f = c[k]
            if not mesen:
                f = (CDL_CODE if f & 1 else 0) | (CDL_DATA if f & 2 else 0) | (CDL_PCM if f & 0x40 else 0)
            out[k] |= f
    return out


# ----------------------------------------------------------------------------- main class
class Disasm:
    def __init__(self, rom_path, cdl_paths, labels_dir):
        d = load_rom(rom_path)
        if d[:4] != b'NES\x1a' or len(d) != 16 + SIZE + CHR_SIZE:
            sys.exit('%s: expected an iNES file with %dKB PRG + %dKB CHR' % (rom_path, SIZE // 1024, CHR_SIZE // 1024))
        self.header = d[:16]
        self.rom = d[16:16 + SIZE]
        self.chr = d[16 + SIZE:]
        if isinstance(cdl_paths, str):
            cdl_paths = [cdl_paths]
        self.cdl = load_cdl(cdl_paths, SIZE, CHR_SIZE)
        self.kind = bytearray(SIZE)
        self.traced = set()         # instruction starts found by static tracing (not in the CDL)
        self.anomalies = []
        self.user = load_rom_labels(os.path.join(labels_dir, 'banks.txt'))     # generated hints first
        self.user = load_rom_labels(os.path.join(labels_dir, 'rom.txt'), self.user)
        self.ram_user = load_ram_labels(os.path.join(labels_dir, 'ram.txt'))
        self.consts = load_consts(os.path.join(labels_dir, 'const.txt'))
        self.hint = self.user['hints']
        self.immconst = {}          # instruction idx -> constant expression of its immediate
        self.dataexpr = {}          # data byte idx -> expression (const.txt "data")
        self.locked = set()         # forced data: never turned into word tables
        self.word_start = set()
        self.word_adj = {}          # word start -> 1 for RTS-trick tables
        self.table_log = []
        self.table_targets = set()
        self.split = {}             # idx -> ('<'|'>', target idx, adj)
        self.split_ram = {}         # idx -> ('<'|'>', RAM address, adj): split table entries pointing to RAM
        self.immref = {}            # instruction idx -> ('<'|'>', target idx)
        self.refs = defaultdict(set)
        self.labels = {}            # idx -> name
        self.local_scope = {}       # idx of a cheap local label (@name) -> its scope label idx
        self.raw = []               # (idx, text) operands left as raw numbers
        self.unresolved = []        # (idx, value) $8000-$BFFF references without a bank
        self.ram_used = defaultdict(int)
        self.ptrs = set()           # zp addresses used as (zp),Y / (zp,X) pointers
        self.row_break = set()
        self.static_hint = set()    # hints found by apply_bankcalls
        self.dispatch_log = {}      # inline table start -> entries
        self.dispatch_bad = []
        self.unread = set()         # data that no CDL/log saw read: classified by elimination (mark_unread)
        self.bitskips = set()       # BIT abs opcodes ($2C) that skip a hidden instruction (rom.txt bitskip + found)      # inline table entries that stopped a table before its first target

    # ------------------------------------------------------------------ banking
    def res(self, a, src):
        """CPU address a used by the instruction / table entry at src -> PRG index, or None"""
        if 0xC000 <= a <= 0xFFFF:
            return fixed_idx(a)
        if not 0x8000 <= a < 0xC000:
            return None
        if src in self.hint:
            pair = self.hint[src]
        elif src is not None and bank_of(src) < 14:
            pair = bank_of(src) & ~1
        else:
            return None
        if pair is None:
            return None
        return (pair + (1 if a >= 0xA000 else 0)) * BANK + (a & 0x1FFF)

    def is_mmc3_write(self, mn, mode, a):
        return mn in WRITES and mode in ('abs', 'abx', 'aby') and a >= 0x8000

    # ------------------------------------------------------------------ decoding
    def rel_dest(self, i):
        v = self.rom[i + 1]
        t = i + 2 + (v - 256 if v & 0x80 else v)
        return t if t >> 14 == i >> 14 and 0 <= t < SIZE else None

    def decode(self, i):
        op = self.rom[i]
        if op not in OPS:
            return None
        mn, mode, n = OPS[op]
        if i + n > unit_end(i) or (mode == 'rel' and self.rel_dest(i) is None):
            return None
        return mn, mode, n

    def operand(self, i, n):
        return self.rom[i + 1] if n == 2 else self.rom[i + 1] | (self.rom[i + 2] << 8)

    def word(self, i):
        return self.rom[i] | (self.rom[i + 1] << 8)

    def word_target(self, j):
        return self.res(self.word(j) + self.word_adj.get(j, 0), j)

    def set_instr(self, i, n):
        self.kind[i] = K_OP
        for j in range(1, n):
            self.kind[i + j] = K_ARG

    # ------------------------------------------------------------------ CDL + forced ranges
    def classify_cdl(self):
        i = 0
        while i < SIZE:
            f = self.cdl[i]
            if f & CDL_CODE:
                d = self.decode(i)
                if d and all(self.cdl[i + j] & CDL_CODE for j in range(1, d[2])):
                    self.set_instr(i, d[2])
                    i += d[2]
                    continue
                self.anomalies.append(i)
                self.kind[i] = K_DATA
            elif f & (CDL_DATA | CDL_PCM):
                self.kind[i] = K_DATA
            i += 1

    def apply_force(self):
        for kind, lo, hi in self.user['force']:
            if kind == 'code':
                i = lo
                while i <= hi:
                    d = self.decode(i)
                    if not d:
                        sys.exit('forced code at %s is not a valid instruction' % where(i))
                    self.set_instr(i, d[2])
                    i += d[2]
                continue
            clash = [j for j in range(lo, hi + 1) if self.cdl[j] & CDL_CODE]
            if clash:
                print('WARNING: forced %s %s-%04X overrides %d byte(s) the CDL saw as code (first %s)'
                      % (kind, where(lo), cpu(hi), len(clash), where(clash[0])))
            for j in range(lo, hi + 1):
                if kind == 'data':
                    self.kind[j] = K_DATA
                    self.locked.add(j)
                else:
                    self.kind[j] = K_WORD
                    if (j - lo) % 2 == 0:
                        self.word_start.add(j)
                        if kind == 'rtswords':
                            self.word_adj[j] = 1
                        t = self.word_target(j)
                        if t is not None:
                            self.table_targets.add(t)   # traced if unknown (data targets must be marked data)
        for i in self.user['entries']:
            self.table_targets.add(i)
        for j in range(SIZE - 6, SIZE, 2):              # interrupt vectors
            self.kind[j] = self.kind[j + 1] = K_WORD
            self.word_start.add(j)
            self.table_targets.add(self.word_target(j))
        for lo, hi, n, adj, prefix in self.user['splits']:
            for e in range(n):
                a = ((self.rom[hi + e] << 8) | self.rom[lo + e]) + adj
                t = self.res(a, lo + e)
                if t is None:
                    if a >= 0x800:
                        sys.exit('split %s/%s entry %d ($%04X) is outside RAM and has no bank'
                                 % (where(lo), where(hi), e, a))
                    for j, part in ((lo + e, '<'), (hi + e, '>')):      # pointer to RAM (e.g. a PPU buffer)
                        self.kind[j] = K_DATA
                        self.locked.add(j)
                        self.split_ram[j] = (part, a - adj, adj)
                    continue
                for j, part in ((lo + e, '<'), (hi + e, '>')):
                    self.kind[j] = K_DATA
                    self.locked.add(j)
                    self.split[j] = (part, t, adj)
                self.table_targets.add(t)
        for t, (n, hi, _hdr) in self.user['tables'].items():
            self.row_break.update(range(t, hi + 1, n))

    # ------------------------------------------------------------------ static tracing
    def successors(self, i, mn, mode, n):
        """-> (targets, falls_through, bad)"""
        targets, fall = [], True
        if mn in BRANCHES:
            targets.append(self.rel_dest(i))
            v = self.prev_imm(i)
            if v is not None and mn in ('BNE', 'BEQ', 'BPL', 'BMI'):
                taken = {'BNE': v != 0, 'BEQ': v == 0, 'BPL': v < 0x80, 'BMI': v >= 0x80}[mn]
                fall = not taken                        # LDY #6 / BNE x: always taken, never falls through
        elif mn in ('JSR', 'JMP') and mode == 'abs':
            a = self.operand(i, n)
            t = self.res(a, i)
            if t is not None:
                targets.append(t)
            elif 0x0800 <= a < 0x8000 or (0x8000 <= a < 0xC000 and bank_of(i) < 14):
                return [], False, True                  # registers / mirrors / own pair outside the PRG: garbage
            fall = mn == 'JSR' and t not in self.user['dispatch']
        elif mn in ('JMP', 'RTS', 'RTI'):
            fall = False
        return targets, fall, False

    def prev_imm(self, i):
        """value loaded by an LDA/LDX/LDY #imm right before i (sets Z/N for a branch at i), else None"""
        k = i - 2
        if k < 0 or bank_of(k) != bank_of(i) or self.kind[k] != K_OP or self.kind[k + 1] != K_ARG:
            return None
        mn, mode, _n = self.decode(k)
        return self.rom[k + 1] if mode == 'imm' and mn in ('LDA', 'LDX', 'LDY') else None

    def speculate(self, i0):
        """decode everything reachable from i0 through unknown bytes; None if it runs into data or garbage"""
        found, cover, stack = {}, set(), [i0]
        while stack:
            i = stack.pop()
            if i in found or self.kind[i] == K_OP:
                continue
            if self.kind[i] != K_UNK or i in cover:
                return None
            d = self.decode(i)
            if not d or d[0] == 'BRK':
                return None
            mn, mode, n = d
            if self.rom[i] == 0x2C and self.kind[i + 1] == K_OP and self.kind[i + 2] == K_ARG                     and bank_of(i) == bank_of(i + 2) and self.decode(i + 1)[2] == 2:
                found[i] = 0                            # BIT abs that skips a known 2-byte instruction
                cover.add(i)
                stack.append(i + 3)
                continue
            if any(self.kind[i + j] != K_UNK or (i + j) in cover for j in range(n)):
                return None
            found[i] = n
            cover.update(range(i, i + n))
            targets, fall, bad = self.successors(i, mn, mode, n)
            if bad:
                return None
            if fall:
                if i + n >= unit_end(i):
                    return None
                stack.append(i + n)
            stack.extend(targets)
        return found

    def try_bitskip(self, t):
        """t is the 2nd byte of a BIT abs ($2C) and something jumps there: the BIT only skips the 2-byte instruction
        hidden in its operand (LDA #$44 / .byte $2C / LDA #$45 ...). Returns True if t is code now."""
        if self.kind[t] != K_ARG or self.kind[t - 1] != K_OP or self.rom[t - 1] != 0x2C or bank_of(t) != bank_of(t - 1):
            return False
        d = self.decode(t)
        if not d or d[2] != 2 or d[0] == 'BRK':
            return False
        self.kind[t - 1] = K_DATA
        self.locked.add(t - 1)
        self.bitskips.add(t - 1)
        self.set_instr(t, 2)
        return True

    def trace(self):
        changed_any = False
        while True:
            cands = {t for t in self.table_targets if t is not None and self.kind[t] == K_UNK}
            for t in self.table_targets:
                if t is not None and self.try_bitskip(t):
                    changed_any = True
            for i in self.instrs():
                mn, mode, n = self.decode(i)
                targets, fall, bad = self.successors(i, mn, mode, n)
                if not bad:
                    for t in targets:
                        if t is not None and self.try_bitskip(t):
                            changed_any = True
                    cands.update(t for t in targets if self.kind[t] == K_UNK)
                    if fall and i + n < unit_end(i) and self.kind[i + n] == K_UNK:
                        cands.add(i + n)
            changed = False
            for i in sorted(cands):
                if self.kind[i] != K_UNK:
                    continue
                found = self.speculate(i)
                if found:
                    for fi, n in found.items():
                        if n == 0:
                            self.kind[fi] = K_DATA
                            self.locked.add(fi)
                            self.bitskips.add(fi)
                            continue
                        self.set_instr(fi, n)
                        self.traced.add(fi)
                    changed = changed_any = True
            if not changed:
                return changed_any

    def mark_unread(self):
        """what is still unknown after tracing is data no log ever read (unused table entries, data of modes the
        logs did not reach, dead data); runs of only $FF stay fill. Listed in docs/unknown.txt for review."""
        i = 0
        while i < SIZE:
            if self.kind[i] != K_UNK:
                i += 1
                continue
            j = i
            while j < bank_end(i) and self.kind[j] == K_UNK:
                j += 1
            if any(b != 0xFF for b in self.rom[i:j]):
                for k in range(i, j):
                    self.kind[k] = K_DATA
                    self.unread.add(k)
            i = j

    def jsr_target(self, i):
        mn, mode, n = self.decode(i)
        return self.res(self.operand(i, n), i) if mn == 'JSR' else None

    def apply_bankcalls(self):
        """fixed banks: JSR PushBankN ... JSR $8xxx -> hint pair N for the operands that follow"""
        calls = self.user['bankcalls']
        changed = False
        for i in self.instrs():
            if bank_of(i) < 14 or self.jsr_target(i) not in calls:
                continue
            tt, k = calls[self.jsr_target(i)], i + 3
            for _ in range(16):
                if k >= unit_end(i) or self.kind[k] != K_OP:
                    break
                mn, mode, n = self.decode(k)
                if n == 3 and mode in ('abs', 'abx', 'aby', 'ind') and 0x8000 <= self.operand(k, n) < 0xC000                         and not self.is_mmc3_write(mn, mode, self.operand(k, n)) and k not in self.hint:
                    self.hint[k] = tt
                    self.static_hint.add(k)
                    changed = True
                if mn in ('RTS', 'RTI', 'JMP') or (mn == 'JSR' and self.jsr_target(k) in calls):
                    break
                k += n
        return changed

    def detect_dispatch(self):
        """inline word tables after JSR <dispatch routine>"""
        found = False
        for i in list(self.instrs()):
            if self.jsr_target(i) not in self.user['dispatch']:
                continue
            j = i + 3
            limit = unit_end(i)     # a target right after the table ends it: the code usually follows the table
            while j + 1 < limit and bank_of(j) == bank_of(j + 1):
                if j in self.word_start:
                    t = self.res(self.word(j), j)
                    if t is not None and j < t < limit and bank_of(t) == bank_of(j):
                        limit = t
                    j += 2
                    continue
                if any(self.kind[x] in (K_OP, K_ARG, K_WORD) or x in self.locked for x in (j, j + 1)):
                    break
                t = self.res(self.word(j), j)
                if t is None:
                    break
                read = self.cdl[j] & CDL_DATA and self.cdl[j + 1] & CDL_DATA
                inside = limit < unit_end(i) or j == i + 3  # before a known target that follows the table, or entry 0
                self.try_bitskip(t)
                if not (self.kind[t] == K_OP or ((read or inside) and self.kind[t] == K_UNK and self.speculate(t))):
                    if inside:
                        self.dispatch_bad.append('%s: inline dispatch entry -> %s is not code (table up to %s)'
                                              % (where(j), where(t), where(limit)))
                    break
                if j < t < limit and bank_of(t) == bank_of(j):
                    limit = t
                self.kind[j] = self.kind[j + 1] = K_WORD
                self.word_start.add(j)
                self.table_targets.add(t)
                found = True
                j += 2
            if j > i + 3 and (i + 3) not in self.dispatch_log:
                self.dispatch_log[i + 3] = (j - i - 3) // 2
        return found

    # ------------------------------------------------------------------ pointer tables
    def data_refs(self):
        """ROM places read as word tables: the operand of two absolute (indexed) data instructions
        (LDA t,Y / INY / LDA t,Y), or t and t+1 both operands (LDA t,X / LDA t+1,X)"""
        cnt = defaultdict(int)
        for i in self.instrs():
            mn, mode, n = self.decode(i)
            if mode in ('abs', 'abx', 'aby') and mn not in ('JMP', 'JSR') and mn not in WRITES:
                t = self.res(self.operand(i, n), i)
                if t is not None:
                    cnt[t] += 1
        return {t for t, c in cnt.items() if c >= 2 or t + 1 in cnt}

    def free(self, j):
        return self.kind[j] in (K_UNK, K_DATA) and j not in self.locked

    def detect_tables(self):
        """runs of little-endian words that point at code: >= UNREF_MIN words all at known instructions,
        or >= 2 words when the table start is an operand of some LDA tbl,X-like instruction"""
        refd = self.data_refs()
        found = False
        i = 0
        while i < SIZE - 1:
            best = None
            for adj in (0, 1):
                j, strong, weak = i, 0, 0
                while j + 1 < bank_end(i) and self.free(j) and self.free(j + 1):
                    t = self.res(self.word(j) + adj, j)
                    if t is None:
                        break
                    if self.kind[t] == K_OP:
                        strong += 1
                    elif self.kind[t] == K_UNK and i in refd and self.speculate(t):
                        weak += 1
                    else:
                        break
                    j += 2
                n = strong + weak
                ok = (n >= UNREF_MIN and weak == 0) or (n >= 2 and i in refd and strong >= 1) or (n >= 2 and i in refd and adj == 0)
                if ok and (best is None or n > best[1]):
                    best = (adj, n, strong, weak)
            if not best:
                i += 1
                continue
            adj, n = best[0], best[1]
            for e in range(n):
                j = i + 2 * e
                self.kind[j] = self.kind[j + 1] = K_WORD
                self.word_start.add(j)
                if adj:
                    self.word_adj[j] = 1
                self.table_targets.add(self.word_target(j))
            self.table_log.append((i, n, best[2], best[3], adj, i in refd))
            found = True
            i += 2 * n
        return found

    def detect_imm_pairs(self):
        """LDx #lo / STx zp ... LDx #hi / STx zp+1 (either order) where hi:lo is a ROM address"""
        ins = list(self.instrs()) if AUTO_IMM_PAIRS else []
        for k, i in enumerate(ins[:-1]):
            mn, mode, n = self.decode(i)
            if mode != 'imm' or mn not in ('LDA', 'LDX', 'LDY') or i in self.immref:
                continue
            j = ins[k + 1]
            m2, md2, n2 = self.decode(j)
            if m2 != 'ST' + mn[2] or md2 not in ('zp', 'abs') or j != i + n:
                continue
            a1 = self.operand(j, n2)
            if 0x2000 <= a1 < 0x4020:
                continue
            for k2 in range(k + 2, min(k + 10, len(ins) - 1)):
                i2, j2 = ins[k2], ins[k2 + 1]
                m3, md3, n3 = self.decode(i2)
                m4, md4, n4 = self.decode(j2)
                if md3 != 'imm' or m3 not in ('LDA', 'LDX', 'LDY') or m4 != 'ST' + m3[2] or md4 not in ('zp', 'abs'):
                    continue
                a2 = self.operand(j2, n4)
                if abs(a2 - a1) != 1 or 0x2000 <= a2 < 0x4020:
                    continue
                lo_i, hi_i = (i, i2) if a2 == a1 + 1 else (i2, i)
                t = self.res((self.rom[hi_i + 1] << 8) | self.rom[lo_i + 1], lo_i)
                if t is not None and i2 not in self.immref:
                    self.immref[lo_i] = ('<', t)
                    self.immref[hi_i] = ('>', t)
                break
        for lo_i, hi_i in self.user['imms']:
            t = self.res((self.rom[hi_i + 1] << 8) | self.rom[lo_i + 1], lo_i)
            if t is None:
                sys.exit('imm %s %s: the address has no bank (add a bank line)' % (where(lo_i), where(hi_i)))
            self.immref[lo_i] = ('<', t)
            self.immref[hi_i] = ('>', t)

    # ------------------------------------------------------------------ labels
    def instrs(self):
        i = 0
        while i < SIZE:
            if self.kind[i] == K_OP:
                yield i
                i += self.decode(i)[2]
            else:
                i += 1

    def start_of(self, i):
        while self.kind[i] == K_ARG:
            i -= 1
        if self.kind[i] == K_WORD and i not in self.word_start:
            i -= 1
        if i not in self.user['labels']:
            t = self.table_start(i)
            if t is not None:
                return t
        return i

    def addref(self, t, what):
        self.refs[self.start_of(t)].add(what)

    def note_ram(self, a, mode):
        if a < 0x800:
            self.ram_used[a] += 1
            if mode in ('izx', 'izy', 'ind'):
                self.ptrs.add(a)

    def operand_target(self, i):
        """PRG index an absolute operand of the instruction at i refers to (None: RAM, register, unresolved)"""
        mn, mode, n = self.decode(i)
        if mode not in ('abs', 'abx', 'aby', 'ind'):
            return None
        a = self.operand(i, n)
        if self.is_mmc3_write(mn, mode, a):
            return None
        return self.res(a, i)

    def gather_refs(self):
        for i in self.instrs():
            mn, mode, n = self.decode(i)
            if mode == 'rel':
                self.addref(self.rel_dest(i), 'loc')
            elif mode in ('abs', 'abx', 'aby', 'ind', 'zp', 'zpx', 'zpy', 'izx', 'izy'):
                a = self.operand(i, n)
                t = self.operand_target(i) if n == 3 else None
                if i in self.user['refs']:
                    continue                            # written as the ref's Name+-N, needs no label of its own
                if t is not None:
                    self.addref(t, 'sub' if mn == 'JSR' else 'loc' if mn == 'JMP' and mode == 'abs' else 'dat')
                elif a < 0x800:
                    self.note_ram(a, mode)
                elif 0x8000 <= a < 0xC000 and not self.is_mmc3_write(mn, mode, a) and a not in self.user['rawsyms']:
                    self.unresolved.append((i, a))
            if i in self.immref:
                self.addref(self.immref[i][1], 'dat')
            if self.cdl[i] & CDL_SUB:
                self.refs[i].add('sub')
            elif self.cdl[i] & CDL_JUMP:
                self.refs[i].add('loc')
        for j in sorted(self.word_start):
            t = self.word_target(j)
            if t is not None:
                self.addref(t, 'ptr')
            elif 0x8000 <= self.word(j) < 0xC000:
                self.unresolved.append((j, self.word(j)))
        for j, (_p, t, _a) in self.split.items():
            self.addref(t, 'ptr')
        for j, (_p, a, _a) in self.split_ram.items():
            self.note_ram(a, 'abs')
        for lo, _hi, _n, _adj, _prefix in self.user['splits']:
            self.refs[lo].add('dat')
        for t in self.user['tables']:
            self.refs[t].add('dat')

    @staticmethod
    def auto_name(pre, i):
        b = bank_of(i)
        return '%s_%04X' % (pre, cpu(i)) if b >= 14 else '%s_%02X_%04X' % (pre, b, cpu(i))

    def build_labels(self):
        self.frame_names = {}
        for lo, n, prefix, first in self.user['framenames']:
            for k in range(n):
                t = self.res(self.word(lo + 2 * k), lo + 2 * k)
                self.frame_names.setdefault(t, '%s%02X' % (prefix, first + k))
        for i, (name, _c) in self.user['labels'].items():
            if self.kind[i] == K_ARG or (self.kind[i] == K_WORD and i not in self.word_start):
                sys.exit('label %s at %s is inside an instruction/word' % (name, where(i)))
            self.labels[i] = name
        for i, kinds in self.refs.items():
            if i in self.labels:
                continue
            k = self.kind[i]
            if i in self.frame_names:
                self.labels[i] = self.frame_names[i]
                continue
            if self.user['soundptrs']:
                self.sound_tokens()
                if i in self.sound_names:
                    self.labels[i] = self.sound_names[i]
                    continue
            if k == K_OP:
                pre = 'sub' if 'sub' in kinds else 'loc'
            elif k == K_WORD:
                pre = 'tbl'
            else:
                pre = 'dat'
            self.labels[i] = self.auto_name(pre, i)
        for b in range(NBANKS):                     # a normal label at every bank start: ca65 local-label scopes
            self.labels.setdefault(b * BANK, 'Bank%02X' % b)
        self.localize()
        seen = {}
        for i, name in self.labels.items():
            if i in self.local_scope:
                continue
            if name in seen:
                sys.exit('duplicate label %s at %s and %s' % (name, where(seen[name]), where(i)))
            seen[name] = i

    def localize(self):
        """Turn branch/JMP-only labels into ca65 cheap locals (@loop, @rts, @skip) when every reference is in the
        same scope (between the same two global labels, same bank). rom.txt names starting with '@' must satisfy
        this too."""
        refs, other = defaultdict(list), set()
        for i in self.instrs():
            mn, mode, n = self.decode(i)
            t = self.rel_dest(i) if mode == 'rel' else self.operand_target(i) if mn == 'JMP' and mode == 'abs' else None
            if t is None:
                continue
            if self.start_of(t) == t and bank_of(t) == bank_of(i):
                refs[t].append(i)
            else:
                other.add(self.start_of(t))
        user = self.user['labels']
        local = {i for i, name in self.labels.items()
                 if (name.startswith('@') or (i not in user and name.startswith('loc_')))
                 and self.refs.get(i, set()) <= {'loc'} and i not in other and self.kind[i] == K_OP
                 and i & 0x1FFF}                                         # never the first byte of a bank
        while True:
            breaks = sorted(set(i for i in self.labels if i not in local) | set(range(0, SIZE, BANK)))
            scope = lambda p: breaks[bisect.bisect_right(breaks, p) - 1]
            bad = {t for t in local if any(scope(r) != scope(t) for r in refs[t])}
            if not bad:
                break
            local -= bad
        for i, name in self.labels.items():
            if name.startswith('@') and i not in local:
                sys.exit('local label %s at %s is used outside its scope' % (name, where(i)))
        by_scope = defaultdict(list)
        for t in sorted(local):
            by_scope[scope(t)].append(t)
        for sc, ts in by_scope.items():
            used = {self.labels[t] for t in ts if t in user}
            for t in ts:
                self.local_scope[t] = sc if sc in self.labels else None
                if t in user:
                    continue
                base = '@loop' if any(r > t for r in refs[t]) else '@rts' if self.decode(t)[0] == 'RTS' else '@skip'
                k, name = 1, base
                while name in used:
                    k += 1
                    name = '%s%d' % (base, k)
                used.add(name)
                self.labels[t] = name

    def global_name(self, i):
        """label usable outside ca65 (Mesen .mlb): Scope_local for cheap locals"""
        name = self.labels[i]
        if i in self.local_scope:
            sc = self.local_scope[i]
            return '%s_%s' % (self.labels[sc] if sc is not None else 'Bank%02X' % bank_of(i), name[1:])
        return name

    def target_expr(self, t):
        s = self.start_of(t)
        return self.labels[s] + ('+%d' % (t - s) if t != s else '')

    def ram_name(self, a):
        for b in range(a, max(-1, a - 0x400), -1):
            if b in self.ram_user and a < b + self.ram_user[b][1]:
                return self.member_expr(self.ram_user[b][0], a - b)
        if a in self.ptrs:
            return 'ptr_%02X' % a
        if a - 1 in self.ptrs and a not in self.ram_used_direct:
            return 'ptr_%02X+1' % (a - 1)
        return 'ram_%04X' % a

    def member_expr(self, var, off):
        """var+off; for an array of structs: var+element+Struct::field (offset 0 of element 0 stays var)"""
        st = self.consts['arrays'].get(var)
        if st is None or off == 0:
            return var + ('+%d' % off if off else '')
        fields = self.consts['structs'][st]
        size = sum(f[2] for f in fields)
        elem, rest = divmod(off, size)
        fn, foff, _sz = [f for f in fields if f[1] <= rest][-1]
        if foff == 0 and elem:
            return '%s+%d' % (var, off)             # start of an element: no field name
        return '%s%s+%s::%s%s' % (var, '+%d' % (elem * size) if elem else '', st, fn,
                                  '+%d' % (rest - foff) if rest != foff else '')

    def addr_expr(self, i, a, mn=None, mode=None):
        if a < 0x800:
            for lo, hi, ram, size, name, _c in self.user['aliases']:
                if lo <= i <= hi and ram <= a < ram + size:
                    return name + ('+%d' % (a - ram) if a > ram else '')
            return self.ram_name(a)
        if a in HW_REGS:
            return HW_REGS[a]
        if mn is not None and self.is_mmc3_write(mn, mode, a) and (a & 0xE001) == a:
            return MMC3_REGS[a]
        t = self.res(a, i) if mn is None or not self.is_mmc3_write(mn, mode, a) else None
        if t is not None:
            return self.target_expr(t)
        if a in self.user['rawsyms']:
            return self.user['rawsyms'][a]
        self.raw.append((i, '$%04X' % a))
        return '$%04X' % a

    def instr_text(self, i):
        mn, mode, n = self.decode(i)
        if mode == 'imp':
            return mn
        if mode == 'acc':
            return mn + ' A'
        if mode == 'rel':
            t = self.rel_dest(i)
            if bank_of(t) != bank_of(i):                # other segment: ca65 cannot branch there, the linker can
                e = '%s - (* + 1)' % self.target_expr(t)      # '*' is already past the opcode byte here
                return '.byte $%02X, <(%s)  ; %s %s' % (self.rom[i], e, mn, self.target_expr(t))
            return '%s %s' % (mn, self.target_expr(t))
        v = self.operand(i, n)
        if mode == 'imm':
            if i in self.immconst:
                return '%s #%s' % (mn, self.immconst[i])
            if i in self.immref:
                part, t = self.immref[i]
                e = self.target_expr(t)
                return '%s #%s%s' % (mn, part, e if NAME_RE.match(e) else '(%s)' % e)   # <a+1 = (<a)+1 in ca65
            return '%s #$%02X' % (mn, v)
        if i in self.user['refs']:
            name, off, e = self.user['refs'][i]
            t = next((k for k, (nm, _c) in self.user['labels'].items() if nm == name), None)
            if t is None or cpu(t) + off != v or n != 3:
                sys.exit('ref %s: %s is not the operand $%04X' % (where(i), e, v))
        else:
            e = self.addr_expr(i, v, mn, mode)
        if n == 3 and v < 0x100 and mode != 'ind':
            e = 'a:' + e                                # keep absolute addressing of a zero page address
        return mn + ' ' + {'zp': '%s', 'abs': '%s', 'zpx': '%s,X', 'abx': '%s,X', 'zpy': '%s,Y', 'aby': '%s,Y',
                           'izx': '(%s,X)', 'izy': '(%s),Y', 'ind': '(%s)'}[mode] % e

    # ------------------------------------------------------------------ output
    def flags(self, i):
        f = self.cdl[i]
        return '%s%s%s%s' % ('C' if f & CDL_CODE else 'T' if i in self.traced else '-',
                             'P' if f & CDL_PCM else 'D' if f & CDL_DATA else '-',
                             'J' if f & CDL_JUMP else '-', 'S' if f & CDL_SUB else '-')

    def comment(self, i, n, extra=''):
        return ';%s %05X %s: %s%s' % (self.flags(i), 16 + i, where(i).lstrip('$'),
                                      ' '.join('%02X' % b for b in self.rom[i:i + n]), extra)

    def stops(self, j, i0):
        return j != i0 and ((j in self.unread) != (i0 in self.unread) or j in self.labels or j in self.bitskips or j in self.user['notes'] or j in self.row_break
                            or j in self.mod_starts or j % BANK == 0)

    def module_ranges(self):
        """[(file name, description, first idx, end idx)] of the PRG source files"""
        mods = {i: (n, d) for i, (n, d) in self.user['modules'].items()}
        for b in range(NBANKS):
            mods.setdefault(b * BANK, ('bank', ''))
        starts = sorted(mods)
        return [('%02X_%s' % (bank_of(a), mods[a][0]), mods[a][1], a, b) for a, b in zip(starts, starts[1:] + [SIZE])]

    def emit(self):
        """{module file name: source text}"""
        files, out, carry = {}, None, None
        ranges = {a: (n, d, b) for n, d, a, b in self.module_ranges()}
        self.mod_starts = set(ranges)
        i = 0
        while i < SIZE:
            if i in ranges:
                name, desc, end = ranges[i]
                out = ['; %s - bank %02X, CPU $%04X-$%04X%s' % (GAME, bank_of(i), cpu(i), cpu(end - 1),
                                                                (': ' + desc) if desc else ''),
                       '; Generated by tools/disasm.py (the line comment format is described in src/main.asm).', '',
                       '.segment "BANK_%02X"' % bank_of(i), '']
                files[name] = out
            for k, (lo, _hi, ram, _size, name, c) in enumerate(self.user['aliases']):
                if lo == i and not any(n2 == name and r2 == ram for _l, _h, r2, _s, n2, _c in self.user['aliases'][:k]):
                    # (the same name for the same RAM in another range is defined once, by its first line)
                    out.append('%-33s ; %s' % ('%s = %s' % (name, self.ram_name(ram)), c) if c
                               else '%s = %s' % (name, self.ram_name(ram)))
            for text in self.user['notes'].get(i, []):
                out.append('; ' + text)
            if i in self.user['tables']:
                n_, hi, hdr = self.user['tables'][i]
                out.append('; table %s-%04X, %d bytes per row%s' % (where(i), cpu(hi), n_, (': ' + hdr) if hdr else ''))
            if i in self.labels:
                c = self.user['labels'].get(i, (None, ''))[1]
                out.append('%-33s ; %s' % (self.labels[i] + ':', c) if c else self.labels[i] + ':')
            k = self.kind[i]
            if carry:                                   # operand bytes of an instruction from the previous bank
                j0, n0, parts = carry
                out.append('  %-31s %s' % (parts[1], self.comment(i, j0 + n0 - i, '  operand of the instruction at %s' % where(j0))))
                i, carry = j0 + n0, None
                continue
            if k == K_OP:
                mn, mode, n = self.decode(i)
                text = self.instr_text(i)
                if i + n > bank_end(i):                 # runs into the next bank of the pair (another segment)
                    m = bank_end(i) - i
                    if n == 3:
                        e = text.split(None, 1)[1].split(',')[0].strip('()')
                        parts = (['.byte $%02X' % self.rom[i], '.word ' + e] if m == 1 else
                                 ['.byte $%02X, <(%s)' % (self.rom[i], e), '.byte >(%s)' % e])
                    else:
                        parts = ['.byte $%02X' % self.rom[i], '.byte $%02X' % self.rom[i + 1]]
                    out.append('  %-31s %s' % (parts[0], self.comment(i, m, '  %s (continues in bank %02X)'
                                                                       % (text, bank_of(i) + 1))))
                    carry = (i, n, parts)
                    i = bank_end(i)
                    continue
                out.append('  %-31s %s' % (text, self.comment(i, n)))
                if mode == 'rel' and bank_of(self.rel_dest(i)) != bank_of(i):
                    e = '%s - *' % self.target_expr(self.rel_dest(i))
                    out.append('  .assert %s >= -128 && %s <= 127, lderror, "branch out of range"' % (e, e))
                i += n
            elif k == K_WORD:
                adj = self.word_adj.get(i, 0)
                t = self.word_target(i)
                if t is not None:
                    e = '%s%s' % (self.target_expr(t), '-1' if adj else '')
                else:
                    v = self.word(i)
                    e = self.addr_expr(i, v) if v < 0x800 or v in HW_REGS else '$%04X' % v
                    if e.startswith('$'):
                        self.raw.append((i, e))
                out.append('  %-31s %s' % ('.word ' + e, self.comment(i, 2, '  RTS-trick' if adj else '')))
                i += 2
            elif i in self.bitskips:
                out.append('  %-31s %s' % ('.byte $2C', self.comment(i, 1, '  BIT abs: skips the next instruction')))
                i += 1
            elif i in self.split_ram:
                part, a, adj = self.split_ram[i]
                out.append('  %-31s %s' % ('.byte %s(%s%s)' % (part, self.ram_name(a), '-%d' % adj if adj else ''),
                                           self.comment(i, 1)))
                i += 1
            elif i in self.split:
                part, t, adj = self.split[i]
                out.append('  %-31s %s' % ('.byte %s(%s%s)' % (part, self.target_expr(t), '-%d' % adj if adj else ''),
                                           self.comment(i, 1)))
                i += 1
            elif self.msprite_lo(i) is not None:
                lo = self.msprite_lo(i)
                n, e, c = self.msprite_item(i, lo, self.user['msprites'][lo])
                out.append('  %-31s %s' % (e, self.comment(i, 0, '-%04X%s' % (cpu(i + n - 1), c))))
                i += n
            elif self.mscript_lo(i) is not None:
                lo = self.mscript_lo(i)
                n, e, c = self.mscript_item(i, lo, self.user['mscripts'][lo])
                out.append('  %-31s %s' % (e, self.comment(i, n, c)))
                i += n
            elif self.aiscript_lo(i) is not None:
                lo = self.aiscript_lo(i)
                n, e = self.aiscript_item(i, lo, self.user['aiscripts'][lo])
                out.append('  %-31s %s' % (e, self.comment(i, 0, '-%04X' % cpu(i + n - 1))))
                i += n
            elif self.user['sound'] and i in self._snd_cover:
                n, e = self.sound_item(i)
                out.append('  %-31s %s' % (e, self.comment(i, 0, '-%04X' % cpu(i + n - 1))))
                i += n
            elif self.screen_lo(i) is not None:
                lo = self.screen_lo(i)
                if i in self.user['screentext']:
                    out.append('  CHARMAP_%s' % self.user['screentext'][i][1].upper())
                n, e, c = self.screen_item(i, lo, self.user['screens'][lo])
                out.append('  %-31s %s' % (e, self.comment(i, 0, '-%04X%s' % (cpu(i + n - 1), c))))
                if any(t <= i <= thi < i + n for t, (thi, _c) in self.user['screentext'].items()):
                    out.append('  CHARMAP_ASCII')
                i += n
            elif self.text_end(i) is not None and self.text_lo(i) in self.user['textfmt']:
                lo, hi = self.text_lo(i), self.text_end(i)
                cname, fmt = self.user['textfmt'][lo]
                fmt = fmt or 'plain'
                if i == lo:
                    out.append('  CHARMAP_%s' % cname.upper())
                n, e, c = self.text_item(i, lo, hi, cname, fmt)
                out.append('  %-31s %s' % (e, self.comment(i, 0, '-%04X%s' % (cpu(i + n - 1), c))))
                i += n
                if i > hi:
                    out.append('  CHARMAP_ASCII')
            elif self.text_end(i) is not None:
                hi, j = self.text_end(i), i
                while j <= hi and j - i < 32 and not self.stops(j, i):
                    j += 1
                out.append('  %-31s %s' % ('.byte ' + self.text_expr(self.rom[i:j]), self.comment(i, 0, '-%04X' % cpu(j - 1))))
                i = j
            elif i in self.user['num16']:
                big = self.user['num16'][i] == 'dbyt'
                v = self.rom[i] << 8 | self.rom[i + 1] if big else self.rom[i] | self.rom[i + 1] << 8
                c = self.consts['datacomment'].get(i)
                out.append('  %-31s %s' % ('%s $%04X' % ('.dbyt' if big else '.word', v),
                                           self.comment(i, 2, ('  ' + c) if c else '')))
                i += 2
            elif i in self.dataexpr:
                ts = self.table_start(i)
                width = self.user['tables'][ts][0] if ts is not None else 8
                j = i
                while j < SIZE and j in self.dataexpr and j - i < width and not self.stops(j, i) \
                        and (j == i or j not in self.consts['datacomment']) \
                        and (j == i or sum(len(self.dataexpr[x]) + 2 for x in range(i, j + 1)) <= 72):
                    j += 1
                c = self.consts['datacomment'].get(i)
                out.append('  %-31s %s' % ('.byte ' + ', '.join(self.dataexpr[x] for x in range(i, j)),
                                           self.comment(i, j - i, ('  ' + c) if c else '')))
                i = j
            else:
                j = i
                while j < SIZE and self.rom[j] == self.rom[i] and self.kind[j] == k and j not in self.split and j not in self.split_ram \
                        and j not in self.dataexpr and not self.stops(j, i):
                    j += 1
                if j - i >= FILL_MIN:
                    out.append('  %-31s %s' % ('.res %d, $%02X' % (j - i, self.rom[i]),
                                               self.comment(i, 0, '-%04X%s' % (cpu(j - 1), ' unknown' if k == K_UNK else ' unread' if i in self.unread else ''))))
                    i = j
                    continue
                ts = self.table_start(i)
                width = self.user['tables'][ts][0] if ts is not None else 8
                j = i
                while j < SIZE and j - i < min(width, 16) and self.kind[j] == k and j not in self.split and j not in self.split_ram \
                        and j not in self.dataexpr and not self.stops(j, i):
                    if j > i and self.run_len(j, k) >= FILL_MIN:
                        break
                    j += 1
                out.append('  %-31s %s' % ('.byte ' + ', '.join('$%02X' % b for b in self.rom[i:j]),
                                           self.comment(i, j - i, ' unknown' if k == K_UNK else ' unread' if i in self.unread else '')))
                i = j
        return {n: '\n'.join(o) + '\n' for n, o in files.items()}

    def table_start(self, i):
        for t, (_n, hi, _h) in self.user['tables'].items():
            if t <= i <= hi:
                return t
        return None

    def text_end(self, i):
        for t, hi in self.user['texts'].items():
            if t <= i <= hi:
                return hi
        return None

    def mscript_lo(self, i):
        for t, hi in self.user['mscripts'].items():
            if t <= i <= hi:
                return t
        return None

    def mscript_tokens(self, lo, hi):
        """move scripts in lo..hi: {position: (length, kind)}; kind pair (frame/MOVE_SOUND/MOVE_HIT + byte) or end"""
        cache = self.__dict__.setdefault('_mscript_tokens', {})
        if lo in cache:
            return cache[lo]
        toks, j, kind = {}, lo, None
        while j <= hi:
            kind = 'end' if self.rom[j] == 0 else 'pair'
            toks[j] = (1 if kind == 'end' else 2, kind)
            j += toks[j][0]
        if j != hi + 1 or kind != 'end':
            sys.exit('movescripts %s-%04X: the last script does not end with MOVE_END at the end of the range' % (where(lo), cpu(hi)))
        cache[lo] = toks
        return toks

    def mscript_item(self, i, lo, hi):
        """(bytes, source, comment) of the next line of a move script block"""
        toks = self.mscript_tokens(lo, hi)
        start = max(t for t in toks if t <= i)
        n, kind = toks[start]
        if start == i and kind == 'end':
            return 1, '.byte MOVE_END', ''
        if start == i and not self.stops(i + 1, i):
            b, v = self.rom[i], self.rom[i + 1]
            if b == 0xFE:
                return 2, '.byte MOVE_SOUND, $%02X' % v, ''
            if b == 0xFF:
                return 2, '.byte MOVE_HIT, $%02X' % v, ''
            return 2, '.byte $%02X, %d' % (b, v), ''
        return 1, '.byte $%02X' % self.rom[i], ''

    AI_ARG = {0xFD: ('AI_WAIT', 'AIC_'), 0xDC: ('AI_WALK_GAP', None), 0xD6: ('AI_WALK_RANGE', None),
              0xD7: ('AI_WAIT_SUB', 'AICS_'), 0xD8: ('AI_GOTO', 'AIA_')}
    AI_ONE = {0xFF: 'AI_END', 0xFC: 'AI_HOLD', 0xD9: 'AI_RELEASE', 0xD4: 'AI_PAUSE', 0xD3: 'AI_CHARGE2',
              0xFE: 'AI_CHARGE', 0xD5: 'AI_RUN', 0xDD: 'AI_TAP_B', 0xDA: 'AI_LOCK', 0xDB: 'AI_UNLOCK',
              0xDE: 'AI_FWD', 0xDF: 'AI_BACK', 0xF0: 'AI_FWD_UP', 0xF1: 'AI_BACK_UP', 0xF2: 'AI_FWD_DOWN',
              0xF3: 'AI_BACK_DOWN', 0xF4: 'AI_TO_BALL', 0xF5: 'AI_FROM_BALL', 0xF6: 'AI_FWD_A', 0xF7: 'AI_FWD_B'}

    def aiscript_lo(self, i):
        for t, hi in self.user['aiscripts'].items():
            if t <= i <= hi:
                return t
        return None

    def const_by_value(self, prefix, v):
        for n, e, _c, _w in self.consts['defs']:
            if n and n.startswith(prefix):
                try:
                    if int(e.strip().replace('$', '0x'), 0) == v:
                        return n
                except ValueError:
                    pass
        return None

    def aiscript_token(self, j):
        """(length, source text) of the AI script token at j"""
        b = self.rom[j]
        if b in self.AI_ARG:
            name, prefix = self.AI_ARG[b]
            v = self.rom[j + 1]
            arg = (prefix and self.const_by_value(prefix, v)) or '$%02X' % v
            return 2, '%s, %s' % (name, arg)
        if b in self.AI_ONE:
            return 1, self.AI_ONE[b]
        if b >= 0xD0:
            sys.exit('aiscripts: unknown control byte $%02X at %s' % (b, where(j)))
        if b == 0:
            return 1, '0'
        bits = [n for n, m in (('BTN_A', 0x80), ('BTN_B', 0x40), ('BTN_UP', 0x08), ('BTN_DOWN', 0x04),
                               ('BTN_LEFT', 0x02), ('BTN_RIGHT', 0x01)) if b & m]
        if sum(m for m in (0x80, 0x40, 0x08, 0x04, 0x02, 0x01) if b & m) != b:
            return 1, '$%02X' % b
        return 1, '|'.join(bits)

    def aiscript_item(self, i, lo, hi):
        """(bytes, source) of the next line of an AI script block: tokens up to AI_END or the next label"""
        toks, j = [], i
        while j <= hi:
            n, t = self.aiscript_token(j)
            if j + n - 1 > hi:
                sys.exit('aiscripts %s: token at %s runs past the range' % (where(lo), where(j)))
            toks.append(t)
            j += n
            if t == 'AI_END' or (j <= hi and self.stops(j, i)):
                break
        return j - i, '.byte ' + ', '.join(toks)

    # ------------------------------------------------------------------ sound data (docs/sound.md)
    NOTE_NAMES = ('C', 'CS', 'D', 'DS', 'E', 'F', 'FS', 'G', 'GS', 'A', 'AS', 'B')
    SC_CMDS = {0xE6: 'SC_ENV', 0xE7: 'SC_RELEASE', 0xE8: 'SC_LENGTH', 0xE9: 'SC_DUTY', 0xEA: 'SC_FADE',
                0xEB: 'SC_VIBRATO', 0xEC: 'SC_FLAGS', 0xED: 'SC_DETUNE', 0xEE: 'SC_TRANSPOSE', 0xEF: 'SC_DIVIDER'}
    SFX_CHANNELS = ((0x80, 'sq', 'SFX_SQ1'), (0x40, 'sq', 'SFX_SQ2'), (0x20, 'tri', 'SFX_TRI'), (0x10, 'noise', 'SFX_NOISE'))

    def snd_idx(self, a):
        """CPU address seen with bank pair 00/01 mapped -> PRG index"""
        return a - 0x8000 if 0x8000 <= a < 0xC000 else fixed_idx(a)

    def snd_word(self, i):
        return self.rom[i] | self.rom[i + 1] << 8

    def sound_tokens(self):
        """({index: (length, source text)} of every sound stream token, set of word operand indices)"""
        if hasattr(self, '_snd'):
            return self._snd
        rom, toks, words, todo, seen = self.rom, {}, set(), [], set()
        self.sound_names = {}                   # stream start -> Sfx<id> / Mus<id>_<channel> / Env<n>
        parts = {}
        ranges = self.user['sound']
        cover = self._snd_cover = set()

        def put(j, n, text, who):
            if not any(lo <= j and j + n - 1 <= hi for lo, hi in ranges):
                sys.exit('sound: %s token at %s is outside the sound ranges' % (who, where(j)))
            if any(k in cover for k in range(j, j + n)) and toks.get(j) != (n, text):
                sys.exit('sound: %s token at %s overlaps another stream' % (who, where(j)))
            toks[j] = (n, text)
            cover.update(range(j, j + n))

        def jump(j, kind, fmt, who):            # word operand at j: queue its target
            words.add(j)
            cover.update((j, j + 1))
            t = self.snd_idx(self.snd_word(j))
            if t is None:
                sys.exit('sound: %s jump at %s leaves the sound banks' % (who, where(j)))
            todo.append((t, kind, fmt, who))
            if t not in self.sound_names:       # SC_CALL / SC_GOTO target: <owning stream>_P<n>
                if who.startswith('sfx $'):
                    base = 'Sfx' + who[5:]
                else:
                    a, b = who[5:].split('.')
                    base = 'Mus%02X_%s' % (0x2E + int(a), ('Sq1', 'Sq2', 'Tri', 'Drum')[int(b)])
                parts[base] = parts.get(base, 0) + 1
                self.sound_names[t] = '%s_P%d' % (base, parts[base])

        def flow(j, b, kind, who, slide):
            """$F9-$FF (both formats): (length, text, word operand follows, stream ends, slide open)"""
            if b == 0xF9:
                sys.exit('sound: %s byte $F9 at %s' % (who, where(j)))
            if b == 0xFA:
                if slide:
                    return 1, 'SC_SLIDE_END', False, False, False
                n = 3 if kind == 'tri' else 4
                return n, ', '.join(['SC_SLIDE'] + ['$%02X' % v for v in rom[j + 1:j + n]]), False, False, True
            if b in (0xFB, 0xFC):
                return 1, 'SC_LOOP' if b == 0xFB else 'SC_LOOP2', False, False, slide
            if b == 0xFD:
                return 1, 'SC_CALL', True, False, slide
            if b == 0xFE:
                if rom[j + 1] == 0xFF:
                    return 2, 'SC_REPEAT, SC_GOTO', True, True, slide
                return 2, 'SC_REPEAT, %d' % rom[j + 1], False, False, slide
            return 1, 'SC_END', False, True, slide

        def music(j, kind, who):
            packed, slide = None, False
            while True:
                b = rom[j]
                word = end = False
                n = 1
                if b < 0xC0:
                    if kind == 'drum':
                        t = self.const_by_value('DRUM_', b & 0xF0)
                        if not t:
                            sys.exit('sound: %s drum $%02X at %s has no DRUM_ constant' % (who, b, where(j)))
                        t = '%s+%d' % (t, b & 15)
                    elif packed is not None:
                        lo = b & 15
                        t = 'NOTE_%s|%s' % (self.NOTE_NAMES[b >> 4],
                                            'NOTE_%s>>4' % self.NOTE_NAMES[lo] if lo < 12 else '$%02X' % lo)
                    else:
                        t = 'NOTE_%s+%d' % (self.NOTE_NAMES[b >> 4], b & 15)
                elif b < 0xD0:
                    t = 'SC_REST+%d' % (b & 15)
                elif b < 0xDE:
                    n = {'sq': 4, 'tri': 2, 'drum': 1}[kind]
                    t = ', '.join(['SC_LEN+%d' % (b & 15)] + ['$%02X' % v for v in rom[j + 1:j + n]])
                elif b < 0xE0:
                    packed = None if packed == (b & 1) else b & 1
                    t = 'SC_PACKED' if b == 0xDE else 'SC_PACKED2'
                elif b < 0xE6:
                    t = 'SC_OCTAVE+%d' % (b & 15)
                elif b < 0xF0:
                    n = 3 if b == 0xEB and rom[j + 1] else 2
                    t = ', '.join([self.SC_CMDS[b]] + ['$%02X' % v for v in rom[j + 1:j + n]])
                elif b < 0xF9:
                    t = 'SC_VOLUME+%d' % (b & 15)
                else:
                    n, t, word, end, slide = flow(j, b, kind, who, slide)
                put(j, n, t, who)
                j += n
                if word:
                    jump(j, kind, 'music', who)
                    j += 2
                if end:
                    return

        def sfx(j, kind, who, first):
            slide = False
            if first and kind != 'noise':
                n = 1 if kind == 'tri' or rom[j] & 15 else 2
                put(j, n, ', '.join('$%02X' % v for v in rom[j:j + n]), who)
                j += n
            while True:
                b = rom[j]
                word = end = False
                n = 1
                if b >= 0xF9:
                    n, t, word, end, slide = flow(j, b, kind, who, slide)
                elif 0xE8 <= b < 0xF0 and kind != 'noise':
                    if b > 0xEA:
                        sys.exit('sound: %s SFX byte $%02X at %s' % (who, b, where(j)))
                    n = 2
                    t = '%s, $%02X' % (self.SC_CMDS[b], rom[j + 1])
                elif b < 0x10 and b & 15:
                    n = {'tri': 2, 'noise': 1, 'sq': 2 if rom[j + 1] & 15 else 3}[kind]
                    t = ', '.join(['SFX_LEN+%d' % b] + ['$%02X' % v for v in rom[j + 1:j + n]])
                elif b < 0x10:
                    t = 'SFX_REST'
                elif kind == 'noise':
                    n = 2 if b == 0x10 else 1
                    t = ', '.join('$%02X' % v for v in rom[j:j + n])
                else:
                    n = 2
                    t = '$%02X, $%02X' % (b, rom[j + 1])
                put(j, n, t, who)
                j += n
                if word:
                    jump(j, kind, 'sfx', who)
                    j += 2
                if end:
                    return

        for p, count, what in self.user['soundptrs']:
            for k in range(count * (4 if what == 'songs' else 1)):
                t = self.snd_idx(self.snd_word(p + 2 * k))
                if what == 'env':
                    self.sound_names.setdefault(t, 'Env%02X' % k)
                    j = t
                    while True:
                        b = rom[j]
                        if b == 0xFF:
                            put(j, 1, 'ENV_HOLD', 'envelope %d' % k)
                            break
                        if b == 0xFE:
                            put(j, 2, 'ENV_REPEAT, %s' % ('ENV_FOREVER' if rom[j + 1] == 0xFF else rom[j + 1]), 'envelope %d' % k)
                            if rom[j + 1] == 0xFF:
                                break
                            j += 2
                            continue
                        put(j, 1, 'ENV_LOOP' if b >= 0xFB else '$%02X' % b, 'envelope %d' % k)
                        j += 1
                    continue
                if what == 'songs':
                    self.sound_names.setdefault(t, 'Mus%02X_%s' % (0x2E + (k >> 2), ('Sq1', 'Sq2', 'Tri', 'Drum')[k & 3]))
                    todo.append((t, ('sq', 'sq', 'tri', 'drum')[k & 3], 'music', 'song %d.%d' % (k >> 2, k & 3)))
                    continue
                who = 'sfx $%02X' % (k + 1)
                self.sound_names.setdefault(t, 'Sfx%02X' % (k + 1))
                h = rom[t]
                if not h & 0xF0:
                    sys.exit('sound: %s header at %s has no channel' % (who, where(t)))
                put(t, 1, '|'.join([nm for m, _k, nm in self.SFX_CHANNELS if h & m] + ['%d' % (h & 15)]), who)
                j, first = t + 1, True
                for m, kind, _nm in self.SFX_CHANNELS:
                    if h & m:
                        todo.append((j, kind, 'sfx1' if first else 'sfx', who))
                        first = False
                        while rom[j] != 0xFF:
                            j += 1
                        j += 1
        while todo:
            j, kind, fmt, who = todo.pop(0)
            if (j, kind, fmt) in seen:
                continue
            seen.add((j, kind, fmt))
            if fmt == 'music':
                music(j, kind, who)
            else:
                sfx(j, kind, who, fmt == 'sfx1')
        self._snd = (toks, words)
        return self._snd

    def apply_sound(self):
        """word operands of SC_CALL / SC_GOTO are label references; their targets must be token starts"""
        if not self.user['sound']:
            return
        toks, words = self.sound_tokens()
        for j in words:
            for k in (j, j + 1):
                self.kind[k] = K_WORD
                self.locked.discard(k)
            self.word_start.add(j)
            t = self.word_target(j)
            if t is None or t not in toks:
                sys.exit('sound: jump target $%04X at %s is not a stream token' % (self.snd_word(j), where(j)))
            self.table_targets.add(t)

    def sound_item(self, i):
        """(bytes, source) of the next line of sound data: tokens up to an end, a command, a word operand or a label"""
        toks, _w = self.sound_tokens()
        cover = self._snd_cover
        if i not in toks:                          # inside a token that a label split: plain bytes
            j = i + 1
            while j not in toks and j in cover and self.kind[j] != K_WORD and not self.stops(j, i):
                j += 1
            return j - i, '.byte ' + ', '.join('$%02X' % b for b in self.rom[i:j])
        parts, j = [], i
        while j in toks and len(parts) < 8:
            n, t = toks[j]
            if j != i and self.stops(j, i):
                break
            if any(self.stops(k, i) for k in range(j + 1, j + n)):
                if not parts:                      # a label inside the token: its bytes up to the label
                    k = j + 1
                    while not self.stops(k, i):
                        k += 1
                    return k - i, '.byte ' + ', '.join('$%02X' % b for b in self.rom[i:k])
                break
            parts.append(t)
            j += n
            if self.kind[j] == K_WORD or t in ('SC_END', 'SC_SLIDE_END', 'ENV_HOLD') or t.startswith('ENV_REPEAT') or t[0] == 'S' and (',' in t or t.startswith('SFX_') and '|' in t):
                break
        return j - i, '.byte ' + ', '.join(parts)

    def msprite_lo(self, i):
        for t, hi in self.user['msprites'].items():
            if t <= i <= hi:
                return t
        return None

    def msprite_tokens(self, lo, hi):
        """metasprite frames in lo..hi: {position: (length, kind)}; kind count / sprite / jump (MSPR_JUMP + word)"""
        cache = self.__dict__.setdefault('_msprite_tokens', {})
        if lo in cache:
            return cache[lo]
        toks, j, left = {}, lo, 0
        while j <= hi:
            b = self.rom[j]
            if b == 0x80:                               # continue the frame at another address (also a stray one)
                toks[j] = (3, 'jump')
                j, left = j + 3, 0
            elif left == 0:
                if b == 0:
                    sys.exit('metasprites %s: frame with 0 sprites at %s' % (where(lo), where(j)))
                toks[j] = (1, 'count')
                j, left = j + 1, b & 0x7F
            else:
                toks[j] = (4, 'sprite')
                j, left = j + 4, left - 1
        if j != hi + 1 or left:
            sys.exit('metasprites %s-%04X: the last frame does not end at the end of the range' % (where(lo), cpu(hi)))
        cache[lo] = toks
        return toks

    def apply_msprites(self):
        """the address after each MSPR_JUMP is a word (label reference); check that targets are token starts"""
        for lo, hi in self.user['msprites'].items():
            toks = self.msprite_tokens(lo, hi)
            for j, (n, kind) in toks.items():
                if kind != 'jump':
                    continue
                for k in (j + 1, j + 2):
                    self.kind[k] = K_WORD
                    self.locked.discard(k)
                self.word_start.add(j + 1)
                t = self.word_target(j + 1)
                if t is None or not lo <= t <= hi or t not in toks:
                    sys.exit('metasprites %s: MSPR_JUMP target $%04X is not a sprite in the range' % (where(j), self.word(j + 1)))
                self.table_targets.add(t)

    @staticmethod
    def oam_attr(b):
        parts = [n for m, n in ((0x80, 'OAM_FLIP_V'), (0x40, 'OAM_FLIP_H'), (0x20, 'OAM_BEHIND')) if b & m]
        if b & 0x1C:
            parts.append('$%02X' % (b & 0x1C))
        if b & 3 or not parts:
            parts.append('%d' % (b & 3))
        return '|'.join(parts)

    def msprite_item(self, i, lo, hi):
        """(bytes, source, comment) of the next line of a metasprite block"""
        toks = self.msprite_tokens(lo, hi)
        start = max(t for t in toks if t <= i)
        n, kind = toks[start]
        if start == i and kind == 'jump':
            return 1, '.byte MSPR_JUMP', ''
        if start == i and kind == 'count':
            return 1, '.byte %d' % self.rom[i], '  %d sprite(s)' % self.rom[i]
        end = start + n
        whole = start == i and not any(self.stops(j, i) for j in range(i + 1, end))
        if whole:
            dy, tile, attr, dx = self.rom[i:end]
            sgn = lambda v: '%d' % (v - 256 if v & 0x80 else v)
            return 4, '.lobytes %s, $%02X, %s, %s' % (sgn(dy), tile, self.oam_attr(attr), sgn(dx)), ''
        j = i + 1
        while j < end and not self.stops(j, i):
            j += 1
        return j - i, '.byte ' + ', '.join('$%02X' % b for b in self.rom[i:j]), ''

    def screen_lo(self, i):
        for t, hi in self.user['screens'].items():
            if t <= i <= hi:
                return t
        return None

    def screen_tokens(self, lo, hi):
        """LoadScreen streams in lo..hi: {position: (length, header source, data bytes, vram address)}"""
        cache = self.__dict__.setdefault('_screen_tokens', {})
        if lo in cache:
            return cache[lo]
        toks, j, vram, want_addr = {}, lo, 0, True
        while j <= hi:
            b = self.rom[j]
            if want_addr:
                vram = self.word(j)
                toks[j] = (2, None, 0, vram)
                j += 2
                want_addr = False
                continue
            if b == 0xFF:
                toks[j] = (1, 'SCR_END', 0, vram)
                j += 1
                want_addr = True                    # the next stream (another screen) follows
            elif b == 0x7F:
                toks[j] = (1, 'SCR_NEXT', 0, vram)
                j += 1
                want_addr = True
            elif b < 0x80:
                toks[j] = (2, 'SCR_RUN|%d' % b, 1, vram)
                vram += b or 256
                j += 2
            elif b & 0x40:
                toks[j] = (2, 'SCR_SEQUENCE|%d' % (b & 0x3F), 1, vram)
                vram += b & 0x3F
                j += 2
            else:
                toks[j] = (1 + (b & 0x3F), 'SCR_LITERAL|%d' % (b & 0x3F), b & 0x3F, vram)
                vram += b & 0x3F
                j += 1 + (b & 0x3F)
        cache[lo] = toks
        return toks

    @staticmethod
    def vram_text(a):
        if not 0x2000 <= a < 0x3000:
            return '$%04X' % a
        nt, k = (a - 0x2000) >> 10, (a - 0x2000) & 0x3FF
        if k >= 0x3C0:
            return 'nametable %d attributes +%d' % (nt, k - 0x3C0)
        return 'nametable %d row %d col %d' % (nt, k >> 5, k & 31)

    def screen_text(self, i, head, end):
        """an SCR_LITERAL run (or the tile of an SCR_SEQUENCE) inside a screentext range, as charmap text (None: no mapping)"""
        if not head.startswith(('SCR_LITERAL', 'SCR_SEQUENCE')):
            return None
        for t, (thi, cname) in self.user['screentext'].items():
            if t <= i <= thi:
                break
        else:
            return None
        if any(self.stops(j, i) for j in range(i + 1, end)):
            return None
        cmap, parts, s = self.user['charmaps'][cname], [], ''
        if head.startswith('SCR_SEQUENCE'):                 # the first tile of the sequence as a character
            ch = cmap.get(self.rom[i + 1])
            return ch if ch and ch != "'''" else None
        for b in self.rom[i + 1:end]:
            ch = cmap.get(b)
            if ch is None:
                return None
            if ch.startswith("'"):
                s += ch[1]
                continue
            if s:
                parts.append('"%s"' % s)
                s = ''
            parts.append(ch)
        if s:
            parts.append('"%s"' % s)
        return ', '.join(parts)

    def screen_item(self, i, lo, hi):
        """(bytes, source, comment) of the next line of a LoadScreen data block"""
        toks = self.screen_tokens(lo, hi)
        start = max(t for t in toks if t <= i)
        n, head, _nd, vram = toks[start]
        end = start + n
        if start == i and head is None:
            if end <= bank_end(i):
                return 2, '.word $%04X' % self.word(i), '  ' + self.vram_text(vram)
            head = '$%02X' % self.rom[i]                # address word split by the bank boundary
            end = i + 1
        text = self.screen_text(i, head, end) if start == i else None
        if text:
            return end - i, '.byte %s, %s' % (head, text), '  ' + self.vram_text(vram)
        j = i + 1 if start == i else i
        while j < end and j - i < 17 and not self.stops(j, i):
            j += 1
        parts = ([head] if start == i else []) + ['$%02X' % b for b in self.rom[(i + 1 if start == i else i):j]]
        c = '  ' + self.vram_text(vram) if start == i and head not in ('SCR_END', 'SCR_NEXT') else ''
        return j - i, '.byte ' + ', '.join(parts), c

    def text_lo(self, i):
        for t, hi in self.user['texts'].items():
            if t <= i <= hi:
                return t
        return None

    def text_tokens(self, lo, hi, fmt):
        """{position: (kind, length, source)} of a text block in FORMAT; kind addr / ctl / last / char"""
        cache = self.__dict__.setdefault('_text_tokens', {})
        if lo in cache:
            return cache[lo]
        addr, ctl = TEXT_FORMATS[fmt]
        toks, j, want_addr = {}, lo, addr is not None
        while j <= hi:
            b = self.rom[j]
            if want_addr and b not in ctl and j < hi:
                toks[j] = ('addr', 2, None)
                j += 2
                want_addr = False
                continue
            if b in ctl:
                name, nargs, effect = ctl[b]
                src = ', '.join([name] + ['$%02X' % x for x in self.rom[j + 1:j + 1 + nargs]])
                toks[j] = ('ctl', 1 + nargs, src)
                j += 1 + nargs
                want_addr = addr is not None and effect in ('addr', 'end')
                continue
            toks[j] = ('last' if fmt == 'bit7' and b & 0x80 else 'char', 1, None)
            j += 1
        cache[lo] = toks
        return toks

    def text_item(self, i, lo, hi, cname, fmt):
        """(bytes, source text, comment) of the next line of a text block with a charmap"""
        cmap = self.user['charmaps'][cname]
        toks = self.text_tokens(lo, hi, fmt)
        kind, n, src = toks.get(i, ('char', 1, None))
        if kind == 'addr':
            big = TEXT_FORMATS[fmt][0] == 'dbyt'
            a = self.rom[i] << 8 | self.rom[i + 1] if big else self.word(i)
            c = ''
            if 0x2000 <= a < 0x3000:
                c = '  nametable %d row %d col %d' % ((a - 0x2000) >> 10, (a >> 5) & 31, a & 31)
            return 2, '%s $%04X' % ('.dbyt' if big else '.word', a), c
        parts, s, j = [], '', i
        while j <= hi and j - i < 40 and (j == i or not self.stops(j, i)):
            kind, n, src = toks.get(j, ('char', 1, None))
            if kind == 'addr' or j + n > hi + 1:
                break
            if kind == 'char':
                ch = cmap.get(self.rom[j])
                if ch and ch.startswith("'"):
                    s += ch[1]
                    j += 1
                    continue
                src = ch or '$%02X' % self.rom[j]
            elif kind == 'last':
                ch = cmap.get(self.rom[j] & 0x7F)
                src = '%s|$80' % ch if ch and ch != "'''" else '$%02X' % self.rom[j]
            if s:
                parts.append('"%s"' % s)
                s = ''
            parts.append(src)
            j += n
            if kind != 'char':
                break
        if s:
            parts.append('"%s"' % s)
        return j - i, '.byte ' + ', '.join(parts), ''

    def charmap_inc(self):
        out = ['; Fonts of the text blocks (charmap lines in tools/labels/rom.txt). Generated by tools/disasm.py', '']
        used = set()
        for name, m in sorted(self.user['charmaps'].items()):
            for b, ch in sorted(m.items()):
                if not ch.startswith("'"):
                    out.append('%-22s = $%02X' % (ch, b))
            out.append('.macro CHARMAP_%s' % name.upper())
            for b, ch in sorted(m.items(), key=lambda x: x[1]):
                if ch.startswith("'"):
                    out.append('  .charmap $%02X, $%02X               ; %s' % (ord(ch[1]), b, ch))
                    used.add(ord(ch[1]))
            out += ['.endmacro', '']
        out.append('.macro CHARMAP_ASCII')
        out += ['  .charmap $%02X, $%02X' % (c, c) for c in sorted(used)]
        out += ['.endmacro', '']
        return '\n'.join(out)

    @staticmethod
    def text_expr(data):
        """printable runs as "..." strings, everything else as $XX"""
        parts, s = [], ''
        for b in data:
            if 0x20 <= b < 0x7F and b != 0x22:
                s += chr(b)
                continue
            if s:
                parts.append('"%s"' % s)
                s = ''
            parts.append('$%02X' % b)
        if s:
            parts.append('"%s"' % s)
        return ', '.join(parts)

    def run_len(self, j, k):
        e = j
        while e < bank_end(j) and self.rom[e] == self.rom[j] and self.kind[e] == k and e not in self.split and e not in self.split_ram:
            e += 1
        return e - j

    def ram_inc(self):
        lines = ['; RAM labels. Generated by tools/disasm.py from tools/labels/ram.txt',
                 '; name = $address ; usage count in code ; comment', '']
        rows = {}
        for a, (name, size, c) in self.ram_user.items():
            rows[a] = (name, sum(self.ram_used[a + k] for k in range(size)),
                       ('(size %d) ' % size if size > 1 else '') + c)
        for a, cnt in self.ram_used.items():
            nm = self.ram_name(a)
            if '+' in nm or nm in (r[0] for r in rows.values()):
                continue
            rows[a] = (nm, cnt + (self.ram_used.get(a + 1, 0) if a in self.ptrs else 0),
                       'auto: indirect pointer (size 2)' if a in self.ptrs else '')
        for a in sorted(rows):
            name, cnt, c = rows[a]
            lines.append('%-22s = $%04X ; %d%s' % (name, a, cnt, (' ; ' + c) if c else ''))
        return '\n'.join(lines) + '\n'

    # ------------------------------------------------------------------ constants
    def apply_consts(self):
        c = self.consts
        names = {n: a for a, (n, _s, _c) in self.ram_user.items()}
        names.update({n: a for a, n in HW_REGS.items()})
        names.update({n: a for a, n in MMC3_REGS.items()})
        names.update({self.labels[i]: cpu(i) for i in self.labels if not self.labels[i].startswith('@')})
        for st, fields in c['structs'].items():
            names.update({'%s__%s' % (st, fn): off for fn, off, _s in fields})
            names[st] = sum(f[2] for f in fields)       # .sizeof
        vals = {}
        for name, expr, _c, at in c['defs']:
            if name in names or name in vals:
                sys.exit('%s: constant %s clashes with another name' % (at, name))
            vals[name] = eval_expr(expr, {**names, **vals}, at)
        self.const_vals = vals
        for var in c['arrays']:
            if var not in names:
                sys.exit('const.txt: array %s: unknown RAM variable' % var)
        allnames = {**names, **vals}
        auto = {}                                       # (address, value) -> constant name
        for name, var, at in c['auto']:
            base, _, off = var.partition('+')
            if base not in names:
                sys.exit('%s: unknown variable %s' % (at, var))
            key = (names[base] + (int(off, 0) if off else 0), vals[name] & 0xFF)
            if key in auto and auto[key] != name:
                sys.exit('%s: %s and %s have the same value for %s' % (at, auto[key], name, var))
            auto[key] = name
        seq = list(self.instrs())
        prev = {}
        for a, b in zip(seq, seq[1:]):
            if a + self.decode(a)[2] == b:
                prev[b] = a
        mem = ('zp', 'abs', 'zpx', 'abx', 'zpy', 'aby')
        reg = {'LDA': 'A', 'LDX': 'X', 'LDY': 'Y', 'CMP': 'A', 'CPX': 'X', 'CPY': 'Y',
               'AND': 'A', 'ORA': 'A', 'EOR': 'A'}
        for i in seq:
            mn, mode, n = self.decode(i)
            if mode != 'imm' or i in self.immref or mn not in reg:
                continue
            var = None
            if mn.startswith('LD'):                     # LDx #v / STx var
                j = i + n
                if prev.get(j) == i:
                    mj, mdj, nj = self.decode(j)
                    if mj == 'ST' + reg[mn] and mdj in mem:
                        var = self.operand(j, nj)
            else:                                       # LDx var / [branches, CPx #] / CPx #v
                j = i
                while j in prev and j not in self.labels:
                    j = prev[j]
                    mj, mdj, nj = self.decode(j)
                    if mj == 'LD' + reg[mn] and mdj in mem:
                        var = self.operand(j, nj)
                        break
                    if not (mj in BRANCHES or (mn[0] == 'C' and mj == mn and mdj == 'imm')):
                        break
            if var is not None and (var, self.rom[i + 1]) in auto:
                self.immconst[i] = auto[(var, self.rom[i + 1])]
        for i, (expr, at) in c['uses'].items():
            mode = self.decode(i)[1] if self.kind[i] == K_OP else None
            if mode != 'imm':
                sys.exit('%s: %s is not an instruction with an immediate operand' % (at, where(i)))
            if i in self.immref:
                sys.exit('%s: %s already is #<label / #>label' % (at, where(i)))
            if eval_expr(expr, allnames, at) != self.rom[i + 1]:
                sys.exit('%s: %s != $%02X at %s' % (at, expr, self.rom[i + 1], where(i)))
            self.immconst[i] = expr
        for i, (expr, at) in c['data'].items():
            if self.kind[i] not in (K_DATA, K_UNK) or i in self.split or i in self.split_ram:
                sys.exit('%s: %s is not a data byte' % (at, where(i)))
            v = eval_expr(expr, allnames, at)
            if v & 0xFF != self.rom[i] or not 0 <= v < 256:
                sys.exit('%s: %s != $%02X at %s' % (at, expr, self.rom[i], where(i)))
            self.dataexpr[i] = expr

    def const_inc(self):
        lines = ['; Constants. Generated by tools/disasm.py from tools/labels/const.txt', '']
        blocks = defaultdict(list)
        for k, kind, arg, comment in self.consts['blocks']:
            blocks[k].append((kind, arg, comment))
        in_enum, nxt = False, 0
        for k, d in enumerate(self.consts['defs'] + [(None, None, None, None)]):
            name, expr, comment, _w = d
            for kind, arg, bc in blocks.get(k, []):
                if kind == 'struct':
                    lines.append('%-39s ; %s' % ('.struct ' + arg, bc) if bc else '.struct ' + arg)
                    for fn, _off, size in self.consts['structs'][arg]:
                        lines.append('  %-20s %s' % (fn, '.byte' if size == 1 else '.res %d' % size))
                    lines.append('.endstruct')
                elif kind == 'enum':
                    lines.append('%-39s ; %s' % ('.enum', bc) if bc else '.enum')
                    in_enum, nxt = True, 0
                else:
                    lines.append('.endenum')
                    in_enum = False
            if name is None:
                break
            first, *more = comment.split('\n')
            if in_enum:
                v = self.const_vals[name]
                text = '  ' + name if v == nxt else '  %s = %s' % (name, expr)
                lines.append('%-39s ; %s%s' % (text, ('%d' % v) if v < 10 else '$%02X' % v,
                                               (': ' + first) if first else ''))
                nxt = v + 1
            else:
                lines.append(('%-22s = %-14s ; %s' % (name, expr, first)) if first else '%-22s = %s' % (name, expr))
            lines.extend('%-39s ; %s' % ('', x) for x in more)
        return '\n'.join(lines) + '\n'

    def run(self):
        self.classify_cdl()
        self.apply_force()
        self.apply_msprites()
        self.apply_sound()
        for _ in range(20):
            a = self.apply_bankcalls()
            b = self.trace()
            c = self.detect_dispatch()
            e = self.detect_tables()
            if not (a or b or c or e):
                break
        for i in self.user['bitskip']:
            if self.rom[i] != 0x2C or self.kind[i] != K_OP:
                sys.exit('bitskip %s: not a BIT abs instruction' % where(i))
            self.kind[i], self.kind[i + 1], self.kind[i + 2] = K_DATA, K_OP, K_ARG
            self.locked.add(i)
            self.bitskips.add(i)
        self.mark_unread()
        self.detect_imm_pairs()
        self.gather_refs()
        # pointer high bytes used only as ptr+1 are printed as ptr_XX+1 instead of getting their own name
        self.ram_used_direct = {a for a in self.ram_used if a - 1 not in self.ptrs or a in self.ram_user}
        self.build_labels()
        self.apply_consts()
        self.mod_starts = {a for _n, _d, a, _b in self.module_ranges()}

    # ------------------------------------------------------------------ files
    def write_all(self, out):
        def w(path, text):
            p = os.path.join(out, path)
            os.makedirs(os.path.dirname(p) or out, exist_ok=True)
            with open(p, 'w', encoding='utf-8', newline='\r\n' if path.endswith('.bat') else '\n') as f:
                f.write(text)

        mods = self.emit()
        for f in glob.glob(os.path.join(out, 'src', 'prg', '*.asm')):
            if os.path.splitext(os.path.basename(f))[0] not in mods:
                os.remove(f)                # a module of an earlier split
        for name, text in mods.items():
            w('src/prg/%s.asm' % name, text)
        w('src/ram.inc', self.ram_inc())
        w('src/const.inc', self.const_inc())
        w('src/charmap.inc', self.charmap_inc())
        w('src/chr.asm', CHR_ASM)
        w('src/defines.inc', '; Hardware registers. Generated by tools/disasm.py\n\n' +
          ''.join('%-22s = $%04X\n' % (n, a) for a, n in sorted(HW_REGS.items())) + '\n; MMC3 (writes only)\n' +
          ''.join('%-22s = $%04X\n' % (n, a) for a, n in sorted(MMC3_REGS.items())) +
          ('\n; fixed CPU addresses read from the switchable windows (rawsym lines in rom.txt)\n' +
           ''.join('%-22s = $%04X\n' % (n, a) for a, n in sorted(self.user['rawsyms'].items()))
           if self.user['rawsyms'] else ''))
        w('src/main.asm', '\n'.join([
            '; %s - ca65 disassembly. Build: assemble.bat (or make)' % GAME,
            '', '.include "defines.inc"', '.include "ram.inc"', '.include "const.inc"', '.include "charmap.inc"', '',
            '.segment "HEADER"', '  .incbin "../header.bin"', '',
            '; PRG ROM: 16 banks of 8KB (MMC3), segments BANK_00..BANK_0F (config.cfg). Even banks run at $8000,',
            '; odd banks at $A000 (always mapped in pairs n, n+1), bank 0E at $C000 and 0F at $E000 (fixed).',
            '; One file per module (module lines in tools/labels/rom.txt), src/prg/BB_name.asm.',
            '; Line comments: flags C = code (CDL), T = code found by static tracing, D = data read (CDL),',
            ';   P = DMC sample read (CDL), J = jump target, S = subroutine entry; then file offset, bank:CPU address',
            ';   (CPU address alone in the fixed banks), bytes. Data that neither the CDL nor the tracer reached is',
            ';   marked "unknown".'] +
            ['%-31s ; %s %s' % ('.include "prg/%s.asm"' % n, where(a), d) for n, d, a, _b in self.module_ranges()] +
            ['', '.include "chr.asm"', '']))
        open(os.path.join(out, 'header.bin'), 'wb').write(self.header)
        w('config.cfg', config_text())
        w('assemble.bat', ASSEMBLE)
        w('compare.bat', COMPARE)
        w('%s.mlb' % OUT_NAME, self.mlb())
        self.write_report(os.path.join(out, 'docs', 'coverage.txt'))

    def mlb(self):
        lines = []
        for i in sorted(self.labels):
            c = self.user['labels'].get(i, (None, ''))[1]
            lines.append('P:%X:%s%s' % (i, self.global_name(i), (':' + c) if c else ''))
        for a, (name, _s, c) in sorted(self.ram_user.items()):
            lines.append('R:%X:%s%s' % (a, name, (':' + c) if c else ''))
        return '\n'.join(lines) + '\n'

    def write_report(self, path):
        cnt = defaultdict(int)
        for k in self.kind:
            cnt[k] += 1
        is_code = lambda i: self.kind[i] in (K_OP, K_ARG)
        r = ['%s PRG coverage (%d bytes, 16 banks of 8KB)' % (GAME, SIZE), '',
             'code (CDL)       %6d' % sum(1 for i in range(SIZE) if is_code(i) and self.cdl[i] & CDL_CODE),
             'code (traced)    %6d' % sum(1 for i in range(SIZE) if is_code(i) and not self.cdl[i] & CDL_CODE),
             'data             %6d  (of them never read in any log, see docs/unknown.txt: %d)' % (cnt[K_DATA], len(self.unread)),
             'word tables      %6d' % cnt[K_WORD],
             'unknown          %6d  (of them $FF: %d)' % (cnt[K_UNK], sum(1 for i in range(SIZE) if self.kind[i] == K_UNK and self.rom[i] == 0xFF)),
             '', 'bank  code   data  words  unknown  unknown-not-$FF']
        for b in range(NBANKS):
            rng = range(b * BANK, (b + 1) * BANK)
            r.append('  %02X %6d %6d %6d %8d %8d' % (b, sum(1 for i in rng if is_code(i)), sum(1 for i in rng if self.kind[i] == K_DATA),
                                                  sum(1 for i in rng if self.kind[i] == K_WORD), sum(1 for i in rng if self.kind[i] == K_UNK),
                                                  sum(1 for i in rng if self.kind[i] == K_UNK and self.rom[i] != 0xFF)))
        r += ['', 'Unresolved $8000-$BFFF references (no bank hint; see tools/labels/banks.txt): %d' % len(self.unresolved)]
        r += ['  %s $%04X' % (where(i), a) for i, a in self.unresolved]
        r += ['', 'Unknown runs:']
        i = 0
        while i < SIZE:
            if self.kind[i] != K_UNK:
                i += 1
                continue
            j = i
            while j < bank_end(i) and self.kind[j] == K_UNK:
                j += 1
            r.append('  %s-%04X %4d  %s' % (where(i), cpu(j - 1), j - i,
                                           ' '.join('%02X' % b for b in self.rom[i:min(j, i + 24)]) + (' ...' if j - i > 24 else '')))
            i = j
        r += ['', 'Traced code (not in CDL):']
        i = 0
        while i < SIZE:
            if i not in self.traced:
                i += 1
                continue
            j = i
            while j < bank_end(i) and (j in self.traced or self.kind[j] == K_ARG):
                j += 1
            r.append('  %s-%04X' % (where(i), cpu(j - 1)))
            i = j
        r += ['', 'Inline dispatch tables (start, entries):']
        r += ['  %s %d' % (where(i), n) for i, n in sorted(self.dispatch_log.items())]
        r += ['', 'Bank hints from bankcall lines: %d' % len(self.static_hint)]
        r += ['', 'Detected word tables (start, words, strong, weak, rts-adj, referenced):']
        r += ['  %s %3d %3d %3d %d %s' % (where(i), n, s, wk, adj, ref) for i, n, s, wk, adj, ref in self.table_log]
        r += ['', 'Immediate pairs #<label/#>label: %d' % (len(self.immref) // 2)]
        r += ['  %s %s%s' % (where(i), p, self.labels[self.start_of(t)]) for i, (p, t) in sorted(self.immref.items())]
        r += ['', 'Raw operands (outside RAM/registers/ROM):']
        r += ['  %s %s' % (where(i), t) for i, t in self.raw]
        r += ['', 'Inline dispatch tables cut short (entry is not code):'] + ['  ' + x for x in sorted(set(self.dispatch_bad))]
        r += ['', 'CDL anomalies (code flag on bytes that do not decode):']
        r += ['  %s' % where(i) for i in self.anomalies]
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8', newline='\n') as f:
            f.write('\n'.join(r) + '\n')
        print('code %d (traced %d), data %d, words %d, unknown %d (not $FF: %d), unresolved %d -> %s'
              % (cnt[K_OP] + cnt[K_ARG], len(self.traced), cnt[K_DATA], cnt[K_WORD], cnt[K_UNK],
                 sum(1 for i in range(SIZE) if self.kind[i] == K_UNK and self.rom[i] != 0xFF), len(self.unresolved), path))


def config_text(shift=None):
    """ld65 config; shift(bank) -> offset subtracted from the bank's start (relocation test)"""
    mem = ['    HDR:     start = $0000, size = $0010, type = ro, file = %O, fill = yes, fillval = $FF;']
    seg = ['    HEADER:  load = HDR, type = ro;']
    for b in range(NBANKS):
        start = base_of(b) - (shift(b) if shift else 0)
        mem.append('    PRG_%02X:  start = $%04X, size = $2000, type = ro, file = %%O, fill = yes, fillval = $FF, bank = $%02X;'
                   % (b, start, b))
        seg.append('    BANK_%02X: load = PRG_%02X, type = ro;' % (b, b))
    mem.append('    CHR:     start = $0000, size = $20000, type = ro, file = %O, fill = yes, fillval = $FF;')
    seg.append('    CHR_ROM: load = CHR, type = ro;')
    return ('# ld65 config: iNES header + 128KB PRG (16 MMC3 banks of 8KB) + 128KB CHR. Generated by tools/disasm.py\n'
            '# even banks run at $8000, odd banks at $A000, bank 0E at $C000, bank 0F at $E000\n'
            'MEMORY {\n' + '\n'.join(mem) + '\n}\n\nSEGMENTS {\n' + '\n'.join(seg) +
            '\n}\n\nFILES {\n    %O: format = bin;\n}\n')


CHR_ASM = """; CHR ROM (128KB = 16 x 8KB, MMC3 1KB/2KB banks). Generated by tools/disasm.py.
; The files are written by tools/chr_tool.py split (gfx/chr_XX.png are the editable sheets).

.segment "CHR_ROM"
""" + ''.join('  .incbin "chr/chr_%02X.chr"                ; CHR $%05X-$%05X\n' % (k, k * 0x2000, k * 0x2000 + 0x1FFF)
              for k in range(16))

ASSEMBLE = """@echo off
cd /d "%~dp0"
del game.nes game.map game_labels.txt 2>nul
ca65 -g src/main.asm -o src/main.o
if errorlevel 1 exit /b 1
ld65 -C config.cfg -Ln game_labels.txt -m game.map -o game.nes src/main.o
"""

COMPARE = """@echo off
cd /d "%~dp0"
call "%~dp0assemble.bat"
if errorlevel 1 exit /b 1
python tools/compare.py
"""


def build_check(out, rom):
    o = os.path.join(out, 'src', 'main.o')
    for cmd in (['ca65', '-g', os.path.join(out, 'src', 'main.asm'), '-o', o],
                ['ld65', '-C', os.path.join(out, 'config.cfg'), '-Ln', os.path.join(out, 'game_labels.txt'),
                 '-m', os.path.join(out, 'game.map'), '-o', os.path.join(out, 'game.nes'), o]):
        p = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
        if p.returncode:
            print(p.stdout + p.stderr)
            return False
    ok, msg = compare_roms(os.path.join(out, 'game.nes'), rom)
    print('build: ' + msg)
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--rom', default=os.path.join(ROOT, ROM_NAME))
    ap.add_argument('--cdl', nargs='+', default=None, help='CDL file(s), merged (default: the game CDL + tmp/merged.cdl if present)')
    ap.add_argument('--out', default=ROOT)
    ap.add_argument('--labels', default=os.path.join(HERE, 'labels'))
    ap.add_argument('--build', action='store_true', help='assemble and compare with --rom')
    ap.add_argument('--no-chr', action='store_true')
    ap.add_argument('--no-verify', action='store_true', help='skip the CRC32/SHA-1 check of the ROM')
    a = ap.parse_args()
    if not a.no_verify:
        import check_rom
        msg = check_rom.problem(a.rom)
        if msg:
            sys.exit(msg)
    d = Disasm(a.rom, a.cdl or default_cdls(), a.labels)
    d.run()
    d.write_all(a.out)
    if not a.no_chr:
        subprocess.run([sys.executable, os.path.join(HERE, 'chr_tool.py'), 'split', '--rom', a.rom, '--out', a.out],
                       check=True)
    if a.build and not build_check(a.out, a.rom):
        sys.exit(1)


def default_cdls():
    """the game CDL plus the CDLs written by the Mesen bot (tools/mesen/*.cdl, kept in git)"""
    return [os.path.join(ROOT, CDL_NAME)] + sorted(glob.glob(os.path.join(HERE, 'mesen', 'cdl', '*.cdl')))


if __name__ == '__main__':
    main()
