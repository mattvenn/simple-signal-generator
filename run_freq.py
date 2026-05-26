"""
Simulates the two mpremote exec calls the HIL test makes.
Run from the project root:
  python run_freq.py
"""
import os
import subprocess
import time

DEV = "/dev/serial/by-id/usb-MicroPython_Board_in_FS_mode_6f890b97e48ced01-if00"

def _make_code(ch, freq_hz):
    return "\n".join([
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
        f'print("ch{ch}: {freq_hz} Hz programmed")',
    ])


def _clean_env():
    env = os.environ.copy()
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    return env


def mpremote_exec(label, code):
    print(f"\n--- {label} ---")
    r = subprocess.run(
        ["mpremote", "connect", DEV, "exec", code],
        capture_output=True, text=True, timeout=30,
        env=_clean_env(),
    )
    if r.stdout.strip():
        print(r.stdout.strip())
    if r.returncode != 0:
        print(f"FAILED (rc={r.returncode})")
        if r.stderr.strip():
            print(r.stderr.strip())
        raise SystemExit(1)


mpremote_exec("boot+program", _make_code(0, 10_000))
print("\nDone — check scope CH1 for 10 kHz")
