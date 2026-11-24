# Mechanical constant names

Many operands in `tools/labels/const.txt` (from the section "objTimer start values of single-site fighter / ball states" down) were
named by script, not by hand: `<ROUTINE>_<VARIABLE>` or `<ROUTINE>_TIME` / `_Y` / `_X` / `_FRAME` / `_SCALE` / `_Y_LIMIT` /
`_GAP_LIMIT` / `_<CALLEE>_ARG` / `_<VAR>_LIMIT|MASK|BITS|FLIP|ADD|SUB`, with `_A`, `_B` .. when one routine uses several. The name says **where the value is loaded**, not what
it means in play. The build checks every byte against its `use` line, so a name can never hold a wrong number.

## What was verified

A union of the PRG exec logs of about 225 Mesen runs (`tmp/*/a.exec`: bot, forced characters, poked modes, plus 12 matchup runs with the
CPU as Casey / Hothead / Shredder / Leo against several opponents) says whether the instruction with each such operand ever ran:

- 466 `use` sites in these sections, 439 executed at least once (the value really is loaded in play), 27 never executed. The first pass
  left 52 unexecuted; the matchup runs covered 25 of them (Casey vs Raph / Mike, Hothead vs Raph, Shredder vs Raph, the Leo AI, `LaunchBallDirection` ...).
- `objTimer` unit: a Mesen watch of both fighter timers shows the value counts down by 1 per frame (loads of $08, $09, $10, $1C, $2C, $30,
  $4A, $80, $96 reached 0 after exactly that many frames), so the `*_TIME` constants are frame counts. Other loads ($20, $28, $40, $A0, $D0) were
  reloaded or replaced by a state change before reaching 0, so their duration was not measured.
- Never executed after all runs: `ENDING_TEXT_TIME@0C:96B4`, `SET_CREDITS_WAIT_TIMER_TIME@0C:98C8`, `CONTINUE_MENU_CURSOR_TIME@0D:A4C7`, `FIGHT_END_CARDS_START_TIME@E758`, `LAUNCH_BALL_DIRECTION_Y_C@03:A11E`, `RAPH_SPECIAL_HIT_VEL_Y_FRAC@03:B54A`, `CONTINUE_START_PRESSED_VEL_X_FRAC@0C:86C5`, `CONTINUE_MENU_CURSOR_X@0D:A4AF`, `DAT_03_A18_A_FRAME@03:A1A0`, `AI_COND_CHARGE2_GAP_LIMIT@0A:8582`, `AI_COND_SUB3_Y_LIMIT@0A:86BC`, `AI_LEO_NEAR_CLOSING_CHECK_Y_LIMIT_A@0A:8F71`, `AI_LEO_NEAR_CLOSING_CHECK_Y_LIMIT_B@0A:8F8D`, `AI_CASEY_VS_HOTHEAD_GAP_LIMIT@0A:9ED5`, `AI_HOTHEAD_VS_LEO_GAP_LIMIT@0A:9F55`, `AI_SHREDDER_VS_LEO_GAP_LIMIT@0B:A02D`, `AI_SHREDDER_VS_MIKE_Y_LIMIT@0B:A0A0`, `AI_SHREDDER_VS_SHREDDER_GAP_LIMIT@0B:A16F`, `AI_EXEC_BYTE_AI_COND_B@0A:831B`, `AI_COND_WATCH_DON_AI_COND@0A:89C0`, `ENDING_TEXT_MODE_STEP@0C:96B0`, `ENDING_CREDITS_SETUP_MODE_STEP@0C:98BC`, `IRQ_SPLIT_H12@0D:A431`, `DAT_03_A18_A_LAUNCH_BALL_ARG@03:A18F`, `ZERO_AIF_NO_DIVIDEND_PPU_QUEUE_PUSH_ARG@0C:9512`, `REMATCH_PROMPT_FAR_CALL_A0_E3_ARG@0D:A45A`, `REMATCH_PROMPT_SET_PALETTE_ENTRY_ARG@0D:A461`.

Executed means "run in Mesen", not "the meaning of the number is known": the durations, heights and limits stay named by routine until
someone watches what they do. Names `LAUNCH_BALL_DIRECTION_2_*` / `_3_*` belong to the code after the `dat_03_A13D` / `dat_03_A18A` labels in the `LaunchBallDirection` area; rename them when that code is named.

Durations: because `objTimer` counts 1 per frame, a `*_TIME` constant is its length in frames (value / 60 s on NTSC), e.g. $20 = 32 frames, $A0 = 160 frames, $D0 = 208 frames.
This follows from the measured unit; the individual routines were not timed against the screen.
