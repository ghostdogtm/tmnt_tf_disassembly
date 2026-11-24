# CPU AI

The CPU fighter plays by writing its own pad bits into `joyHeld,X` / `joyPressed,X` (X = fighter slot 0/1), so the
fighter code cannot tell it from a player. The AI code is in bank 0A (`$8000-$9FFF`, the last reactions run on into 0B:A000-0B:A18C) and in helpers in the fixed bank
(`EC5B-EF60`). Names below are those in `tools/labels/*.txt`; the conditions and trees were read from the code, most were not run in Mesen (see "Not run in Mesen" below).

## Frame loop

`FarRunCpuAi` (F70B) maps pair 0A/0B and calls `RunCpuAi` (0A:8001) once a frame in fights. It runs
`RunFighterAi` for each CPU-controlled fighter (by `gameType`; in tournaments by the table at `$0154`). That clears
the pad and runs the `aiMode` step:

| `aiMode` | routine | |
|---|---|---|
| `AI_MODE_INIT` 0 | `AiInit` | clear the AI state, `aiTarget` = the other fighter, `aiRanges` from the character |
| `AI_MODE_CHOOSE` 1 | `AiChooseAction` | `AiGatherContext`, then `AiDecide` returns an action id |
| `AI_MODE_RUN` 2 | `AiRunAction` | `AiGatherContext`, `AiStepScript`; when the situation changes, `AiReact` / `AiDecide` may interrupt |

`AiGatherContext` sets what the decisions read:

- `aiRange` ($13): range class of the target, 0 (close) to 3 (far): `fighterGap` against `aiRanges+0..+2`
  (`GetTargetRange`). `aiRanges` is set by `AiInit`: `CharCloseRange[character] - 1`, then 3 bytes of `AiRangeTable`.
- `aiTargetDx`: target X - own X (16 bits, big endian). Its sign gives "forward".
- `aiBallRange` ($12) and `aiBallDx`: the same for the ball (slot 6); 3 = no ball or a far one (`GetBallRange`; Mesen: 5 676 of 6 431 reads are 3).
- `aiShotRange`: range class of the target's flying shot object (`ATK_SHREDDER_WAVE`, `ATK_CASEY_RAIN`), or `$FF`.
- `$10` = `AiHpLead` (1 = we lead by `$30`+ HP, `$FF` = behind, 0 = even), `aiTargetState` ($11) = the target's
  `objState`.

`AiRunAction` hashes `objState`, `aiTargetState`, `aiRange`, the target's `fighterAttacking`, `ballOwner` and
`aiBallRange` into `aiSituation`. When the hash changes and the action is not locked (`aiLocked`), the character's
`AiReact` routine may name an action that replaces the running one at once; otherwise `AiDecide` runs, and its
action is used only if the routine called `AiResetState` (which clears `aiNoInterrupt`). `aiInterrupted` allows one
such interruption until the next reset.

## Decision routines

Both are jump tables by character (`objSpriteSet`, `CHAR_*` order):

| character | `AiDecide` (returns the action in A) | `AiReact` (sets `aiReaction`, `$17`) |
|---|---|---|
| Leo | `AiDecideLeo` 0A:8DEB | `AiReactLeo` 0A:9C11 |
| Raph | `AiDecideRaph` 0A:90BC | `AiReactRaph` 0A:9CF6 |
| Mike | `AiDecideMike` 0A:93BD | `AiReactMike` 0A:9D1C |
| Don | `AiDecideDon` 0A:92A4 | `AiReactDon` 0A:9D64 |
| Casey | `AiDecideCasey` 0A:9597 | `AiReactCasey` 0A:9DAF |
| Hothead | `AiDecideHothead` 0A:985C | `AiReactHothead` 0A:9EE4 |
| Shredder | `AiDecideShredder` 0A:99CA | `AiReactShredder` 0A:9FAF |

They are trees of tests on the context above (range class, target state, ball, HP lead, random numbers) that end in
`LDA #AIA_… : RTS` (`AiDecide`) or `STA aiReaction` (`AiReact`, `$17`; 0 = no reaction). A reaction always wins: it
is stored in `aiLocked` too, so `AiResetState` cannot cancel it until the script ends.

## Decision trees

### Random numbers and difficulty

