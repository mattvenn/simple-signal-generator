# Unified phase-counter redesign

## Problem

The current design drives ch0 (`uo_out[0]`) with an independent `sq_wave_gen`
FSM (IDLE/HIGH/LOW) and ch1 (`uo_out[1]`) with a `phase_shifted_gen` FSM
(IDLE/DELAY/ON) that is *retriggered* by ch0's rising edge and must return to
IDLE before the next trigger arrives.

This trigger/retrigger model has two bugs, both stemming from the same root
cause — encoding "phase" as a *relative delay from an edge* requires the FSM
to finish one cycle before the next trigger, which constrains `actual_delay`
to `< off_count`:

1. **Original bug**: when `actual_delay >= off_count`, `phase_shifted_gen` is
   still in `ON`/`DELAY` when the next `ch0_rising` arrives and misses the
   trigger, so ch1 only pulses every other ch0 period.
2. **Regression from the first fix**: clamping `actual_delay` to
   `off_count - 1` maps both "excess lag" and "small lead" (`total_phase`
   slightly negative) onto the same clamped value, creating a discontinuity
   at `total_phase ≈ 0` that causes ch1 to occasionally start on ch0's
   falling edge and produce a spurious one-cycle-low blip.

## Chosen approach: unified shared phase counter

Both channels are views of the **same free-running counter**. There is no
triggering and no FSM — each channel's output is a comparator against the
counter, so any `actual_delay` in `[0, period)` is valid with no clamping and
no special-casing.

```
period       = on_count + off_count
ch0_out      = (count < on_count)
ch1_phase    = (count >= actual_delay) ? (count - actual_delay)
                                        : (count - actual_delay + period)
ch1_out      = (ch1_phase < on_count)
```

## Components

### `src/phase_counter.sv` (new)

Free-running counter, shared by both channels.

```systemverilog
module phase_counter (
    input  wire        clk,
    input  wire        rst_n,
    input  wire [15:0] on_count,
    input  wire [15:0] off_count,
    output reg  [15:0] count
);
    wire [15:0] period = on_count + off_count;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n)                       count <= 16'd0;
        else if (period == 16'd0)         count <= 16'd0;  // silence
        else if (count + 16'd1 >= period) count <= 16'd0;  // wrap
        else                              count <= count + 16'd1;
    end
endmodule
```

Note: `period_start` was removed when the timing-fix pipeline stage was added (see
"Timing fix" section below) — `phase_shifted_gen` now derives its own `period_end`
signal locally.

### `src/sq_wave_gen.sv` (rewrite, ch0)

Becomes a registered comparator:

```systemverilog
module sq_wave_gen (
    input  wire        clk,
    input  wire        rst_n,
    input  wire [15:0] on_count,
    input  wire [15:0] count,
    output reg         out
);
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) out <= 1'b0;
        else         out <= (count < on_count);
    end
endmodule
```

(`off_count` is no longer needed by this module — `period`/wrapping is owned
by `phase_counter`.)

### `src/phase_shifted_gen.sv` (rewrite, ch1)

Keeps the existing encoder + sigma-delta logic that computes `actual_delay`
(same `total_phase` → `actual_delay_raw` → `actual_delay_mod` formula as
today), **minus the `off_count` clamp**, which is deleted entirely. The FSM
(`IDLE`/`DELAY`/`ON`, `counter`, `ch0_prev`/`ch0_rising`) is removed.

New combinational phase shift + registered comparator:

```systemverilog
wire [15:0] ch1_phase = (count >= actual_delay)
    ? (count - actual_delay)
    : (count - actual_delay + period);

always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) out <= 1'b0;
    else         out <= (ch1_phase < on_count);
end
```

The sigma-delta accumulator update (currently triggered on `ch0_rising`) is
instead triggered on `period_end` (`count + 1 >= period`, one cycle before the
counter wraps — functionally equivalent but doesn't require `ch0_out`/`ch0_prev`
as inputs at all, and places `sd_carry` one cycle early so the pipeline stage
below can register `actual_delay` in time).

Module inputs change: drop `ch0_out`; add `count` (driven by the shared
`phase_counter`); keep `on_count`, `off_count` (still needed for `period` and
the `actual_delay` formula), `spi_offset`, `enc_step`, `enc_up`, `enc_dn`.

### `src/project.v`

Instantiate `phase_counter` once, feeding `on_count`/`off_count` (from config
regs 0-3, same as today). Wire its `count` output to both `sq_wave_gen` (ch0)
and `phase_shifted_gen` (ch1). Remove the `ch0_out` → `phase_shifted_gen.ch0_out`
connection (ch1 no longer depends on ch0's registered output at all — both are
independent views of `count`).

### `test/Makefile`

Add `phase_counter.sv` to `PROJECT_SOURCES`.

## Edge cases

All fall out of the comparator formulas with no special-casing, since
`count ∈ [0, period-1]` and `actual_delay ∈ [0, period)`:

| Config | `count` range | `ch0_out` | `ch1_out` | Result |
|---|---|---|---|---|
| `on=0, off=0` | stuck at 0 (`period==0` guard) | `0<0` = false | `0<0` = false | both silent |
| `on=0, off>0` | `0..off-1` | always `count<0` = false | `ch1_phase<0` = false | both silent |
| `on>0, off=0` | `0..on-1` | always `count<on` = true | `ch1_phase<on=period` = always true | both permanently HIGH |
| `on>0, off>0` | `0..period-1` | normal duty cycle | normal phase-shifted duty cycle | normal operation |

