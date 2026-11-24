# Fighter data

What is decoded so far: how fighters (and all other objects) are drawn, the metasprite format, the frame tables of
each sprite set with their CHR banks, per-character tables, the animations, the normal moves (selection, scripts,
attack objects), the collision boxes and the special moves (commands, routines, attack objects). The CPU AI is in
[ai.md](ai.md).

## Drawing objects

`DrawObjects` (D71F, run as `FarDrawObjects` with pair 04 mapped) goes over the 16 object slots. A slot is drawn
when `objFrame` != 0 and `objXHi` = 0. `objFrame` picks one of two frame sources:

| `objFrame` | frame table | pair mapped |
|---|---|---|
| `$01-$7F` | `MetaspritePtrs` (08:8235): shared objects (projectiles, effects, menu sprites ...); entry = id − 1 | 08 (pushed by DrawObjects) |
| `$80-$FF` | the sprite set of the fighter: `SpriteSetPtrs` (D87E)[`objSpriteSet`] → `Frames*` table, entry = id & `$7F` | 04/05 |

For a `$80+` frame the sprite set is taken from fighter slot (X & 1): slot 0 = P1, slot 1 = P2. Slot 6 uses the
fighter number stored in `objState+6`. P2's tiles get `$80` ORed in (`tmp12`), so P1 uses sprite tiles
`$00-$7F` and P2 uses `$80-$FF`. Each player's half of the sprite pattern table has its own CHR banks (below).

`DrawMetasprite` (D7A3) writes the sprites of one frame, at `oamCycle`, stepping `$1C` bytes in OAM for each sprite
(the order rotates every frame against flicker). All objects together get at most 64 sprites per frame
(`ptr_0A` = `$3F`); unused OAM entries are hidden (Y = `$F4`).

## Metasprite format (`metasprites` lines in rom.txt)

```
  .byte 9                         ; number of sprites (bit 7 ignored)
  .lobytes -62, $41, 0, -4        ; Y offset, tile, OAM attributes, X offset (offsets signed)
  ...
  .byte MSPR_JUMP                 ; $80 in place of a Y offset: the rest of the frame is at
  .word dat_05_BBB9               ;   this address (frames share their tails)
```

- Sprites are 8×16 (`PPUCTRL` bit 5). The tiles used by fighter frames are odd, so they come from pattern table
  `$1000`.
- Position: object Y + Y offset, object X + X offset. When the sum leaves the screen (carry), the sprite gets Y =
  `$F4` (hidden). For fighter slots on the floor (`objY` >= `FLOOR_Y`), `shakeOffsetX` (the screen shake) is added to Y.
- `objFlip` bits 7/6 are XORed into the attributes. With horizontal flip the X offset becomes −X − 10; with vertical
  flip the Y offset becomes −Y − 18.
- If `objAttr` bit 7 is set, the attribute byte is (frame attributes & `$FC`) | (`objAttr` & `$23`). The object
  then picks the palette (and the priority bit) itself.

The generator writes attributes as `OAM_FLIP_V|OAM_FLIP_H|palette`. `tools/frames_png.py` draws every fighter frame
from the ROM into `gfx/frames_<set>.png`, so the decoding can be checked against the graphics.

## Sprite sets and CHR banks

| `objSpriteSet` | frames (pair 04/05) | count | CHR per frame (bank 03) |
|---|---|---|---|
| `CHAR_LEO` .. `CHAR_DON` | `FramesTurtles` 04:8001 | 102 | `FrameChrTurtles` 03:B17B |
| `CHAR_CASEY` | `FramesCasey` 04:8E13 | 89 | `FrameChrCasey` 03:B1E1 |
| `CHAR_HOTHEAD` | `FramesHothead` 04:9B52 (frames run on into bank 05) | 69 | `FrameChrHothead` 03:B23A |
| `CHAR_SHREDDER` | `FramesShredder` 05:AEC5 | 75 | `FrameChrShredder` 03:B27F |

The four turtles share one frame table and one CHR table. In the drawings they are identical, so they differ only
in palette (`CharFightPalette`: `$2D`-`$30` by character, applied by `SetFightPalettes`).