| routine | value | effect of `difficulty` (0 easy, 1 normal, 2 hard) |
|---|---|---|
| `AiRandomScaled` | `rngSeed >> difficulty` | smaller on hard: tests `AiRandomScaled < n` pass more often |
| `AiRandomScaledInv` | `rngSeed >> (2 - difficulty)` | smaller on easy: tests `AiRandomScaledInv >= n` pass more often on hard |
| `AiRandom4` | top 2 bits of `AiRandomScaledInv` | Y = 0 on easy, 0-1 on normal, 0-3 on hard |
| `AiRandom8` | top 3 bits of `AiRandomScaledInv` | Y = 0-1 on easy, 0-3 on normal, 0-7 on hard |
| `rngSeed AND 3` / `AND 7`, `rngSeed` sign | plain random | no effect |

So the action lists read with `AiRandom4` / `AiRandom8` are ordered by difficulty: easy only uses the first one or
two entries, the dash and special moves at the end of a list are seen on hard only.

### Shape of every `AiDecide*` tree

Most characters start with a jump table on `aiRange` (Leo, Casey and Hothead first try their special move on a hurt
target, Shredder first counters two of the target's moves). The four branches are named `Ai<Char>Close`, `…Near`,
`…Mid`, `…Far`. Inside them the tests come in roughly this order:

1. `AiNoticeShot` carry clear (the target's ball shot flies and the roll in `AiShotChance` passed): `AIA_GUARD_SHOT`
   (`Ai<Char>GuardShot`).
2. The target attacks (`fighterAttacking`) or does a character move (`FST_CHAR_MOVE`): `Ai<Char>Guard`, which picks
   `AIA_BACK_WATCH_B`, or `AIA_GUARD_LOW` against a crouching target. `AiTargetAttacksMe` (the move goes toward us)
   sends some branches to a counter list (`Ai<Char>CounterActs`).
3. The ball: `BallHeldBy` (we hold it, near enough in height: `ObjDeltaY16` + `AbsDeltaBelow`) gives
   `AIA_BALL_SPECIAL_B`; `BallFree` with `aiBallRange` 0-2 gives `AIA_GET_BALL`.
4. The target's state: knocked down (`FST_KNOCKDOWN`, dash attacks: `…KnockdownActs`), jumping (`FST_JUMP`,
   anti-air: `…JumpActs`), crouching (`FST_CROUCH`, low attacks: `…CrouchActs`).
5. A random pick from the range's list (`…CloseActs`, `…NearActs`, `…MidActs`, `…FarActs`).

The far branches mostly go for the ball or dash in (`AIA_DASH_*`); the close branches use the simple attacks and the
character's special.

### Per character

| character | own specials used | notes |
|---|---|---|
| Leo | `AIA_LEO_SPIN` (also first: on a hurt target when `AiRandomScaled < $20`, 1/8 on easy to 1/2 on hard) | `AiLeoRandomAttack` makes a random id `$11-$1D` from `rngSeed`; `AiLeoKnockdownPick` rerolls while the pick repeats `aiLastAction` |
| Raph | `AIA_RAPH_ROLL`, `AIA_WATCH_RAPH_ROLL`, `AIA_HEIGHT_RAPH_ROLL` (after `AIA_DASH_BACK_JUMP`) | `AiRaphFarActs` is 4 bytes but read with `AiRandom8`: on hard entries 4-7 come from `AiRaphMidActs` (harmless, both are lists) |
| Mike | `AIA_MIKE_KICK_A` / `_B`, `AIA_WATCH_MIKE_KICK_A` | close range: while `specialTimer` ≠ `chargeTime` it picks `AIA_MIKE_KICK_A` 3/4 of the time; **bug**: `LDA AiMikeJumpActs` has no `,Y`, so the anti-air pick is always `AIA_B`; `AiMikeFar` tests `aiRange = 4`, which never happens |
| Don | `AIA_DON_SPIN` | `AiDonGetBall` is the shared ball test of the mid and far branches |
| Casey | `AIA_CASEY_KICK`, `AIA_CASEY_RAIN` (first, on a hurt target) | presses pad bits itself (`AiSetInput`) for some jumps; picks `AIA_TAP_B_X4` instead of the rain against Raph |
| Hothead | `AIA_HOTHEAD_FIRE`, `AIA_HOTHEAD_FIRE_IN` (first, on a hurt target) | `AIA_CROUCH_B` when it is in the air close by |
| Shredder | `AIA_SHREDDER_WAVE`, `AIA_GAP48_WAVE`, `AIA_GAP68_WAVE`, `AIA_SHREDDER_BOLTS` | **bug**: `AiShredderHurtActs` has 4 entries but is read with `AiRandom8`, so on hard half the picks read the code after it (`$A5 $28 $30 $8B` → ids `$A5`/`$8B` → `AIA_IDLE`, `$28` `AIA_WATCH_FWD_B`, `$30` `AIA_BACK_CASEY_RAIN`); `AiShredderMid` tests `aiRange = 8` and `= 1`, which never happen there |

### Reactions

Each `AiReact*` first runs `AiReactCommon` (against a turtle: crouching while the target attacks at range 1 gives
`AIA_DOWN_BACK_A`; any target doing move `$0A` or `$0D` gives `AIA_BACK_WATCH_B`), then a jump table on the
**target's** character. Most entries are a plain `RTS`; the shared ones are `AiReactVsLeo` (dodge forward over Leo's
move or back off), `AiReactVsRaph` (`AIA_BALL_SPECIAL_B` within `AiBallSpecialGap[own character]`, or
`AIA_BACK_FWD_HOLD` when held) and `AiReactVsDon` (`AIA_BACK_WATCH`). Shredder's `AiShredderVs*` handlers are also
used by Hothead against Mike and Casey. Raph's table was taken for code before (`words 0A:9D09-0A:9D16`): its last
three entries point at single `RTS` bytes.

