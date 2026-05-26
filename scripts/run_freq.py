"""
Program one or more channels on the Simple Signal Generator.

Usage:
  python scripts/run_freq.py <ch> <freq_hz> [<ch> <freq_hz> ...]

Examples:
  python scripts/run_freq.py 0 1000
  python scripts/run_freq.py 0 1000 1 10000 2 100000 3 1000000
"""
import os
import subprocess
import sys

DEV = "/dev/serial/by-id/usb-MicroPython_Board_in_FS_mode_6f890b97e48ced01-if00"


def _clean_env():
    env = os.environ.copy()
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    return env


def _mpremote_exec(code):
    r = subprocess.run(
        ["mpremote", "connect", DEV, "exec", code],
        capture_output=True, text=True, timeout=30,
        env=_clean_env(),
    )
    if r.stdout.strip():
        print(r.stdout.strip())
    if r.returncode != 0:
        print(f"FAILED (rc={r.returncode}): {r.stderr.strip()}")
        raise SystemExit(1)


def main():
    args = sys.argv[1:]
    if not args or len(args) % 2 != 0:
        print(__doc__)
        raise SystemExit(1)

    pairs = [(int(args[i]), int(args[i + 1])) for i in range(0, len(args), 2)]

    lines = [
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
    ]
    for ch, freq_hz in pairs:
        lines.append(f"demo.set_channel(spi, cs, {ch}, {freq_hz})")
        lines.append(f'print("ch{ch}: {freq_hz} Hz")')

    _mpremote_exec("\n".join(lines))


if __name__ == "__main__":
    main()
