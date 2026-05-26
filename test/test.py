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
    """Write on_count and off_count (16-bit each) for the given channel (0-3)."""
    base = channel * 4
    await spi_write(clk, uio_in, base + 0, (on_count  >>  8) & 0xFF)
    await spi_write(clk, uio_in, base + 1,  on_count         & 0xFF)
    await spi_write(clk, uio_in, base + 2, (off_count >>  8) & 0xFF)
    await spi_write(clk, uio_in, base + 3,  off_count        & 0xFF)


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
    """Write random data to all 16 config registers and read back."""
    dut._log.info("test_spi_registers: start")
    clock = Clock(dut.clk, 20, units="ns")   # 50 MHz
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    for _ in range(3):
        written = [random.randint(0, 0xFF) for _ in range(16)]

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
        (0,  5,  5, 4, 4),   # period=10 cyc, 5 MHz, run extra → ~4 edges
        (1,  5, 15, 4, 4),   # period=20 cyc, 2.5 MHz
        (2, 20, 30, 4, 4),   # period=50 cyc, 1 MHz
        (3,  3,  7, 4, 4),   # period=10 cyc, 5 MHz asymmetric
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

    # Run for exactly LCM(10,14,20,40)=280 cycles
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

    for ch, expected_approx in enumerate([28, 20, 14, 7]):
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
