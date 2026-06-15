# Encoder Fast-Scan Button Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a PmodEnc pushbutton input (`ui_in[2]`, active-high) that multiplies the encoder's per-click phase step by 8x while held, for fast scanning across ch1's phase range.

**Architecture:** `ui_in[2]` is synchronized through the existing 2-stage `synchronizer` (same pattern as `enc_a_sync`/`enc_b_sync`) and fed into `phase_shifted_gen` as a new `enc_btn` input. Inside `phase_shifted_gen`, the per-click step (`enc_step_s`) is shifted left by 3 (×8) when `enc_btn` is high before being applied to `enc_phase_fp`. No new SPI register; purely combinational/level-based.

**Tech Stack:** SystemVerilog (icarus via oss-cad-suite), cocotb (Python) for simulation tests.

**Spec:** `docs/superpowers/specs/2026-06-15-encoder-fast-scan-button-design.md`

---

## Task 1: Add failing test for the fast-scan button (RED)

**Files:**
- Modify: `test/test.py`

This task only touches the testbench. The RTL is unchanged, so all 9 existing
tests keep passing. The new test below exercises `ui_in[2]` (currently
unconnected to anything), so it fails against the current RTL.

- [ ] **Step 1: Add the `set_enc_btn` helper**

In `test/test.py`, immediately after the `encoder_steps` function (it ends at
line 382, just before the blank lines leading into the `# ── Test 7 ──`
comment), add:

```python
async def set_enc_btn(dut, pressed):
    """Drive ui_in[2] (encoder button) and wait for the synchronizer to settle."""
    ui = int(dut.ui_in.value)
    if pressed:
        ui |= (1 << 2)
    else:
        ui &= ~(1 << 2)
    dut.ui_in.value = ui
    await ClockCycles(dut.clk, 5)
```

This follows the same pattern as `_set_enc_ab` (set a `ui_in` bit, wait 5
cycles for the 2-stage synchronizer to settle). It only ever touches bit 2,
so it doesn't disturb the encoder A/B bits (4/5) or SPI mode bits (0/1) that
`_set_enc_ab` and `reset_dut` manage.

- [ ] **Step 2: Append the new test at the end of the file**

Append this at the end of `test/test.py` (after the final line of
`test_sigma_delta_no_stutter`):

```python


# ── Test 10: Encoder button multiplies enc_step by 8x while held ───────────

@cocotb.test()
async def test_encoder_button_fast_scan(dut):
    """Holding ui_in[2] multiplies the encoder's per-click phase step by 8x."""
    dut._log.info("test_encoder_button_fast_scan: start")
    clock = Clock(dut.clk, 20, units="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    on, off = 20, 80   # period=100
    period = on + off
    await set_ch0(dut.clk, dut.uio_in, on, off)
    await set_phase_offset(dut.clk, dut.uio_in, 0)
    # enc_step=32 -> 0.125 cycle/click (1x); 8x = 1.0 cycle/click exactly,
    # so every step below lands on an integer cycle with enc_frac=0 --
    # no sigma-delta dithering, fully deterministic.
    await set_enc_step(dut.clk, dut.uio_in, 32)
    await ClockCycles(dut.clk, 20)

    # Reset encoder to known state 00, button released
    _enc_idx[0] = 0
    await _set_enc_ab(dut, _ENC_STATES[0])
    await set_enc_btn(dut, False)
    await ClockCycles(dut.clk, 10)

    # Baseline: enc_phase_fp=0 -> actual_delay=0 -> d=0
    d0 = await measure_ch1_delay(dut, period)
    assert d0 == 0, f"baseline: expected d=0, got {d0}"

    # 8 clicks @ 1x (button released): enc_phase_fp += 8*32 = 256 (1.0 cycle,
    # frac=0) -> actual_delay=1 -> d=1
    await encoder_steps(dut, +8)
    await ClockCycles(dut.clk, 10)
    d1 = await measure_ch1_delay(dut, period)
    assert d1 == 1, f"after 8 clicks @ 1x: expected d=1, got {d1}"

    # 1 click @ 8x (button held): enc_phase_fp += 1*32*8 = 256 (another 1.0
    # cycle, frac=0) -> actual_delay=2 -> d=2. Demonstrates 1 click @ 8x ==
    # 8 clicks @ 1x.
    await set_enc_btn(dut, True)
    await encoder_steps(dut, +1)
    await ClockCycles(dut.clk, 10)
    d2 = await measure_ch1_delay(dut, period)
    assert d2 == 2, f"after 1 click @ 8x (button held): expected d=2, got {d2}"

    # Release the button: 8 more clicks @ 1x -> enc_phase_fp += 256 ->
    # actual_delay=3 -> d=3. If the multiplier had remained stuck at 8x,
    # this would instead add 8*256=2048 (enc_phase_fp=2304, actual_delay=9),
    # so this confirms the multiplier reverts immediately on release.
    await set_enc_btn(dut, False)
    await encoder_steps(dut, +8)
    await ClockCycles(dut.clk, 10)
    d3 = await measure_ch1_delay(dut, period)
    assert d3 == 3, f"after release + 8 clicks @ 1x: expected d=3, got {d3}"

    dut._log.info("test_encoder_button_fast_scan: PASS")
```

