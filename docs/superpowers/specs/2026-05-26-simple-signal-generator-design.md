# Simple Signal Generator — Design Spec

**Date:** 2026-05-26  
**Shuttle:** ttgf26a  
**Tile size:** 1×1  
**Clock:** 50 MHz  

---

## Overview

Four independent square wave generators on `uo_out[3:0]`. Each channel's high-time and low-time are independently programmable via SPI, allowing arbitrary frequency and duty cycle. The SPI slave is the `spi_wrapper` module from calonso88/tt07_alu_74181, reused verbatim with adjusted parameters. The SPI master is an RP2350 running MicroPython.

---

## Frequency range and resolution

- Minimum frequency: limited by 24-bit counter at 50 MHz → 50,000,000 / 16,777,215 ≈ 3 Hz
- Maximum frequency: limited by minimum count of 1 → 25 MHz (on=1, off=1)
- Target range per spec: 10 Hz – 10 MHz
- Duty cycle: arbitrary, set independently via on_count and off_count
- Exact 50% duty: `on_count = off_count = 25_000_000 // F`
- 10 MHz at 50%: on=2, off=3 (or 3,2) → 40%/60% duty, exact 10 MHz leading-edge period
- Silenced channel: on_count = 0 AND off_count = 0 → output held LOW

---

## Pin mapping

Identical to calonso88/tt07_alu_74181 for SPI signals.

| Pin | Dir | Signal |
|-----|-----|--------|
| `ui_in[0]` | in | CPOL (SPI mode bit) |
| `ui_in[1]` | in | CPHA (SPI mode bit) |
| `ui_in[7:2]` | in | unused |
| `uio_in[4]` | in | SPI_CS_N (active low) |
| `uio_in[5]` | in | SPI_CLK |
| `uio_in[6]` | in | SPI_MOSI |
| `uio_out[3]` | out | SPI_MISO |
| `uio_oe[3]` | — | 1 (MISO output enable) |
| `uio_oe[6:4]` | — | 0 (SPI inputs) |
| `uio_oe[2:0]` | — | 0 |
| `uio_oe[7]` | — | 0 |
| `uo_out[0]` | out | ch0 square wave |
| `uo_out[1]` | out | ch1 square wave |
| `uo_out[2]` | out | ch2 square wave |
| `uo_out[3]` | out | ch3 square wave |
| `uo_out[7:4]` | out | 0 (unused) |

---

## SPI protocol

Frame format (2 bytes total):
- Byte 0: `[7]` = R/W (1=write, 0=read), `[5:0]` = register address, `[6]` = don't care
- Byte 1: data (8 bits)

SPI wrapper instantiated with `NUM_CFG=24`, `NUM_STATUS=24`, `REG_WIDTH=8`.  
`ADDR_WIDTH = $clog2(48) = 6` bits.  
Config registers: addresses 0–23 (addr[5]=0).  
Status registers: addresses 32–55 (addr[5]=1) — unused in this design.

The `spi_wrapper` supports all four SPI modes (CPOL×CPHA), selected via `ui_in[1:0]`.  
All SPI inputs are double-registered (synchronizer chain from the referenced design).

MicroPython on RP2350 programs a channel with 6 `machine.SPI.write()` calls:
```python
spi.write(bytes([0x80 | reg_addr, byte_value]))  # one byte at a time
```

---

## Register map

6 registers per channel (3 for on_count, 3 for off_count), big-endian byte order.

| Reg | Channel | Field | Bits |
|-----|---------|-------|------|
| 0 | ch0 | on_count[23:16] | MSB |
| 1 | ch0 | on_count[15:8] | |
| 2 | ch0 | on_count[7:0] | LSB |
| 3 | ch0 | off_count[23:16] | MSB |
| 4 | ch0 | off_count[15:8] | |
| 5 | ch0 | off_count[7:0] | LSB |
| 6–11 | ch1 | on_count, off_count | same layout |
| 12–17 | ch2 | on_count, off_count | same layout |
| 18–23 | ch3 | on_count, off_count | same layout |

