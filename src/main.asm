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
.include "prg/00_bank.asm"      ; 00:8000 
.include "prg/01_bank.asm"      ; 01:A000 
.include "prg/02_bank.asm"      ; 02:8000 
.include "prg/03_bank.asm"      ; 03:A000 
.include "prg/04_bank.asm"      ; 04:8000 
.include "prg/05_bank.asm"      ; 05:A000 
.include "prg/06_bank.asm"      ; 06:8000 
.include "prg/07_bank.asm"      ; 07:A000 
.include "prg/08_bank.asm"      ; 08:8000 
.include "prg/09_bank.asm"      ; 09:A000 
.include "prg/0A_bank.asm"      ; 0A:8000 
.include "prg/0B_bank.asm"      ; 0B:A000 
.include "prg/0C_bank.asm"      ; 0C:8000 
.include "prg/0D_bank.asm"      ; 0D:A000 
.include "prg/0E_bank.asm"      ; $C000 
.include "prg/0F_bank.asm"      ; $E000 

.include "chr.asm"
