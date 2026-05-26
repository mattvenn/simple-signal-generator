"""
Hardware-in-the-loop frequency tests for the Simple Signal Generator.

Wiring:
  uo_out[0] → scope CH1
  uo_out[1] → scope CH2

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

def _clean_env():
    env = os.environ.copy()
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    return env

import pytest
import pyvisa  # pip install pyvisa pyvisa-py

SCOPE_RESOURCE = os.environ.get("SCOPE_RESOURCE", "TCPIP0::192.168.50.11::inst0::INSTR")
MPREMOTE_DEV   = os.environ.get(
    "MPREMOTE_DEV",
    "/dev/serial/by-id/usb-MicroPython_Board_in_FS_mode_6f890b97e48ced01-if00",
)

FREQ_TOL  = 0.02    # 2 % tolerance (FPGA clock is not exactly 50 MHz)
SETTLE_S  = 2.0     # seconds to wait after scope timebase change before measuring

# scope input channel for each DUT output channel
SCOPE_CH = {0: 1, 1: 2, 2: 3, 3: 4}

TEST_CASES = [
    # (dut_ch, freq_hz)
    (0,      1_000),
    (0,     10_000),
    (0,    100_000),
    (0,  1_000_000),
    (1,      1_000),
    (1,     10_000),
    (1,    100_000),
    (1,  1_000_000),
    (2,      1_000),
    (2,     10_000),
    (2,    100_000),
    (2,  1_000_000),
    (3,      1_000),
    (3,     10_000),
    (3,    100_000),
    (3,  1_000_000),
]


# ── fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def scope():
    rm = pyvisa.ResourceManager()
    inst = rm.open_resource(SCOPE_RESOURCE)
    inst.timeout = 5000
    print(f"\nScope: {inst.query('*IDN?').strip()}")
    yield inst
    inst.close()
    rm.close()


# ── helpers ───────────────────────────────────────────────────────────────────

def _mpremote_args():
    args = ["mpremote"]
    if MPREMOTE_DEV != "auto":
        args += ["connect", MPREMOTE_DEV]
    return args


def _mpremote_exec(code):
    r = subprocess.run(
        _mpremote_args() + ["exec", code],
        capture_output=True, text=True, timeout=15,
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


def _program(ch, freq_hz):
    _mpremote_exec("\n".join([
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
        "demo.silence_all(spi, cs)",
        f"demo.set_channel(spi, cs, {ch}, {freq_hz})",
    ]))


def _measure(scope, scope_ch, freq_hz):
    # Set timebase to show ~5 cycles so the scope re-acquires quickly
    time_per_div = (5.0 / freq_hz) / 10
    scope.write(f":TIMebase:SCALe {time_per_div:.3e}")
    scope.write(f":MEASure:FREQuency CHANnel{scope_ch}")
    time.sleep(SETTLE_S)
    raw = scope.query(f":MEASure:FREQuency? CHANnel{scope_ch}").strip()
    freq = float(raw)
    if freq > 1e30:   # scope returns 9.91E+37 when measurement is invalid
        raise RuntimeError(f"Scope CH{scope_ch} returned no valid measurement — check probe connection")
    return freq


# ── tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("ch,freq_hz", TEST_CASES)
def test_frequency(scope, ch, freq_hz):
    _program(ch, freq_hz)
    measured = _measure(scope, SCOPE_CH[ch], freq_hz)
    tol = freq_hz * FREQ_TOL
    assert abs(measured - freq_hz) <= tol, (
        f"ch{ch} {freq_hz} Hz: scope measured {measured:.2f} Hz "
        f"(expected {freq_hz} ± {tol:.0f} Hz)"
    )