### Unused code and data

Never jumped to (and not executed in the Mesen runs below): 0A:8E71, 0A:9068, 0A:908F (a reroll pick from
`AiLeoRetreatActs`), 0A:921D-0A:922D (a pick from `AiRaphUnusedActs`), 0A:9275, 0A:94B8, 0A:94C4-0A:94DB (reads
`AiMikeUnusedActs`), 0A:964D, 0A:9733, 0A:980D, 0A:98CA, 0A:9AFE, 0B:A0B5 and EDE8 (reached only if `difficulty` > 2).
Unread table bytes: `AiLeoUnusedActs` (0A:9085, 10 bytes), `AiRaphUnusedActs2` (0A:92A0, 4 bytes) and entries 1-3 of
`AiMikeJumpActs`.

## Action scripts

An action id (`$00-$45`, `AI_ACTIONS`; larger ids become `AIA_IDLE` `$41`) indexes `AiScriptPtrs`
(0A:8B0B). `AiStartAction` copies the script into the fighter's 32-byte buffer (`aiScriptBuf` $0680 for slot 0,
`aiScriptBuf2` $06A0 for slot 1) through `AiTranslateByte`, which turns the relative directions into pad bits for
the side the target is on. `AiExecByte` then reads the buffer at `aiScriptPos`. The scripts (0A:8B97-0A:8DAD) are
decoded by the generator (`aiscripts` in `rom.txt`): one line per script, ending in `AI_END`; scripts that share a
tail start in the middle of another one (for example `AiScript0B` inside `AiScript0C`).

Bytes below `$D0` are pad bits (`BTN_*`, 0 = nothing): they are pressed (`joyPressed` gets the bits that were not
held last frame) and held together with `aiPadKeep`, then the script waits one frame. The rest:

| byte | name | argument | effect |
|---|---|---|---|
| `$DE` / `$DF` | `AI_FWD` / `AI_BACK` | | toward / away from the target (`BTN_LEFT` or `BTN_RIGHT`) |
| `$F0`-`$F3` | `AI_FWD_UP`, `AI_BACK_UP`, `AI_FWD_DOWN`, `AI_BACK_DOWN` | | the same with up / down |
| `$F6` / `$F7` | `AI_FWD_A` / `AI_FWD_B` | | forward + A / B |
| `$F4` / `$F5` | `AI_TO_BALL` / `AI_FROM_BALL` | | toward / away from the ball (`aiBallDx`) |
| `$FF` | `AI_END` | | end: `aiLocked` = 0, `AiResetState` (the next action is chosen) |
| `$FC` | `AI_HOLD` | | keep the pad one more frame (not used by any script) |
| `$D9` | `AI_RELEASE` | | release all buttons |
| `$FD` | `AI_WAIT` | `AIC_*` | wait until the condition is met (below) |
| `$D7` | `AI_WAIT_SUB` | n | wait on `AIC_SUB` with sub-condition n (`AiCondSub0`-`9`) |
| `$DC` | `AI_WALK_GAP` | gap | walk until `fighterGap` = gap ± 1 (`AIC_WALK_GAP`) |
| `$D6` | `AI_WALK_RANGE` | n | the same with gap = `aiRanges[fighter*4 + n]` |
| `$D4` | `AI_PAUSE` | | keep the pad for `AiHoldTimes[character*4 + difficulty]` frames |
| `$FE` / `$D3` | `AI_CHARGE` / `AI_CHARGE2` | | hold back until the charge time is reached (`AIC_CHARGE` / `AIC_CHARGE2`) |
| `$D5` | `AI_RUN` | | keep only left/right and set `dashStage` = 2: a dash, as if forward had been tapped twice |
| `$DD` | `AI_TAP_B` | | press B (`aiTapCount`++) |
| `$DA` / `$DB` | `AI_LOCK` / `AI_UNLOCK` | | forbid / allow interrupting the action |
| `$D8` | `AI_GOTO` | action | start that action now |
| `$F8`-`$FB` | `AI_INCLUDE` | | `AiIncludeScript`: unused, and broken (it indexes `AiScriptPtrs` with the control byte itself) |

