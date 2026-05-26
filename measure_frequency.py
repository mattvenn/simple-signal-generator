#!/usr/bin/env python3
"""Measure frequency on CH1 of a Keysight HD304MSO for a given duration and print the mean."""

import argparse
import statistics
import time

import pyvisa


def measure_frequency(resource: str, duration: float, interval: float) -> None:
    rm = pyvisa.ResourceManager()
    scope = rm.open_resource(resource)
    scope.timeout = 5000

    print(f"Connected: {scope.query('*IDN?').strip()}")

    scope.write(":MEASure:FREQuency CHANnel1")

    samples = []
    end_time = time.monotonic() + duration
    while time.monotonic() < end_time:
        raw = scope.query(":MEASure:FREQuency? CHANnel1").strip()
        try:
            freq = float(raw)
            if freq > 0:
                samples.append(freq)
        except ValueError:
            pass
        time.sleep(interval)

    scope.close()
    rm.close()

    if not samples:
        print("No valid samples collected.")
        return

    mean_hz = statistics.mean(samples)
    print(f"Samples: {len(samples)}")
    print(f"Mean frequency: {mean_hz:.6g} Hz  ({mean_hz / 1e6:.6g} MHz)")


def list_devices() -> None:
    rm = pyvisa.ResourceManager()
    resources = rm.list_resources()
    if not resources:
        print("No VISA devices found.")
        return
    for r in resources:
        try:
            dev = rm.open_resource(r)
            dev.timeout = 2000
            idn = dev.query("*IDN?").strip()
            dev.close()
            print(f"{r}\n  {idn}")
        except Exception:
            print(f"{r}\n  (no IDN response)")
    rm.close()


def main():
    parser = argparse.ArgumentParser(description="Measure CH1 frequency on Keysight HD304MSO")
    parser.add_argument("resource", nargs="?", help="VISA resource string, e.g. USB0::0x2A8D::0x9027::MYSERIAL::INSTR")
    parser.add_argument("--list", action="store_true", help="List available VISA devices and exit")
    parser.add_argument("--duration", type=float, default=10.0, help="Measurement duration in seconds (default: 10)")
    parser.add_argument("--interval", type=float, default=0.2, help="Poll interval in seconds (default: 0.2)")
    args = parser.parse_args()

    if args.list:
        list_devices()
        return

    if not args.resource:
        parser.error("resource is required unless --list is specified")

    measure_frequency(args.resource, args.duration, args.interval)


if __name__ == "__main__":
    main()
