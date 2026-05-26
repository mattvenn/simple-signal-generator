"""
MicroPython demo for Simple Signal Generator (tt_um_example).
Target: RP2350 on TT demo board v3.

Before running:
  - Set ui_in[0] (CPOL) and ui_in[1] (CPHA) switches to OFF (both = 0) for SPI mode 0.
  - Or call tt.ui_in[0].value(0); tt.ui_in[1].value(0) from the REPL.

SPI pins (handled by the demo board PCB):
  uio[3] = MISO  (GPIO 28)
  uio[4] = CS_N  (GPIO 29)
  uio[5] = SCK   (GPIO 30)
  uio[6] = MOSI  (GPIO 31)

Alpha board users: change pin numbers to UIO3=25, UIO4=26, UIO5=27, UIO6=28.
"""

from machine import Pin, SoftSPI

CLOCK_HZ = 50_000_000

# GPIO pin numbers — TT demo board v3
PIN_MISO = 28   # uio[3]
PIN_CS   = 29   # uio[4]
PIN_SCK  = 30   # uio[5]
PIN_MOSI = 31   # uio[6]


def init_spi():
    miso = Pin(PIN_MISO, Pin.IN,  Pin.PULL_DOWN)
    cs   = Pin(PIN_CS,   Pin.OUT)
    sck  = Pin(PIN_SCK,  Pin.OUT)
    mosi = Pin(PIN_MOSI, Pin.OUT)
    cs(1)
    spi = SoftSPI(baudrate=100_000, polarity=0, phase=0, bits=8,
                  firstbit=SoftSPI.MSB, sck=sck, mosi=mosi, miso=miso)
    return spi, cs


def _write_reg(spi, cs, addr, data):
    cs(0)
    spi.write(bytes([0x80 | (addr & 0x1F), data & 0xFF]))
    cs(1)


def set_channel_counts(spi, cs, ch, on_count, off_count):
    """Program channel ch (0–3) with explicit cycle counts (16-bit max)."""
    base = ch * 4
    _write_reg(spi, cs, base + 0, (on_count  >>  8) & 0xFF)
    _write_reg(spi, cs, base + 1,  on_count         & 0xFF)
    _write_reg(spi, cs, base + 2, (off_count >>  8) & 0xFF)
    _write_reg(spi, cs, base + 3,  off_count        & 0xFF)


def set_channel(spi, cs, ch, freq_hz):
    """Program channel ch (0–3) to output freq_hz square wave (~50% duty)."""
    period = CLOCK_HZ // freq_hz
    on_count  = period // 2
    off_count = period - on_count
    set_channel_counts(spi, cs, ch, on_count, off_count)


def silence(spi, cs, ch):
    """Hold channel ch output LOW."""
    set_channel_counts(spi, cs, ch, 0, 0)


def silence_all(spi, cs):
    for ch in range(4):
        silence(spi, cs, ch)


# ── Example ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    spi, cs = init_spi()
    silence_all(spi, cs)

    set_channel(spi, cs, 0,     1_000)   # ch0:   1 kHz
    set_channel(spi, cs, 1,    10_000)   # ch1:  10 kHz
    set_channel(spi, cs, 2,   100_000)   # ch2: 100 kHz
    set_channel(spi, cs, 3, 1_000_000)   # ch3:   1 MHz

    print("ch0:   1 kHz  → uo_out[0]")
    print("ch1:  10 kHz  → uo_out[1]")
    print("ch2: 100 kHz  → uo_out[2]")
    print("ch3:   1 MHz  → uo_out[3]")