The arguments go through `AiTranslateByte` too, so they must stay below `$D0`. Example (`AiScript13`):
`AI_FWD, AI_RUN, AI_WAIT, AIC_WALK_IN, AI_FWD, AI_FWD_B, AI_END`: tap forward, dash, run in until close, forward,
forward + B.

`AiStepScript` runs the step in `aiStep`: `AI_STEP_NEXT` (read bytes), `AI_STEP_HOLD` (`aiHoldTimer` frames),
`AI_STEP_TIMED` (`aiPadTimer` frames, then release), `AI_STEP_WAIT` (run the condition every frame). Before that, when the fighter is in `FST_JUMP`, `objStep` is 1 (in the air; step 0 is the crouch before the leap) and
`aiRange` < `AIR_MID` (classes 0-1), it presses A (the jump attack) every frame and skips the script (`AiStepScript`, read from the code).
The test reads `objStep` without `,X`, so it is slot 0's step (fighter 0) even for the CPU fighter 1: a game bug. Mesen (14 000 frames, `tmp/w60`): three passes of the A branch had fighter 1 in `FST_JUMP` with its own `objStep` = 2 and fighter 0's `objStep` = 1.

## Conditions

`AiStepWait` copies `aiRanges[fighter*4 + aiRange]` to `$0C` and `aiTargetDx` to `$0E/$0F`, then jumps through the
table after `JSR JumpTable` at 0A:84AF by `aiCond`. A condition routine either ends the wait (`AiCondDone`: back to
`AI_STEP_NEXT`, pad released) or keeps waiting with the pad held (`AiCondKeep`); some reset the AI instead.

| id | name | routine | |
|---|---|---|---|
| `$00` | `AIC_WATCH` | `AiCondWatch` | wait `AiWatchCounts[difficulty]` frames (more if the target does a move) while nothing happens; its gap test compares X*4 by mistake |
| `$01` | `AIC_CLOSING` | `AiCondClosing` | keep going while there is room, the gap is closing and the target is not far |
| `$02` | `AIC_WALK_IN` | `AiCondWalkIn` | walk / run forward until the target is close |
| `$03` | `AIC_WALK_CLOSE` | `AiCondWalkClose` | walk forward until range class 0 |
| `$04` | `AIC_DOWN_TAP` | `AiCondDownTap` | press down, then the next script byte for 5 frames |
| `$05` | `AIC_PRESS_B` | `AiCondPressB` | when standing: press B, keep it `$30` frames |
| `$06` | `AIC_WALK_TO_BALL` | `AiCondWalkToBall` | walk while the ball is free and more than 6 pixels away |
| `$07` | `AIC_HEIGHT` | `AiCondHeight` | wait until the height difference to the target is below `AiTargetHeight` |
| `$08` | `AIC_DOWN_ATTACK` | `AiCondDownAttack` | as `$04`, then wait for the attack to start and end |
| `$09` | `AIC_ATTACK_END` | `AiCondAttackEnd` | wait while `fighterAttacking` |
| `$0A` | `AIC_WALK_GAP` | `AiCondWalkGap` | walk toward or away (`AiWalkDirs`) until `fighterGap` = `aiCondArg` ± 1; stops at the walls |
| `$0B` | `AIC_WALK_FAR` | `AiCondWalkFar` | as `$03` when no up/down is held and the target is far |
| `$0C` | `AIC_LAND_A` | `AiCondLandA` | wait to land and stand, then press A |
| `$0D` | `AIC_WATCH_DON` | `AiCondWatchDon` | as `$00`; against Don doing a move it switches to `$19` |
| `$0E` | `AIC_STOP` | `AiCondStop` | wait while in the air or moving |
| `$0F` | `AIC_LAND` | `AiCondLand` | release up / down / B, wait to land |
| `$10` | `AIC_B_STANDING` | `AiCondBStanding` | unless crouching: press B, keep it `$30` frames |
| `$11` | `AIC_SHOT` | `AiCondShot` | wait while the opponent's ball shot flies |
| `$12` | `AIC_STOP_MOVING` | `AiCondStopMoving` | on the ground: release, wait for velocity 0 |
| `$13` | `AIC_TARGET_HURT` | `AiCondTargetHurt` | wait while the target is hurt |
| `$14` | `AIC_HOLD_B` | `AiCondHoldB` | press and keep B unless the target is hurt or we jump |
| `$15` | `AIC_SUB` | `AiCondSub` | sub-table by `aiCondArg` (`AI_WAIT_SUB`): `AiCondSub0`-`AiCondSub9` |
| `$16` | `AIC_B_NOW` | `AiCondBNow` | standing: press B; otherwise wait |
| `$17` | `AIC_CHARGE` | `AiCondCharge` | hold back (`AiAddBack`) until `specialTimer` > `chargeTime` |
| `$18` | `AIC_CHARGE2` | `AiCondCharge2` | a variant of `$17` |
| `$19` | `AIC_DON` | `AiCondDon` | used against Don |

