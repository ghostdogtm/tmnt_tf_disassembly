"""Optional byte patches that fix the bugs of the original game (README: "Known bugs in the game").

Used by tools/patch_rom.py. Each patch is independent: it lists its edits as (bank, CPU address, expected original
bytes, new bytes). Banked addresses are $8000-$9FFF / $A000-$BFFF of the given bank (a pair of banks is mapped there at
the time, the address is the position inside the bank), fixed-bank addresses are $E000-$FFFF (bank $0F). The tool
refuses to apply an edit when the bytes in the ROM are not the expected ones.

Two patches need a few bytes of code. They go to the $FF fill of the fixed bank ($0F:EF61-EFFF, 159 bytes unused in the
original; 46 of them are used here): `FIX_KEEP_Y` at $EF61 and `FIX_BALL_HALF` at $EF68. Those two addresses are the same
whichever patches are selected, so the patches can be combined freely.

Every patch is described in English only: README.md has the full story of the bugs (and README.uk.md the translation).
"""

FIX_KEEP_Y = 0xEF61      # AbsDeltaBelow, then LDY aiTarget,X
FIX_BALL_HALF = 0xEF68   # GetBallRange: |aiTargetDx| into tmp04 for both signs

# $0F:EF61  JSR AbsDeltaBelow ; LDY aiTarget,X ; RTS
_KEEP_Y = bytes([0x20, 0x3E, 0xEE,        # JSR $EE3E (AbsDeltaBelow)
                 0xBC, 0xDE, 0x06,        # LDY aiTarget,X   (carry is not touched by LDY)
                 0x60])                   # RTS

# $0F:EF68  replaces `LDA aiTargetDx ; BPL $EF07` of GetBallRange (the old negative-value block stays as dead code)
_BALL_HALF = bytes([
    0xAD, 0xD6, 0x06,                     # LDA aiTargetDx
    0x10, 0x17,                           # BPL positive (+23)
    0x49, 0xFF,                           # EOR #$FF
    0x85, 0x05,                           # STA tmp04+1
    0xAD, 0xD7, 0x06,                     # LDA aiTargetDx+1
    0x49, 0xFF,                           # EOR #$FF
    0x18,                                 # CLC
    0x69, 0x01,                           # ADC #1
    0x85, 0x04,                           # STA tmp04
    0xA5, 0x05,                           # LDA tmp04+1
    0x69, 0x00,                           # ADC #0
    0x85, 0x05,                           # STA tmp04+1
    0x4C, 0x07, 0xEF,                     # JMP $EF07
    # positive:
    0x85, 0x05,                           # STA tmp04+1  (A = aiTargetDx)
    0xAD, 0xD7, 0x06,                     # LDA aiTargetDx+1
    0x85, 0x04,                           # STA tmp04
    0x18,                                 # CLC (as after the negation)
    0x4C, 0x07, 0xEF,                     # JMP $EF07
])
assert len(_KEEP_Y) == 7 and FIX_BALL_HALF == FIX_KEEP_Y + len(_KEEP_Y)
assert _BALL_HALF[4] == 0x17 and _BALL_HALF[5 + 0x17] == 0x85 and len(_BALL_HALF) == 39

PATCHES = [
    {
        'id': 1, 'name': 'casey-dy-gap',
        'title': "Casey's second vertical-distance check works",
        'text': "AbsDeltaBelow leaves its limit in Y, so the second ObjDeltaY16 of the CPU Casey measured the wrong objects. "
                "The two first calls (0A:9614, 0A:96AD) now go to a stub in the fixed bank that reloads Y = aiTarget,X. "
                "The CPU Casey presses A only while $30 <= |dy| < $50, as intended.",
        'edits': [
            (0x0F, FIX_KEEP_Y, b'\xFF' * len(_KEEP_Y), _KEEP_Y),
            (0x0A, 0x9615, bytes([0x3E, 0xEE]), bytes([FIX_KEEP_Y & 0xFF, FIX_KEEP_Y >> 8])),
            (0x0A, 0x96AE, bytes([0x3E, 0xEE]), bytes([FIX_KEEP_Y & 0xFF, FIX_KEEP_Y >> 8])),
        ],
    },
    {
        'id': 2, 'name': 'attack-idle-time',
        'title': 'AttackIdleTimeByChar is indexed by the character',
        'text': "StartAttackIdleState did LDA table,X (the fighter slot) after LDY objSpriteSet,X; now LDA table,Y. "
                "Every character gets its own value (Leo 4, Raph 3, Mike 3, Don 4, Casey 2, Hothead 5, Shredder 4) "
                "instead of 4 for slot 0 and 3 for slot 1.",
        'edits': [(0x02, 0x8352, bytes([0xBD]), bytes([0xB9]))],
    },
    {
        'id': 3, 'name': 'ball-range',
        'title': 'GetBallRange uses the current target distance',
        'text': "The half of |aiTargetDx| was computed in tmp04 only for a negative aiTargetDx; for a positive one the "
                "previous contents were used. A stub in the fixed bank now fills tmp04 for both signs.",
        'edits': [
            (0x0F, FIX_BALL_HALF, b'\xFF' * len(_BALL_HALF), _BALL_HALF),
            (0x0F, 0xEEEE, bytes([0xAD, 0xD6, 0x06, 0x10, 0x14]),
             bytes([0x4C, FIX_BALL_HALF & 0xFF, FIX_BALL_HALF >> 8, 0xEA, 0xEA])),
        ],
    },
    {
        'id': 4, 'name': 'target-attacks-me',
        'title': 'AiTargetAttacksMe reads the high byte of aiTargetDx',
        'text': "LDA aiTargetDx,Y (the target slot as an index) becomes LDA aiTargetDx, so the sign test works for any "
                "distance, not only while the gap is under 128 pixels. Found by reading the code; the moving-target "
                "branch was not reached in the Mesen runs.",
        'edits': [(0x0F, 0xED6B, bytes([0xB9, 0xD6, 0x06]), bytes([0xAD, 0xD6, 0x06]))],
    },
    {
        'id': 5, 'name': 'step-script-objstep',
        'title': 'AiStepScript tests its own fighter step',
        'text': "LDA objStep (slot 0) becomes LDA objStep,X: the CPU on slot 1 no longer presses A by the jump step of "
                "fighter 0.",
        'edits': [(0x0A, 0x81C2, bytes([0xAD, 0x40, 0x05]), bytes([0xBD, 0x40, 0x05]))],
    },
    {
        'id': 6, 'name': 'shredder-hurt-acts',
        'title': 'Shredder picks only the four entries of AiShredderHurtActs',
        'text': "AiShredderNearHurtPick called AiRandom8 (0-7) for a four-entry table, so on the higher difficulties it "
                "read the code that follows the table as actions. It now calls AiRandom4.",
        'edits': [(0x0A, 0x9AE6, bytes([0xCD]), bytes([0xC2]))],
    },
]
