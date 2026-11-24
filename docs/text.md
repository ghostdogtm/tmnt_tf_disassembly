# Text and fonts

All text in the game is made of nametable tiles. The generator writes every text block as ca65 strings through a
`.charmap` (`charmap` and `text` lines in `tools/labels/rom.txt`; the macros are in the generated
`src/charmap.inc`). Each block starts with `CHARMAP_<NAME>` and ends with `CHARMAP_ASCII`, which puts the default
mapping back. The control bytes are constants in `tools/labels/const.txt`, and the formats are listed in
`TEXT_FORMATS` in `tools/disasm.py`. The build compares every byte with the original ROM, so a wrong mapping fails
the build.

## Fonts (charmaps)

| charmap | tiles | used by |
|---|---|---|
| `font` | space `$00`, `0-9` = `$81-$8A`, `A-Z` = `$8B-$A4`, `.` `$A7`, `,` `$A8`, `?` `$A9`, `!` `$AC`, `` ` `` `$AD`, `'` `$AE`; named tiles: `TILE_REGISTERED` `$A5` (®), `TILE_COPYRIGHT` `$A6` (©), `QUOTE_OPEN` `$AA`, `QUOTE_CLOSE` `$AB`, `TILE_TM` `$AF` (™) | DrawText strings, credits, story text, UnusedFighterNames |
| `bgm` | the `font` tiles − `$80`: space `$00`, `0-9` = `$01-$0A`, `A-Z` = `$0B-$24` | option screen BGM test names (DrawBgmTestName ORs in `$80`), FighterNames |
| `hud` | only the letters of the fighter names: `A` 1, `C` 2, `D` 3, `E` 4, `H` 5, `I` 6, `L` 7, `M` 8, `N` 9, `O` `$0A`, `P` `$0B`, `R` `$0C`, `S` `$0D`, `T` `$0E`, `Y` `$0F`, `K` `$60` (checked: the HUD shows MIKE, Mesen with `fighterChar` held at 2) | FighterNamesHud (names at the top of the fight screen) |

The glyphs of `font` were checked by drawing tiles `$80-$BF` of CHR 1 KB banks `$76` and `$7E`, the two font
styles. `$AD` and `$AE` are single quotes that lean in opposite directions; the text uses `$AE` for the
apostrophe (`DON'T`). A `"` cannot be written inside a ca65 string, so the quote marks are named tiles. The `hud`
letters follow from the names (`LEO` = `07 04 0A` ...); `K` = `$60` was not checked in the CHR.

## Formats

### `ppu`: DrawText strings (08:80F1, `TextPtrs`, ids `TXT_*`)

`DrawText` (08:8076) gets a string id in A. With carry set, it writes tile 0 in place of each character, which
erases the string.

```
  .word $224C                     ; PPU address (little-endian)
  .byte "STORY", TEXT_END         ; tiles .. TEXT_END ($FF)
  .word $2502
  .byte "PLAYER1", TEXT_NEXT      ; TEXT_NEXT ($FE): another PPU address and tiles follow
  .word $231A
  .byte "PLAYER2", TEXT_END
```

`TextNames` (08:8209) uses the same format: LEO .. HOTHEAD, with no pointer in `TextPtrs`. Nothing reads it.

### `credits`: staff credits (0C:99E2, `CreditsText`)

Each call of the credits step handles one record. The record number is `objPhase`; the code skips that many
records, each one ended by `$FF`.

```
  .dbyt $282D                     ; PPU address (big-endian), tiles, TEXT_END
  .byte "STAFF", TEXT_END
  .byte CREDITS_ERASE             ; $FE + address + TEXT_END: fill CREDITS_LINE_LEN (21) blank tiles there
  .dbyt $282D
  .byte TEXT_END
  .byte CREDITS_END               ; $FD: end of the credits
```

### `story`: the typewriter text box (0C:9C25, `StoryTextPtrs`, ids `STXT_*`)

`RunStoryText` (0C:9B36, `FarRunStoryText` from the fixed bank) types one character every `STORY_CHAR_DELAY` (6)
frames. It starts at `STORY_BOX` + 4 (`$2284`: nametable 0, row 20, column 4).

