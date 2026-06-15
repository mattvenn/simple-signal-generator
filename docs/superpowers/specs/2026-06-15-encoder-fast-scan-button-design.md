# Encoder fast-scan button

## Problem

Scanning ch1's phase offset across the full `[0, period)` range one encoder
click at a time (via `enc_step`) can be slow when the user wants to move far
before fine-tuning. The PmodEnc's built-in pushbutton is unused. Pressing it
should temporarily multiply the per-click phase step so the user can scan
quickly, then release to return to fine adjustment.

## Design

A new top-level input, `ui_in[2]` ("encoder button", active-high: `1` while
pressed), is synchronized the same way as the other `ui_in` signals and fed
into `phase_shifted_gen`. While held, the per-click step (`enc_step_s`,
derived from the `enc_step` SPI register) is multiplied by 8 (`<<< 3`) before
being applied to `enc_phase_fp`. This is purely combinational/level-based:
release the button and the very next click reverts to the normal step size.
No new SPI register, no latching, no debounce beyond the existing 2-stage
synchronizer.

**Why 8x is safe:** `enc_step` is 8-bit (0-255), so `enc_step_s` (its 16-bit
signed widening) is at most 255. `255 * 8 = 2040`, well within the existing
16-bit signed `enc_phase_fp` range (±32512, enforced by the existing
`ENC_MAX`/`ENC_MIN` clamp). No new overflow cases are introduced — a held
button just reaches the clamp faster.

## Components

### `src/project.v`

Add a synchronizer for `ui_in[2]`, alongside the existing `enc_a_sync`/
`enc_b_sync` synchronizers:

```verilog
wire enc_a_sync, enc_b_sync, enc_btn_sync, enc_up, enc_dn;
...
synchronizer #(.STAGES(SYNC_STAGES), .WIDTH(1)) sync_enc_btn (.rstb(rst_n), .clk(clk), .ena(ena), .data_in(ui_in[2]), .data_out(enc_btn_sync));
```

Wire `enc_btn_sync` into `ch1_inst`'s new `enc_btn` port.

### `src/phase_shifted_gen.sv`

Add a new input port `enc_btn` (active-high, synchronized). Introduce
`enc_step_eff`, the step actually applied to `enc_phase_fp`:

```systemverilog
wire signed [15:0] enc_step_s   = {8'b0, enc_step};
wire signed [15:0] enc_step_eff = enc_btn ? (enc_step_s <<< 3) : enc_step_s;
wire signed [15:0] enc_next_up  = enc_phase_fp + enc_step_eff;
wire signed [15:0] enc_next_dn  = enc_phase_fp - enc_step_eff;
```

(`enc_next_up`/`enc_next_dn` currently use `enc_step_s` directly — they
switch to `enc_step_eff`. Everything downstream — `ENC_MAX`/`ENC_MIN`
clamping, `enc_int`/`enc_frac` extraction, sigma-delta — is unchanged.)

Update the module's header comment to document the button and the 8x
multiplier.

### `info.yaml`

Add the pinout entry:

```yaml
  ui[2]: "Encoder button (hold for 8x fast-scan)"
```

### `docs/info.md`

Document the button under the encoder section: pressing it multiplies
`enc_step` by 8 for as long as it's held, for fast scanning; releasing
returns to normal step size on the next click. Note in "External hardware"
that the PmodEnc's button (SWT) connects to `ui[2]`.

## Edge cases

- `enc_step == 0`: 8x of 0 is still 0 — button has no effect, as expected.
- Button held while `enc_phase_fp` is at `ENC_MAX`/`ENC_MIN`: existing clamp
  still applies; no overflow.
- Sigma-delta dithering (`enc_frac`) is unaffected in mechanism — it dithers
  whatever fractional part results from the (possibly 8x) step.
- Button pressed/released between clicks: takes effect on the very next
  `enc_up`/`enc_dn` pulse (combinational, no extra latency).

## Testing plan

Add a new cocotb test, `test_encoder_button_fast_scan`:

- Configure `enc_step` to a small value (e.g. 8, giving a clean 8x = 64
  per-click step in Q8 units).
- With the button released, perform one encoder click and measure the
  resulting `actual_delay` shift (via the existing encoder-delay measurement
  pattern from `test_encoder_integer_phase`).
- Reset/reconfigure, hold `ui_in[2]=1`, perform one encoder click in the same
  direction, and confirm the resulting phase shift is 8x the released-button
  shift (within the `[0, period)` wrap and `ENC_MAX`/`ENC_MIN` clamp).
- Confirm releasing the button mid-scan reverts the next click to the normal
  (1x) step size.

Existing tests (`test_encoder_integer_phase`, `test_encoder_sigma_delta`,
`test_sigma_delta_no_stutter`) must continue to pass unchanged — they leave
`ui_in[2]=0` (button released), so `enc_step_eff == enc_step_s` for them,
identical to current behavior.