- [ ] **Step 3: Run the suite and confirm the expected RED pattern**

```bash
source /home/matt/oss-cad-suite/environment
cd test && make
```

Expected: `TESTS=10 PASS=9 FAIL=1` — all 9 previously-passing tests still pass,
`test_encoder_button_fast_scan` **fails** (the `d2 == 2` assertion at minimum,
since `ui_in[2]` currently has no effect on `enc_phase_fp`).

If any of the 9 previously-passing tests now fail, or
`test_encoder_button_fast_scan` passes outright, stop and re-check Steps 1-2
before continuing.

- [ ] **Step 4: Clean up simulation artifacts**

```bash
rm -rf sim_build results.xml
```

- [ ] **Step 5: Commit**

```bash
git add test/test.py
git commit -m "$(cat <<'EOF'
Add failing test for encoder fast-scan button (RED)

test_encoder_button_fast_scan exercises ui_in[2] (currently
unconnected) and expects it to multiply the encoder's per-click
phase step (enc_step) by 8x while held. Fails against the current
RTL, which Task 2 implements.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Implement the 8x multiplier in RTL (GREEN)

**Files:**
- Modify: `src/phase_shifted_gen.sv`
- Modify: `src/project.v`

- [ ] **Step 1: Add the `enc_btn` port and 8x multiplier to `src/phase_shifted_gen.sv`**

Update the header comment. Replace the `enc_phase_fp` paragraph (currently):

```
 * enc_phase_fp: Q8 signed 16-bit fixed-point, range +/-127 cycles.
 *   Updated by enc_up/enc_dn in steps of enc_step/256 cycles per click.
```

with:

```
 * enc_phase_fp: Q8 signed 16-bit fixed-point, range +/-127 cycles.
 *   Updated by enc_up/enc_dn in steps of enc_step/256 cycles per click
 *   (8x that -- enc_step*8/256 cycles per click -- while enc_btn is held,
 *   for fast scanning across the phase range).
