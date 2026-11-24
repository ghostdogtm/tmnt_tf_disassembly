-- TMNT Tournament Fighters (U): headless explorer / profiler for Mesen 2 (--testrunner).
--
-- tools/mesen/run_mesen.py prepends a global table CFG to a copy of this script:
--   out        absolute path prefix of the output files
--   frames     number of frames to run
--   seed       seed of the random bot
--   shotEvery  take a screenshot every N frames (0 = never)
--   sites      CPU addresses ($C000-$FFFF) of fixed-bank instructions with a $8000-$BFFF operand: log the bank pair
--   light      true = no per-instruction callback (pc unknown in the RAM logs; faster)
--   script     optional list of {frame, button-set} overrides: { {f, "start"}, ... } (button-set: comma list)
--   pokes      optional list of {frame, addr, value}: RAM writes done at the start of that frame
--   bot        "random" (default) or "idle" (only the script)
--   holds      optional list of {fromFrame, toFrame, addr, value}: RAM write at the start of every frame in range
--   chrTrace   optional {R, value, max}: log "frame pc" of the MMC3 CHR writes of that value to <out>.chrtrace
--   chrSwap    optional {R, from, to, fromFrame}: every MMC3 write of value `from` to CHR register R becomes `to`
--   randomFrom frame from which the random bot plays (default 1; the script still overrides it)
--   dumpEvery  dump the 2KB RAM to <out>_ramNNNNNN.bin every N frames (0 = never)
--   watch      optional list of RAM addresses: every change is logged to <out>.watch ("frame addr old new")
--   fixY       optional list of CPU addresses: Y := aiTarget,X before the instruction there (patch test)
--   traceAt    optional list of CPU addresses: first traceMax (50) executions of each -> <out>.trace ("frame addr bank A=..");
--              traceFrom = first frame to log, traceNonZeroA = log only hits with A != 0
--   shotWatch  optional list of RAM addresses (subset of watch): screenshot <out>_wAAAA_fNNNNNN.png on each change
--
-- Output:
--   <out>.exec   131072 bytes, 1 = PRG byte fetched as part of an instruction (opcode or operand; Mesen exec counters)
--   <out>.read   131072 bytes, 1 = PRG byte read as data (includes (zp),Y and DMC reads)
--   <out>.hints  "cpu pair count": bank at $8000 each time a site ran
--   <out>.chr    "Rn value count": CHR banks written to MMC3 R0-R5
--   <out>.pairs  "R6 R7 count": PRG bank pairs written to the MMC3 (after the R7 write)
--   <out>.acc    "W|R prg_pc addr count": RAM accesses by instruction (PRG offset of the instruction; not light)
--   <out>.vals   "addr writes changes min max ndistinct v1 v2 ...": values written to each RAM byte
--   <out>.watch  changes of the watched RAM bytes (checked once per frame, at the end of the frame)
--   <out>.progress  one line every 300 frames
--   <out>_fNNNNNN.png  screenshots

local MT = emu.memType.nesMemory
local PRG = emu.memType.nesPrgRom

local rng = (CFG.seed or 1) % 2147483647
if rng == 0 then rng = 1 end
local function rand(n)
  rng = (rng * 48271) % 2147483647
  return rng % n
end

-- MMC3 PRG banks ---------------------------------------------------------------------------------------------------
local frame = 0
local sel, R6, R7 = 0, 0, 1
local pairs_ = {}
local chrW = {}
emu.addMemoryCallback(function(_, v) sel = v end, emu.callbackType.write, 0x8000, 0x8000, emu.cpuType.nes, MT)
emu.addMemoryCallback(function(_, v)
  local r = sel & 7
  if r < 6 then chrW[r * 256 + v] = (chrW[r * 256 + v] or 0) + 1 end
  local ct = CFG.chrTrace  -- {R, value, max}: log "frame pc" of the MMC3 data writes of that bank value to <out>.chrtrace
  if ct and r == ct[1] and v == ct[2] then
    chrTraceN = (chrTraceN or 0) + 1
    if chrTraceN <= (ct[3] or 40) then
      chrTraceF = chrTraceF or io.open(CFG.out .. ".chrtrace", "w")
      chrTraceF:write(string.format("%d %04X\n", frame, emu.getState()["cpu.pc"]))
      chrTraceF:flush()
    end
  end
  local sw = CFG.chrSwap   -- {R, from, to, fromFrame}: replace one MMC3 CHR bank value to see what it draws
  if sw and r == sw[1] and v == sw[2] and frame >= sw[4] then return sw[3] end
  if r == 6 then R6 = v & 0x0F
  elseif r == 7 then
    R7 = v & 0x0F
    local k = R6 * 16 + R7
    pairs_[k] = (pairs_[k] or 0) + 1
  end
end, emu.callbackType.write, 0x8001, 0x8001, emu.cpuType.nes, MT)