## Tables

| table | | |
|---|---|---|
| `AiScriptPtrs` | 0A:8B0B | 70 words: action id -> script |
| `AiRangeTable` | 0A:80FB | by character*4: `aiRanges+1..+3` (the last row is 3 bytes) |
| `AiHoldTimes` | 0A:8DB5 | `AI_PAUSE` frames by character*4 + difficulty |
| `AiCondHoldTimes` | 0A:8DD0 | `AiCondSub1` frames by character*4 + difficulty |
| `AiWatchCounts`, `AiWatchCountsMove` | 0A:8A1D, 0A:8A20 | `AIC_WATCH` counts by difficulty |
| `AiWalkDirs` | 0A:886B | `AIC_WALK_GAP` direction by side and gap |
| `AiTargetHeight` | 0A:8B04 | `AIC_HEIGHT` limit by target slot (only 0/1 used) |
| `AiShotChance` | ED53 | by character: chance to react to a ball shot (`AiNoticeShot`) |

Unused: `AiScriptUnused` (0A:8C46, no action points to it), a second `AI_END` at 0A:8BAC and 7 bytes at
0A:8DAE.

## Distance thresholds

`AbsDeltaBelow` (0F:EE3E) compares |`tmpDeltaHi:tmpDeltaLo`| ($0F:$0E) with A (carry clear = below). Of its 15 callers in bank 0A,
13 run `ObjDeltaY16` just before it, so their immediates are *vertical* gaps between the fighter and its target: $20 (2x),
$30 (6x), $40 (2x), $50 (2x), $70 (1x), plus `AiTargetHeight,Y` at 0A:8922. The other two load `aiBallDx` / the
horizontal ball gap by hand ($06 at 0A:8ACF, $40 at 0A:999A). They are left as numbers: what each band means in play
(grounded / jumping target) has not been tested in Mesen.

A 30 000-frame bot run logged the callers it reached (`traceAt` EE3E + `traceRam`, `tools/mesen/explore.lua`): 0A:8922 (A = `AiTargetHeight`
= $30, 233 calls, |dy| 0-93, 66 below the limit), 0A:8AD1 (ball dx, $06, 132 calls, |dx| 4-154, 4 below) and 0A:9394 ($20, 7 calls,
|dy| 17-68, 3 below). The other callers belong to characters the run did not meet. The same log showed that `$0E` is the
*low* byte of the 16-bit gap and `$0F` the sign/high byte, so `tmpDeltaLo`/`tmpDeltaHi` were swapped in ram.txt and are now fixed.

A 22 000-frame run with P2 forced to Leonardo (`fighterChar+1` held at 0, P2 HP held, P1 random) reached more callers: 0A:8925 ($30,
9 calls, |dy| 0-38), 0A:8AD4 ($06 ball dx, 305 calls, |dx| 2-120, P1 in states 0/1/2/3/7/10), and the Leo callers 0A:8FB8 ($70, 5 calls)
and 0A:9043 ($30, 6 calls); all of those saw |dy| = 0 (P1 in state 0 resp. 3). Too few samples to say what the Leo bands mean, so the
immediates stay numbers.

## Checked in Mesen

