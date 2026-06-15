# Unified Phase Counter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the trigger/retrigger FSMs driving ch0 (`sq_wave_gen`) and ch1 (`phase_shifted_gen`) with a single shared free-running phase counter and per-channel comparators, fixing the "every other ch1 pulse missing" bug and the sigma-delta stutter regression, with full `[0, period)` phase range and no clamping.

**Architecture:** New `src/phase_counter.sv` module produces a free-running `count[15:0]` (`0..period-1`, `period = on_count+off_count`) plus a `period_start` pulse. `src/sq_wave_gen.sv` becomes `out <= (count < on_count)`. `src/phase_shifted_gen.sv` keeps its encoder/sigma-delta `actual_delay` logic (minus the old clamp) and adds `out <= (ch1_phase < on_count)` where `ch1_phase = (count - actual_delay) mod period`. `src/project.v` instantiates `phase_counter` once and feeds both channels.

**Tech Stack:** SystemVerilog (icarus via oss-cad-suite), cocotb (Python) for simulation tests.

**Spec:** `docs/superpowers/specs/2026-06-15-unified-phase-counter-design.md`

---

## Task 1: Rewrite tests to RED (new behavior, old RTL)

**Files:**
- Modify: `test/test.py`

This task only touches the testbench. The RTL is unchanged, so the existing
`test_spi_registers`, `test_frequency_generation`, `test_ch1_inphase`, and
`test_channel_silence` tests are untouched and should keep passing. The tests
below are rewritten to express the *new* phase-delay definition
(`actual_delay=N` ⇒ ch1's transition is `N` counter-ticks after ch0's, no
clamping) and should **fail** against the current FSM-based RTL.

- [ ] **Step 1: Rewrite the `measure_ch1_delay` helper**

Replace lines 145-162 (the whole `measure_ch1_delay` function) with:

```python
async def measure_ch1_delay(dut, period):
    """Cycles from a ch0 rising edge to the next ch1 rising edge (mod period)."""
    prev_ch0 = (int(dut.uo_out.value) >> 0) & 1
    prev_ch1 = (int(dut.uo_out.value) >> 1) & 1
    ch0_rise_t = None
    for tick in range(1, 4 * period):
        await RisingEdge(dut.clk)
        val = int(dut.uo_out.value)
        c0 = val & 1
        c1 = (val >> 1) & 1
        if c0 == 1 and prev_ch0 == 0 and ch0_rise_t is None:
            ch0_rise_t = tick
        if c1 == 1 and prev_ch1 == 0 and ch0_rise_t is not None:
            return tick - ch0_rise_t
        prev_ch0, prev_ch1 = c0, c1
    return None
```