This matches the documented behavior ("Setting `on_count = 0` silences both
channels"; `off_count = 0` → ch0 stays HIGH).

**Reset behavior is unchanged**: `count` starts at 0 and `out` is itself
registered, so `ch0_out` follows exactly the same cycle-by-cycle sequence
after reset as the old FSM (`out_N = ((N-1) mod period) < on_count` for
`N >= 1`, `out_0 = 0` — identical to the old IDLE→HIGH→LOW sequence).

**ch1's phase definition changes by one cycle**: the old FSM's
`ch0_rising`-triggered, two-state (`DELAY`→`ON`) transition added one extra
cycle of latency, so `actual_delay=N` meant ch1's edge appeared `N+1` cycles
after ch0's. The new design uses `actual_delay=N` to mean ch1's transition
occurs exactly `N` counter-ticks after ch0's
(`ch1_out_N = ch0_out_{N-actual_delay}`, indices mod period). This is a more
direct/intuitive definition and the redesign adopts it; tests that measure
this delay are updated accordingly (see Testing plan).

Note: a pipeline stage for `actual_delay` was subsequently added (see "Timing
fix" section below), but this does not change the phase definition — only the
cycle on which `out` is registered.

## Config-change behavior

`on_count`/`off_count`/`spi_offset`/`enc_step` are read live, every cycle, by
the comparators. An SPI write that changes these mid-period can
truncate/extend *that one* pulse; from the next period onward (and for `count`
itself, since `phase_counter`'s wrap condition is `count + 1 >= period`, which
self-corrects even if `period` shrinks below the current `count`) everything
is clean. No latching/snapshot registers are added (this was an explicit
trade-off — see below).

## Known limitation (pre-existing, out of scope)

`actual_delay` is computed via `actual_delay_raw = total_phase[16] ? period +
total_phase[15:0] : total_phase[15:0]`, then `actual_delay_mod = (raw >=
period) ? 0 : raw`. This is correct only when `|total_phase| < period` (single
wrap). `total_phase` can range up to ~±32895 (`spi_offset` ±32767 + `enc_int`
±127 + `sd_carry` ±1); for very small `period` combined with large offsets,
`actual_delay` would be numerically wrong (not glitchy — just an incorrect
phase value). This limitation exists in the current code today and is not
introduced or worsened by this redesign. Not addressed here.

## Testing plan

- **`measure_ch1_delay` helper rewrite**: change from "is ch1 high N cycles
  after ch0's rise" (which baked in the old FSM's +1 latency) to "cycles from
  ch0's rising edge to ch1's next rising edge" — directly measures
  `actual_delay` under the new definition, including wrap (lead) cases.

- **Existing tests 1-8** (`test_spi_registers`, `test_frequency_generation`,
  `test_ch1_inphase`, `test_spi_phase_offset`, `test_channel_silence`,
  `test_encoder_integer_phase`, `test_encoder_sigma_delta`, etc.): re-verify.
  Most pass unchanged. `test_spi_phase_offset` and `test_encoder_integer_phase`
  use `measure_ch1_delay` and need their expected values updated from
  `offset+1` to `offset` (per the one-cycle phase-definition change above).
  `test_encoder_sigma_delta` updates its expected delay set from `{2,3}` to
  `{1,2}` for the same reason.

- **Replace `test_spi_phase_offset_boundary`** (tests the now-removed clamp
  boundary) with **`test_phase_full_range`**: asymmetric `on=20, off=80`
  (period=100). Sweep `spi_offset` across values spanning the whole period,
  including the old clamp boundary and the lead/wrap region: `-50, -1, 0, 1,
  50, 79, 80, 99`. For each, assert `measure_ch1_delay == offset_cycles %
  period`, and over several periods assert `ch1_edges == ch0_edges`. This is
  the regression test for **bug #1**.

- **New `test_sigma_delta_no_stutter`**: `on=off=100`, `spi_offset=0`,
  `enc_step=1`, one `enc_dn` click (reproduces the live config that triggered
  **bug #2** — dithering between `actual_delay=0` and `actual_delay=period-1`
  near zero phase). Run ~20 periods and measure every ch1 high-pulse's width;
  assert each equals `on_count` exactly (a stutter/blip would split one pulse
  into two non-`on_count`-width pieces) and that the pulse count matches
  `ch0_edges`.

## Documentation

`docs/info.md`: remove the clamp paragraph ("If `|spi_offset + enc_int|` would
reach or exceed `off_count`, the delay is clamped..."). Replace with a note
that ch1's delay supports the full `[0, period)` range with no clamping, plus
a short note on the pre-existing small-period/large-offset limitation above.

## Timing fix (post-redesign)

After the ASIC flow revealed a **-1.81 ns setup violation** (worst-case
**-23.68 ns** at slow corner) on the path
`enc_phase_fp[9] → total_phase → actual_delay → ch1_phase → out`,
a pipeline register (`actual_delay_r`) was added to split the combinational
chain across two cycles:

- **Cycle N**: `enc_phase_fp` / `sd_carry` → `total_phase` → `actual_delay` →
  registered into `actual_delay_r`
- **Cycle N+1**: `count` − `actual_delay_r` → `ch1_phase` → `out`

To keep `actual_delay_r` correct at period boundaries, `sd_carry` is now
updated one cycle **before** the wrap (`period_end`: `count + 1 >= period`)
rather than at `period_start` (`count == 0`). This way the new `sd_carry`
propagates through `actual_delay` and into `actual_delay_r` so that by
`count == 0` of the next period, `actual_delay_r` already holds the correct
value. `period_start` is removed from `phase_counter.sv`; `phase_shifted_gen`
derives `period_end` locally.

The phase definition is unchanged: `actual_delay=N` still means
`ch1_out_N = ch0_out_{N-actual_delay}`. The extra register adds one cycle of
latency to delay *changes* (e.g. after an encoder click, the new delay takes
effect one cycle later than before), but the steady-state waveform and all
nine cocotb tests pass unchanged.