local function prgOff(a)
  if a >= 0xE000 then return 0x1E000 + (a - 0xE000)
  elseif a >= 0xC000 then return 0x1C000 + (a - 0xC000)
  elseif a >= 0xA000 then return R7 * 0x2000 + (a - 0xA000)
  else return R6 * 0x2000 + (a - 0x8000) end
end

-- fixed-bank sites with $8000-$BFFF operands ------------------------------------------------------------------------
local hints = {}
for _, s in ipairs(CFG.sites or {}) do
  emu.addMemoryCallback(function()
    local ai = emu.convertAddress(0x8000, MT)
    local b = ai and math.floor(ai.address / 0x2000) or -1
    local k = s * 256 + (b & 0xFF)
    hints[k] = (hints[k] or 0) + 1
  end, emu.callbackType.exec, s, s, emu.cpuType.nes, MT)
end

-- fixY: list of CPU addresses; before the instruction there, Y := RAM[$06DE + X] (aiTarget,X) -- tests the Casey AbsDeltaBelow Y clobber
for _, s in ipairs(CFG.fixY or {}) do
  emu.addMemoryCallback(function()
    local st = emu.getState()
    local y = emu.read(0x06DE + st["cpu.x"], MT)
    emu.setState({ ["cpu.y"] = y })
  end, emu.callbackType.exec, s, s, emu.cpuType.nes, MT)
end

-- exec traps: the first 50 hits of each CFG.traceAt CPU address -> <out>.trace ("frame addr bankAt8000") ------------
frame = 0
local traceF = CFG.traceAt and io.open(CFG.out .. ".trace", "w")
for _, s in ipairs(CFG.traceAt or {}) do
  local n = 0
  emu.addMemoryCallback(function()
    if frame < (CFG.traceFrom or 0) then return end
    local a = emu.getState()["cpu.a"]
    if CFG.traceNonZeroA and a == 0 then return end
    n = n + 1
    if n <= (CFG.traceMax or 50) then
      local ai = emu.convertAddress(0x8000, MT)
      local st = emu.getState()
      local sp = st["cpu.sp"]
      local ret = emu.read(0x100 + ((sp + 1) & 0xFF), MT) | emu.read(0x100 + ((sp + 2) & 0xFF), MT) << 8
      local extra = ""
      for _, ra in ipairs(CFG.traceRam or {}) do extra = extra .. string.format(" %04X=%02X", ra, emu.read(ra, MT)) end
      traceF:write(string.format("%d %04X %02X A=%02X ret=%04X X=%02X Y=%02X%s\n", frame, s, ai and math.floor(ai.address / 0x2000) or 255, a, ret + 1, st["cpu.x"], st["cpu.y"], extra))
    end
  end, emu.callbackType.exec, s, s, emu.cpuType.nes, MT)
end

-- instructions and RAM -----------------------------------------------------------------------------------------------
local pc = 0
if not CFG.light then
  emu.addMemoryCallback(function(a) pc = prgOff(a) end, emu.callbackType.exec, 0x8000, 0xFFFF, emu.cpuType.nes, MT)