A Story fight with P1 idle and P1 HP held at `$B0` (`tmp/ai`, `run_mesen.py --cfg`, watching `aiLastAction+1`,
`aiCond+1`, `aiStep+1`, `dashStage+1` and `joyHeld+1` every frame): the CPU (slot 1) ran 17 different actions, and the
conditions and pad bits seen follow the decoded scripts, for example:

- action `$40` (`AI_FWD, AI_RUN, AI_WAIT, AIC_WALK_CLOSE, AI_FWD, AI_PAUSE, AI_WAIT, AIC_B_NOW, AI_BACK,
  AI_WAIT_SUB, 5, AI_GOTO, $07`): forward tap (`dashStage` 1), `AI_RUN` (`dashStage` 2), condition 3, forward,
  condition `$16` with B, condition `$15`, then action `$07` started;
- action `$29` (`AI_WAIT, AIC_DOWN_ATTACK, BTN_DOWN, BTN_A`, twice): down, then down + A held;
- action `$3E` (`AI_LOCK, AI_RELEASE`, nine 0 bytes): nine frames with no buttons.

Decision trees (`tmp/ai2`, 40 000 frames, P1 random from frame 6000, P1 HP held, `difficulty` held at 2; compared
with `tmp/ai` on normal): the CPU played Raph, Don, Mike and Casey. The PRG read log shows `AiRandom8` lists read only
in entries 0-3 on normal and in all 8 on hard (`AiRaphMidActs`, `AiDonMidActs`, `AiMikeMidActs`, `AiCaseyMidActs`),
and `AiMikeJumpActs` read only at its first byte. None of the unused code above ran.

Not run in Mesen (read from the code only): most conditions, `AI_TO_BALL` / `AI_FROM_BALL`, `AI_CHARGE2`, the Leo, Hothead and
Shredder trees and reactions (not met in the runs), the Shredder table bug in play, the meaning of moves `$0A` / `$0D`.

### AbsDeltaBelow limit names

The 15 call sites in bank 0A use the names `AI_SPECIAL_B_DY_LT_*`, `AI_GET_BALL_DX_LT_*`, `AI_PRESS_A_DY_LT_*`, `AI_PRESS_A_GAP2_LT_30` and `AI_BALL_DX_LT_06` (const.txt; superseded by the section at the end of this file). They are checked against the
byte only. What each band means in play (reach of a move, "close enough to press A") is not measured yet.

Mesen trace of `AbsDeltaBelow` (EE3E), 9 matches of 12 000 frames (P1 held at full HP; P2 = Leo, Raph, Mike, Don, Casey, Hothead, Shredder
vs Raph, plus Don vs Leo and Casey). 611 calls in total; `ret` is the address after the JSR. |gap| = |$0F:$0E| at entry:

| call (0A) | limit | calls | \|gap\| min-max | below limit |
|---|---|---|---|---|
| 8925 (`AiTargetHeight,Y`) | $30 | 177 | 0-97 | 39 % |
| 8AD4 (ball dx) | $06 | 353 | 4-82 | 3 % |
| 9043 | $30 | 2 | 0-54 | 1 of 2 |
| 93A4 | $20 | 1 | 3 | 1 of 1 |
| 9617 / 9621 (Casey) | $50 / $30 | 2 / 2 | 22-41 / 135-154 | 2 / 0 |
| 96B0 / 96BA (Casey) | $50 / $30 | 34 / 25 | 10-96 / 76-179 | 74 % / 0 % |
| 9703 | $40 | 13 | 0-95 | 85 % |
| 999F | $40 | 2 | 4-37 | 2 of 2 |

The other callers (Leo/Raph/Don mid and far, Mike near, Hothead) did not run in these matches. The ball check (8AD4) is almost
always "not near" (the gap is rarely under 6), the Casey second check (96BA, limit $30) never fired below the limit. The samples are
too few to say which game situation a limit stands for, so the first names were meaning-free (see the end of this file for the final ones).

Second batch (6 more matches of 24 000 frames: Casey/Leo, Leo/Raph, Mike/Don, Don/Mike, Casey/Hothead, Leo/Mike as P1/P2; 1 972 calls
in both batches). Changes against the table above: 8925 866 calls, 0-97, 29 % below; 8AD4 1 012 calls, 1-113, 2 % below; new sites
8FB8 ($70, 1 call, gap 0), 93A4 ($20, 9 calls, 3-42, 8 below), 948E ($30, 1 call, gap 100), 9D8C ($20, 1 call, gap 0). The rest is
unchanged. Mid and far callers of Raph/Don/Hothead still produced no samples, so no limit gets a meaning from this data.