---

## Module hierarchy

```
tt_um_example (project.v)
├── spi_wrapper (spi_wrapper.sv)        # from calonso88/tt07_alu_74181
│   └── spi_reg (spi_reg.sv)
│       ├── rising_edge_detector.sv
│       └── falling_edge_detector.sv
└── sq_wave_gen (sq_wave_gen.sv) ×4
```

Source files to add to `src/` and list in `info.yaml`:
- `spi_wrapper.sv`
- `spi_reg.sv`
- `rising_edge_detector.sv`
- `falling_edge_detector.sv`
- `synchronizer.sv`
- `sq_wave_gen.sv`

---

## sq_wave_gen module

```
module sq_wave_gen (
    input  wire        clk,
    input  wire        rst_n,
    input  wire [23:0] on_count,
    input  wire [23:0] off_count,
    output reg         out
);
```

Behaviour — state machine with states `{IDLE, HIGH, LOW}`:

- **Reset:** state=IDLE, out=0, counter=0
- **IDLE:** out=0; if on_count≠0 OR off_count≠0, transition to HIGH on next cycle (load counter=on_count, out=1)
- **HIGH:** decrement counter each cycle; when counter reaches 0:
  - if off_count≠0 → go to LOW, load counter=off_count, out=0
  - else → stay HIGH, reload counter=on_count
- **LOW:** decrement counter each cycle; when counter reaches 0:
  - if on_count≠0 → go to HIGH, load counter=on_count, out=1
  - else → stay LOW, reload counter=off_count
- **Silence:** if both on_count=0 AND off_count=0 while in HIGH or LOW, transition to IDLE on next counter expiry (output goes LOW cleanly)
- **Count update timing:** new on_count/off_count values are latched at the moment of state transition; no mid-phase glitches

---

## Testbench

File: `test/test.py`  
Adapted from calonso88/tt07_alu_74181 `test/test.py`.

### Test 1: `test_spi_registers`
- Adapted directly from the referenced repo
- Address helpers extended to send 6-bit addresses (bits [5:0]) instead of 4-bit
- Writes random data to all 24 config registers, reads back, asserts equality
- Tests across multiple SPI modes (CPOL=0/CPHA=0, CPOL=0/CPHA=1, etc.)

### Test 2: `test_frequency_generation`
- Programs on_count and off_count for a set of simulation-friendly frequencies
- Test frequencies (chosen to complete in reasonable simulation time):
  - 5 MHz: on=5, off=5 (50% duty, 10 cycle period)
  - 1 MHz: on=25, off=25
  - 500 kHz: on=50, off=50
  - Asymmetric: on=30, off=70 (357 kHz, ~30% duty)
- For each: runs clock for `4 × (on_count + off_count)` cycles, counts rising edges on the output pin
- Asserts edge count == 4 (±0, exact)
- All 4 channels run simultaneously with different frequencies to verify independence

### Test 3: `test_channel_independence`
- Programs all 4 channels with different frequencies simultaneously
- Runs simulation and counts edges on all 4 outputs
- Verifies each channel hits its own expected count regardless of others

### Test 4: `test_channel_silence`
- Programs on_count=0, off_count=0
- Verifies output stays LOW for 1000 cycles

---

## Files to create/modify

| File | Action |
|------|--------|
| `src/project.v` | Rewrite as top-level |
| `src/sq_wave_gen.sv` | New |
| `src/spi_wrapper.sv` | Copy from calonso88/tt07_alu_74181 |
| `src/spi_reg.sv` | Copy from calonso88/tt07_alu_74181 |
| `src/rising_edge_detector.sv` | Copy from calonso88/tt07_alu_74181 |
| `src/falling_edge_detector.sv` | Copy from calonso88/tt07_alu_74181 |
| `src/synchronizer.sv` | Copy from calonso88/tt07_alu_74181 |
| `info.yaml` | Update title, author, description, clock_hz, source_files, pinout |
| `test/test.py` | Rewrite based on referenced repo test |
| `docs/info.md` | Update with project description |
