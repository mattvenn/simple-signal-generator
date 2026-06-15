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
    output reg  [15:0] count,
    output wire        period_start
);
    wire [15:0] period = on_count + off_count;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n)                   count <= 16'd0;
        else if (period == 16'd0)     count <= 16'd0;          // silence
        else if (count + 16'd1 >= period) count <= 16'd0;       // wrap (handles
                                                                  // period shrinking too)
        else                           count <= count + 16'd1;
    end

    assign period_start = (count == 16'd0);
endmodule
```

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
instead triggered on `period_start` (one cycle per period, independent of
`ch0_out`'s polarity — functionally equivalent but doesn't require `ch0_out`/
`ch0_prev` as inputs at all).

Module inputs change: drop `ch0_out`; add `count` and `period_start` (driven
by the shared `phase_counter`); keep `on_count`, `off_count` (still needed for
`period` and the `actual_delay` formula), `spi_offset`, `enc_step`, `enc_up`,
`enc_dn`.

### `src/project.v`

Instantiate `phase_counter` once, feeding `on_count`/`off_count` (from config
regs 0-3, same as today). Wire its `count`/`period_start` outputs to both
`sq_wave_gen` (ch0) and `phase_shifted_gen` (ch1). Remove the `ch0_out` →
`phase_shifted_gen.ch0_out` connection (ch1 no longer depends on ch0's
registered output at all — both are independent views of `count`).

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

**Reset behavior shifts by one cycle**: `count` starts at 0, so if
`on_count > 0`, `ch0_out` is HIGH from cycle 0 of normal operation (the old
FSM had a 1-cycle LOW "IDLE" period after reset before going HIGH). Frequency,
duty cycle, and the ch0/ch1 phase relationship are unaffected — only the
reset-relative absolute phase shifts by 1 cycle. Tests are adjusted for this.

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

- **Existing tests 1-8** (`test_spi_registers`, `test_frequency_generation`,
  `test_ch1_inphase`, `test_spi_phase_offset`, `test_channel_silence`,
  `test_encoder_integer_phase`, `test_encoder_sigma_delta`, etc.): re-verify.
  Most pass unchanged since frequency/duty-cycle/in-phase/silence/encoder
  accumulation are preserved by construction. `test_frequency_generation` may
  need a tolerance/offset tweak for the 1-cycle reset shift.

- **Replace `test_spi_phase_offset_boundary`** (tests the now-removed clamp
  boundary) with **`test_phase_full_range`**: asymmetric `on=20, off=80`
  (period=100). Sweep `spi_offset` across values spanning the whole period,
  including the old clamp boundary and the lead/wrap region: `-50, -1, 0, 1,
  50, 79, 80, 99`. For each, run several periods and assert `ch1_edges ==
  ch0_edges` and that ch1's rising edge lands at `(ch0_rise + actual_delay) mod
  period`. This is the regression test for **bug #1**.

- **New `test_sigma_delta_no_stutter`**: `on=off=100`, `spi_offset=0`,
  `enc_step=1`, a couple of `enc_dn` clicks (reproduces the live config that
  triggered **bug #2** — dithering near zero phase). Run ~20 periods; for each
  assert exactly one rising→falling ch1 pulse per ch0 period, in the correct
  order, with `ch1_edges == ch0_edges` overall.

## Documentation

`docs/info.md`: remove the clamp paragraph ("If `|spi_offset + enc_int|` would
reach or exceed `off_count`, the delay is clamped..."). Replace with a note
that ch1's delay supports the full `[0, period)` range with no clamping, plus
a short note on the pre-existing small-period/large-offset limitation above.