`SetFighterChrBanks` (03:B142) runs for both fighters that show a `$80+` frame. It reads the frame's byte in
`FrameChr*` and uses it as an index into `ChrBankPairs` (03:B2CA, two bytes per entry). The two bytes are the 1 KB
CHR banks for tiles `$00-$3F` and `$40-$7F`: `chrBanks+2/+3` (MMC3 R2/R3) for P1 and `chrBanks+4/+5` (R4/R5) for P2.
The second bank holds the shared tiles of a character (`$00` turtles, `$14`, `$28`, `$3C` for the others); the
first one changes with the pose.

`FramesUnused` (05:BB9E) is a 13-frame table in the same format that nothing references. Its frames are rows of
8x16 sprites (tiles `$C2-$FE`, 6-8 in a row, 8 pixels apart; frames share rows and tails through `MSPR_JUMP`) plus a small symmetric figure of 8 sprites (tiles `$67-$6F`); purpose unknown.

## Per-character tables

Indexed by `objSpriteSet` / `fighterChar` (`CHAR_*` order: Leo, Raph, Mike, Don, Casey, Hothead, Shredder).

| table | values | use |
|---|---|---|
| `CharVoices` (E15E) | `$53` ×4, `$55`, `$59`, `$52` | DPCM voice: played at the player select confirm and in `StateWin` |
| `CharKoVoices` (02:99D2) | `$4D` ×4, `$4E`, `$50`, `$4F` | DPCM sample ids (`SND_SAMPLE` range) played by `KoVoice` when `objCounter` runs out in `PhaseKo` |
| `CharJumpVelY` (02:9729) | `$F93F` `$F8E8` `$F86F` `$FA42` `$F75A` `$FA99` `$F9EC` | starting `objVelY:objVelYFrac` of a jump (8.8, up is negative); ×1.25 when `gameSpeed` > 0 |
| `CharGravity` (02:9737) | 0, 0, 6, −21, 24, −28, −13 | added (low byte) to `GRAVITY` (`$50`) = the `objVelYFrac` step per frame (`AddVelYFrac`); ×1.5 when `gameSpeed` > 0 |
| `CharLandingTime` (02:9990) | 5, 4, 4, 6, 2, 8, 6 | `objTimer` after landing from a jump |
| `SelectCursorX` / `Y` (06:8350/8357) | | player select: cursor position for each character |
| `SelectMarkX` / `Y` (06:8349/8342) | | player select: the mark object (slot X+2, frame `$1B` + character) at the cursor + (4, 9) |

`StateCharMove` (02:8753, `FST_CHARMOVE`) jumps to each character's own move routine. `AiReact` / `AiDecide` in
bank 0A are the CPU AI's tables by character ([ai.md](ai.md)); the one at 02:9A06 is `ReadSpecialInput`'s.

## Animations

`RunAnim` (DF4F) plays animation Y on object X; it is called once per frame. An animation is a list of
`(objFrame, frames)` byte pairs in `AnimData` (E000-E0FF); `AnimOffsets` (DFE6) gives the offset of each
animation's first pair (it is written in the source as `AnimWinLeo-AnimData` ...). The data holds no length:

- `StartAnim` (DF38) sets `objAnimIndex` = A (the number of pairs) and `objAnimTimer` = 0. The lengths come from
  `CharIdleAnimLen` (DF48), `CharWinAnimLen` (E100), `CharLoseAnimLen` (E107) or from an immediate in the caller.
- Every call counts `objAnimTimer` down. When it goes below 0 and `objAnimIndex` > 0, the index goes down by one
  and the pair at that index is loaded. So **the pairs play from the last one in ROM to the first**, and the
  first pair (index 0) stays on screen when the animation has run out.
- A pair with frame 0 plays the sound id in its second byte and moves on to the next pair at once.
- With `gameSpeed` > 0 the frame time is cut to t − t/2, but only for animation ids below 4 or from `$0B` up (not
  for the win animations).