| byte | constant | effect |
|---|---|---|
| `$BB` n | `STORY_WAIT` | wait n frames |
| `$BC` | `STORY_CLEAR` | clear the 4 box rows (`StoryClearBox`) and go back to the first line |
| `$BD` | `STORY_NEWLINE` | next line (+ `NT_WIDTH`) |
| `$BE` | `STORY_EASY_ONLY` | the rest is shown only on EASY (`difficulty` 0); on other difficulties the text ends here |
| `$BF` | `STORY_FADE_MUSIC` | `SND_FADE_OUT` |
| `$FF` | `STORY_END` | end; `storyTextState` goes back to 0 |

The eight texts:

| id | when | text |
|---|---|---|
| `STXT_MANHATTAN` | story intro | MANHATTAN.... PRESENT DAY. |
| `STXT_LETTER` | | THE TURTLES RECEIVE A STRANGE LETTER |
| `STXT_SHREDDER_LETTER` | | Shredder's challenge |
| `STXT_SHREDDER_ESCAPES` | the Shredder ending picture (`EndingTextId[0]`) | "YOU HAVE NOT SEEN THE LAST OF ME!!"; on EASY, CHALLENGE THE NORMAL MODE NEXT TIME! |
| `STXT_SPLINTER` | ending | "YOU HAVE PERFORMED WELL, MY SONS..." |
| `STXT_SHREDDER_TAUNT` | before a Story fight from stage 6 on (`FightShredderTaunt`; Mesen: frame 5790) | "YOU MAY HAVE BEATEN ME IN THE PAST..." |
| `STXT_SHREDDER_WINS` | `FightShredderWins`, then `SetModeLost` (code read, not seen in play) | "HA! I EXPECTED A TOUGHER OPPONENT..." |
| `STXT_HARD_MODE` | after the credits | CHALLENGE THE HARD MODE NEXT TIME! |

The ending picks `STXT_SHREDDER_ESCAPES` or `STXT_SPLINTER` from a two-entry table at 0C:9951.

### `bit7`: option screen BGM test names (0C:820D, `BgmTestNames`)

There are 18 names, each padded to 8 bytes. The last byte has bit 7 set: `.byte "OPENING", '2'|$80`. The table
lists BGM1-4, OPENING1-2 and SE1-SE11, and SE4 appears twice.

### `plain`: name lists

Each string ends with `TEXT_END`. `FighterNamesHud` (`hud`) and `FighterNames` (`bgm`) are indexed by `CHAR_*`.
`DrawFighterNames` (EBA0) draws them at `FighterNamePpuAddr`, with A = 0 for the HUD names and A = 4 for
FighterNames. `UnusedFighterNames` (DDB6, `font`) has the same names plus DRAW GAME, and nothing reads it.

### The legal screen (`SCR_LEGAL`, 06:8ADE)

Not a text format of its own: the screen stream (docs/screens.md) writes each line as a `SCR_LITERAL` run of `font` tiles
between `SCR_RUN` runs of blank tile $00, and the generator turns the runs into strings (`screentext 06:8ADE-06:8BDA font`).
The rows (nametable 0, column 3 unless noted; `(R)` and `(C)` are the tiles `TILE_REGISTERED` and `TILE_COPYRIGHT`):

```
row  6  TEENAGE MUTANT NINJA
row  7  TURTLES (R)   MIRAGE STUDIOS,        (the "STU" is one SCR_SEQUENCE run of 'S', 'T', 'U')
row  8  USA.  ALL RIGHTS RESERVED.
row  9  TRADEMARK USE GRANTED TO
row 10  KONAMI UNDER LICENSE FROM
row 11  MIRAGE STUDIOS,USA.
row 13  (col 9)  TM AND (C)  1993
row 14  (col 9)  KONAMI CO.,LTD.
row 15  (col 6)  ALL RIGHTS RESERVED.
row 17  (col 6)  LICENSED BY NINTENDO
```

## Not decoded yet

- The glyph of tile `$B9` (used once in the credits: `J`, `$B9`, `KANE`) differs between the two font banks: it is
  a low bar in bank `$7E` and graphics in bank `$76`. It is written as `$B9`.
- Not checked in the emulator: which story texts appear in the ending and loss paths (`STXT_SHREDDER_WINS`).