end
local wr, rd = {}, {}
local wN, wChg, wMin, wMax, wVals, last = {}, {}, {}, {}, {}, {}
emu.addMemoryCallback(function(a, v)
  local k = pc * 2048 + a
  wr[k] = (wr[k] or 0) + 1
  wN[a] = (wN[a] or 0) + 1
  if last[a] ~= v then wChg[a] = (wChg[a] or 0) + 1 end
  last[a] = v
  if not wMin[a] or v < wMin[a] then wMin[a] = v end
  if not wMax[a] or v > wMax[a] then wMax[a] = v end
  local s = wVals[a]
  if not s then s = {} wVals[a] = s end
  s[v] = true
end, emu.callbackType.write, 0x0000, 0x07FF, emu.cpuType.nes, MT)
if CFG.reads then
  emu.addMemoryCallback(function(a)
    local k = pc * 2048 + a
    rd[k] = (rd[k] or 0) + 1
  end, emu.callbackType.read, 0x0000, 0x07FF, emu.cpuType.nes, MT)
end

-- input ----------------------------------------------------------------------------------------------------------------
-- script entries: {frame, "button,button", pad (Mesen port index, default 0), frames held (default 1)}
local scripted = { [0] = {}, [1] = {} }
for _, e in ipairs(CFG.script or {}) do
  local b = {}
  for name in string.gmatch(e[2], "[^,]+") do b[name] = true end
  local pad = e[3] or 0
  scripted[pad] = scripted[pad] or {}
  for f = e[1], e[1] + (e[4] or 1) - 1 do scripted[pad][f] = b end
end
local pokes = {}
for _, e in ipairs(CFG.pokes or {}) do
  pokes[e[1]] = pokes[e[1]] or {}
  table.insert(pokes[e[1]], e)
end
local held, heldLeft = {}, 0
local function pickInput(pad)
  if scripted[pad][frame] then return scripted[pad][frame] end
  if CFG.bot == "idle" or frame < (CFG.randomFrom or 1) then return {} end
  local b = {}
  if heldLeft <= 0 then
    held = {}
    local r = rand(100)
    if r < 35 then held.right = true elseif r < 70 then held.left = true end
    if rand(4) == 0 then held.up = true elseif rand(4) == 0 then held.down = true end
    heldLeft = 6 + rand(30)
  end
  heldLeft = heldLeft - 1
  for k, v in pairs(held) do b[k] = v end
  if rand(4) == 0 then b.b = true end
  if rand(4) == 0 then b.a = true end
  if CFG.startEvery and CFG.startEvery > 0 and frame % CFG.startEvery < 2 then b.start = true end
  return b
end
emu.addEventCallback(function()
  emu.setInput(pickInput(0), 0)
  if CFG.p2Hook then return end
  if CFG.p2 then emu.setInput(pickInput(1), 1) end
  for pad, s in pairs(scripted) do
    if pad ~= 0 and s[frame] and not (pad == 1 and CFG.p2) then emu.setInput(s[frame], pad) end
  end
end, emu.eventType.inputPolled)

-- player 2 by RAM injection: emu.setInput(..., 1) reached player 1 in our Mesen build, so CFG.p2Hook = {pc, addr, ...}
-- ORs the pad-1 script (and the random bot when CFG.p2) into the raw pad bytes at addr... when pc executes
-- (TMNT TF: {0xF2F7, 0x01, 0x03}, right after ReadJoypads read both pads twice).
local BITS = { a = 0x80, b = 0x40, select = 0x20, start = 0x10, up = 0x08, down = 0x04, left = 0x02, right = 0x01 }
if CFG.p2Hook then
  emu.addMemoryCallback(function()
    local b = (scripted[1] and scripted[1][frame]) or (CFG.p2 and pickInput(1)) or {}
    local v = 0
    for k in pairs(b) do v = v | (BITS[k] or 0) end
    if v ~= 0 then
      for i = 2, #CFG.p2Hook do emu.write(CFG.p2Hook[i], emu.read(CFG.p2Hook[i], MT) | v, MT) end
    end
  end, emu.callbackType.exec, CFG.p2Hook[1], CFG.p2Hook[1], emu.cpuType.nes, MT)
end