| id | label | used for |
|---|---|---|
| `$00`-`$03` | `AnimData`, `Anim01`-`Anim03` | `$00` is also `AnimData`; `$01` the held pose and the pose after a ball hit; `$02`/`$03` the Raph special hit (`RaphSpecialHit`) |
| `ANIM_WIN` + `CHAR_*` (`$04`-`$0A`) | `AnimWinLeo` .. `AnimWinShredder` | win pose, `StartWinAnim` (DFA9) + `StateWin`; Mike and Don share one |
| `$0B`-`$0D`, `$12` | `Anim0B`-`Anim0D`, `Anim12` | Don and Hothead special moves, Casey, the ending (0C:9745) |
| `$0E`-`$11` | `AnimIdleTurtles` .. `AnimIdleShredder` | stand loop, `RunIdleAnim` (DF23) via `CharIdleAnim` (DF41) |
| `ANIM_LOSE` + `CHAR_*` (`$13`-`$19`) | `AnimLoseTurtles` .. `AnimLoseShredder` | the other fighter at the round end, `StartLoseAnim` / `RunLoseAnim` (E72A); the turtles share one |

`SetFighterPose` (02:8AE7) shows a single fixed pose instead: `objFrame` = `CharPoses`[pose × 7 + character]
(02:98E8).

## Moves

### Picking the move

`StartAttack` (02:8221) runs when A or B is pressed. It builds an index group + character into `MoveSelA`
(02:93B2, A button) or `MoveSelB` (02:9388, B button); each holds 6 groups of 7 move ids (`CHAR_*` order):

| group | index | when |
|---|---|---|
| close | `$00` + char | on the floor, `fighterGap` <= `CharCloseRangeA` / `B` (02:937A / 02:9381) |
| far | `$07` + char | on the floor, farther away |
| jump | `$0E` + char | `FST_JUMP` |
| crouch | `$15` + char | `FST_CROUCH` |
| anti-air | `$1C` + char | on the floor and the opponent is above Y = `$A6` |
| dash | `$23` + char | turtles only: `dashStage` = 2 (forward tapped twice) and facing the held direction |

`PickCloseFar` (02:8AC1) makes the close / far / anti-air choice. Two moves are picked in code: `Move20` (Hothead,
B in a jump with down held) and `Move25` (Shredder, B when both fighters are on the floor and `fighterGap` >=
`$16`). Down + a button on the floor first checks `NearBall` (03:B11A): when the fighter touches the ball object (`NearBall` carry clear) `StartAttackAir` runs: `FST_SHOT` (crouch pose, then `ShotThrowBall`), in the air `ShotThrowBall` at once. The four turtles share move
ids `$00`-`$0D` (Leo has his own A crouch move `$09`, Raph/Don their own A far move `$08`); Casey has `$0E`-`$16`,
Hothead `$18`-`$22`, Shredder `$23`-`$2D`. The labels `Move00`..`Move2D` in rom.txt say which button and group use
each one.

### Move scripts (`movescripts` line in rom.txt)

`fighterMoveId` indexes `MovePtrs` (02:9401, 46 words). The scripts (02:945D-02:9692) are read by
`ReadMoveScript` (02:8BC5) in order, from `fighterMoveStep` 0:

```
Move00:
  .byte MOVE_SOUND, $06           ; $FE: play sound $06, go on
  .byte $8D, 6                    ; objFrame $8D for 6 frames (fighterMoveTimer)
  .byte $8F, 1
  .byte MOVE_HIT, $01             ; $FF: start attack object $01 in slot fighter+2, go on
  .byte $8F, 20
  .byte $8D, 6
  .byte MOVE_END                  ; $00: the attack is over (fighterAttacking = 0), face the opponent
```

With `gameSpeed` > 0 each time is cut to t − t/4. `RunMove` (02:8B01) also moves the fighter during some moves
(Leo's `$09`, `$0A`/`$0D`, Raph's `$00`/`$08`). `tools/frames_png.py` draws every script as a row of frames into
`gfx/moves.png` (and the animations, in play order, into `gfx/anims.png`).

### Attack objects

`MOVE_HIT` writes the attack id into `objSpriteSet` of object slot fighter + 2 (slots 2 and 3), with `objState` =
the owner. The attack object has no picture; it is a hit box. `StartAttackObj` (03:A2F8) sets it up from tables in
bank 03 indexed by the attack id (`$01`-`$2E` for normal moves; projectiles and special moves use higher ids):

