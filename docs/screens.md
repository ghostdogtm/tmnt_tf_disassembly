# Screens (compressed nametables)

Full-screen backgrounds (title, menus, stages, story pictures, the fighter parade) are written to the PPU by
`LoadScreen` (F049) in one go, with rendering off. The generator decodes the streams (`screens` lines in
`tools/labels/rom.txt`, code in `screen_tokens` / `screen_item` of `tools/disasm.py`); the command bytes are
constants in `tools/labels/const.txt`. The build compares every byte with the original ROM.

## Calling

| routine | what it does |
|---|---|
| `LoadScreen` (F049) | X = `SCR_*` (screen id × 2). Maps the pair `ScreenBanks`[X/2] with `PushBankA`, runs `LoadScreenData`, then `PopBank`. |
| `LoadScreenClear` (F047) | `LDX #SCR_CLEAR`, falls into `LoadScreen`. |
| `LoadScreenData` (F058) | the decoder; the pair must already be mapped. Turns rendering off (`DisableRenderingForNmi`), sets `scrollX` / `scrollY` to 0, reads the stream at `ScreenPtrs`,X through `ptr_00`. At `SCR_END` it jumps to F2B5, which writes PPUCTRL back. |
| `AddToPtr` (D051) | `ptr_00,X` += A, 16-bit. The decoder uses it to step over each command. |

`ScreenPtrs` (F0E5) holds 30 stream addresses, and `ScreenBanks` (F121) holds 30 `BANK_SEL|pair` bytes. Screens
`SCR_CLEAR` and `SCR_SELECT_TURTLES_ONLY` are in the fixed bank (F13F–F173), so their entry is `BANK_SEL|0` and the
mapped pair does not matter. All other streams are in pair 06/07. They are stored one after another from
06:836A to 07:A590, and one stream crosses the 06/07 boundary at $A000.

## Stream format

```
  .word $2000                     ; PPU address (little-endian; the high byte goes to PPUADDR first)
  .byte SCR_RUN|126, $00          ; $00-$7E n, tile: n copies of tile (n = 0: 256)
  .byte SCR_SEQUENCE|12, $01      ; $C0-$FE: n = byte & $3F; tiles tile, tile+1, .. (n = 0: 256)
  .byte SCR_LITERAL|3, $15, $13, $14  ; $80-$BF: n = byte & $3F, then n tiles
  .byte SCR_NEXT                  ; $7F: a new PPU address word follows
  .word $23C0
  ...
  .byte SCR_END                   ; $FF: end of the screen
```

The PPU address auto-increments by 1, so the commands simply go on along the rows, and into the attribute table
after row 29. The generator's comment on each command gives the place where it starts (`nametable N row R col C`
or `attributes +k`). `SCR_LITERAL|0` would write 255 tiles (the copy loop checks the count only after `INY`); no
stream uses it.

`ScreenBonusLogo` (06:8447) starts inside `ScreenFightHud`, right after its `SCR_NEXT`: the fight screen draws the
top bars and then the same bottom logo that the bonus game draws on its own.

The legal screen (`ScreenLegal`) has its text as `SCR_LITERAL` runs of `font` tiles (docs/text.md). The
`screentext 06:8ADE-06:8BDA font` line makes the generator write them as strings, for example
`.byte SCR_LITERAL|20, "TEENAGE MUTANT NINJA"`. "STU" in MIRAGE STUDIOS is packed as `SCR_SEQUENCE|3, 'S'`.

## Screens

Checked with Mesen screenshots taken 60 frames after each `LoadScreenData` call, except the `StagePalettes` row, which is read from the code.