-- output ---------------------------------------------------------------------------------------------------------------
local progress = io.open(CFG.out .. ".progress", "w")
local watchF = CFG.watch and io.open(CFG.out .. ".watch", "w")
local watchV, shotW = {}, {}
for _, a in ipairs(CFG.shotWatch or {}) do shotW[a] = true end
local function shot(name)
  local g = io.open(name, "wb")
  g:write(emu.takeScreenshot())
  g:close()
end
local function writeBin(path, counters)
  local f = io.open(path, "wb")
  local chunk = {}
  for i = 0, 131071 do                     -- emu.getAccessCounters returns a 0-based array
    chunk[#chunk + 1] = (counters[i] or 0) > 0 and "\1" or "\0"
    if #chunk == 4096 then f:write(table.concat(chunk)) chunk = {} end
  end
  f:write(table.concat(chunk))
  f:close()
end

local function finish()
  writeBin(CFG.out .. ".exec", emu.getAccessCounters(PRG, emu.counterType.execCount))
  writeBin(CFG.out .. ".read", emu.getAccessCounters(PRG, emu.counterType.readCount))
  local f = io.open(CFG.out .. ".hints", "w")
  for k, n in pairs(hints) do f:write(string.format("%04X %02X %d\n", k // 256, k % 256, n)) end
  f:close()
  f = io.open(CFG.out .. ".pairs", "w")
  for k, n in pairs(pairs_) do f:write(string.format("%02X %02X %d\n", k // 16, k % 16, n)) end
  f:close()
  f = io.open(CFG.out .. ".chr", "w")
  for k, n in pairs(chrW) do f:write(string.format("R%d %02X %d\n", k // 256, k % 256, n)) end
  f:close()
  f = io.open(CFG.out .. ".acc", "w")
  for k, n in pairs(wr) do f:write(string.format("W %05X %04X %d\n", k // 2048, k % 2048, n)) end
  for k, n in pairs(rd) do f:write(string.format("R %05X %04X %d\n", k // 2048, k % 2048, n)) end
  f:close()
  f = io.open(CFG.out .. ".vals", "w")
  for a = 0, 0x7FF do
    if wN[a] then
      local vs, n = {}, 0
      for v in pairs(wVals[a]) do vs[#vs + 1] = v n = n + 1 end
      table.sort(vs)
      local shown = {}
      for i = 1, math.min(#vs, 24) do shown[i] = string.format("%02X", vs[i]) end
      f:write(string.format("%04X %d %d %02X %02X %d %s\n", a, wN[a], wChg[a] or 0, wMin[a], wMax[a], n, table.concat(shown, " ")))
    end
  end
  f:close()
  progress:close()
  if watchF then watchF:close() end
  if traceF then traceF:close() end
  emu.stop(0)
end

emu.addEventCallback(function()
  frame = frame + 1
  for _, e in ipairs(pokes[frame] or {}) do emu.write(e[2], e[3], MT) end
  for _, h in ipairs(CFG.holds or {}) do
    if frame >= h[1] and frame <= h[2] then emu.write(h[3], h[4], MT) end
  end
  if CFG.shotEvery and CFG.shotEvery > 0 and frame % CFG.shotEvery == 0 then
    shot(string.format("%s_f%06d.png", CFG.out, frame))
  end
  for _, a in ipairs(CFG.watch or {}) do
    local v = emu.read(a, MT)
    if watchV[a] ~= v then
      watchF:write(string.format("%d %04X %s %02X\n", frame, a, watchV[a] and string.format("%02X", watchV[a]) or "--", v))
      watchV[a] = v
      if shotW[a] then shot(string.format("%s_w%04X_f%06d.png", CFG.out, a, frame)) end
    end
  end
  if CFG.dumpEvery and CFG.dumpEvery > 0 and frame % CFG.dumpEvery == 0 then
    local t = {}
    for a = 0, 0x7FF do t[a + 1] = string.char(emu.read(a, MT)) end
    local g = io.open(string.format("%s_ram%06d.bin", CFG.out, frame), "wb")
    g:write(table.concat(t))
    g:close()
  end
  if frame % 300 == 0 then
    progress:write(string.format("%d R6=%02X\n", frame, R6))
    progress:flush()
  end
  if frame >= CFG.frames then finish() end
end, emu.eventType.endFrame)