| table | meaning |
|---|---|
| `AttackOffsetX1` (03:A6DF, id 1 first) | X offset from the owner, mirrored when the owner faces left |
| `AttackOffsetY` (03:A70D) | Y offset from the owner (signed) |
| `AttackTime` (03:A73C) | frames the object stays (`objTimer`, adjusted for `gameSpeed` by `ScaleTime`) |
| `AttackBox` (03:A76B) | `objBox` |
| `AttackPower` (03:A7A4) | `objPower`, the damage |
| `TurtlePowerAdd` (03:A82D) | added for turtle attacks `$01`-`$0E`: Leo +0, Raph +1, Mike +0, Don −2 |

On a hit the attacker's `objPower` ends up in `ptr_08`; `HitReaction` (03:AC24) scales it with `ScaleDamage` (DE3C: the victim's
level and `DamageBaseByChar`) and adds it to `pendingDamage`, which `UpdateFighters` takes off `fighterHp` at 1 per frame
(Mesen: a throw adds `$25`, `fighterHp` `$B0` -> `$8B`). Only the bonus game subtracts `objPower` from the dummy's HP directly
(`AttackObjHitCheck`, 03:BD0A).

Every frame `UpdateAttackObjs` (03:A23F) runs slots 2-5 of the fighter: `AttackPhasePtrs` (03:A282) gives, by
attack id, a list of routines, and `objPhase` picks one. Normal attacks use `AtkPhasesStd` (`StartAttackObj`, then
`AtkStayByOwner`); a few anti-air moves and all special-move objects have their own lists. The same loop copies
`AttackPriority`[id] (03:A7E1) into `fighterHp` of the slot: when two attack objects touch, the higher priority wins
(equal: the older one); projectiles have `$10`.

### Collision boxes

Every object that can hit or be hit has a box id in `objBox` (`$0570`). A box is centred on `objX` with half width
`BoxHalfWidth`[id] (03:AD4C), and its centre is `BoxHalfHeight`[id] (03:AD6E) above `objY`. `CheckHits` (03:A99D)
tests two boxes for overlap on both axes. A fighter's box comes from `SetFighterBox` (03:AF50): first the
`(objFrame, box)` list of the character in `FrameBoxes` (03:AF86, offset `CharFrameBoxOffs`), else `CharBox`
(03:AFAE: stand, crouch). `UpdateFighterGap` (F775) keeps `fighterGap` = distance − both half widths; it chooses
close or far moves and throws.

## Special moves

### Commands

`ReadSpecialInput` (02:99D9) runs every frame for each fighter. It builds `ptr_08` = the "forward" d-pad bit (right,
or left when the fighter faces left) and `ptr_09` = the d-pad held, runs the ball command (`ReadBallInput`), then
the character's command routine (jump table by `objSpriteSet`). A command is a chain of stages (`specialStage`); each
stage has `$14` frames (`specialTimer`) and collects directions and the button in `specialBits`. A second chain
(`special2Stage` / `special2Timer` / `special2Bits`) runs at the same time for the characters with two specials.
Charge commands need the direction held for `chargeTime` frames (`CharChargeTime` E999: Raph `$1C`, Mike `$1E`, Don
`$28`, Casey `$1E`, set at the round start through `ScaleTime`). On success `StartSpecial0` / `StartSpecial1` put 0
or 1 into `objJumpVelX` and switch the fighter to `FST_CHAR_MOVE` (only from a normal state, not while hurt).

Verified in Mesen (P1 facing right, each command entered twice, the fighter reached `FST_CHAR_MOVE` with the
expected `objJumpVelX`):

| character | command | what it does |
|---|---|---|
| Leo | down, down-back, back + A | spins forward with the sword (`LeoSpecial`, attack `$31`) |
| Raph | hold back `$1C` frames, forward + B | rolls forward, longer after a longer charge (`RaphSpecial`, `$32`) |
| Mike | hold down-back `$1E`, forward + A or B | flying kick, A and B fly at different heights (`MikeSpecial`, `$33` / `$34`) |
| Don | hold down `$28`, release, up + A | jumps up spinning (`DonSpecial`, `$35`, `$38`) |
| Casey | hold down `$1E`, release, up + B | rising jump kick (`CaseyJumpKick`, `$37`) |
| Casey | forward, down, back + B | jumps up; things come down on the opponent (`CaseyRain`, `$39`) |
| Hothead | down, down-forward, forward + A | breathes fire along the floor (`HotheadSpecial`, `$2F`) |
| Shredder | forward, down-forward, down + B | a wave runs along the floor (`ShredderWave`, `$30`) |
| Shredder | B tapped 4 times, each within 16 frames | bolts hit in front of him (`ShredderBolts`, `$36`) |

