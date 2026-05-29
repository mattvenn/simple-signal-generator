"""
Hardware-in-the-loop tests for the Simple Signal Generator.

Wiring:
  uo_out[0] → scope CH1  (channel 0 square wave)
  uo_out[1] → scope CH2  (channel 1 phase-shifted output)

Prerequisites:
  pip install pyvisa pyvisa-py  (or NI-VISA backend)
  mpremote must be on PATH
  demo.py must already be on the RP2350 (mpremote cp scripts/demo.py :)

Environment variables:
  SCOPE_RESOURCE   VISA resource string  (default: TCPIP0::192.168.50.11::inst0::INSTR)
  MPREMOTE_DEV     mpremote device path  (default: auto)

Run:
  pytest test/test_hil.py -v
"""

import os
import subprocess
import time

import pytest
import pyvisa

SCOPE_RESOURCE = os.environ.get("SCOPE_RESOURCE", "TCPIP0::192.168.50.11::inst0::INSTR")
MPREMOTE_DEV   = os.environ.get(
    "MPREMOTE_DEV",
    "/dev/serial/by-id/usb-MicroPython_Board_in_FS_mode_6f890b97e48ced01-if00",
)

CLOCK_HZ       = 50_000_000
FREQ_TOL       = 0.02   # 2% tolerance for frequency measurements
PHASE_TOL_CYC  = 2      # ±2 clock cycles tolerance for phase measurements
SETTLE_S       = 2.0    # seconds to wait after scope configuration before measuring

FREQ_TEST_CASES = [1_000, 10_000, 100_000, 1_000_000]

PHASE_TEST_CASES = [
    # (freq_hz, offset_cycles)  — offset must be < off_count (half-period at 50% duty)
    (10_000,    100),
    (10_000,    500),
    (10_000,  1_000),
    ( 1_000,  5_000),
]

BOILERPLATE = [
    "import gc",
    "gc.threshold(10000)",
    "from ttboard.demoboard import DemoBoard",
    "from ttboard.boot.demoboard_detect import DemoboardDetect",
    "DemoboardDetect.probe()",
    "tt = DemoBoard()",
    "tt.shuttle.tt_um_mattvenn_signal_generator.enable()",
    "tt.clock_project_PWM(50_000_000)",
    "tt.reset_project(True)",
    "tt.reset_project(False)",
    "tt.ui_in[0] = 0",
    "tt.ui_in[1] = 0",
    "import demo",
    "spi, cs = demo.init_spi()",
    "demo.silence(spi, cs)",
]


# ── helpers ───────────────────────────────────────────────────────────────────

def _clean_env():
    env = os.environ.copy()
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    return env


def _mpremote_exec(code):
    args = ["mpremote"]
    if MPREMOTE_DEV != "auto":
        args += ["connect", MPREMOTE_DEV]
    r = subprocess.run(
        args + ["exec", code],
        capture_output=True, text=True, timeout=30,
        env=_clean_env(),
    )
    if r.stdout.strip():
        print(f"\n[mpremote] {r.stdout.strip()}")
    if r.returncode != 0:
        raise RuntimeError(
            f"mpremote exec failed (rc={r.returncode})\n"
            f"stdout: {r.stdout.strip()}\n"
            f"stderr: {r.stderr.strip()}"
        )


def _hz(freq_hz):
    """Human-readable frequency string."""
    if freq_hz >= 1_000_000:
        return f"{freq_hz // 1_000_000} MHz"
    if freq_hz >= 1_000:
        return f"{freq_hz // 1_000} kHz"
    return f"{freq_hz} Hz"


def _program_ch0(freq_hz):
    period    = CLOCK_HZ // freq_hz
    on_count  = period // 2
    off_count = period - on_count
    period_us = period / (CLOCK_HZ / 1e6)
    print(f"\n  programming: ch0 {_hz(freq_hz)}  on={on_count} off={off_count} cycles  period={period_us:.2f} µs")
    print(f"  expect on scope CH1: {_hz(freq_hz)} square wave, 50% duty")
    _mpremote_exec("\n".join([
        *BOILERPLATE,
        f"demo.set_ch0_counts(spi, cs, {on_count}, {off_count})",
    ]))


