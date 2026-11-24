# Build and verify the disassembly (needs ca65/ld65 and Python 3 in PATH; works on Linux, macOS and Windows)
# Python is called 'python3' on most Linux systems: make PYTHON=python3 (the default tries python3, then python)
PYTHON ?= $(shell command -v python3 2>/dev/null || command -v python)
ROM = Teenage Mutant Ninja Turtles - Tournament Fighters (U) [!].nes

.PHONY: all gen check test docs clean fixed

all: game.nes

game.nes: $(wildcard src/*.asm src/prg/*.asm src/*.inc) config.cfg
	ca65 -g src/main.asm -o src/main.o
	ld65 -C config.cfg -Ln game_labels.txt -m game.map -o game.nes src/main.o

# regenerate src/ from the ROM, CDL and tools/labels/*.txt (overwrites src/!)
gen:
	$(PYTHON) tools/disasm.py --build

# byte-for-byte comparison with the original ROM
check: game.nes
	$(PYTHON) tools/compare.py --original "$(ROM)"

# regenerate the reports that are not part of --build (docs/xref.txt, docs/unknown.txt)
docs:
	$(PYTHON) tools/xref.py
	$(PYTHON) tools/unknown_report.py

test: gen check
	$(PYTHON) tools/lint_labels.py
	$(PYTHON) tools/reloc_test.py
	$(PYTHON) tools/selftest.py
	$(PYTHON) tools/docs_fresh.py

# optional bug-fix patches (tools/patches.py): make fixed [PATCHES=all|1,3,casey-dy-gap|-2,6]  -> game_fixed.nes
PATCHES ?= all
fixed: game.nes
	$(PYTHON) tools/patch_rom.py $(if $(filter all,$(PATCHES)),--all,$(if $(filter -%,$(PATCHES)),--except $(patsubst -%,%,$(PATCHES)),--only $(PATCHES))) --out game_fixed.nes

clean:
	rm -f game.nes game.map game_labels.txt src/main.o
