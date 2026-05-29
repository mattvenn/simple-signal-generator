"""
Program the Simple Signal Generator via RP2350/mpremote.

Ch0 (uo[0]): independent square wave
Ch1 (uo[1]): phase-shifted replica of ch0 — static offset set via SPI and/or encoder

Usage:
  Frequency mode (50% duty):
    python scripts/run_freq.py <freq_hz>

  Counts mode (explicit cycle counts):
    python scripts/run_freq.py --counts <on_count> <off_count>

  Static phase offset (combined with either mode above):
    python scripts/run_freq.py <freq_hz> --offset <cycles>

  Encoder step size (combined with any mode above):
    python scripts/run_freq.py <freq_hz> --enc-step <step>

Arguments:
  freq_hz   ch0 output frequency in Hz
  cycles    signed integer; ch1 lags ch0 by this many clock cycles (negative = lead)
  step      encoder step size (0–255); phase change per click in 1/256-cycle units
            e.g. 64 → 0.25 cycles/click, 128 → 0.5 cycles/click

Examples:
  python scripts/run_freq.py 1000
  python scripts/run_freq.py 1000 --offset 500
  python scripts/run_freq.py 1000 --offset 500 --enc-step 64
  python scripts/run_freq.py --counts 5 25000 --offset 1000 --enc-step 64
"""
import os
import subprocess
import sys

DEV = "/dev/serial/by-id/usb-MicroPython_Board_in_FS_mode_6f890b97e48ced01-if00"
CLOCK_HZ = 50_000_000


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
    "demo.silence(spi, cs)",
]


def parse_args(args):
    counts_mode = False
    on_count = off_count = None
    freq_hz = None
    offset = None
    enc_step = None

    if "--enc-step" in args:
        idx = args.index("--enc-step")
        try:
            enc_step = int(args[idx + 1])
            if not 0 <= enc_step <= 255:
                raise ValueError
        except (IndexError, ValueError):
            print("--enc-step requires an integer 0–255")
            raise SystemExit(1)
        args = args[:idx] + args[idx + 2:]

    if "--offset" in args:
        idx = args.index("--offset")
        try:
            offset = int(args[idx + 1])
        except (IndexError, ValueError):
            print("--offset requires one integer: <cycles>")
            raise SystemExit(1)
        args = args[:idx] + args[idx + 2:]

    if args and args[0] == "--counts":
        args = args[1:]
        counts_mode = True
        if len(args) < 2:
            print(__doc__)
            raise SystemExit(1)
        on_count  = int(args[0])
        off_count = int(args[1])
    elif args:
        freq_hz = int(args[0])
        period  = CLOCK_HZ // freq_hz
        on_count  = period // 2
        off_count = period - on_count
    else:
        print(__doc__)
        raise SystemExit(1)

    return counts_mode, freq_hz, on_count, off_count, offset, enc_step


def main():
    counts_mode, freq_hz, on_count, off_count, offset, enc_step = parse_args(sys.argv[1:])

    lines = list(BOILERPLATE)

    # Program ch0
    lines.append(f"demo.set_ch0_counts(spi, cs, {on_count}, {off_count})")
    if freq_hz:
        lines.append(f'print("ch0: {freq_hz} Hz  on={on_count}  off={off_count}")')
    else:
        lines.append(f'print("ch0: on={on_count}  off={off_count}")')

    # Program phase offset
    if offset is not None:
        lines.append(f"demo.set_phase_offset(spi, cs, {offset})")
        lines.append("_off = demo.get_phase_offset(spi, cs)")
        lines.append(
            f'print("ch1: offset=" + str(_off) + "/{offset}  " + ("OK" if _off == {offset} else "MISMATCH"))'
        )
    else:
        lines.append('print("ch1: in-phase with ch0 (use --offset to shift)")')

    # Program encoder step size
    if enc_step is not None:
        lines.append(f"demo.set_enc_step(spi, cs, {enc_step})")
        lines.append("_step = demo.get_enc_step(spi, cs)")
        lines.append(
            f'print("enc: step=" + str(_step) + "/{enc_step}  " + ("OK" if _step == {enc_step} else "MISMATCH"))'
        )
    else:
        lines.append('print("enc: step unchanged (use --enc-step to configure)")')

    _mpremote_exec("\n".join(lines))


if __name__ == "__main__":
    main()