def _program_phase(freq_hz, offset_cycles):
    period    = CLOCK_HZ // freq_hz
    on_count  = period // 2
    off_count = period - on_count
    offset_us = offset_cycles / (CLOCK_HZ / 1e6)
    print(f"\n  programming: ch0 {_hz(freq_hz)}  offset={offset_cycles} cycles ({offset_us:.2f} µs)")
    print(f"  expect on scope: CH1={_hz(freq_hz)} square wave, CH2 lags CH1 by {offset_us:.2f} µs")
    _mpremote_exec("\n".join([
        *BOILERPLATE,
        f"demo.set_ch0_counts(spi, cs, {on_count}, {off_count})",
        f"demo.set_phase_offset(spi, cs, {offset_cycles})",
    ]))


def _measure_freq(scope, scope_ch, freq_hz):
    time_per_div = (10.0 / freq_hz) / 10   # 10 complete cycles on screen
    scope.write(f":TIMebase:SCALe {time_per_div:.3e}")
    scope.write(":RUN")                      # force re-acquisition at new timebase
    scope.write(f":MEASure:FREQuency CHANnel{scope_ch}")
    time.sleep(SETTLE_S)
    raw  = scope.query(f":MEASure:FREQuency? CHANnel{scope_ch}").strip()
    freq = float(raw)
    if freq > 1e30:
        raise RuntimeError(
            f"Scope CH{scope_ch} returned no valid frequency measurement — check probe"
        )
    tol = freq_hz * FREQ_TOL
    print(f"  measured: {freq:.2f} Hz  (expected {freq_hz} ± {tol:.0f} Hz)  {'OK' if abs(freq - freq_hz) <= tol else 'FAIL'}")
    return freq


def _measure_delay_cycles(scope, freq_hz, offset_cycles):
    """Return the CH1→CH2 rising-edge delay in clock cycles."""
    period_s     = 1.0 / freq_hz
    time_per_div = (3 * period_s) / 10
    scope.write(f":TIMebase:SCALe {time_per_div:.3e}")
    scope.write(":TRIGger:EDGE:SOURce CHANnel1")
    scope.write(":MEASure:DELay CHANnel1,CHANnel2")
    time.sleep(SETTLE_S)
    raw     = scope.query(":MEASure:DELay? CHANnel1,CHANnel2").strip()
    delay_s = float(raw)
    if delay_s > 1e30:
        raise RuntimeError(
            "Scope returned no valid delay measurement — check both probes"
        )
    measured_cycles = delay_s * CLOCK_HZ
    offset_us = offset_cycles / (CLOCK_HZ / 1e6)
    print(f"  measured: {measured_cycles:.1f} cycles ({delay_s*1e6:.3f} µs)  "
          f"(expected {offset_cycles} ± {PHASE_TOL_CYC} cycles / {offset_us:.2f} µs)  "
          f"{'OK' if abs(measured_cycles - offset_cycles) <= PHASE_TOL_CYC else 'FAIL'}")
    return measured_cycles


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def scope():
    rm   = pyvisa.ResourceManager()
    inst = rm.open_resource(SCOPE_RESOURCE)
    inst.timeout = 5000
    print(f"\nScope: {inst.query('*IDN?').strip()}")
    yield inst
    inst.close()
    rm.close()


# ── tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("freq_hz", FREQ_TEST_CASES)
def test_ch0_frequency(scope, freq_hz):
    _program_ch0(freq_hz)
    measured = _measure_freq(scope, 1, freq_hz)
    tol = freq_hz * FREQ_TOL
    assert abs(measured - freq_hz) <= tol, (
        f"ch0 {freq_hz} Hz: scope measured {measured:.2f} Hz "
        f"(expected {freq_hz} ± {tol:.0f} Hz)"
    )


@pytest.mark.parametrize("freq_hz,offset_cycles", PHASE_TEST_CASES)
def test_phase_offset(scope, freq_hz, offset_cycles):
    _program_phase(freq_hz, offset_cycles)
    measured_cycles = _measure_delay_cycles(scope, freq_hz, offset_cycles)
    assert abs(measured_cycles - offset_cycles) <= PHASE_TOL_CYC, (
        f"offset={offset_cycles} cyc @ {freq_hz} Hz: "
        f"scope measured {measured_cycles:.1f} cycles "
        f"(expected {offset_cycles} ± {PHASE_TOL_CYC})"
    )
