# Sound

The sound driver lives in bank pair 00/01 (`MapSoundBank` F669 maps it, `UpdateSound` runs `SoundFrame` 00:8001
once per NMI). Game code starts a sound with `PlaySound` → `SoundStart` 00:8E8D, A = id:

| id | what | table |
|---|---|---|
| $01-$2D | sound effects (`SND_*` in const.txt) | `SfxPtrs` 00:8D3C, one word per id (id 0 would read code) |
| $2E-$46 (`SND_MUSIC`..) | music, 25 songs | `SongPtrs` 00:8D96, 4 words per song: SQ1, SQ2, TRI, drums |
| $47-$5A (`SND_SAMPLE`..) | DPCM samples | `DpcmSamples` 00:959B, 5 bytes each (`PlaySample`) |
| $5B (`SND_FADE_OUT`) | fade the music out | `FadeOutParams` 00:905B |

All song and SFX data is decoded by the generator (rom.txt `soundptrs` + `sound`, see below). Most of it is in
00:909E-01:BFFB; SFX $01-$03, $23, $28, $29 and $2D are in the fixed bank at CF40-CFFF (readable while any pair is
mapped). SFX $2D (`SND_PAUSE`) starts 8 bytes before the end of a DPCM sample, so those bytes are both.

## Channels

The driver keeps six channels; every channel variable is an array indexed by X = `SNDCH_*`:

| X | channel | streams | APU |
|---|---|---|---|
| 0 `SNDCH_SQ1` | music | song word 0 | square 1 |
| 1 `SNDCH_SQ2` | music | song word 1 | square 2 |
| 2 `SNDCH_TRI` | music | song word 2 | triangle |
| 3 `SNDCH_DRUM` | music drums | song word 3 | noise (through SFX) / DMC |
| 4 `SNDCH_SFX_SQ` | effect | SFX with `SFX_SQ1` | square 1 |
| 5 `SNDCH_SFX_NOISE` | effect | SFX with `SFX_NOISE` | noise |

`sndChanId` ($070C) holds the id playing on each channel (0 = idle). A new effect takes a channel only when its id
is not lower than the one playing there, so higher ids win. While an effect plays on square 1, `Sq1Busy` stops the
music channel 0 from writing the registers; the music keeps running and is heard again when the effect ends.
`SFX_SQ2` and `SFX_TRI` effects use the music channels 1 and 2 themselves (`SfxChannels` 00:8E88).

While a fight is paused (`gamePaused` $97, toggled by Start in `ModeGame`) the driver silences everything and only
runs the channel that plays `SND_PAUSE`.

## Music streams

A stream is read one command at a time; a note waits its length, commands run at once. Parser: `ReadMusic`
00:840F. Constants: `NOTE_*`, `DRUM_*`, `SC_*` (const.txt).

