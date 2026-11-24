#!/usr/bin/env python3
"""Check that the ROM you supplied is the one this project disassembles.

  python tools/check_rom.py [ROM]

The repository does not contain the game. Put your own dump in the repository root under the name below; the checks are
the size, the iNES header and the CRC32 / SHA-1 of the whole file. tools/disasm.py runs the same check before it builds.
"""
import hashlib
import os
import sys
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROM_NAME = 'Teenage Mutant Ninja Turtles - Tournament Fighters (U) [!].nes'
SIZE = 262160                      # 16-byte iNES header + 128 KB PRG + 128 KB CHR
CRC32 = 0xAC05464F
SHA1 = '182f901142530a509a7c9f5831b5a7f7f4c923a8'


def problem(path):
    """None when the file is the expected ROM, otherwise a message that says what to do."""
    if not os.path.isfile(path):
        return ('ROM not found: %s\nPut your own dump of "TMNT: Tournament Fighters (U) [!]" (NES) into the repository root '
                'as:\n  %s\n(the game is not part of this repository; see README, "Quick start").' % (path, ROM_NAME))
    data = open(path, 'rb').read()
    if len(data) != SIZE or data[:4] != b'NES\x1a':
        return ('%s is not the expected ROM: %d bytes (expected %d, iNES header "NES\x1a"). A headerless or trimmed '
                'dump will not do.' % (os.path.basename(path), len(data), SIZE))
    crc = zlib.crc32(data) & 0xFFFFFFFF
    if crc != CRC32 or hashlib.sha1(data).hexdigest() != SHA1:
        return ('%s has CRC32 %08X, expected %08X (SHA-1 %s). It is another dump or region of the game; the disassembly '
                'only matches the (U) [!] dump.' % (os.path.basename(path), crc, CRC32, SHA1))
    return None


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, ROM_NAME)
    msg = problem(path)
    if msg:
        print(msg)
        return 1
    print('ROM OK: %s (CRC32 %08X)' % (os.path.basename(path), CRC32))
    return 0


if __name__ == '__main__':
    sys.exit(main())