The pictures were checked on screenshots taken every 6 frames after each command. The release frame of a charge
command only moves the command to the next stage, so the button must come at least one frame later.

When a fighter holds the ball (`fighterHasBall` bit 7, set after `NearBall` 03:B11A) `ReadBallInput` (02:9D1F)
looks for down, then forward + B (Mike: A or B) and starts `FST_SPECIAL` (?: read from the code only).

### Special-move routines

`StateCharMove` (02:8753) jumps by character to `LeoSpecial` (03:B35C), `RaphSpecial` (03:B4A8), `MikeSpecial`
(03:B5A5), `DonSpecial` (03:B678), `CaseySpecial` (02:8772), `HotheadSpecial` (03:B8DA) and `ShredderSpecial`
(02:8767); Casey and Shredder choose by `objJumpVelX`. Each routine is a list of steps (`objStep`) that sets the
frames and the velocity itself, without a move script. The hit box is an attack object started with
`SpawnSpecialAtk` (03:B3CC, A = attack id) in slot 4 + side, so it can live next to a normal attack in slot 2 +
side. Its phase list in `AttackPhasePtrs` usually starts with `StartSpecialAtk` (03:A475: offset from the owner,
`objTimer` `$80`, box and power) and then keeps the object on the owner while the owner is in `FST_CHAR_MOVE`
(`AtkFollowSpecial`, the object blinks). The projectiles (`$2F` fire, `$30` wave) move on their own; when a `$2F`
or `$30` meets one of the other side they both disappear.

| attack | constant | phase list |
|---|---|---|
| `$2F` | `ATK_HOTHEAD_FIRE` | `AtkPhasesHotheadFire`: the flame grows (`HotheadFireFrames`, `HotheadFireBoxes`) and runs |
| `$30` | `ATK_SHREDDER_WAVE` | `AtkPhasesShredderWave` |
| `$31` | `ATK_LEO_SPIN` | `AtkPhasesLeo` |
| `$32` | `ATK_RAPH_ROLL` | `AtkPhasesRaph` |
| `$33`, `$34` | `ATK_MIKE_KICK_A`, `ATK_MIKE_KICK_B` | `AtkPhasesMikeA`, `AtkPhasesMikeB` (`MikeKickAtk`, `MikeKickVelY`) |
| `$35`, `$38` | `ATK_DON`, `ATK_DON_2` | `AtkPhasesDon`, `AtkPhasesDon2` |
| `$36` | `ATK_SHREDDER_BOLT` | `AtkPhasesShredderBolt`: hits again every 4 frames at the next `ShredderBoltY` |
| `$37` | `ATK_CASEY_KICK` | `AtkPhasesCasey` |
| `$39` | `ATK_CASEY_RAIN` | `AtkPhasesCaseyRain` |

## Hold (grab) animation

`FST_HOLD` runs `StepHoldAnim` 02:90A4 each step. `HoldAnimStart` 02:9745 gives, per character, the byte offset of its
first entry in `HoldAnim` 02:974C (Leo and Don share offset 0; Raph $48, Mike $24, Casey $68, then $90 and $B2).
Entries are 4 bytes, `objAnimIndex` * 4 further on (read from the code end to end, not run in the emulator):

| byte | meaning |
|---|---|
| 0 | `objFrame` of the held fighter; 0 = no frame, only the sound in byte 1 (`HoldAnimSound`), then the next entry |
| 1 | bits 0-4: time (`objTimer`; with `gameSpeed` non-zero it is cut by a quarter, minimum 1), bit 7 ($80): kept in `objTimer` (a long hold), bit 5 ($20): `shakeTimer` = `SHAKE_FRAMES`, bit 6 ($40): the throw (score, `SND_THROW`, the victim goes to `HOLD_STATE_RUN_OBJ_STEP`; Casey sets its Y to `FLOOR_Y`). For frame 0 this byte is the sound id |
| 2 | X offset of the held fighter, mirrored by `objFlip` |
| 3 | Y offset added to the holder's `objY` |