Why the mid/far callers are silent: a trace of the range handlers (4 matches of 12 000 frames, P1 Leo, P2 Raph/Don/Mike/Hothead) shows they
do run (`AiRaphMid` 212 entries, `AiRaphFar` 228, `AiDonMid` 203, `AiMikeNear` 29, `AiHotheadMid` 126), so the `AbsDeltaBelow` calls
sit behind rare conditions. Example `AiRaphMid`: the call at 0A:91DF is reached only when the target is in `FST_CHAR_MOVE` and
`BallHeldBy` says no (the code there is still `T` = traced, never seen executing in the original CDL); the result is
`AIA_BALL_SPECIAL_B`. Reaching such sites needs a scripted situation (ball in flight, target in a character move), not longer matches.

Forced ball scenario (P2 AI holds the ball: `ballOwner` held to $41, P1 `objState` held to `FST_CHAR_MOVE`, both for 25 frames every 300;
4 matches of 23 000 frames, P2 = Raph/Don/Mike/Hothead). The states are poked, so this shows what the code does in that situation,
not how often it happens. New samples (|gap| = |dy| of `ObjDeltaY16`):

| call (ret) | limit | calls | \|gap\| | below | what the code does |
|---|---|---|---|---|---|
| 91E4 (`AiRaphMid`) | $30 | 4 | 0-69 | 3 | below: `AiResetState`, action `AIA_BALL_SPECIAL_B` (throw the ball) |
| 9258 (`AiRaphFar`) | $30 | 5 | 0-76 | 2 | same check on the far path |
| 93A4 (Don) | $20 | 4 | 43-82 | 0 | |
| 999F (Hothead) | $40 | 4 | 73-100 | 0 | |
| 9D8C | $20 | 3 | 0-61 | 2 | |

So for Raph the $30 limit is "the target is within 48 pixels vertically (about the same lane): the ball special can hit it". That is
read from the branch and the samples; nobody has watched the throw, so the constants keep their neutral names.

### Limit names by what the caller does

After reading every call site, the limits are named by the action taken when the gap is under the limit (the traces above agree):

| name | limit | where | when under the limit |
|---|---|---|---|
| `AI_SPECIAL_B_DY_LT_20` | $20 | `AiDonMid` (jumping, 0A:939F), `AiReactDon` (0A:9D87) | action `AIA_BALL_SPECIAL_B` |
| `AI_SPECIAL_B_DY_LT_30` | $30 | `AiRaphMid` 91DF, `AiRaphFar` 9253, `AiLeoFar` 903E | `AIA_BALL_SPECIAL_B` (Leo far also needs the target in a character move) |
| `AI_SPECIAL_B_DY_LT_70` | $70 | `AiLeoMid` 8FB3 | ball special B (target in a character move) |
| `AI_GET_BALL_DX_LT_30` / `_40` | $30 / $40 | `AiMikeNear` 9489, `AiHotheadMid` 999A | `AIA_GET_BALL` (horizontal gap to the ball) |
| `AI_PRESS_A_DY_LT_40` | $40 | `AiCaseyNear` 96FE | presses A |
| `AI_PRESS_A_DY_LT_50` | $50 | Casey 9612, 96AB | first of two checks, then A |
| `AI_PRESS_A_GAP2_LT_30` | $30 | Casey 961C, 96B5 | second check, see below |
| `AI_BALL_DX_LT_06` | $06 | 8ACF (`AiCondWalkToBall`) | ball very near (only 2 % of 1 012 calls) |

Casey's two-stage check looks like "A when 30 <= |dy| < 50" but is not. `AbsDeltaBelow` starts with `TAY`, so after the first check Y is $50
(the limit), and the second `JSR ObjDeltaY16` computes `objY,Y - objY,X` = `objVelY[0] - objY,X` (objY+$50 = $0460 = objVelY slot 0). The
traced second gaps are 76-179 (and 135-154), never under $30, as that explanation predicts: the second check always passes, so Casey
presses A for every |dy| < $50. Checked in Mesen (Casey as P2, 14 000 frames, 9 second checks): every traced gap equals `objVelY[0] - objY[X]` exactly (e.g. $FF8D = $0460 - $0411), with Y = $50 at the call. The code was not patched, so the effect on play (Casey presses A for every |dy| < $50) is derived, not watched.

