# Simple Signal Generator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a 4-channel square wave generator with SPI-programmable on/off counts for each channel, targeting the Tiny Tapeout ASIC platform at 50 MHz.

**Architecture:** The SPI slave (`spi_wrapper` from calonso88/tt07_alu_74181) exposes 24 config registers — 6 per channel (3 bytes on_count, 3 bytes off_count). Four `sq_wave_gen` modules read those registers and independently drive `uo_out[3:0]` using a three-state (IDLE/HIGH/LOW) counter FSM.

**Tech Stack:** Verilog/SystemVerilog, Icarus Verilog, cocotb (Python testbench), Tiny Tapeout toolchain.

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `src/spi_wrapper.sv` | Create (copy) | SPI slave register bank |
| `src/spi_reg.sv` | Create (copy) | SPI protocol FSM |
| `src/rising_edge_detector.sv` | Create (copy) | SPI helper |
| `src/falling_edge_detector.sv` | Create (copy) | SPI helper |
| `src/synchronizer.sv` | Create (copy) | SPI input sync chain |
| `src/reclocking.sv` | Create (copy) | Single-stage FF (used by synchronizer) |
| `src/sq_wave_gen.sv` | Create (new) | Per-channel counter FSM |
| `src/project.v` | Rewrite | Top-level wiring |
| `test/Makefile` | Modify | Add SV sources + `-g2012` flag |
| `test/test.py` | Rewrite | SPI + frequency tests |
| `info.yaml` | Modify | Metadata + source file list |
| `docs/info.md` | Modify | User-facing documentation |

---

## Task 1: Copy SPI source files from calonso88/tt07_alu_74181

**Files:**
- Create: `src/spi_wrapper.sv`
- Create: `src/spi_reg.sv`
- Create: `src/rising_edge_detector.sv`
- Create: `src/falling_edge_detector.sv`
- Create: `src/synchronizer.sv`
- Create: `src/reclocking.sv`

- [ ] **Step 1: Copy reclocking.sv**

Create `src/reclocking.sv`:
```systemverilog
/*
 * Copyright (c) 2024 Caio Alonso da Costa
 * SPDX-License-Identifier: Apache-2.0
 */

module reclocking #(parameter int WIDTH = 4) (rstb, clk, ena, data_in, data_out);
  input logic rstb;
  input logic clk;
  input logic ena;
  input logic [WIDTH-1:0] data_in;
  output logic [WIDTH-1:0] data_out;
  logic [WIDTH-1:0] data_sync;
  always_ff @(negedge(rstb) or posedge(clk)) begin
    if (!rstb) begin
      data_sync <= '0;
    end else begin
      if (ena == 1'b1) begin
        data_sync <= data_in;
      end
    end
  end
  assign data_out = data_sync;
endmodule
```

- [ ] **Step 2: Copy synchronizer.sv**

Create `src/synchronizer.sv`:
```systemverilog
/*
 * Copyright (c) 2024 Caio Alonso da Costa
 * SPDX-License-Identifier: Apache-2.0
 */

module synchronizer #(parameter int STAGES = 2, parameter int WIDTH = 4) (rstb, clk, ena, data_in, data_out);
  input logic rstb;
  input logic clk;
  input logic ena;
  input logic [WIDTH-1:0] data_in;
  output logic [WIDTH-1:0] data_out;
  logic [WIDTH-1:0] data_sync [STAGES+1];
  assign data_sync[0] = data_in;
  generate
    for (genvar i=0; i<STAGES; i++) begin : gen_reclocking
      reclocking #(.WIDTH(WIDTH)) reclocking_i0 (.rstb(rstb), .clk(clk), .ena(ena), .data_in(data_sync[i]), .data_out(data_sync[i+1]));
    end
  endgenerate
  assign data_out = data_sync[STAGES];
endmodule
```

- [ ] **Step 3: Copy rising_edge_detector.sv**