Raph (`CHAR_RAPH`) also drains the victim while holding: every `STEP_HOLD_ANIM_HURT_TIMER` frames `SND_HOLD_HIT` and scaled damage 7 (`AddPendingDamage`; a lethal hit ends in `HoldThrowSound`). `objHurtPower` is a struggle counter: -1 per frame, -3 when the held player pressed a button; when it runs out the hold ends in the throw (`HoldThrowSound`).

## Hurt reactions

`StateHurt` 02:8C18 (`FST_HURT`) jumps by `objHitType` ($04C0) to one of nine handlers. The hit code in bank 03
(`SetHurtState`, 03:ABF8) stores the kind just before it sets `FST_HURT`:

| kind | handler | set when |
|---|---|---|
| 0 `HIT_STAND` | `HurtStand` 8C40 | normal hit |
| 1 `HIT_AIR` | `HurtAir` 8C72 | hit in the air (also set when a ball hit ends, 02:87D6) |
| 2 `HIT_CROUCH` | `HurtCrouch` 8CD9 | victim in `FST_CROUCH` or `FST_SHOT` (crouch pose): `HitTypeByState` 03:AD38 gives it for states 2 and 7; Mesen: `HurtCrouch` ran 24 times in 20 000 frames (fighters with 0520 = 3, `objHitType` = 2) |
| 3 `HIT_BLOCK` | `HurtBlock` 8CE3 | blocked hit (03:AB3B) |
| 4 `HIT_FIRE` | `HurtFire` 8D0E | Hothead fire (03:ABB8; Mesen: Casey hit by Hothead's fire, `objHitType` = 4, frame 8714) |
| 5 `HIT_KNOCKDOWN` | `HurtKnockdown` 8D45 | knockdown (03:ABCC) |
| 6 `HIT_BLOCK_SPECIAL` | `HurtBlockSpecial` 8E22 | blocked special attack (03:AB54) |
| 7 `HIT_BALL` | `HurtBall` 8E38 | hit by the ball (03:ABB3); `02:8056` tests it |
| 8 `HIT_RAIN` | `HurtRain` 8ECA | Casey rain (03:ABD0; Mesen: Hothead hit by Casey's rain, `objHitType` = 8, frame 6249) |

Checked in Mesen (34 hit samples, then a 20 000-frame run): all nine kinds occurred (kinds 4 and 8 in runs with Casey and Hothead forced through `fighterChar`). `objHitType` is also a temp in attack objects and `bgmTestNum` on the option screen
(no `@var` binding; the `use` lines in const.txt name each site).

### Inside the handlers

Read from the code (not stepped in Mesen except where the table above says so). Common frame: `StateHurt` calls
`ResetFighterForHurt` when `objStep` = 0 (clears attacks, specials, `objAnimIndex`; faces the opponent; sets
`OBJST_BUSY`; `objHurtTimer` = $10; `objVelY` = 0); the handler then runs with Y = `objStep`, so `BNE` on the entry
means "step 0 first, later steps elsewhere". Poses are `SetFighterPose` ids (Y), sideways knock-back is
`SetVelXBackward` (A = speed byte: low nibble whole part, high nibble fraction; bit 7 = move on the spot).

| handler | step 0 | later steps |
|---|---|---|
| `HurtStand` | `objHurtTimer` = $0B when `objHurtPower` < $10 (a weak hit), `objHitDelay` = $14, step 1 | `HurtRecoverPose`: pose $0F, `objHurtTimer` counts down, pushed back at speed $C0 (>= 8 left) then $30; at 0 `HurtLandingFace` |
| `HurtAir` | `HurtAirFall`: `HurtLandingSetup` (drops the ball), `objVelY` = `HurtAirFallVelY`[`objY` >> 6] ($FD / $FB), `objAnimIndex` = 3, `objHitDelay` = $14, step 1 | `HurtAirLand` step 1: `LandOnFloor`; in the air pose $0F (rising), $09 (falling < 2), $06 (falling fast; Casey and Shredder keep the previous pose, the turtles run `RunAnim` 0); on the floor `objTimer` = 8, crouch pose, step 2; step 2 counts `objTimer`, then `HurtEndToStand` |
| `HurtCrouch` | as `HurtStand` | as `HurtStand` but pose 4 (crouch hit) |
| `HurtBlock` | `objHurtTimer` = $0C, step 1 | `HurtBlockBlink`: every 4th frame X moves one pixel back and forth (bit 2 of the timer), pose 7, or 8 when Down is held; `HurtRecoverFrame` counts the timer down |
| `HurtBlockSpecial` | as `HurtBlock` | the same, but Y jitters by +-1 with `frameCounter` bit 1 |
| `HurtFire` | `HurtLandingSetup`, step 1, `objTimer` = $3C, palette entry $23 for 60 frames | `PaletteEntryBlink`: palette entry $23 / $24 by `frameCounter` bit 0 (the burning flash), pose $0F, `LandOnFloor`; at 0 `HurtLandingFace` -> `HurtPaletteThenStand` restores the stage palette |
| `HurtKnockdown` | `HurtBallRun`: `objParam` = 2, then `HurtAirFall` | step 1 `HurtBallFirstFrame`: speed from `HurtBallSpeedA`[`objParam`], pose by `objVelY` and `objY` ($0F rising, $15 low, $09 / $06 falling); on landing the turtles step 2 (`objTimer` = $1C), Casey / Hothead / Shredder bounce (`objParam` - 1, `HurtJumpVelocity`, `objHurtTimer` = 8) until `objParam` < 0 -> `HurtBallGetUp` |
| `HurtBall` | sprite set > 3, or the ball was thrown by Casey: as `HurtKnockdown` with `objVelY` = $FE (`HOP_VEL_Y` $FB when the thrower is Casey); otherwise (a turtle hit by a turtle ball) a short slide: step 0 `objTimer` = $2C, step 1 slides back (speed 2, 1 when `objTimer` < $10) with `AnimCycle` 20, then frame $A6 for $10 frames, step 3 counts, then `objAnimIndex` = 5 | `HurtBallStage2`: `objTimer` counts, `objY` = `FLOOR_Y`, slide speed 2 then $21; `HurtBallGetUp` plays the get-up (`objAnimIndex` 6, `HurtBallPose` poses $00 $00 $09 $09 $0A $0A) and ends in `HurtLandingFace` |
| `HurtRain` | `objAnimIndex` = 0, step 1, `objTimer` = `ScaleTime`(5) | `HurtRainLand`: `LandOnFloor` + idle animation; while Casey's rain object (`ATK_CASEY_RAIN`) lasts, `objTimer` counts and at 0 deals `ScaleDamage`(4) (`AddDamageOrKo`, `SND_LAND`) and walks the victim one pixel towards Casey's X; when the rain ends the victim goes to `FST_KNOCKDOWN` step 4, `objTimer` = $30 |

Checked in Mesen (six random-bot runs, 16 000 frames each, fighters forced through `fighterChar`, execution traced in bank 02):
- `HurtBall`, victim a turtle and the ball thrown by another turtle (Leo vs Raph) or by Hothead (Don vs Hothead): always the slide branch
  (`objStep` 0, 1, 2, 3 all run; 117 and 280 frames). Victim Casey hit by Leo's ball, and Mike hit by Casey's ball (35 and 125 frames): always the
  flying branch (`HurtBallRun`, then step 1 through `HurtBallSpeedB`[`objParam`], seen with `objParam` = 2 only: `$23`).
  A Hothead or Shredder victim of a ball did not occur; it takes the same branch as Casey (the test is only `objSpriteSet` > 3).
- `HurtKnockdown`: turtles land once (`objStep` 2, `objTimer` = $1C), then `HurtBallGetUp`. Casey, Hothead and Shredder bounce three times per
  knockdown: `objParam` 2, 1, 0 (each landing runs `HurtJumpVelocity`; with `objParam` 0 and 1 the speed byte of `HurtBallSpeedA` is not used,
  only `objParam` 2 reaches `SetVelXBackward`), the fourth landing (`objParam` < 0) starts the get-up. The counts matched exactly (45 landings for 15 get-ups, 57 for 19).

Exits: `HurtLandingFace` (faces the opponent, Y = `FLOOR_Y`, clamps X, clears `OBJST_BUSY` / `OBJST_SPECIAL`, velocities and
`objTimer`) ends a hit: fire goes through `HurtPaletteThenStand`, crouch hits go back to `FST_CROUCH` step 1 (so a
crouching fighter stays crouched), everything else to `HurtEndToStand` (`objHitDelay` = 4, 2 at `gameSpeed` > 0, then `ReturnToStand`).
`objHitDelay` blocks a new hit while it counts down (see `CheckHits`).

### Hold tables (02:9818-98D2)

`HeldFighterCheck` (02:919A) runs for the holder (`FST_HOLD`, slot X) every frame and sets the frame and the flip of the held fighter
(slot Y = `otherFighter`). Both are looked up by the holder's `objAnimIndex` (the throw / squeeze animation step); the row
depends on the holder's and the held fighter's character (`objSpriteSet`, `CHAR_*`):

```
row   = HoldFrameRow[ HoldFrameRowStart[holder] + held ]          ; offset into HoldFrames
frame = HoldFrames[ row + holder objAnimIndex ]                    ; objFrame of the held fighter
flip  = objFlip(held) EOR HoldFlip[ HoldFlipStart[holder] + objAnimIndex ]   ; $40 = mirrored (after FaceOpponent)
```

`HoldFrameRowStart` = 0, 14, 0, 0, 7, 0, 21 for Leo, Raph, Mike, Don, Casey, Hothead, Shredder, so the three turtles Leo, Mike and Don
and Hothead share one 7-entry block of `HoldFrameRow`. Each block has one entry per held character; the four turtles share a row:

| holder block | held turtle | held Casey | held Hothead | held Shredder |
|---|---|---|---|---|
| Leo / Mike / Don / Hothead (block 0), 8 steps | 0: `A2`x5 `A7`x3 | 8: `A4`x5 `A9`x3 | 16: `9F`x5 `A3`x3 | 24: `A4`x5 `A8`x3 |
| Casey (block 7), 6 steps | 32 | 38 | 44 | 50 |
| Raph (block 14), 8 steps (the Hothead row has a 9th byte that is never read) | 56: `A2 D1` x4 (frame alternates) | 64: `A3 8E` x4 | 72: `9B` x9 (one frame) | 81: `A9 A2` x4 |
| Shredder (block 21), 6 steps | 89 | 95 | 101 | 107 |

The frame ids are the held fighter's `objFrame` ($9F-$A9 are its hit-reaction poses; $9B, $8E and $D1 occur only in Raph's squeeze).
Checked in Mesen (six random-bot runs, 16 000 frames each, `HeldFighterCheck` traced at 02:91C2 and 02:91F3): in all 1 888 hold frames the
frame loaded from `HoldFrames` and the `HoldFlip` index equal the model above (nine holder / held pairs: Leo-Casey, Raph-Hothead, Mike-Shredder,
Don-Hothead, Casey-Leo, Casey-Shredder, Hothead-Raph, Hothead-Don, Shredder-Casey). The holder's `objAnimIndex` went 0-7 for Raph and 1, 3-7 for
Leo, Mike and Don, up to 5 for Casey and Hothead's rows, and up to 4 for Shredder, so the six-byte rows of Casey and Shredder are never overrun.
The four turtles are held with the same frames, so their entries in `HoldFrameRow` point to one row.
`HoldFlipStart` = 0, 9, 1, 0, 19, 11, 26 gives the holder's row in `HoldFlip` (rows overlap and are compressed: Leo and Don use row 0, Mike row 1);
the flip values are 0 or $40. While Casey holds, from `objAnimIndex` 5 on, `HoldCaseyYOfs`[held character] is added to the held fighter's `objY`.
Other per-holder tables read by the held-fighter code: `HeldFallVelX`, `HeldPoseVelY`, `HeldFallTime`, `KnockdownTimer` (7 entries each, by character).

## Not decoded yet

- The ranges 93DC and 96D8 (move-select and frame data, not hurt tables).
- The step-by-step details of each special-move routine (velocities, frame lists) beyond the names above.
  (`hitFlags` ($061E): bit 7 = a hit or block connected, value 1 = this fighter won the trade; `RaphSpecialHit` reads the other fighter's flags.)
- Not checked in the emulator: the KO voice, the gravity numbers in play, the player-select mark objects, the
  damage numbers in play, the ball command. The move and animation decoding was checked by drawing the frames
  (`gfx/moves.png`, `gfx/anims.png`): every frame id is inside its character's sprite set and the rows read as complete motions.
