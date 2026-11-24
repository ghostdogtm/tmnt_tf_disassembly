# Unread data (what the biggest regions are)

`docs/unknown.txt` (generated) lists 209 runs of PRG bytes that no Mesen run or CDL ever read: 1 143 bytes that are not `$FF`
fill. "Unread" means "not read in 234 Mesen runs", not "dead": some are table entries for choices nobody made (a character in
a mode that cannot be picked), some are padding, some are dead code. Everything below was read from the bytes; nothing was
tested by forcing it to be read.

The VS-info records of Mike and Don (`VsInfoRec02/03`, 52 bytes) were read by a tournament run with `fighterChar` held at 2 and 3 (tournament script of `tmp/modes5`, holds on `$00A2`/`$00A3` from frame 5300); `DrawVsFighterInfo` is a tournament-bracket routine, not the VS screen.

Pressing Start on the CONTINUE screen (frames 9600-10300 of the `tmp/lose2` scenario) ran `ContinueQueueDataB` and the states 4 and 5 (`ContinueFinalCount`, `ContinueExit`): they are live code, not dead.

The tail of `PlayerSeqData` (character 4, `tmp04` non-zero) is read by the CONTINUE card (`StoryCardFighter2`, card 1) when `fighterChar` of player 1 is 4: the lose scenario with `$00A2` held at 4 from frame 9500.

Passes so far: the unread total went 5 032 -> 1 758 (metasprite frames of bank 05, tables, texts decoded) -> 1 143 (dead
routines recovered as `code`, see below). Dead code now disassembled and named `Unused...`: the 16x8 / 8x8 multipliers, the
angle -> velocity library (`UnusedSetVelFromAngle`, `UnusedCosOfAngle`, `UnusedSinOfAngle`, `UnusedMulBySpeed`, `CosTable16`),
an MMC3 IRQ clock helper, an alternate bank-0 push, small AI action stubs, and the
ball-launch variants 2-6 (`BallLaunchStep2..6`).

| bytes | region | what it is |
|---|---|---|
| 365 | $FE8D-FFF9 | `$FF` padding of the fixed bank (the 5-byte signature at $FFF5 is separate) |
| 127 | 06:8036-80B4 | `InputScriptPad0`: (pad, frames) pairs for a routine nothing calls; buttons use the `BTN_` bits |
| 82 | 0C:83AB-83FC | `UnusedBracketRecords`: records of the unused bracket screen |
| 36 + 16 | $D9BB-D9DE, $DA73-DA82 | tail of the cosine table and its neighbour in the unused geometry library |
| 16 | 0C:85BE-85CD | `UnusedAttrRecords` |
| rest | about 125 runs of 1-12 bytes | single dead entry stubs (`UnusedFadeTimerStep8`, `UnusedIncStoryStage`, ...) are code now; the others are single padding bytes between tables, small table gaps (`PaletteSetIds`, `SpecialScript`, ...) |

A systematic way to shrink the list further: play every character against every other and every song, or poke the game mode
to reach the CONTINUE, bonus-card and ending states; the matchup runner `tmp/cov.sh` (scratch, not in git) does the first part.