Patch test (`tools/mesen/explore.lua` option `fixY`: Y := `aiTarget,X` before the second `ObjDeltaY16`, at 0A:9619 and 0A:96B2; Casey as P2 vs
Leo, 20 000 frames each, same seed, runs diverge after the first changed decision, so only shares are comparable):

| | second gap (96BA) | A pressed at 96BC |
|---|---|---|
| original | 13 calls, 101-170 (never < $30) | 13 of 13 |
| Y fixed | 20 calls, 6-79 (equals the first dy) | 12 of 20 (8 skipped as < $30) |

With Y fixed the second check does what it looks like: "A only while $30 <= |dy| < $50". In the original ROM it never filters, so
the intended band is not active. This is an observation of 33 samples in a changed emulator state, not of a patched ROM.

Is the Y clobber elsewhere? `AbsDeltaBelow` leaves Y = its limit. A scan of all 15 call sites (the next 25 instructions of each, until an `LDY`, `RTS` or
`JMP`) found no other `,Y` operand, `TYA`, `CPY`, `STY` or Y-reading routine except the two Casey sites (0A:9619 and 0A:96B2, second
`ObjDeltaY16`). `BallFree`, `BallHeldBy`, `AiTargetCharMove` do not use Y. Branch targets further away were not followed.

Register-clobber scan: `python tools/clobber_scan.py` (in git). It follows the control flow of the generated sources (branches, `JMP`, fixpoint over `JSR`; `BPL`+`BMI`-style complementary pairs count as one unconditional jump). A routine clobbers X/Y when some path to its `RTS` ends with the register written by anything but a restore (`LDX/LDY` from memory, `PLA`+`TAX/TAY`). A call site is reported when the register is set within the 40 instructions before the call and a path after it (25 instructions) reads the register, directly or through a callee that takes it as input, before it is reloaded. It rediscovers the Casey bug (`0A:9614` -> `ObjDeltaY16`, which is the second distance check). The remaining ~18 candidates (run it for the list) are mostly routines that return an index in the register on purpose (`ClearOpponentPower` loads Y = otherFighter, `PickCloseFar`), plus routines that restore through the stack in a way the model does not see (`FarSetFighterPose`); `LDY` from memory is always treated as a restore, so a routine that changes Y that way is missed. It is a candidate generator: each hit still has to be read. Read so far, none a bug: `PpuQueue*` (return the queue index in X on purpose), `PickCloseFar` / `ClearOpponentPower` (return a fighter index in Y), `SetFighterChrBanks` (leaves X = 0, which `FightLostAnim` happens to need: it only runs for fighter 0), `AiNotClosing` (rewrites Y with the same `aiTarget` value). The rest (`AddCarryToY`, `AiTranslateByte`, `ReadMoveScript`, `ClaimSpecialSlot`, `AnimCycle`, `StartWinAnimF751`, `InitSweepAndFade`) are unread.

Clobber candidates read in full (none a bug): `AddCarryToY` and `ReadMoveScript` return Y on purpose (16-bit add helper; Y = script entry index, the caller does `INY`). `ClaimSpecialSlot` returns Y = 4 + side by design; the reported use is a fall-through past an always-taken `BNE` after `LDA #imm`. `AnimCycle` at 0C:971D: the reported "use" is `JSR JumpTable` after `INX`, which does not read Y. `AiTranslateByte`: Y changes only on the `AI_INCLUDE` path (AiIncludeScript, never executed, marked unused), where Y is the buffer write index and is meant to advance. `InitSweepAndFade`: `TXA`/`TAY` is a `LDY #0` idiom (X = 0 after the header loop) and `SfxStreamPtrSet` wants Y = 0. `StartWinAnimF751`: X is untouched by `WinVoiceSelect`; `PopBank` only reaches `SetChrBanks` for a CHR entry, which this stack never holds.

Accumulator variant: `python tools/clobber_scan_a.py` (same graph; a `PHA`..`PLA` pair counts as a restore). It lists 13 callees whose call sites reload nothing and read A again. All were read: the callee returns the value in A (`AiBack`, `AiForward`, `GetTargetRange`, `ScaleByTimer`, `SetTimerScaled`, `AiBufLoad`, `AiSetInput` returns 0 on purpose), or the write goes to a register that ignores the value (`SetChrR0R1` before `MMC3_IRQ_DISABLE`), or the path is unreachable in practice (`PlaySound` before `ReadMoveScript` falling out of the loop with `fighterMoveStep` wrapping to 0). No new game bug.