Create `src/rising_edge_detector.sv`:
```systemverilog
/*
 * Copyright (c) 2024 Caio Alonso da Costa
 * SPDX-License-Identifier: Apache-2.0
 */

module rising_edge_detector (rstb, clk, ena, data, pos_edge);
  input logic rstb;
  input logic clk;
  input logic ena;
  input logic data;
  output logic pos_edge;
  logic data_dly;
  always_ff @(negedge(rstb) or posedge(clk)) begin
    if (!rstb) begin
      data_dly <= '0;
    end else begin
      if (ena == 1'b1) begin
        data_dly <= data;
      end
    end
  end
  assign pos_edge = data & (!data_dly);
endmodule
```

- [ ] **Step 4: Copy falling_edge_detector.sv**

Create `src/falling_edge_detector.sv`:
```systemverilog
/*
 * Copyright (c) 2024 Caio Alonso da Costa
 * SPDX-License-Identifier: Apache-2.0
 */

module falling_edge_detector (rstb, clk, ena, data, neg_edge);
  input logic rstb;
  input logic clk;
  input logic ena;
  input logic data;
  output logic neg_edge;
  logic data_dly;
  always_ff @(negedge(rstb) or posedge(clk)) begin
    if (!rstb) begin
      data_dly <= '0;
    end else begin
      if (ena == 1'b1) begin
        data_dly <= data;
      end
    end
  end
  assign neg_edge = (!data) & data_dly;
endmodule
```

- [ ] **Step 5: Copy spi_reg.sv**

Create `src/spi_reg.sv` — copy verbatim from https://github.com/calonso88/tt07_alu_74181/blob/main/src/spi_reg.sv

The key interface (for reference):
```systemverilog
module spi_reg #(
    parameter int ADDR_W = 3,
    parameter int REG_W = 8
) (
    input  logic clk, rstb, ena,
    input  logic [1:0] mode,
    input  logic spi_mosi, spi_clk, spi_cs_n,
    output logic spi_miso,
    output logic [ADDR_W-1:0] reg_addr,
    input  logic [REG_W-1:0] reg_data_i,
    output logic [REG_W-1:0] reg_data_o,
    output logic reg_data_o_dv,
    input  logic [7:0] status
);
```

- [ ] **Step 6: Copy spi_wrapper.sv**

Create `src/spi_wrapper.sv` — copy verbatim from https://github.com/calonso88/tt07_alu_74181/blob/main/src/spi_wrapper.sv

The key interface (for reference):
```systemverilog
module spi_wrapper #(
    parameter int NUM_CFG = 8,
    parameter int NUM_STATUS = 8,
    parameter int REG_WIDTH = 8
) (
    input  logic rstb, clk, ena,
    input  logic [1:0] mode,
    input  logic spi_cs_n, spi_clk, spi_mosi,
    output logic spi_miso,
    output logic [NUM_CFG*REG_WIDTH-1:0] config_regs,
    input  logic [NUM_STATUS*REG_WIDTH-1:0] status_regs
);
```

- [ ] **Step 7: Commit**

```bash
git add src/reclocking.sv src/synchronizer.sv src/rising_edge_detector.sv \
        src/falling_edge_detector.sv src/spi_reg.sv src/spi_wrapper.sv
git commit -m "feat: add SPI source files from calonso88/tt07_alu_74181"
```

---

## Task 2: Update build configuration

**Files:**
- Modify: `test/Makefile:9`
- Modify: `info.yaml:19-20`

- [ ] **Step 1: Update test/Makefile**

Replace line 9 (`PROJECT_SOURCES = project.v`) and add a compile flag. The full updated section:
```makefile
SIM ?= icarus
FST ?= -fst
TOPLEVEL_LANG ?= verilog
SRC_DIR = $(PWD)/../src
PROJECT_SOURCES = project.v \
                  sq_wave_gen.sv \
                  spi_wrapper.sv \
                  spi_reg.sv \
                  rising_edge_detector.sv \
                  falling_edge_detector.sv \
                  synchronizer.sv \
                  reclocking.sv

ifneq ($(GATES),yes)

SIM_BUILD               = sim_build/rtl
VERILOG_SOURCES += $(addprefix $(SRC_DIR)/,$(PROJECT_SOURCES))
COMPILE_ARGS    += -g2012
```

(Keep the rest of the Makefile unchanged.)

- [ ] **Step 2: Update info.yaml source_files**

