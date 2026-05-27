"""
Program one or more channels on the Simple Signal Generator.

Frequency mode (default):
  python scripts/run_freq.py <ch> <freq_hz> [<ch> <freq_hz> ...]

Count mode (--counts): pass raw clock-cycle counts matching simulation test values
  python scripts/run_freq.py --counts <ch> <on> <off> [<ch> <on> <off> ...]

Examples:
  python scripts/run_freq.py 0 1000
  python scripts/run_freq.py 0 1000000 1 1010000
  python scripts/run_freq.py --counts 0 5 5 1 7 7
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
    "demo.silence_all(spi, cs)",
]


def main():
    args = sys.argv[1:]

    if args and args[0] == "--counts":
        args = args[1:]
        if not args or len(args) % 3 != 0:
            print(__doc__)
            raise SystemExit(1)
        triples = [(int(args[i]), int(args[i+1]), int(args[i+2]))
                   for i in range(0, len(args), 3)]
        lines = list(BOILERPLATE)
        for ch, on, off in triples:
            lines.append(f"demo.set_channel_counts(spi, cs, {ch}, {on}, {off})")
            lines.append(f"_on, _off = demo.get_channel_counts(spi, cs, {ch})")
            lines.append(f'print("ch{ch}: on=" + str(_on) + "/{on} off=" + str(_off) + "/{off} " + ("OK" if _on == {on} and _off == {off} else "MISMATCH"))')
    else:
        if not args or len(args) % 2 != 0:
            print(__doc__)
            raise SystemExit(1)
        pairs = [(int(args[i]), int(args[i+1])) for i in range(0, len(args), 2)]
        lines = list(BOILERPLATE)
        for ch, freq_hz in pairs:
            period = 50_000_000 // freq_hz
            exp_on  = period // 2
            exp_off = period - exp_on
            lines.append(f"demo.set_channel(spi, cs, {ch}, {freq_hz})")
            lines.append(f"_on, _off = demo.get_channel_counts(spi, cs, {ch})")
            lines.append(f'print("ch{ch}: {freq_hz} Hz  on=" + str(_on) + "/{exp_on} off=" + str(_off) + "/{exp_off} " + ("OK" if _on == {exp_on} and _off == {exp_off} else "MISMATCH"))')

    _mpremote_exec("\n".join(lines))


if __name__ == "__main__":
    main()
