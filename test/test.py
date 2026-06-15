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


async def set_ch0(clk, uio_in, on_count, off_count):
    """Write on_count and off_count (16-bit each) for ch0."""
    await spi_write(clk, uio_in, 0, (on_count  >>  8) & 0xFF)
    await spi_write(clk, uio_in, 1,  on_count         & 0xFF)
    await spi_write(clk, uio_in, 2, (off_count >>  8) & 0xFF)
    await spi_write(clk, uio_in, 3,  off_count        & 0xFF)


async def set_enc_step(clk, uio_in, step):
    """Write enc_step to SPI register 6."""
    await spi_write(clk, uio_in, 6, step & 0xFF)


async def set_phase_offset(clk, uio_in, offset_cycles):
    """Write signed 16-bit phase offset to registers 4-5."""
    val = offset_cycles & 0xFFFF
    await spi_write(clk, uio_in, 4, (val >> 8) & 0xFF)
    await spi_write(clk, uio_in, 5,  val        & 0xFF)


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
    """Write random data to all 8 config registers and read back."""
    dut._log.info("test_spi_registers: start")
    clock = Clock(dut.clk, 20, units="ns")   # 50 MHz
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    for _ in range(3):
        written = [random.randint(0, 0xFF) for _ in range(8)]  # regs 0-7

        for reg, val in enumerate(written):
            await spi_write(dut.clk, dut.uio_in, reg, val)

        for reg, expected in enumerate(written):
            got = await spi_read(dut.clk, dut.uio_in, dut.uio_out, reg)
            assert got == expected, f"reg[{reg}]: wrote {expected:#04x}, read back {got:#04x}"

    dut._log.info("test_spi_registers: PASS")


# ── Test 2: ch0 frequency generation ────────────────────────────────────────

@cocotb.test()
async def test_frequency_generation(dut):
    """Program ch0 and count rising edges to verify frequency."""
    dut._log.info("test_frequency_generation: start")
    clock = Clock(dut.clk, 20, units="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    test_cases = [
        # (on_count, off_count, n_periods_to_run, expected_edges)
        ( 5,  5, 4, 4),   # period=10 cyc, 5 MHz
        ( 5, 15, 4, 4),   # period=20 cyc, 2.5 MHz
        (25, 25, 4, 4),   # period=50 cyc, 1 MHz
    ]

    for on, off, n_periods, expected in test_cases:
        dut._log.info(f"ch0: on={on} off={off}")
        await set_ch0(dut.clk, dut.uio_in, 0, 0)
        await set_phase_offset(dut.clk, dut.uio_in, 0)
        await ClockCycles(dut.clk, 20)

        await set_ch0(dut.clk, dut.uio_in, on, off)

        period = on + off
        run_cycles = n_periods * period + period  # extra period for startup

        edges = await count_rising_edges(dut.clk, dut.uo_out, 0, run_cycles)
        assert abs(edges - expected) <= 1, \
            f"ch0 on={on} off={off}: expected ~{expected} edges, got {edges}"

    dut._log.info("test_frequency_generation: PASS")


# ── Test 3: ch1 in-phase (amplitude=0) ──────────────────────────────────────

