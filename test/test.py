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


async def measure_ch1_delay(dut):
    """After one ch0 rising edge, return how many cycles until ch1 rises."""
    await RisingEdge(dut.clk)
    # wait for ch0 rising edge
    while True:
        await RisingEdge(dut.clk)
        ch0_curr = (int(dut.uo_out.value) >> 0) & 1
        ch0_prev_val = getattr(measure_ch1_delay, '_ch0_prev', 0)
        measure_ch1_delay._ch0_prev = ch0_curr
        if ch0_curr == 1 and ch0_prev_val == 0:
            break

    # count cycles until ch1 rises
    for delay in range(1, 10000):
        await RisingEdge(dut.clk)
        if (int(dut.uo_out.value) >> 1) & 1:
            return delay
    return None  # ch1 never rose


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

    # Positive offsets (lag): actual_delay=k → measured d=k+1
    # measure_ch1_delay checks ch1 high (not rising edge), so only valid for lag
    # where ch1 fires fresh each period without overlapping into the next.
    for offset_cycles in [0, 1, 5, 10, 15]:
        await set_phase_offset(dut.clk, dut.uio_in, offset_cycles)
        await ClockCycles(dut.clk, 10)
        d = await measure_ch1_delay(dut)
        expected = offset_cycles + 1
        assert d == expected, \
            f"offset=+{offset_cycles}: expected d={expected}, got {d}"

    dut._log.info("test_spi_phase_offset: PASS")


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

    # Reset encoder to known state 00
    _enc_idx[0] = 0
    await _set_enc_ab(dut, _ENC_STATES[0])
    await ClockCycles(dut.clk, 10)

    # Baseline: enc_phase_fp=0 → actual_delay=0 → d=1
    d0 = await measure_ch1_delay(dut)
    assert d0 == 1, f"baseline: expected d=1 (in-phase), got {d0}"

    # 2 CW steps → enc_phase_fp=256 (1.0 cycle), enc_int=1, frac=0 → actual_delay=1 → d=2
    await encoder_steps(dut, +2)
    await ClockCycles(dut.clk, 10)
    d1 = await measure_ch1_delay(dut)
    assert d1 == 2, f"after +2 steps (1 cycle lag): expected d=2, got {d1}"

    # 2 more CW steps → enc_phase_fp=512 (2.0 cycles) → actual_delay=2 → d=3
    await encoder_steps(dut, +2)
    await ClockCycles(dut.clk, 10)
    d2 = await measure_ch1_delay(dut)
    assert d2 == 3, f"after +4 steps (2 cycle lag): expected d=3, got {d2}"

    # 2 CCW steps → back to 256 (1.0 cycle) → d=2
    await encoder_steps(dut, -2)
    await ClockCycles(dut.clk, 10)
    d3 = await measure_ch1_delay(dut)
    assert d3 == 2, f"after -2 steps (back to 1 cycle): expected d=2, got {d3}"

    # 2 more CCW steps → back to 0 → d=1
    await encoder_steps(dut, -2)
    await ClockCycles(dut.clk, 10)
    d4 = await measure_ch1_delay(dut)
    assert d4 == 1, f"after returning to zero: expected d=1, got {d4}"

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
    # sigma-delta alternates carry 0,1,0,1... → actual_delay alternates 1,2 → d alternates 2,3
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

    # All delays must be 2 or 3 (enc_int=1 ± sigma-delta carry)
    unexpected = [d for d in delays if d not in (2, 3)]
    assert not unexpected, f"unexpected delay values: {unexpected}"

    # sigma-delta with frac=128 gives carry=1 roughly half the time
    d2_count = delays.count(2)
    d3_count = delays.count(3)
    assert 5 <= d2_count <= 15, f"expected ~10 d=2 values (got {d2_count}): {delays}"
    assert 5 <= d3_count <= 15, f"expected ~10 d=3 values (got {d3_count}): {delays}"

    dut._log.info("test_encoder_sigma_delta: PASS")