| byte | source | meaning |
|---|---|---|
| $00-$BF | `NOTE_E+4` | note: pitch in the high nibble (C..B), length in the low nibble × base length (0 = 16) |
| $00-$BF (drums) | `DRUM_S48+2` | drum: `DrumSounds` 00:867C[high nibble] → noise SFX `SND_DRUM1`-`3` or a DPCM sample |
| $C0-$CF | `SC_REST+n` | rest, n × base length |
| $D0-$DD | `SC_LEN+n, …` | base length n; then square: 3 bytes (duty<<4 \| volume, envelope id, release), triangle: 1 (release), drums: none |
| $DE / $DF | `SC_PACKED` / `SC_PACKED2` | toggle packed notes: each byte holds two pitches (`NOTE_C\|NOTE_E>>4`), 1 / 2 base lengths each; a low nibble $D-$F = one note only |
| $E0-$E5 | `SC_OCTAVE+n` | octave |
| $E6 n | `SC_ENV` | envelope id (`sndEnvId`) |
| $E7 n | `SC_RELEASE` | cut the note after n/16 of its length (triangle: n ≥ $10 = linear counter n − $10) |
| $E8 n | `SC_LENGTH` | base length |
| $E9 n | `SC_DUTY` | n = 0 clears `sndDutyFlags`; n with a non-zero low nibble: `sndDutyFlags` = n (bit 1 = the volume register takes the high nibble of n instead of `sndDuty`); n with low nibble 0: `sndDuty` = n (duty bits ORed into the volume register) (read from `CmdSetDuty` / `WriteVolFlags`) |
| $EA n | `SC_FADE` | fade-in at each note start: high nibble = starting volume, low nibble = frames per volume step until `sndVolumeBase` is reached (`StartEnvelope`, `ResetEnvTimersScaled`); 0 = off (read from the code) |
| $EB 0 / $EB a b | `SC_VIBRATO` | vibrato off / on: a = pitch envelope ((a − $50) × 2), b: low nibble = depth (envelope offset × depth), high nibble = delay before the vibrato starts (× base length) (read from `VibratoScaleDepth` / `StartVibrato`) |
| $EC n | `SC_FLAGS` | bits 7-6 = `sndVolMin` (lowest volume), bits 3-0 = echo mode (0 off, 1-3: `$A0`+n, 4-F: `$B0`+n−3 in `sndEchoFlags`), bits 5-4 go to `sndEchoFlags` bits 3-2 (`CmdSetFlags`); what the echo does to the sound is not checked (?) |
| $ED n | `SC_DETUNE` | period offset, bit 7 = up |
| $EE n | `SC_TRANSPOSE` | note offset, bit 7 = down |
| $EF n | `SC_DIVIDER` | every n-th frame the music skips its update (slower tempo); 0 = off |
| $F0-$F8 | `SC_VOLUME+n` | volume offset |
| $FA a b [c] | `SC_SLIDE` | opens a repeat block (`CmdSlide`): a = passes, b = period step, c = volume ramp (square/drums 3 bytes, triangle 2). Every pass replays the block with the period lowered by another `b & $7F` (accumulating 16-bit); with c, every `c >> 4` passes the volume index grows by `c & 7` (max $F). Read from the code, not heard |
| $FA | `SC_SLIDE_END` | the next `$FA` jumps back to the block start while passes are left, then closes the block |
| $FB / $FC | `SC_LOOP` / `SC_LOOP2` | loop start, two levels |
| $FD word | `SC_CALL` | call a sub-stream (one level; `SC_END` returns) |
| $FE n | `SC_REPEAT, n` | back to the loop start until it ran n times |
| $FE $FF word | `SC_REPEAT, SC_GOTO` | jump (songs loop this way) |
| $FF | `SC_END` | return from `SC_CALL`, else the channel stops |

$F9 is not a valid command (no stream uses it). Notes are turned into periods by `NotePeriod` with
`PeriodTable` 00:8C8F (7 octaves × 12 words); a negative transpose reads `PeriodTableLow` 00:8C77.

## Effect streams

An SFX id points at a header byte: channel bits in the high nibble (`SFX_SQ1` $80, `SFX_SQ2` $40, `SFX_TRI` $20,
`SFX_NOISE` $10) and the base length in the low nibble. One stream per set bit follows, in that order; each ends
with its own `SC_END`. The first stream starts with the channel setup: square = duty byte (plus a sweep byte when
its low nibble is 0), triangle = 1 byte, noise = none. Parser: `ReadSfx` 00:8873.

| byte | source | meaning |
|---|---|---|
| $00 | `SFX_REST` | silence for one base length |
| $01-$0F | `SFX_LEN+n, …` | base length n, then the channel setup again |
| $E8 / $E9 / $EA n | `SC_LENGTH` / `SC_DUTY` / `SC_FADE` | as in music (not on noise) |
| square, triangle | `$vh, $ll` | volume<<4 \| period high, period low |
| noise | `$vp` | volume<<4 \| noise period; `$10` takes one more byte |
| $FA-$FF | `SC_*` | as in music |

## Envelopes

`EnvelopePtrs` 00:9541 (9 words) is shared by the volume envelopes (`SC_ENV`, third `SC_LEN` byte) and the
vibrato pitch envelopes (`SC_VIBRATO`). A step is `time<<4 | value` (volume, or a signed pitch offset 0-7 / 8-F).
`ENV_LOOP` ($FB) marks the loop start, `ENV_REPEAT, n` goes back n times (`ENV_FOREVER` = always), `ENV_HOLD`
($FF) keeps the last value. Code: `EnvelopeNext`, `VibratoNext`, `EnvelopeControl`.

## rom.txt directives