This now measures `actual_delay` directly (cycles between ch0's rise and
ch1's next rise), instead of the old "is ch1 high N cycles later" check that
baked in the FSM's extra pipeline cycle. It also requires a `period` argument
(needed for the loop bound and to handle wrap/lead cases).

- [ ] **Step 2: Update `test_spi_phase_offset` (Test 4) for the new delay definition**

Replace the body of `test_spi_phase_offset` (lines 268-294) with:

```python
@cocotb.test()
async def test_spi_phase_offset(dut):
    """SPI phase offset shifts ch1 by exactly the programmed number of cycles."""
    dut._log.info("test_spi_phase_offset: start")
    clock = Clock(dut.clk, 20, units="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    on, off = 20, 80  # period = 100
    await set_ch0(dut.clk, dut.uio_in, on, off)
    await set_enc_step(dut.clk, dut.uio_in, 0)  # disable encoder contribution
    await ClockCycles(dut.clk, 10)

    period = on + off

    # actual_delay=N means ch1's rising edge is exactly N cycles after ch0's.
    for offset_cycles in [0, 1, 5, 10, 15]:
        await set_phase_offset(dut.clk, dut.uio_in, offset_cycles)
        await ClockCycles(dut.clk, 10)
        d = await measure_ch1_delay(dut, period)
        assert d == offset_cycles, \
            f"offset=+{offset_cycles}: expected d={offset_cycles}, got {d}"

    dut._log.info("test_spi_phase_offset: PASS")
```

- [ ] **Step 3: Replace `test_spi_phase_offset_boundary` (Test 5) with `test_phase_full_range`**

Replace the whole `test_spi_phase_offset_boundary` function and its section
comment (lines 297-330) with:

```python
# ── Test 5: ch1 phase delay covers the full [0, period) range ──────────────

@cocotb.test()
async def test_phase_full_range(dut):
    """ch1's delay covers the full [0, period) range with no missing/duplicate edges."""
    dut._log.info("test_phase_full_range: start")
    clock = Clock(dut.clk, 20, units="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    on, off = 20, 80  # period = 100
    period = on + off
    await set_ch0(dut.clk, dut.uio_in, on, off)
    await set_enc_step(dut.clk, dut.uio_in, 0)  # disable encoder contribution

    # Spans the old clamp boundary (off=80) and the lead/wrap region.
    for offset_cycles in [-50, -1, 0, 1, 50, 79, 80, 99]:
        await set_phase_offset(dut.clk, dut.uio_in, offset_cycles)
        await ClockCycles(dut.clk, 10)

        expected_delay = offset_cycles % period
        d = await measure_ch1_delay(dut, period)
        assert d == expected_delay, \
            f"offset={offset_cycles}: expected delay={expected_delay}, got {d}"

        prev_ch0 = prev_ch1 = 0
        ch0_edges = ch1_edges = 0
        for _ in range(5 * period):
            await RisingEdge(dut.clk)
            val = int(dut.uo_out.value)
            c0 = val & 1
            c1 = (val >> 1) & 1
            if c0 == 1 and prev_ch0 == 0:
                ch0_edges += 1
            if c1 == 1 and prev_ch1 == 0:
                ch1_edges += 1
            prev_ch0, prev_ch1 = c0, c1

        assert ch1_edges == ch0_edges, \
            f"offset={offset_cycles}: ch0_edges={ch0_edges}, ch1_edges={ch1_edges}"

    dut._log.info("test_phase_full_range: PASS")
```

- [ ] **Step 4: Update `test_encoder_integer_phase` (Test 7) expected delays**

In `test_encoder_integer_phase` (lines 382-430), update every
`measure_ch1_delay(dut)` call to `measure_ch1_delay(dut, period)` (add
`period = on + off` right after the `on, off = 20, 80` line), and shift every
expected delay down by 1 (the old `+1` was the FSM's extra pipeline cycle).
Replace lines 396-428 (from the `await ClockCycles(dut.clk, 20)` after
`set_enc_step` through the final assertion) with:

```python
    await ClockCycles(dut.clk, 20)
    period = on + off

    # Reset encoder to known state 00
    _enc_idx[0] = 0
    await _set_enc_ab(dut, _ENC_STATES[0])
    await ClockCycles(dut.clk, 10)

    # Baseline: enc_phase_fp=0 -> actual_delay=0 -> d=0
    d0 = await measure_ch1_delay(dut, period)
    assert d0 == 0, f"baseline: expected d=0 (in-phase), got {d0}"

    # 2 CW steps -> enc_phase_fp=256 (1.0 cycle), enc_int=1, frac=0 -> actual_delay=1 -> d=1
    await encoder_steps(dut, +2)
    await ClockCycles(dut.clk, 10)
    d1 = await measure_ch1_delay(dut, period)
    assert d1 == 1, f"after +2 steps (1 cycle lag): expected d=1, got {d1}"

    # 2 more CW steps -> enc_phase_fp=512 (2.0 cycles) -> actual_delay=2 -> d=2
    await encoder_steps(dut, +2)
    await ClockCycles(dut.clk, 10)
    d2 = await measure_ch1_delay(dut, period)
    assert d2 == 2, f"after +4 steps (2 cycle lag): expected d=2, got {d2}"

    # 2 CCW steps -> back to 256 (1.0 cycle) -> d=1
    await encoder_steps(dut, -2)
    await ClockCycles(dut.clk, 10)
    d3 = await measure_ch1_delay(dut, period)
    assert d3 == 1, f"after -2 steps (back to 1 cycle): expected d=1, got {d3}"

    # 2 more CCW steps -> back to 0 -> d=0
    await encoder_steps(dut, -2)
    await ClockCycles(dut.clk, 10)
    d4 = await measure_ch1_delay(dut, period)
    assert d4 == 0, f"after returning to zero: expected d=0, got {d4}"

    dut._log.info("test_encoder_integer_phase: PASS")
```

- [ ] **Step 5: Update `test_encoder_sigma_delta` (Test 8) expected delay values**

In `test_encoder_sigma_delta` (lines 435-491), the inline measurement loop
already measures "cycles from ch0 rise to ch1 rise" directly (same definition
as the rewritten `measure_ch1_delay`), so its mechanics don't change. Only the
*expected values* shift down by 1 (sigma-delta carry alternates 0/1, so
`total_phase = enc_int + carry = 1 + {0,1} = {1,2}`, giving `actual_delay`
(and thus `d`) alternating between 1 and 2, not 2 and 3).

Update the comment above the measurement loop (around line 450) from:

```python
    # 3 CW steps → enc_phase_fp=384 (1.5 cycles), enc_int=1, enc_frac=128
    # sigma-delta alternates carry 0,1,0,1... → actual_delay alternates 1,2 → d alternates 2,3
```

to:

```python
    # 3 CW steps -> enc_phase_fp=384 (1.5 cycles), enc_int=1, enc_frac=128
    # sigma-delta alternates carry 0,1,0,1... -> actual_delay alternates 1,2 -> d alternates 1,2
```

Then replace lines 481-489 (the post-collection assertions) with:

```python
    # All delays must be 1 or 2 (enc_int=1 +/- sigma-delta carry)
    unexpected = [d for d in delays if d not in (1, 2)]
    assert not unexpected, f"unexpected delay values: {unexpected}"

    # sigma-delta with frac=128 gives carry=1 roughly half the time
    d1_count = delays.count(1)
    d2_count = delays.count(2)
    assert 5 <= d1_count <= 15, f"expected ~10 d=1 values (got {d1_count}): {delays}"
    assert 5 <= d2_count <= 15, f"expected ~10 d=2 values (got {d2_count}): {delays}"
```

- [ ] **Step 6: Add new `test_sigma_delta_no_stutter` test**

Append this new test at the end of `test/test.py`:

```python
# ── Test 9: Sigma-delta dithering produces no stutter/blip ─────────────────

@cocotb.test()
async def test_sigma_delta_no_stutter(dut):
    """Sigma-delta dithering near zero phase produces one full-width ch1 pulse per ch0 period."""
    dut._log.info("test_sigma_delta_no_stutter: start")
    clock = Clock(dut.clk, 20, units="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    on, off = 100, 100  # period = 200
    period = on + off
    await set_ch0(dut.clk, dut.uio_in, on, off)
    await set_phase_offset(dut.clk, dut.uio_in, 0)
    await set_enc_step(dut.clk, dut.uio_in, 1)  # finest resolution

    # 1 CCW click: enc_phase_fp=-1 -> enc_int=-1, enc_frac=255
    # sigma-delta carry=1 most periods (total_phase=0, actual_delay=0)
    # and carry=0 occasionally (total_phase=-1, actual_delay=period-1)
    _enc_idx[0] = 0
    await _set_enc_ab(dut, _ENC_STATES[0])
    await encoder_steps(dut, -1)
    await ClockCycles(dut.clk, 20)

    n_periods = 20
    ch0_edges = 0
    prev_ch0 = 0
    pulse_widths = []
    width = 0
    in_pulse = False
    for _ in range(n_periods * period):
        await RisingEdge(dut.clk)
        val = int(dut.uo_out.value)
        c0 = val & 1
        c1 = (val >> 1) & 1

        if c0 == 1 and prev_ch0 == 0:
            ch0_edges += 1

        if c1 == 1:
            width += 1
            in_pulse = True
        elif in_pulse:
            pulse_widths.append(width)
            width = 0
            in_pulse = False

        prev_ch0 = c0
    if in_pulse:
        pulse_widths.append(width)

    dut._log.info(f"ch1 pulse widths: {pulse_widths}")
    bad = [w for w in pulse_widths if w != on]
    assert not bad, f"ch1 pulses should all be {on} cycles wide, got {pulse_widths}"
    assert abs(len(pulse_widths) - ch0_edges) <= 1, \
        f"ch0_edges={ch0_edges}, ch1 pulse count={len(pulse_widths)}"

    dut._log.info("test_sigma_delta_no_stutter: PASS")
```

- [ ] **Step 7: Run the suite and confirm the expected RED pattern**

Run:
```bash
source /home/matt/oss-cad-suite/environment
cd test && make
```

Expected: `test_spi_registers`, `test_frequency_generation`,
`test_ch1_inphase`, and `test_channel_silence` **PASS** (unaffected by these
edits). `test_spi_phase_offset`, `test_phase_full_range`,
`test_encoder_integer_phase`, `test_encoder_sigma_delta`, and
`test_sigma_delta_no_stutter` **FAIL** — these exercise the new phase
definition / full-range / no-clamp behavior that the current FSM-based RTL
doesn't implement yet.

If any of the four tests that should still pass now fail, or any of the five
that should fail instead pass, stop and re-check Steps 1-6 before continuing
— don't proceed to Task 2 until the RED pattern matches.

- [ ] **Step 8: Commit**

```bash
git add test/test.py
git commit -m "$(cat <<'EOF'
Rewrite tests for unified phase-counter design (RED)

Updates measure_ch1_delay and the phase-delay tests to the new
definition (actual_delay=N means ch1's edge is N cycles after ch0's,
full [0,period) range, no clamping), and adds a regression test for
the sigma-delta stutter bug. These fail against the current
FSM-based RTL, which Task 2-6 replace.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Create `phase_counter.sv`

**Files:**
- Create: `src/phase_counter.sv`
- Modify: `test/Makefile:9-18`

- [ ] **Step 1: Write `src/phase_counter.sv`**

```systemverilog
/*
 * Copyright (c) 2024 Matt Venn
 * SPDX-License-Identifier: Apache-2.0
 *
 * Shared free-running phase counter.
 *
 * count cycles 0 .. period-1 .. 0 .. where period = on_count + off_count.
 * period_start is high for one cycle when count == 0, marking the start
 * of each period. If period == 0 (on_count == off_count == 0), count
 * stays at 0 (silence).
 */

`default_nettype none

module phase_counter (
    input  wire        clk,
    input  wire        rst_n,
    input  wire [15:0] on_count,
    input  wire [15:0] off_count,
    output reg  [15:0] count,
    output wire        period_start
);

    wire [15:0] period = on_count + off_count;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            count <= 16'd0;
        end else if (period == 16'd0) begin
            count <= 16'd0;
        end else if (count + 16'd1 >= period) begin
            count <= 16'd0;
        end else begin
            count <= count + 16'd1;
        end
    end

    assign period_start = (count == 16'd0);

endmodule
```

- [ ] **Step 2: Add `phase_counter.sv` to the test Makefile's source list**

In `test/Makefile`, the `PROJECT_SOURCES` list (lines 9-18) currently reads:

```makefile
PROJECT_SOURCES = project.v \
                  sq_wave_gen.sv \
                  phase_shifted_gen.sv \
                  enc_decoder.sv \
                  spi_wrapper.sv \
                  spi_reg.sv \
                  rising_edge_detector.sv \
                  falling_edge_detector.sv \
                  synchronizer.sv \
                  reclocking.sv
```

Add `phase_counter.sv` after `project.v`:

```makefile
PROJECT_SOURCES = project.v \
                  phase_counter.sv \
                  sq_wave_gen.sv \
                  phase_shifted_gen.sv \
                  enc_decoder.sv \
                  spi_wrapper.sv \
                  spi_reg.sv \
                  rising_edge_detector.sv \
                  falling_edge_detector.sv \
                  synchronizer.sv \
                  reclocking.sv
```

- [ ] **Step 3: Add `phase_counter.sv` to `info.yaml`'s `source_files` list**

`info.yaml` lines 19-29 list each source file individually for the
TinyTapeout hardening flow:

```yaml
  source_files:
    - "project.v"
    - "sq_wave_gen.sv"
    - "phase_shifted_gen.sv"
    - "enc_decoder.sv"
    - "spi_wrapper.sv"
    - "spi_reg.sv"
    - "rising_edge_detector.sv"
    - "falling_edge_detector.sv"
    - "synchronizer.sv"
    - "reclocking.sv"
```

Add `"phase_counter.sv"` after `"project.v"`:

```yaml
  source_files:
    - "project.v"
    - "phase_counter.sv"
    - "sq_wave_gen.sv"
    - "phase_shifted_gen.sv"
    - "enc_decoder.sv"
    - "spi_wrapper.sv"
    - "spi_reg.sv"
    - "rising_edge_detector.sv"
    - "falling_edge_detector.sv"
    - "synchronizer.sv"
    - "reclocking.sv"
```

No commit yet — `project.v` doesn't reference `phase_counter` until Task 5,
so the design won't compile until then.

---

## Task 3: Rewrite `src/sq_wave_gen.sv`

**Files:**
- Modify: `src/sq_wave_gen.sv` (full rewrite)

- [ ] **Step 1: Replace the entire contents of `src/sq_wave_gen.sv`**

```systemverilog
/*
 * Copyright (c) 2024 Matt Venn
 * SPDX-License-Identifier: Apache-2.0
 *
 * Channel 0: square wave generator.
 *
 * out is high while the shared phase counter is in [0, on_count).
 */

`default_nettype none

module sq_wave_gen (
    input  wire        clk,
    input  wire        rst_n,
    input  wire [15:0] on_count,
    input  wire [15:0] count,
    output reg         out
);

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            out <= 1'b0;
        end else begin
            out <= (count < on_count);
        end
    end

endmodule
```

This drops the `off_count` port (no longer needed — `phase_counter` owns
`period`/wrapping) and the IDLE/HIGH/LOW FSM entirely.

No commit yet — `project.v` still instantiates this with the old port list
until Task 5.

---

## Task 4: Rewrite `src/phase_shifted_gen.sv`

**Files:**
- Modify: `src/phase_shifted_gen.sv` (full rewrite)

- [ ] **Step 1: Replace the entire contents of `src/phase_shifted_gen.sv`**

```systemverilog
/*
 * Copyright (c) 2024 Matt Venn
 * SPDX-License-Identifier: Apache-2.0
 *
 * Channel 1: phase-shifted replica of ch0, sharing the same free-running
 * phase counter (see phase_counter.sv).
 *
 * total_delay = spi_offset + floor(enc_phase_fp/256) + sigma_delta_carry
 *
 * spi_offset: signed 16-bit static offset set via SPI (registers 4-5).
 *
 * enc_phase_fp: Q8 signed 16-bit fixed-point, range +/-127 cycles.
 *   Updated by enc_up/enc_dn in steps of enc_step/256 cycles per click.
 *
 * sigma_delta_carry: 0 or 1, averages to enc_frac/256 per period.
 *
 * actual_delay = total_delay mod period, in [0, period). ch1's phase is
 * the shared counter shifted back by actual_delay:
 *   ch1_phase = (count - actual_delay) mod period
 *   out       = (ch1_phase < on_count)
 * No clamping is needed: any actual_delay in [0, period) is valid.
 */

`default_nettype none

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

    wire [15:0] period = on_count + off_count;

    // Encoder: Q8 signed 16-bit fixed-point, range +/-127 cycles
    localparam signed [15:0] ENC_MAX =  16'sd32512;  // +127 * 256
    localparam signed [15:0] ENC_MIN = -16'sd32512;

    reg  signed [15:0] enc_phase_fp;
    wire signed [15:0] enc_step_s  = {8'b0, enc_step};
    wire signed [15:0] enc_next_up = enc_phase_fp + enc_step_s;
    wire signed [15:0] enc_next_dn = enc_phase_fp - enc_step_s;

    wire signed  [7:0] enc_int  = enc_phase_fp[15:8];
    wire         [7:0] enc_frac = enc_phase_fp[7:0];

    // Sigma-delta: carry averages to enc_frac/256 per period
    reg [7:0] sd_acc;
    reg       sd_carry;

    // Total signed phase -> actual delay in [0, period)
    wire signed [16:0] total_phase   = {spi_offset[15], spi_offset}
                                     + {{9{enc_int[7]}}, enc_int}
                                     + {16'b0, sd_carry};

    wire        [15:0] actual_delay_raw = total_phase[16] ?
        (period + total_phase[15:0]) :
        total_phase[15:0];
    wire        [15:0] actual_delay = (actual_delay_raw >= period) ? 16'd0 : actual_delay_raw;

    // ch1_phase = (count - actual_delay) mod period
    wire [15:0] ch1_phase = (count >= actual_delay) ?
        (count - actual_delay) :
        (count - actual_delay + period);

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            enc_phase_fp <= 16'sd0;
            sd_acc       <= 8'd0;
            sd_carry     <= 1'b0;
            out          <= 1'b0;
        end else begin
            if (enc_up) begin
                enc_phase_fp <= (enc_next_up > ENC_MAX) ? ENC_MAX : enc_next_up;
            end else if (enc_dn) begin
                enc_phase_fp <= (enc_next_dn < ENC_MIN) ? ENC_MIN : enc_next_dn;
            end

            if (period_start) begin
                {sd_carry, sd_acc} <= {1'b0, sd_acc} + enc_frac;
            end

            out <= (ch1_phase < on_count);
        end
    end

endmodule
```

This removes the `IDLE`/`DELAY`/`ON` FSM, the `ch0_out`/`ch0_prev`/
`ch0_rising` inputs and logic, and the `off_count`-based clamp on
`actual_delay`. The sigma-delta accumulator now updates on `period_start`
instead of `ch0_rising`.

No commit yet — `project.v` still instantiates this with the old port list
until Task 5.

---

## Task 5: Wire up `phase_counter` in `src/project.v`

**Files:**
- Modify: `src/project.v:77-106`

- [ ] **Step 1: Replace the ch0/ch1 instantiation block**

Replace lines 77-106 of `src/project.v` (from `// Channel 0: independent
square wave generator` through the closing `);` of `ch1_inst`) with:

```verilog
    // Shared free-running phase counter (drives both channels)
    // config regs 0-3: on_count[15:8], on_count[7:0], off_count[15:8], off_count[7:0]
    wire [15:0] on_count  = {config_regs[7  -: 8], config_regs[15 -: 8]};
    wire [15:0] off_count = {config_regs[23 -: 8], config_regs[31 -: 8]};
    wire [15:0] phase_count;
    wire        period_start;

    phase_counter phase_counter_i (
        .clk         (clk),
        .rst_n       (rst_n),
        .on_count    (on_count),
        .off_count   (off_count),
        .count       (phase_count),
        .period_start(period_start)
    );

    // Channel 0: square wave generator
    sq_wave_gen ch0_inst (
        .clk     (clk),
        .rst_n   (rst_n),
        .on_count(on_count),
        .count   (phase_count),
        .out     (uo_out[0])
    );

    // Channel 1: phase-shifted replica of ch0
    // config regs 4-5:  spi_offset[15:0] (signed; static phase offset in clock cycles)
    // config reg  6:    enc_step[7:0]    (Q8 encoder step per click: 1/256 cycle per unit)
    wire [15:0] ch1_spi_offset = {config_regs[39 -: 8], config_regs[47 -: 8]};
    wire  [7:0] ch1_enc_step   = config_regs[55 -: 8];

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

This removes the old `wire ch0_out;` intermediate (ch1 no longer depends on
ch0's output — both are independent views of `phase_count`), and factors
`on_count`/`off_count` out once instead of duplicating the `config_regs`
slicing for each instance.

---

## Task 6: Run the full suite and verify GREEN

- [ ] **Step 1: Run the test suite**

```bash
source /home/matt/oss-cad-suite/environment
cd test && make
```

Expected: all 9 tests pass — `test_spi_registers`,
`test_frequency_generation`, `test_ch1_inphase`, `test_spi_phase_offset`,
`test_phase_full_range`, `test_channel_silence`, `test_encoder_integer_phase`,
`test_encoder_sigma_delta`, `test_sigma_delta_no_stutter`.

- [ ] **Step 2: If any test fails, diagnose before changing anything else**

If a test other than the five from Task 1 Step 7 fails, that's a regression
from the RTL rewrite — use `superpowers:systematic-debugging` rather than
re-editing the RTL ad hoc. Likely culprits to check first if something fails:

- `test_phase_full_range` at `offset_cycles=99` or `offset_cycles=-1`: these
  exercise `ch1_phase` wrapping across the period boundary — check the
  `(count >= actual_delay)` comparison and the `+ period` branch in
  `phase_shifted_gen.sv`.
- `test_channel_silence`: check `phase_counter`'s `period == 0` guard and that
  `sq_wave_gen`/`phase_shifted_gen`'s comparators correctly read `on_count==0`.
- Any test hanging/timing out: check `test/Makefile`'s `PROJECT_SOURCES`
  includes `phase_counter.sv` (Task 2 Step 2) and that `project.v` compiles
  (Task 5).

- [ ] **Step 3: Clean up simulation artifacts**

```bash
cd test && rm -rf sim_build results.xml
```

(Both are gitignored, but avoids leaving stale build output around.)

- [ ] **Step 4: Commit the RTL rewrite**

```bash
git add src/phase_counter.sv src/sq_wave_gen.sv src/phase_shifted_gen.sv src/project.v test/Makefile info.yaml
git commit -m "$(cat <<'EOF'
Replace ch0/ch1 FSMs with unified shared phase counter

sq_wave_gen and phase_shifted_gen no longer use trigger/retrigger FSMs.
A new phase_counter module provides a free-running count (0..period-1)
shared by both channels; each channel is now a simple registered
comparator against count (ch1 against a phase-shifted view of count).

Fixes the "every other ch1 pulse missing" bug (actual_delay >= off_count
previously caused phase_shifted_gen to miss ch0's retrigger) and the
sigma-delta stutter regression (the old off_count-1 clamp created a
discontinuity near actual_delay=0 that caused a one-cycle blip). Any
actual_delay in [0, period) is now valid with no clamping.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

This commit includes the `info.yaml` change from Task 2 Step 3.

---

## Task 7: Update documentation

**Files:**
- Modify: `docs/info.md:41-42`

- [ ] **Step 1: Replace the clamp paragraph**

Replace lines 41-42 of `docs/info.md`:

```
If `|spi_offset + enc_int|` would reach or exceed `off_count`, the delay is
clamped to `off_count - 1` so ch1's pulse always fits within the period.
```

with:

```
ch1's delay (`spi_offset + enc_int + sigma_delta_carry`) covers the full
`[0, period)` range with no clamping — it wraps modulo the period, so ch1's
pulse can land anywhere relative to ch0's, including spanning the period
boundary. (For very small periods combined with large `spi_offset`/encoder
values — larger in magnitude than the period — the wrap is computed mod one
period only, so the resulting delay may not match the mathematical mod for
`|total_delay| >= period`; this is a pre-existing edge case unrelated to
normal use.)
```

- [ ] **Step 2: Update the register-map table if it references the clamp**

Run:
```bash
grep -n "clamp\|off_count - 1\|off_count-1" docs/info.md
```

If any other lines reference the clamp (e.g. in the register-map notes or
worked examples), update them consistently with Step 1's wording. If none
found, no change needed.

- [ ] **Step 3: Commit**

```bash
git add docs/info.md
git commit -m "$(cat <<'EOF'
docs: describe full-range ch1 phase delay (no clamping)

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```