Replace the `source_files` section in `info.yaml`:
```yaml
  source_files:
    - "project.v"
    - "sq_wave_gen.sv"
    - "spi_wrapper.sv"
    - "spi_reg.sv"
    - "rising_edge_detector.sv"
    - "falling_edge_detector.sv"
    - "synchronizer.sv"
    - "reclocking.sv"
```

- [ ] **Step 3: Commit**

```bash
git add test/Makefile info.yaml
git commit -m "build: add SV source files and -g2012 compile flag"
```

---

## Task 3: Create sq_wave_gen stub and rewrite project.v

**Files:**
- Create: `src/sq_wave_gen.sv`
- Modify: `src/project.v`

The stub lets the design compile so we can run tests. The full state machine comes in Task 6.

- [ ] **Step 1: Create sq_wave_gen stub**

Create `src/sq_wave_gen.sv`:
```systemverilog
`default_nettype none

module sq_wave_gen (
    input  wire        clk,
    input  wire        rst_n,
    input  wire [23:0] on_count,
    input  wire [23:0] off_count,
    output reg         out
);
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) out <= 1'b0;
        else        out <= 1'b0;  // stub: always low
    end
    wire _unused = &{on_count, off_count, 1'b0};
endmodule
```

- [ ] **Step 2: Rewrite src/project.v**

Replace the entire contents of `src/project.v`:
```verilog
`default_nettype none

module tt_um_example (
    input  wire [7:0] ui_in,
    output wire [7:0] uo_out,
    input  wire [7:0] uio_in,
    output wire [7:0] uio_out,
    output wire [7:0] uio_oe,
    input  wire       ena,
    input  wire       clk,
    input  wire       rst_n
);

    localparam NUM_CFG    = 24;
    localparam NUM_STATUS = 24;
    localparam REG_WIDTH  = 8;

    wire [NUM_CFG*REG_WIDTH-1:0]    config_regs;
    wire [NUM_STATUS*REG_WIDTH-1:0] status_regs;
    wire spi_miso;

    // SPI pins: CS_N=uio[4], CLK=uio[5], MOSI=uio[6], MISO=uio[3]
    assign uio_oe  = 8'b0000_1000;   // uio[3]=MISO output, rest inputs
    assign uio_out = {4'b0, spi_miso, 3'b0};

    // CPOL=ui[0], CPHA=ui[1]; unused uo_out bits
    assign uo_out[7:4] = 4'b0;

    // Status registers unused
    assign status_regs = {(NUM_STATUS*REG_WIDTH){1'b0}};

    // Synchronise SPI inputs and mode bits (2-stage)
    localparam SYNC_STAGES = 2;
    wire spi_cs_n_sync, spi_clk_sync, spi_mosi_sync, cpol_sync, cpha_sync;

    synchronizer #(.STAGES(SYNC_STAGES), .WIDTH(1)) sync_cs_n  (.rstb(rst_n), .clk(clk), .ena(ena), .data_in(uio_in[4]), .data_out(spi_cs_n_sync));
    synchronizer #(.STAGES(SYNC_STAGES), .WIDTH(1)) sync_clk   (.rstb(rst_n), .clk(clk), .ena(ena), .data_in(uio_in[5]), .data_out(spi_clk_sync));
    synchronizer #(.STAGES(SYNC_STAGES), .WIDTH(1)) sync_mosi  (.rstb(rst_n), .clk(clk), .ena(ena), .data_in(uio_in[6]), .data_out(spi_mosi_sync));
    synchronizer #(.STAGES(SYNC_STAGES), .WIDTH(1)) sync_cpol  (.rstb(rst_n), .clk(clk), .ena(ena), .data_in(ui_in[0]),  .data_out(cpol_sync));
    synchronizer #(.STAGES(SYNC_STAGES), .WIDTH(1)) sync_cpha  (.rstb(rst_n), .clk(clk), .ena(ena), .data_in(ui_in[1]),  .data_out(cpha_sync));

    spi_wrapper #(
        .NUM_CFG   (NUM_CFG),
        .NUM_STATUS(NUM_STATUS),
        .REG_WIDTH (REG_WIDTH)
    ) spi_wrapper_i (
        .rstb      (rst_n),
        .clk       (clk),
        .ena       (ena),
        .mode      ({cpol_sync, cpha_sync}),
        .spi_cs_n  (spi_cs_n_sync),
        .spi_clk   (spi_clk_sync),
        .spi_mosi  (spi_mosi_sync),
        .spi_miso  (spi_miso),
        .config_regs(config_regs),
        .status_regs(status_regs)
    );

    // 4 square wave generators; channel i uses config regs [i*6 .. i*6+5]
    // config_regs layout: reg N occupies bits [N*8+7 : N*8]
    // on_count  = {reg[i*6], reg[i*6+1], reg[i*6+2]} = MSB..LSB
    // off_count = {reg[i*6+3], reg[i*6+4], reg[i*6+5]}
    genvar i;
    generate
        for (i = 0; i < 4; i = i + 1) begin : gen_ch
            sq_wave_gen ch_inst (
                .clk      (clk),
                .rst_n    (rst_n),
                .on_count ({config_regs[i*48 +  7 -: 8],
                            config_regs[i*48 + 15 -: 8],
                            config_regs[i*48 + 23 -: 8]}),
                .off_count({config_regs[i*48 + 31 -: 8],
                            config_regs[i*48 + 39 -: 8],
                            config_regs[i*48 + 47 -: 8]}),
                .out      (uo_out[i])
            );
        end
    endgenerate

endmodule
```

- [ ] **Step 3: Verify compilation**

```bash
cd test && make 2>&1 | head -40
```

Expected: simulation compiles. The test from the old test.py (`assert dut.uo_out.value == 50`) will fail, which is fine.

- [ ] **Step 4: Commit**

```bash
git add src/sq_wave_gen.sv src/project.v
git commit -m "feat: add sq_wave_gen stub and top-level wiring"
```

---

## Task 4: Write SPI register test and verify it passes

**Files:**
- Modify: `test/test.py`

This replaces the placeholder test with the adapted SPI R/W test from the referenced repo. The SPI layer is copied code so this should pass with no hardware changes.

- [ ] **Step 1: Write test.py with SPI register test**

Replace `test/test.py` entirely:

```python
# SPDX-FileCopyrightText: © 2024 Tiny Tapeout
# SPDX-License-Identifier: Apache-2.0

import random
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge


# ── SPI bit helpers (pin positions match calonso88/tt07_alu_74181) ──────────
# uio_in[4]=CS_N, uio_in[5]=SCK, uio_in[6]=MOSI
# uio_out[3]=MISO

def get_bit(value, bit_index):
    return value & (1 << bit_index)

def pull_cs_high(v):  return v |  (1 << 4)
def pull_cs_low(v):   return v & ~(1 << 4)
def spi_clk_high(v):  return v |  (1 << 5)
def spi_clk_low(v):   return v & ~(1 << 5)
def spi_clk_invert(v):return v ^  (1 << 5)
def spi_mosi_high(v): return v |  (1 << 6)
def spi_mosi_low(v):  return v & ~(1 << 6)
def spi_miso_read(port_out): return (int(port_out.value) >> 3) & 1


# ── 6-bit address SPI write (CPHA=1, data changes on rising, samples falling) ─
async def spi_write(clk, port, address, data):
    port.value = pull_cs_high(int(port.value))
    await ClockCycles(clk, 10)
    port.value = pull_cs_low(int(port.value))
    await ClockCycles(clk, 10)

    # Bit 7: R/W = 1 (write)
    port.value = spi_mosi_high(spi_clk_invert(int(port.value)))
    await ClockCycles(clk, 10)
    port.value = spi_clk_invert(int(port.value))
    await ClockCycles(clk, 10)

    # Bit 6: don't care (0)
    port.value = spi_mosi_low(spi_clk_invert(int(port.value)))
    await ClockCycles(clk, 10)
    port.value = spi_clk_invert(int(port.value))
    await ClockCycles(clk, 10)

    # Bits 5:0 — 6-bit address, MSB first
    for bit_idx in range(5, -1, -1):
        if get_bit(address, bit_idx):
            port.value = spi_mosi_high(spi_clk_invert(int(port.value)))
        else:
            port.value = spi_mosi_low(spi_clk_invert(int(port.value)))
        await ClockCycles(clk, 10)
        port.value = spi_clk_invert(int(port.value))
        await ClockCycles(clk, 10)

    # 8 data bits, MSB first
    for bit_idx in range(7, -1, -1):
        if get_bit(data, bit_idx):
            port.value = spi_mosi_high(spi_clk_invert(int(port.value)))
        else:
            port.value = spi_mosi_low(spi_clk_invert(int(port.value)))
        await ClockCycles(clk, 10)
        port.value = spi_clk_invert(int(port.value))
        await ClockCycles(clk, 10)

    port.value = pull_cs_high(int(port.value))
    await ClockCycles(clk, 10)


async def spi_read(clk, port_in, port_out, address):
    port_in.value = pull_cs_high(int(port_in.value))
    await ClockCycles(clk, 10)
    port_in.value = pull_cs_low(int(port_in.value))
    await ClockCycles(clk, 10)

    # Bit 7: R/W = 0 (read)
    port_in.value = spi_mosi_low(spi_clk_invert(int(port_in.value)))
    await ClockCycles(clk, 10)
    port_in.value = spi_clk_invert(int(port_in.value))
    await ClockCycles(clk, 10)

    # Bit 6: don't care (0)
    port_in.value = spi_mosi_low(spi_clk_invert(int(port_in.value)))
    await ClockCycles(clk, 10)
    port_in.value = spi_clk_invert(int(port_in.value))
    await ClockCycles(clk, 10)

    # Bits 5:0 — 6-bit address, MSB first
    for bit_idx in range(5, -1, -1):
        if get_bit(address, bit_idx):
            port_in.value = spi_mosi_high(spi_clk_invert(int(port_in.value)))
        else:
            port_in.value = spi_mosi_low(spi_clk_invert(int(port_in.value)))
        await ClockCycles(clk, 10)
        port_in.value = spi_clk_invert(int(port_in.value))
        await ClockCycles(clk, 10)

    miso_byte = 0
    # 8 data bits, MSB first — sample MISO on falling edge
    for bit_idx in range(7, -1, -1):
        port_in.value = spi_mosi_low(spi_clk_invert(int(port_in.value)))
        await ClockCycles(clk, 10)
        miso_byte |= (spi_miso_read(port_out) << bit_idx)
        port_in.value = spi_clk_invert(int(port_in.value))
        await ClockCycles(clk, 10)

    port_in.value = pull_cs_high(int(port_in.value))
    await ClockCycles(clk, 10)
    return miso_byte


async def set_channel(clk, uio_in, channel, on_count, off_count):
    """Write on_count and off_count (24-bit each) for the given channel (0-3)."""
    base = channel * 6
    await spi_write(clk, uio_in, base + 0, (on_count  >> 16) & 0xFF)
    await spi_write(clk, uio_in, base + 1, (on_count  >>  8) & 0xFF)
    await spi_write(clk, uio_in, base + 2,  on_count         & 0xFF)
    await spi_write(clk, uio_in, base + 3, (off_count >> 16) & 0xFF)
    await spi_write(clk, uio_in, base + 4, (off_count >>  8) & 0xFF)
    await spi_write(clk, uio_in, base + 5,  off_count        & 0xFF)


async def count_rising_edges(clk, signal, bit_idx, n_cycles):
    """Count rising edges on signal[bit_idx] over n_cycles clock cycles."""
    count = 0
    prev = (int(signal.value) >> bit_idx) & 1
    for _ in range(n_cycles):
        await RisingEdge(clk)
        curr = (int(signal.value) >> bit_idx) & 1
        if curr == 1 and prev == 0:
            count += 1
        prev = curr
    return count


async def reset_dut(dut):
    dut.ena.value   = 1
    dut.ui_in.value = 0b10   # CPHA=1 (bit1), CPOL=0 (bit0)
    dut.uio_in.value = pull_cs_high(0) | spi_clk_low(0)  # CS=1, SCK=0
    dut.rst_n.value  = 0
    await ClockCycles(dut.clk, 10)
    dut.rst_n.value  = 1
    await ClockCycles(dut.clk, 10)


# ── Test 1: SPI register round-trip ─────────────────────────────────────────

@cocotb.test()
async def test_spi_registers(dut):
    """Write random data to all 24 config registers and read back."""
    dut._log.info("test_spi_registers: start")
    clock = Clock(dut.clk, 20, units="ns")   # 50 MHz
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    for _ in range(3):
        written = [random.randint(0, 0xFF) for _ in range(24)]

        for reg, val in enumerate(written):
            await spi_write(dut.clk, dut.uio_in, reg, val)

        for reg, expected in enumerate(written):
            got = await spi_read(dut.clk, dut.uio_in, dut.uio_out, reg)
            assert got == expected, f"reg[{reg}]: wrote {expected:#04x}, read back {got:#04x}"

    dut._log.info("test_spi_registers: PASS")


# ── Test 2: Frequency generation ────────────────────────────────────────────

@cocotb.test()
async def test_frequency_generation(dut):
    """Program each channel and count rising edges to verify frequency."""
    dut._log.info("test_frequency_generation: start")
    clock = Clock(dut.clk, 20, units="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    test_cases = [
        # (channel, on_count, off_count, n_periods_to_run, expected_edges)
        (0,  5,  5, 4, 4),   # period=10 cyc, 5 MHz, 40 cyc → 4 edges
        (1,  5, 15, 4, 4),   # period=20 cyc, 2.5 MHz, 80 cyc → 4 edges
        (2, 20, 30, 4, 4),   # period=50 cyc, 1 MHz, 200 cyc → 4 edges
        (3,  3,  7, 4, 4),   # period=10 cyc, 5 MHz asymmetric, 40 cyc → 4 edges
    ]

    for ch, on, off, n_periods, expected in test_cases:
        dut._log.info(f"ch{ch}: on={on} off={off}")
        # Silence all channels first
        for c in range(4):
            await set_channel(dut.clk, dut.uio_in, c, 0, 0)
        await ClockCycles(dut.clk, 20)

        await set_channel(dut.clk, dut.uio_in, ch, on, off)

        period = on + off
        run_cycles = n_periods * period + period  # extra period for startup

        edges = await count_rising_edges(dut.clk, dut.uo_out, ch, run_cycles)
        # Accept ±1 edge for startup alignment
        assert abs(edges - expected) <= 1, \
            f"ch{ch} on={on} off={off}: expected ~{expected} edges, got {edges}"

    dut._log.info("test_frequency_generation: PASS")


# ── Test 3: Channel independence ────────────────────────────────────────────

@cocotb.test()
async def test_channel_independence(dut):
    """All 4 channels run simultaneously with different periods."""
    dut._log.info("test_channel_independence: start")
    clock = Clock(dut.clk, 20, units="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    # Silence all, then program all 4 channels
    for c in range(4):
        await set_channel(dut.clk, dut.uio_in, c, 0, 0)
    await ClockCycles(dut.clk, 20)

    # ch0: period=10, ch1: period=14, ch2: period=20, ch3: period=40
    await set_channel(dut.clk, dut.uio_in, 0,  5,  5)
    await set_channel(dut.clk, dut.uio_in, 1,  7,  7)
    await set_channel(dut.clk, dut.uio_in, 2, 10, 10)
    await set_channel(dut.clk, dut.uio_in, 3, 20, 20)

    # Run for exactly LCM(10,14,20,40)=280 cycles → integer number of periods for all channels
    # Expected rising edges: 28, 20, 14, 7 respectively
    run_cycles = 280
    edges = [0] * 4
    prev  = [0] * 4
    for _ in range(run_cycles):
        await RisingEdge(dut.clk)
        val = int(dut.uo_out.value)
        for ch in range(4):
            curr = (val >> ch) & 1
            if curr == 1 and prev[ch] == 0:
                edges[ch] += 1
            prev[ch] = curr

    for ch, (expected_approx) in enumerate([28, 20, 14, 7]):
        assert abs(edges[ch] - expected_approx) <= 1, \
            f"ch{ch}: expected ~{expected_approx} edges, got {edges[ch]}"

    dut._log.info("test_channel_independence: PASS")


# ── Test 4: Channel silence ──────────────────────────────────────────────────

@cocotb.test()
async def test_channel_silence(dut):
    """Setting on_count=0, off_count=0 holds output LOW."""
    dut._log.info("test_channel_silence: start")
    clock = Clock(dut.clk, 20, units="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    # Start a channel, then silence it
    await set_channel(dut.clk, dut.uio_in, 0, 10, 10)
    await ClockCycles(dut.clk, 50)   # let it run briefly
    await set_channel(dut.clk, dut.uio_in, 0, 0, 0)
    await ClockCycles(dut.clk, 30)   # wait for current phase to expire

    edges = await count_rising_edges(dut.clk, dut.uo_out, 0, 200)
    assert edges == 0, f"silenced channel produced {edges} rising edges"

    dut._log.info("test_channel_silence: PASS")
```

- [ ] **Step 2: Run the SPI register test only**

```bash
cd test && make COCOTB_TEST_MODULES=test TESTCASE=test_spi_registers 2>&1 | tail -20
```

Expected output: `test_spi_registers PASSED`

If it fails with a compilation error, check that all `.sv` files are in `src/` and `PROJECT_SOURCES` in `test/Makefile` lists them all.

- [ ] **Step 3: Commit passing SPI test**

```bash
git add test/test.py
git commit -m "test: add SPI register round-trip test (passes)"
```

---

## Task 5: Verify frequency tests fail with stub

**Files:** none (just running existing tests)

- [ ] **Step 1: Run frequency test against stub**

```bash
cd test && make TESTCASE=test_frequency_generation 2>&1 | tail -20
```

Expected: `test_frequency_generation FAILED` — the stub always outputs 0, so `edges == 0` but `expected == 4`.

This confirms the test is exercising the real behaviour.

---

## Task 6: Implement sq_wave_gen state machine

**Files:**
- Modify: `src/sq_wave_gen.sv`

- [ ] **Step 1: Replace stub with full implementation**

Replace the entire contents of `src/sq_wave_gen.sv`:
```systemverilog
`default_nettype none

module sq_wave_gen (
    input  wire        clk,
    input  wire        rst_n,
    input  wire [23:0] on_count,
    input  wire [23:0] off_count,
    output reg         out
);

    typedef enum logic [1:0] {
        IDLE = 2'b00,
        HIGH = 2'b01,
        LOW  = 2'b10
    } state_t;

    state_t  state;
    reg [23:0] counter;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state   <= IDLE;
            counter <= 24'd0;
            out     <= 1'b0;
        end else begin
            case (state)

                IDLE: begin
                    if (on_count != 0 || off_count != 0) begin
                        state   <= HIGH;
                        counter <= on_count;
                        out     <= 1'b1;
                    end
                end

                HIGH: begin
                    if (counter <= 24'd1) begin
                        if (on_count == 0 && off_count == 0) begin
                            state <= IDLE;
                            out   <= 1'b0;
                        end else if (off_count != 0) begin
                            state   <= LOW;
                            counter <= off_count;
                            out     <= 1'b0;
                        end else begin
                            // off_count=0: stay HIGH, reload
                            counter <= on_count;
                        end
                    end else begin
                        counter <= counter - 24'd1;
                    end
                end

                LOW: begin
                    if (counter <= 24'd1) begin
                        if (on_count == 0 && off_count == 0) begin
                            state <= IDLE;
                            out   <= 1'b0;
                        end else if (on_count != 0) begin
                            state   <= HIGH;
                            counter <= on_count;
                            out     <= 1'b1;
                        end else begin
                            // on_count=0: stay LOW, reload
                            counter <= off_count;
                        end
                    end else begin
                        counter <= counter - 24'd1;
                    end
                end

                default: state <= IDLE;

            endcase
        end
    end

endmodule
```

- [ ] **Step 2: Run frequency generation test**

```bash
cd test && make TESTCASE=test_frequency_generation 2>&1 | tail -20
```

Expected: `test_frequency_generation PASSED`

- [ ] **Step 3: Run all tests**

```bash
cd test && make 2>&1 | tail -30
```

Expected: all 4 tests PASSED.

- [ ] **Step 4: Commit**

```bash
git add src/sq_wave_gen.sv
git commit -m "feat: implement sq_wave_gen IDLE/HIGH/LOW state machine"
```

---

## Task 7: Update project metadata and documentation

**Files:**
- Modify: `info.yaml`
- Modify: `docs/info.md`

- [ ] **Step 1: Update info.yaml metadata**

Fill in the top section of `info.yaml` (leave `source_files` as set in Task 2):
```yaml
project:
  title:       "Simple Signal Generator"
  author:      "Matt Venn"
  discord:     ""
  description: "4-channel square wave generator with SPI-programmable on/off counts per channel"
  language:    "Verilog"
  clock_hz:    50000000

  tiles: "1x1"
  top_module: "tt_um_example"
```

Update the pinout section:
```yaml
pinout:
  ui[0]: "SPI CPOL"
  ui[1]: "SPI CPHA"
  ui[2]: ""
  ui[3]: ""
  ui[4]: ""
  ui[5]: ""
  ui[6]: ""
  ui[7]: ""

  uo[0]: "Channel 0 square wave output"
  uo[1]: "Channel 1 square wave output"
  uo[2]: "Channel 2 square wave output"
  uo[3]: "Channel 3 square wave output"
  uo[4]: ""
  uo[5]: ""
  uo[6]: ""
  uo[7]: ""

  uio[0]: ""
  uio[1]: ""
  uio[2]: ""
  uio[3]: "SPI MISO"
  uio[4]: "SPI CS_N (active low)"
  uio[5]: "SPI CLK"
  uio[6]: "SPI MOSI"
  uio[7]: ""
```

- [ ] **Step 2: Update docs/info.md**

Replace `docs/info.md` with:
```markdown
## How it works

Four independent square wave generators drive `uo[3:0]`. Each channel's high-time
(`on_count`) and low-time (`off_count`) are programmed independently via SPI, giving
full control over frequency and duty cycle per channel.

At 50 MHz, the smallest programmable period is 2 clock cycles (25 MHz). To generate
a 10 Hz square wave at 50% duty cycle, set `on_count = off_count = 2_500_000`.

Setting both counts to zero silences the channel (output held LOW).

## How to test

The SPI master (e.g. RP2350 running MicroPython) programs each channel using
`machine.SPI`. Each SPI frame is 2 bytes:

- Byte 0: `0x80 | reg_addr` (write), or `reg_addr` (read)
- Byte 1: data

Register map (6 registers per channel, big-endian):

| Reg | Ch | Field |
|-----|----|-------|
| 0–2 | 0 | on_count [23:16], [15:8], [7:0] |
| 3–5 | 0 | off_count [23:16], [15:8], [7:0] |
| 6–11 | 1 | on_count, off_count |
| 12–17 | 2 | on_count, off_count |
| 18–23 | 3 | on_count, off_count |

MicroPython example (50% duty, 1 kHz on ch0):

```python
from machine import SPI, Pin
spi = SPI(0, baudrate=1_000_000, polarity=0, phase=1)
cs  = Pin(5, Pin.OUT, value=1)

def write_reg(reg, val):
    cs.value(0)
    spi.write(bytes([0x80 | reg, val]))
    cs.value(1)

on = off = 25_000  # 25_000_000 // 1000
for i, v in enumerate([(on>>16)&0xFF, (on>>8)&0xFF, on&0xFF,
                        (off>>16)&0xFF,(off>>8)&0xFF, off&0xFF]):
    write_reg(i, v)
```

## External hardware

- RP2350 (or any SPI master) connected to `uio[6:4]` (MOSI, CLK, CS_N) and `uio[3]` (MISO)
- Oscilloscope or frequency counter on `uo[3:0]`
```

- [ ] **Step 3: Run full test suite one final time**

```bash
cd test && make 2>&1 | tail -10
```

Expected: 4 tests PASSED, 0 FAILED.

- [ ] **Step 4: Final commit**

```bash
git add info.yaml docs/info.md
git commit -m "docs: update project metadata, pinout, and user documentation"
```