```
soundptrs 00:8D3C 45 sfx        SFX pointer table: 45 words, each -> header byte
soundptrs 00:9541 9 env         envelope pointer table
soundptrs 00:8D96 25 songs      25 songs x 4 channel words
sound 00:909E-00:9FFF           ranges that hold stream data (forced data)
sound 01:A000-01:BFFB
sound CF40-CFFF
```

The generator walks every stream from these tables, following `SC_CALL` and `SC_GOTO` targets (they become
`.word` label references). It stops with an error on an unknown byte, a token outside the `sound` ranges, two
streams that disagree about a byte, or a jump target that is not a token start. Bytes no stream reaches stay plain
data (only `DpcmSamples` in these ranges).

## Channel flags and sound ids by caller

`sndChanFlags` ($EA + channel, bank 00 only; the byte is a scratch variable elsewhere) holds `SNDF_*` bits: $01 `SNDF_SFX`
(effect stream format), $02 `SNDF_REST`, $04 `SNDF_LOOP1` and $08 `SNDF_LOOP2` (a `SC_LOOP` / `SC_LOOP2` is open),
$10 `SNDF_CALL` (inside `SC_CALL`), $40 `SNDF_SLIDE` (slide block open), $80 `SNDF_FADE_IN` (set by `ResetEnvTimersScaled`, cleared when the fade-in reaches the base volume). A Mesen run saw $01, $02, $04, $10, $40 and $80 on the channels; $08 never occurred.

Many game sounds are named after the routine that plays them (`SND_*` / `MUS_*` / `SND_VOICE_*` in const.txt, marked `(?)`
when only the caller is known). A Mesen trace of `PlaySound` (F694) over two 16 000-frame bot runs confirmed these callers:
$0A `BallIdle`, $0B `RaphSpecialAnimWait`, $12 `HitReactionFlagged` (the hit-type table plays $0D-$13, $1F, $21),
$20 `Slot7Appear`, $2A `KoWaitOpponent`, $54 `RaphSpecialAnimWait`, $39 the game over music, $3A-$3C the intro songs.
Forced-character runs (`fighterChar` held at the round start: Casey/Hothead, Shredder/Don, Hothead/Shredder) added $0C `HurtRainLand`, $16 `SpawnSpecialAtkSnd`, $1B Hothead fire, $1D Shredder wave start, $1E `State0BRun`, $56 `CaseyRainWait`, $57 `ShredderBoltsAnim` and $58 `ShredderWave`. A Story run (frame 20573, `IntroBannerDraw`) played $14 and a tournament run (frame 5883, the name entry, `NameEntryLetterCursor`) played $26.

## Checked

- The build is byte-identical with every stream decoded; the relocation test moves all `SC_CALL` / `SC_GOTO`
  targets.
- Mesen (30 000 frames of the bot, `tmp/snd2`, a hook on every `LDA (sndStream),Y` of the driver): 10 783 stream reads,
  all inside decoded tokens; every read by the two stream parsers (`ReadMusic`, `ReadSfx`) lands on a token start
  (0 mid-token, 0 outside). 4 957 distinct bytes (3 568 token starts) were reached; the rest of the songs was not played.

## Music ids seen in Mesen

Each id below was caught at the entry of `PlaySound` (headless run, RAM poked to enter the screen; the caller is the
return address on the stack): `$38` `MUS_SCORES` (ranking screen, gameMode `$0C`; the continue and name entry screens
load the same id in the code), `$3D` `MUS_BONUS_CARD` (`FightBonusCardWait`), `$41` `MUS_ENDING` (`EndingSetup`),
`$42` `MUS_CREDITS` (`EndingCreditsSetup`, only when `difficulty` >= 2), `$43` `MUS_REMATCH` (`RematchPrompt`),
`$45` `MUS_CHALLENGER` (`FightChallengerCardB`). Reaching a screen by poking is not the same as playing the game to
it: the ids and callers are real, the natural trigger conditions were read from the code.

## Not checked

- `SC_DUTY` and `SC_FADE` are read from the code only (no listening test); `SC_FLAGS` and `SC_VIBRATO` are decoded from the code (field layout), the effect of the echo and `SC_SLIDE` are still `(?)`.
- The drum and DPCM sample names (`DRUM_S47`..) are by id, nobody listened to them.