```

Add a new port `enc_btn` after `enc_dn`. The port list currently reads:

```systemverilog
module phase_shifted_gen (
    input  wire               clk,
    input  wire               rst_n,
    input  wire        [15:0] on_count,
    input  wire        [15:0] off_count,
    input  wire signed [15:0] spi_offset, // static phase offset (clock cycles)
    input  wire        [7:0]  enc_step,   // Q8 step per encoder click (1/256 cycle per unit)
    input  wire               enc_up,
    input  wire               enc_dn,
    input  wire        [15:0] count,        // shared phase counter (0..period-1)
    input  wire               period_start, // one cycle per period, when count==0
    output reg                out
);
```

becomes:

```systemverilog
module phase_shifted_gen (
    input  wire               clk,
    input  wire               rst_n,
    input  wire        [15:0] on_count,
    input  wire        [15:0] off_count,
    input  wire signed [15:0] spi_offset, // static phase offset (clock cycles)
    input  wire        [7:0]  enc_step,   // Q8 step per encoder click (1/256 cycle per unit)
    input  wire               enc_up,
    input  wire               enc_dn,
    input  wire               enc_btn,      // fast-scan: 1 while held, multiplies enc_step by 8x
    input  wire        [15:0] count,        // shared phase counter (0..period-1)
    input  wire               period_start, // one cycle per period, when count==0
    output reg                out
);
```

Replace the `enc_step_s`/`enc_next_up`/`enc_next_dn` declarations (currently):

```systemverilog
    reg  signed [15:0] enc_phase_fp;
    wire signed [15:0] enc_step_s  = {8'b0, enc_step};
    wire signed [15:0] enc_next_up = enc_phase_fp + enc_step_s;
    wire signed [15:0] enc_next_dn = enc_phase_fp - enc_step_s;
```

with:

```systemverilog
    reg  signed [15:0] enc_phase_fp;
    wire signed [15:0] enc_step_s   = {8'b0, enc_step};
    wire signed [15:0] enc_step_eff = enc_btn ? (enc_step_s <<< 3) : enc_step_s;
    wire signed [15:0] enc_next_up  = enc_phase_fp + enc_step_eff;
    wire signed [15:0] enc_next_dn  = enc_phase_fp - enc_step_eff;
```

(`enc_step_s` keeps its existing meaning -- the raw Q8 step from the
`enc_step` register, widened to 16 bits. `enc_step_eff` is the step actually
applied to `enc_phase_fp`, 8x'd while `enc_btn` is held. `255 * 8 = 2040`,
well within the existing `ENC_MAX`/`ENC_MIN` clamp range of ±32512, so no new
overflow case is introduced.)

- [ ] **Step 2: Wire `ui_in[2]` through a synchronizer to `enc_btn` in `src/project.v`**

The wire declaration on line 40 currently reads:

```verilog
    wire enc_a_sync, enc_b_sync, enc_up, enc_dn;
```

Add `enc_btn_sync`:

```verilog
    wire enc_a_sync, enc_b_sync, enc_btn_sync, enc_up, enc_dn;
```

After the `sync_enc_b` instantiation (line 48), add a new synchronizer for
the encoder button:

```verilog
    synchronizer #(.STAGES(SYNC_STAGES), .WIDTH(1)) sync_enc_btn (.rstb(rst_n), .clk(clk), .ena(ena), .data_in(ui_in[2]), .data_out(enc_btn_sync));
```

In the `ch1_inst` instantiation (the `phase_shifted_gen` instance near the
end of the file), add `.enc_btn(enc_btn_sync)` after `.enc_dn(enc_dn),`. The
instantiation currently reads:

```verilog
    phase_shifted_gen ch1_inst (
        .clk         (clk),
        .rst_n       (rst_n),
        .on_count    (on_count),
        .off_count   (off_count),
        .spi_offset  (ch1_spi_offset),
        .enc_step    (ch1_enc_step),
        .enc_up      (enc_up),
        .enc_dn      (enc_dn),
        .count       (phase_count),
        .period_start(period_start),
        .out         (uo_out[1])
    );
```

becomes:

```verilog
    phase_shifted_gen ch1_inst (
        .clk         (clk),
        .rst_n       (rst_n),
        .on_count    (on_count),
        .off_count   (off_count),
        .spi_offset  (ch1_spi_offset),
        .enc_step    (ch1_enc_step),
        .enc_up      (enc_up),
        .enc_dn      (enc_dn),
        .enc_btn     (enc_btn_sync),
        .count       (phase_count),
        .period_start(period_start),
        .out         (uo_out[1])
    );
```

- [ ] **Step 3: Run the suite and confirm GREEN**

```bash
source /home/matt/oss-cad-suite/environment
cd test && make
```

Expected: `TESTS=10 PASS=10 FAIL=0`.

If `test_encoder_button_fast_scan` still fails, use
`superpowers:systematic-debugging` -- check that `enc_btn_sync` is actually
reaching `phase_shifted_gen` (port name/order in the instantiation) and that
`enc_step_eff` (not `enc_step_s`) is used in both `enc_next_up` and
`enc_next_dn`.

If any of the other 9 tests now fail, that's a regression -- they all run
with `ui_in[2]=0` (button released, set by `reset_dut`'s `ui_in = 0b10`), so
`enc_step_eff == enc_step_s` for them, identical to the pre-change behavior.
Check for a typo in the `enc_btn ? ... : ...` ternary.

- [ ] **Step 4: Clean up simulation artifacts**

```bash
rm -rf sim_build results.xml
```

- [ ] **Step 5: Commit**

```bash
git add src/phase_shifted_gen.sv src/project.v
git commit -m "$(cat <<'EOF'
Add encoder fast-scan button (8x enc_step multiplier)

ui_in[2] (active-high, synchronized like the other ui_in signals) is
wired to phase_shifted_gen's new enc_btn input. While held, the
per-click phase step (enc_step) is shifted left by 3 (x8) before
being applied to enc_phase_fp, for fast scanning across ch1's phase
range. Releasing the button reverts the next click to the normal
step size immediately (combinational, no latching). No new SPI
register; the existing ENC_MAX/ENC_MIN clamp already covers the
8x'd step (255*8=2040, well within +/-32512).

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Update documentation

**Files:**
- Modify: `info.yaml`
- Modify: `docs/info.md`

- [ ] **Step 1: Update the `ui[2]` pinout entry in `info.yaml`**

Line 38 currently reads:

```yaml
  ui[2]: ""
```

Replace with:

```yaml
  ui[2]: "Encoder button (hold for 8x fast-scan)"
```

- [ ] **Step 2: Document the button in `docs/info.md`'s "Phase control" section**

After the `enc_step` examples list (ends at line 39 with
`` - `enc_step = 255` → ~1 cycle/click``) and before the "ch1's delay ...
covers the full `[0, period)` range" paragraph (starts at line 41), insert a
new paragraph:

```
**Encoder button** (`ui[2]`, PmodEnc's `SWT` pin, active-high): while held,
multiplies `enc_step` by 8x for fast scanning across the phase range.
Releasing it reverts the very next click to the normal step size.
```

- [ ] **Step 3: Update the "Encoder hardware" section**

Lines 125-127 currently read:

```
Connect a [Digilent PModEnc](https://digilent.com/reference/pmod/pmodenc/start)
to the **bottom row** of the input Pmod connector on the Tiny Tapeout demo
board. This maps the encoder A/B outputs to `ui[4]` and `ui[5]`.
```

Replace with:

```
Connect a [Digilent PModEnc](https://digilent.com/reference/pmod/pmodenc/start)
to the **bottom row** of the input Pmod connector on the Tiny Tapeout demo
board. This maps the encoder A/B outputs to `ui[4]` and `ui[5]`, and the
encoder's pushbutton (`SWT`) to `ui[2]` (fast-scan, see "Phase control"
above).
```

- [ ] **Step 4: Update the "External hardware" bullet list**

Line 156 currently reads:

```
- [Digilent PModEnc](https://digilent.com/reference/pmod/pmodenc/start) on the bottom row of the input Pmod connector (→ `ui[4]`=A, `ui[5]`=B)
```

Replace with:

```
- [Digilent PModEnc](https://digilent.com/reference/pmod/pmodenc/start) on the bottom row of the input Pmod connector (→ `ui[4]`=A, `ui[5]`=B, `ui[2]`=button/SWT for 8x fast-scan)
```

- [ ] **Step 5: Add a row to the cocotb test table**

In the "Simulation (cocotb)" test table (lines 138-146), add a row after the
`test_encoder_sigma_delta` row:

```
| `test_encoder_button_fast_scan` | Holding the encoder button multiplies enc_step by 8x |
```

- [ ] **Step 6: Commit**

```bash
git add info.yaml docs/info.md
git commit -m "$(cat <<'EOF'
docs: document encoder fast-scan button (ui[2], 8x enc_step)

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```