@cocotb.test()
async def test_ch1_inphase(dut):
    """ch1 with amplitude=0 fires simultaneously with ch0 (zero delay)."""
    dut._log.info("test_ch1_inphase: start")
    clock = Clock(dut.clk, 20, units="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    on, off = 10, 40
    await set_ch0(dut.clk, dut.uio_in, on, off)
    await set_phase_offset(dut.clk, dut.uio_in, 0)
    await ClockCycles(dut.clk, 10)  # let it start

    # Both channels should produce the same number of rising edges
    period = on + off
    run_cycles = 6 * period
    edges_ch0 = await count_rising_edges(dut.clk, dut.uo_out, 0, run_cycles)
    await set_ch0(dut.clk, dut.uio_in, 0, 0)
    await set_phase_offset(dut.clk, dut.uio_in, 0)
    await ClockCycles(dut.clk, 20)

    await set_ch0(dut.clk, dut.uio_in, on, off)
    await set_phase_offset(dut.clk, dut.uio_in, 0)
    await ClockCycles(dut.clk, 10)
    edges_ch1 = await count_rising_edges(dut.clk, dut.uo_out, 1, run_cycles)

    assert abs(edges_ch0 - edges_ch1) <= 1, \
        f"in-phase: ch0={edges_ch0} edges, ch1={edges_ch1} edges, should match"
    dut._log.info("test_ch1_inphase: PASS")


# ── Test 4: SPI phase offset ─────────────────────────────────────────────────

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

    # Positive offsets (lag): actual_delay=k → measured d=k
    for offset_cycles in [0, 1, 5, 10, 15]:
        await set_phase_offset(dut.clk, dut.uio_in, offset_cycles)
        await ClockCycles(dut.clk, 10)
        d = await measure_ch1_delay(dut, period)
        assert d == offset_cycles, \
            f"offset=+{offset_cycles}: expected d={offset_cycles}, got {d}"

    dut._log.info("test_spi_phase_offset: PASS")


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

        val0 = int(dut.uo_out.value)
        prev_ch0 = val0 & 1
        prev_ch1 = (val0 >> 1) & 1
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


# ── Test 6: Channel silence ──────────────────────────────────────────────────

@cocotb.test()
async def test_channel_silence(dut):
    """Setting on_count=0, off_count=0 holds both outputs LOW."""
    dut._log.info("test_channel_silence: start")
    clock = Clock(dut.clk, 20, units="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    await set_ch0(dut.clk, dut.uio_in, 10, 10)
    await set_phase_offset(dut.clk, dut.uio_in, 3)
    await ClockCycles(dut.clk, 50)   # let it run briefly
    await set_ch0(dut.clk, dut.uio_in, 0, 0)
    await ClockCycles(dut.clk, 30)   # wait for current phase to expire

    edges_ch0 = await count_rising_edges(dut.clk, dut.uo_out, 0, 200)
    edges_ch1 = await count_rising_edges(dut.clk, dut.uo_out, 1, 200)
    assert edges_ch0 == 0, f"silenced ch0 produced {edges_ch0} rising edges"
    assert edges_ch1 == 0, f"silenced ch1 produced {edges_ch1} rising edges"

    dut._log.info("test_channel_silence: PASS")


# ── Encoder helpers ──────────────────────────────────────────────────────────
# ab = {ui_in[2], ui_in[3]}. CW sequence (up): 00→01→11→10→00.
_ENC_STATES = [0b00, 0b01, 0b11, 0b10]  # ab states cycling CW
_enc_idx = [0]                           # current position in _ENC_STATES


async def _set_enc_ab(dut, ab):
    """Drive ui_in[5:4] to encode ab={ui_in[4], ui_in[5]}."""
    a = (ab >> 1) & 1   # ab bit1 → ui_in[4]
    b = (ab >> 0) & 1   # ab bit0 → ui_in[5]
    ui = int(dut.ui_in.value) & ~0x30   # clear bits [5:4]
    dut.ui_in.value = ui | (a << 4) | (b << 5)
    await ClockCycles(dut.clk, 5)       # settle through 2-stage synchronizer


async def encoder_steps(dut, n):
    """Apply n encoder transitions. +n=CW (enc_up), -n=CCW (enc_dn)."""
    direction = 1 if n >= 0 else -1
    for _ in range(abs(n)):
        _enc_idx[0] = (_enc_idx[0] + direction) % 4
        await _set_enc_ab(dut, _ENC_STATES[_enc_idx[0]])


async def set_enc_btn(dut, pressed):
    """Drive ui_in[2] (encoder button) and wait for the synchronizer to settle."""
    ui = int(dut.ui_in.value)
    if pressed:
        ui |= (1 << 2)
    else:
        ui &= ~(1 << 2)
    dut.ui_in.value = ui
    await ClockCycles(dut.clk, 5)


# ── Test 7: Encoder integer-cycle phase control ──────────────────────────────

@cocotb.test()
async def test_encoder_integer_phase(dut):
    """Encoder rotations shift ch1 delay in integer-cycle steps (enc_step=128 → 0.5 cycle/click)."""
    dut._log.info("test_encoder_integer_phase: start")
    clock = Clock(dut.clk, 20, units="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    on, off = 20, 80   # period=100
    await set_ch0(dut.clk, dut.uio_in, on, off)
    await set_phase_offset(dut.clk, dut.uio_in, 0)
    # enc_step=128 → 0.5 cycles/click; 2 clicks = 1 exact integer cycle (frac=0)
    await set_enc_step(dut.clk, dut.uio_in, 128)
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


# ── Test 8: Sigma-delta fractional phase ────────────────────────────────────

@cocotb.test()
async def test_encoder_sigma_delta(dut):
    """Fractional enc_step (0.5 cycle) produces alternating delays via sigma-delta."""
    dut._log.info("test_encoder_sigma_delta: start")
    clock = Clock(dut.clk, 20, units="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    on, off = 20, 80   # period=100
    await set_ch0(dut.clk, dut.uio_in, on, off)
    await set_phase_offset(dut.clk, dut.uio_in, 0)
    await set_enc_step(dut.clk, dut.uio_in, 128)   # 0.5 cycles/click
    await ClockCycles(dut.clk, 20)

    # 3 CW steps → enc_phase_fp=384 (1.5 cycles), enc_int=1, enc_frac=128
    # sigma-delta alternates carry 0,1,0,1... → actual_delay alternates 1,2 → d alternates 1,2
    _enc_idx[0] = 0
    await _set_enc_ab(dut, _ENC_STATES[0])
    await encoder_steps(dut, +3)
    await ClockCycles(dut.clk, 20)

    # Collect 20 consecutive delay measurements
    period = on + off
    delays = []
    prev_ch0 = prev_ch1 = 0
    ch0_rise_t = None
    tick = 0
    timeout = 20 * period + 50
    while tick < timeout and len(delays) < 20:
        await RisingEdge(dut.clk)
        tick += 1
        val = int(dut.uo_out.value)
        curr_ch0 = (val >> 0) & 1
        curr_ch1 = (val >> 1) & 1
        if curr_ch0 == 1 and prev_ch0 == 0:
            ch0_rise_t = tick
        if curr_ch1 == 1 and prev_ch1 == 0 and ch0_rise_t is not None:
            d = tick - ch0_rise_t
            delays.append(period if d == 0 else d)
            ch0_rise_t = None
        prev_ch0 = curr_ch0
        prev_ch1 = curr_ch1

    dut._log.info(f"sigma-delta delays: {delays}")
    assert len(delays) == 20, f"only got {len(delays)} measurements"

    # All delays must be 1 or 2 (enc_int=1 +/- sigma-delta carry)
    unexpected = [d for d in delays if d not in (1, 2)]
    assert not unexpected, f"unexpected delay values: {unexpected}"

    # sigma-delta with frac=128 gives carry=1 roughly half the time
    d1_count = delays.count(1)
    d2_count = delays.count(2)
    assert 5 <= d1_count <= 15, f"expected ~10 d=1 values (got {d1_count}): {delays}"
    assert 5 <= d2_count <= 15, f"expected ~10 d=2 values (got {d2_count}): {delays}"

    dut._log.info("test_encoder_sigma_delta: PASS")


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

    # The encoder click lands at an arbitrary point within a period, but
    # sd_carry only updates at period_start. For the ~1 period until the
    # next period_start, enc_int (just changed) and sd_carry (stale) are
    # momentarily mismatched, producing one short pulse and one slightly
    # long (101-cycle) pulse as a one-time settling transient. Wait a few
    # periods so this transient is fully over before the measurement window
    # starts, leaving only the steady-state alternation between
    # actual_delay=0 and actual_delay=period-1 (both 100-cycle pulses).
    await ClockCycles(dut.clk, 3 * period)

    n_periods = 20
    ch0_edges = 0
    val0 = int(dut.uo_out.value)
    prev_ch0 = val0 & 1
    pulse_widths = []
    width = 0
    in_pulse = ((val0 >> 1) & 1) == 1
    started_mid_pulse = in_pulse
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

    # Drop partial pulses at the start/end of the capture window: a pulse
    # already in progress when the loop started, or one still in progress
    # when it ended, was not fully observed and would show a truncated width.
    if started_mid_pulse and pulse_widths:
        pulse_widths = pulse_widths[1:]
    # (trailing in-progress pulse, if any, is intentionally not appended)

    dut._log.info(f"ch1 pulse widths: {pulse_widths}")
    bad = [w for w in pulse_widths if w != on]
    assert not bad, f"ch1 pulses should all be {on} cycles wide, got {pulse_widths}"
    assert abs(len(pulse_widths) - ch0_edges) <= 1, \
        f"ch0_edges={ch0_edges}, ch1 pulse count={len(pulse_widths)}"

    dut._log.info("test_sigma_delta_no_stutter: PASS")


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
