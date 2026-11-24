; TMNT Tournament Fighters (U) - ca65 disassembly. Build: assemble.bat (or make)

.include "defines.inc"
.include "ram.inc"
.include "const.inc"
.include "charmap.inc"

.segment "HEADER"
  .incbin "../header.bin"

; PRG ROM: 16 banks of 8KB (MMC3), segments BANK_00..BANK_0F (config.cfg). Even banks run at $8000,
; odd banks at $A000 (always mapped in pairs n, n+1), bank 0E at $C000 and 0F at $E000 (fixed).
; One file per module (module lines in tools/labels/rom.txt), src/prg/BB_name.asm.
; Line comments: flags C = code (CDL), T = code found by static tracing, D = data read (CDL),
;   P = DMC sample read (CDL), J = jump target, S = subroutine entry; then file offset, bank:CPU address
;   (CPU address alone in the fixed banks), bytes. Data that neither the CDL nor the tracer reached is
;   marked "unknown".
.include "prg/00_sound_frame.asm" ; 00:8000 SoundFrame, fade, UpdateChannel, volume / envelope / vibrato / echo
.include "prg/00_sound_music.asm" ; 00:8404 ReadStream / ReadMusic, note timers, periods, drums, DPCM start, SC_* setup commands
.include "prg/00_sound_stream.asm" ; 00:8872 ReadSfx, SFX commands, WritePeriod, loop / call / repeat / end, ChannelOff, RestoreChannels
.include "prg/00_sound_start.asm" ; 00:8C59 SndJumpTable, period table, SfxPtrs / SongPtrs, SoundStart, StartMusic, fade-out
.include "prg/00_sound_data.asm" ; 00:909E SFX streams, envelopes, DpcmSamples
.include "prg/00_music_2e_2f.asm" ; 00:95FF songs 2E and 2F
.include "prg/01_music_30_31.asm" ; 01:A000 tail of song 2F, songs 30 and 31
.include "prg/01_music_32_38.asm" ; 01:A915 songs 37, 32-36, 38
.include "prg/01_music_39_3d.asm" ; 01:AEFB songs 39-3D
.include "prg/01_music_3e_46.asm" ; 01:B828 songs 3E-46
.include "prg/02_fighter_phase.asm" ; 02:8000 UpdateFighters, phases, stand, attack start, knockdown, shot
.include "prg/02_fighter_states.asm" ; 02:84FC StateJump, special, turn, crouch, StateCharMove
.include "prg/02_fighter_ko.asm" ; 02:88A9 StateWin, PhaseKo, KO sequence
.include "prg/02_fighter_move.asm" ; 02:8AC1 PickCloseFar, SetFighterPose, RunMove, ReadMoveScript
.include "prg/02_fighter_hurt.asm" ; 02:8C18 StateHurt and the hurt reactions
.include "prg/02_fighter_hold.asm" ; 02:8FC9 StateHold, StateHeld, hold / held animation
.include "prg/02_fighter_tables.asm" ; 02:936A per-character tables, MovePtrs and move scripts, HoldAnim, CharPoses
.include "prg/02_special_input.asm" ; 02:99D9 ReadSpecialInput, per-character special input, ReadBallInput
.include "prg/02_ball.asm"      ; 02:9E4F BallPhaseRun, ball spawn / idle / flight / held / thrown / bounce
.include "prg/03_ball_launch.asm" ; 03:A000 LaunchBall, ball launch steps, BallClampX
.include "prg/03_attack_objs.asm" ; 03:A23F UpdateAttackObjs, per-character attack phases and tables
.include "prg/03_slot7_obj.asm" ; 03:A82D TurtlePower, slot 7 object
.include "prg/03_hit_check.asm" ; 03:A991 CheckHits, SetHurtState, HitReaction, hit sparks, hit tables
.include "prg/03_fighter_boxes.asm" ; 03:AD91 SeparateFighters, FightersEdgeCheck, SetFighterBox, box tables
.include "prg/03_scores.asm"    ; 03:AFF6 DrawScores, AddScore, score tables
.include "prg/03_fighter_chr.asm" ; 03:B11A NearBall, SetFighterChrBanks, FrameChr, ChrBankPairs
.include "prg/03_specials_a.asm" ; 03:B35C Leo, Raph, Mike and Don specials
.include "prg/03_specials_b.asm" ; 03:B75E Shredder bolts, Casey jump kick / rain, Hothead fire, special frame tables
.include "prg/03_fight_frame.asm" ; 03:BA96 ReadDashInput, DashAnimStep, win voices, FightFrame, AttackObjHitCheck
.include "prg/03_intro_objs.asm" ; 03:BD7C intro fighters, fight banner, board splinters
.include "prg/04_frames_turtles.asm" ; 04:8000 FramesTurtles and the turtle frames
.include "prg/04_frames_casey.asm" ; 04:8E13 FramesCasey
.include "prg/04_frames_hothead.asm" ; 04:9B52 FramesHothead (continues in bank 05)
.include "prg/05_frames_hothead.asm" ; 05:A000 rest of the Hothead frames
.include "prg/05_frames_shredder.asm" ; 05:AEC5 FramesShredder
.include "prg/05_frames_unused.asm" ; 05:BB9E FramesUnused (no reference)
.include "prg/06_charselect.asm" ; 06:8000 PlayInputScript and input scripts, character select
.include "prg/06_screens_front.asm" ; 06:836A Konami, Title, FightHud, BonusLogo, Waterfront, Sewer, Legal screens
.include "prg/06_screens_select.asm" ; 06:8BDB PirateShip, PlayerSelect, VsSetup, Downtown screens
.include "prg/06_screens_modes.asm" ; 06:949C Tournament, BonusGame, NameEntry screens
.include "prg/06_screens_end.asm" ; 06:9BA6 EndingShredder, EndingTurtles, Ranking, Vs, Option screens
.include "prg/07_bank.asm"      ; 07:A000 
.include "prg/08_ppu_text.asm"  ; 08:8000 RunPpuQueue, DrawText, TextPtrs and the text strings
.include "prg/08_metasprites.asm" ; 08:8235 MetaspritePtrs, CommonFrame
.include "prg/09_bank.asm"      ; 09:A000 
.include "prg/0A_ai_core.asm"   ; 0A:8000 RunCpuAi, AiInit, AiRunAction, step script, AiExecByte
.include "prg/0A_ai_conditions.asm" ; 0A:84E6 the AiCond routines
.include "prg/0A_ai_scripts.asm" ; 0A:8B0B AiScriptPtrs, AiScript, AiHoldTimes
.include "prg/0A_ai_leo.asm"    ; 0A:8DEB AiDecideLeo, Leo trees and acts
.include "prg/0A_ai_raph_don.asm" ; 0A:90BC Raph and Don trees
.include "prg/0A_ai_mike_casey.asm" ; 0A:93BD Mike and Casey trees
.include "prg/0A_ai_hothead_shredder.asm" ; 0A:985C Hothead and Shredder trees
.include "prg/0A_ai_react.asm"  ; 0A:9BD6 AiReact routines (the JSR JumpTable at 9FFF continues in bank 0B)
.include "prg/0B_bank.asm"      ; 0B:A000 
.include "prg/0C_option.asm"    ; 0C:8000 option screen, BGM test
.include "prg/0C_tournament_vsinfo.asm" ; 0C:82BB tournament bracket, DrawVsFighterInfo, VsInfo
.include "prg/0C_continue.asm"  ; 0C:85D6 continue screen
.include "prg/0C_vs_setup.asm"  ; 0C:8890 VS CPU strength and stage select
.include "prg/0C_fight_end_bonus.asm" ; 0C:8A6A fight-end bonus
.include "prg/0C_name_entry.asm" ; 0C:8C7B name entry
.include "prg/0C_intro.asm"     ; 0C:909F intro, parade
.include "prg/0C_ending.asm"    ; 0C:9600 ending
.include "prg/0C_credits_story.asm" ; 0C:996B credits, story text box, StoryText data
.include "prg/0C_ranking.asm"   ; 0C:9F2B InsertHighScores, RankingScreen (continues in bank 0D)
.include "prg/0D_bank.asm"      ; 0D:A000 
.include "prg/0E_dpcm_sfx.asm"  ; $C000 DPCM sample data, then the first sound effects
.include "prg/0E_util.asm"      ; $D000 ClearGameRam, JumpTable, AnimCycle, speed and facing helpers, PPU queue push, game modes
.include "prg/0E_palette.asm"   ; $D346 SetPaletteEntry, LoadPaletteSets, fades, PaletteUploadRun
.include "prg/0E_sprites.asm"   ; $D71F DrawObjects, DrawMetasprite, SpriteSetPtrs
.include "prg/0E_math.asm"      ; $D88C BCD add, multiply, divide, angle / sin / cos (mostly unused)
.include "prg/0E_objects.asm"   ; $DABE ClearAllObjs, move / velocity, CHR bank setters, gravity, flip
.include "prg/0E_fighter_util.asm" ; $DDB6 SetCrouch, damage and KO, RunAnim, StartAnim, win / lose animation
.include "prg/0F_anim_util.asm" ; $E000 AnimData, fade and screen-task starters, ScaleTime / ScaleSpeed
.include "prg/0F_fight_start.asm" ; $E187 FightSubState, FightStart, FightVsScreen, fight palettes, stage intro scroll, FightRoundSetup
.include "prg/0F_fight_round.asm" ; $E46D round intro / running / over, challenger, KO pause, match over, win pose
.include "prg/0F_fight_cards.asm" ; $E7A1 bonus game card, lost, challenger card, Shredder taunt
.include "prg/0F_fight_hud.asm" ; $E90E per-stage tables, FightFrameClear, HUD, health bar, names
.include "prg/0F_ai_helpers.asm" ; $EC5B AiCheckShot, AiForward, AiRandom, GetBallRange, GetTargetRange
.include "prg/0F_screen_load.asm" ; $F000 TitleScreenInit, LoadScreen, ScreenPtrs, ScreenBanks
.include "prg/0F_core.asm"      ; $F174 Reset, MainLoop, Nmi, joypads, InitPpuHardware, GameFrame
.include "prg/0F_game_modes.asm" ; $F380 RunGameMode, title / demo / Konami / legal modes, mode timers
.include "prg/0F_banking.asm"   ; $F5DB PushBank, SetChrBanks, PlaySound, UpdateSound, Far wrappers
.include "prg/0F_irq_mmc3.asm"  ; $F814 SetIrqSplit, Irq and stage handlers, MMC3 CHR and mirroring helpers
.include "prg/0F_fight_tail.asm" ; $FCC9 BuildFloorScrollTable, FightFrameTail, CheckNametableSignature, vectors

.include "chr.asm"