| X | constant | stream | picture | loaded by |
|---|---|---|---|---|
| $00 | `SCR_CLEAR` | F13F | blank nametables 0 and 3 | `LoadScreenClear` (FightStart, ModeGameInit, ModeKonami, 0C:96BC) |
| $02 | `SCR_TITLE` | 06:83A5 | title | F00C |
| $04 | `SCR_KONAMI` | 06:836A | Konami logo | F51C |
| $06 | `SCR_LEGAL` | 06:8ADE | legal / license text | F576 |
| $08 | `SCR_STAGE_WATERFRONT` | 06:8460 | stage: waterfront, Statue of Liberty | `StageScreens`, 0C:96C6 |
| $0A | `SCR_STAGE_SEWER` | 06:875F | stage: sewer | `StageScreens` |
| $0C | `SCR_FIGHT_HUD` | 06:8435 | fight HUD: top bars and the bottom logo | E401 (after the stage) |
| $0E | `SCR_STAGE_PIRATE_SHIP` | 06:8BDB | stage: pirate ship | `StageScreens` |
| $10 | `SCR_PLAYER_SELECT` | 06:8EF4 | player select | 06:810B |
| $12 | `SCR_VS_SETUP` | 06:9046 | VS CPU: strength and stage select | 0C:88AD |
| $14 | `SCR_STAGE_DOWNTOWN` | 06:913F | stage: downtown ("FOOT" wall) | `StageScreens` |
| $16 | `SCR_TOURNAMENT` | 06:949C | tournament bracket | 0C:82C9 |
| $18 | `SCR_OPTION` | 06:9F8E | option screen | 0C:8036 |
| $1A | `SCR_SELECT_TURTLES_ONLY` | F169 | blanks rows 16–29 of nametable 0 | 06:8116 (story: only the turtles can be picked) |
| $1C | `SCR_BONUS_GAME` | 06:9639 | bonus game stage | E803 |
| $1E | `SCR_BONUS_LOGO` | 06:8447 | the bottom logo only | E810 |
| $20 | `SCR_NAME_ENTRY` | 06:99B2 | tournament name entry | 0C:8C8D |
| $22 | `SCR_ENDING_SHREDDER` | 06:9BA6 | ending: turtle vs Shredder | `EndingScreens`[0] (0C:9673) |
| $24 | `SCR_ENDING_TURTLES` | 06:9C44 | ending: the turtles | `EndingScreens`[1] |
| $26 | `SCR_RANKING` | 06:9D04 | ranking 1ST–5TH (?: not seen in Mesen; only the text was read) | 0C:9FE0 |
| $28 | `SCR_VS` | 06:9EAE | the VS screen before a fight | E251 (FightVsScreen) |
| $2A | `SCR_STORY_MANHATTAN` | 07:A075 | story: Manhattan skyline | 0C:90FA |
| $2C | `SCR_STORY_LETTER` | 07:A181 | story: the letter scene | 0C:9123 |
| $2E | `SCR_SPLINTER` | 07:A277 | ending: Splinter | 0C:983D |
| $30–$3A | `SCR_PARADE_LEO` .. `SCR_PARADE_HOTHEAD` | 07:A2CF.. | fighter parade (attract mode): LEO, RAPH, MIKE, DON, CASEY, HOTHEAD | 0C:91F0 (`SCR_PARADE_LEO` + 2 × fighter) |

## Per-stage tables

`storyStage` ($9E, 0-6 = `STAGE_COUNT`) indexes seven small tables in bank F (all read by `FightRoundSetup` E3B8,
`FightRoundIntro` E46D and the timer code at EAF3):

| table | address | content |
|---|---|---|
| `StageScreens` | E920 | `SCR_STAGE_*` : sewer, downtown, sewer, downtown, pirate ship, pirate ship, waterfront |
| `StageMusic` | E935 | `MUS_SEWER` $2E, `MUS_DOWNTOWN` $2F, `MUS_SHIP` $30, `MUS_WATERFRONT` $31, same arena order |
| `StageMusicHurry` | E93C | `MUS_*_HURRY` $33-$36, played when `timerTens` reaches 1 |
| `StageIrqSplit` | E943 | argument of `SetIrqSplit` (3, 4, 3, 4, 1, 1, 2) |
| `StageChrBanks` | E912 | 7 x (R0, R1): two 2 KB CHR banks the IRQ handler switches in mid-screen (`$4E`/`$4F`, F8DD); Mesen with `storyStage` held at 1-6: sewer `$68`/`$6A`, downtown `$64`/`$66`, pirate ship `$60`/`$62`, waterfront `$5C`/`$5E` (`CHR_BG_*`) |
| `StagePalettes` | E927 | 7 x (Y, A) passed to `LoadPaletteSets`: palette set ids of `PaletteSetIds` |
| `RandomStages` | E90E | 0, 1, 4, 6: the demo / VS pick `rngSeed & 3` from them |

Checked in Mesen (`tmp/stg`, 40 000 frames): stage 1 gave screen `SCR_STAGE_DOWNTOWN` ($14), music $2F, hurry music $34,
banks $64/$66 and split 4, as the tables say. Stages 1-6 were then forced with `storyStage` held (see Arenas below): the screen, the CHR banks and
the music agree with the tables for every one of them.

## Arenas

The values come from Mesen screenshots (`storyStage` ($9E) held at the value from the second round on, the CHR banks and IRQ split are
those of the table row; the screenshots themselves are not in the repository). Stages 1 and 3 are the same arena (same
screen, CHR banks, palettes and split), and so are 4 and 5; only the scroll position and the fighters differ.

| arena | stages | screen | BG CHR (R0/R1 after the split) | palette row (background) | IRQ split |
|---|---|---|---|---|---|
| sewer | 0, 2 | `SCR_STAGE_SEWER` | `CHR_BG_SEWER` $68 / $6A | 3 | 3 |
| downtown | 1, 3 | `SCR_STAGE_DOWNTOWN` | `CHR_BG_DOWNTOWN` $64 / $66 | 8 | 4 |
| pirate ship | 4, 5 | `SCR_STAGE_PIRATE_SHIP` | `CHR_BG_SHIP` $60 / $62 | 5 | 1 |
| waterfront | 6 | `SCR_STAGE_WATERFRONT` | `CHR_BG_WATERFRONT` $5C / $5E | 1 | 2 |

The sprite palette row is 2 for every stage. Stage 6 is fought against Shredder (the story card with his portrait comes
first). The arenas use several CHR banks (R0-R5, switched again
by the IRQ split), so a static render (not done) needs the whole bank setup of each split.

## Not covered here

- The palettes and CHR banks of each screen are set by the callers, not by the stream.
- Smaller screen updates during play go through the PPU queue (`RunPpuQueue`) and `DrawText`, not through
  `LoadScreen`.
