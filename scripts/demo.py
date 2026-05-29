"""
MicroPython demo for Simple Signal Generator (tt_um_mattvenn_signal_generator).
Target: RP2350 on TT demo board v3.

Channel 0: independent square wave (frequency + duty cycle via on/off counts).
Channel 1: phase-shifted replica of ch0. Amplitude controls the sweep range;
           speed controls how fast the phase walks (system clock ticks per step).

Before running:
  - Set ui_in[0] (CPOL) and ui_in[1] (CPHA) switches to OFF (both = 0).

SPI pins (TT demo board v3):
  uio[3] = MISO  (GPIO 28)
  uio[4] = CS_N  (GPIO 29)
  uio[5] = SCK   (GPIO 30)
  uio[6] = MOSI  (GPIO 31)
"""

from machine import Pin, SoftSPI

CLOCK_HZ = 50_000_000

PIN_MISO = 28
PIN_CS   = 29
PIN_SCK  = 30
PIN_MOSI = 31


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
    spi.write(bytes([0x80 | (addr & 0x3F), data & 0xFF]))
    cs(1)


def read_reg(spi, cs, addr):
    tx = bytes([addr & 0x3F, 0x00])
    rx = bytearray(2)
    cs(0)
    spi.write_readinto(tx, rx)
    cs(1)
    return rx[1]


# ── Channel 0 ────────────────────────────────────────────────────────────────

def set_ch0_counts(spi, cs, on_count, off_count):
    """Program ch0 with explicit cycle counts (16-bit)."""
    _write_reg(spi, cs, 0, (on_count  >>  8) & 0xFF)
    _write_reg(spi, cs, 1,  on_count         & 0xFF)
    _write_reg(spi, cs, 2, (off_count >>  8) & 0xFF)
    _write_reg(spi, cs, 3,  off_count        & 0xFF)


def set_ch0(spi, cs, freq_hz, duty=0.5):
    """Program ch0 to freq_hz with given duty cycle (0.0–1.0)."""
    period = CLOCK_HZ // freq_hz
    on_count  = max(1, int(period * duty))
    off_count = max(1, period - on_count)
    set_ch0_counts(spi, cs, on_count, off_count)


def silence(spi, cs):
    """Silence both channels and zero the phase offset."""
    set_ch0_counts(spi, cs, 0, 0)
    set_phase_offset(spi, cs, 0)


# ── Channel 1 phase offset (registers 4-5) ───────────────────────────────────

def set_phase_offset(spi, cs, offset_cycles):
    """Set ch1 static phase offset (signed 16-bit, clock cycles).

    offset_cycles > 0: ch1 lags ch0 by that many cycles.
    offset_cycles < 0: ch1 leads ch0 by |offset_cycles| cycles.

    Constraint: |offset_cycles| < off_count.
    """
    val = offset_cycles & 0xFFFF  # two's complement 16-bit
    _write_reg(spi, cs, 4, (val >> 8) & 0xFF)
    _write_reg(spi, cs, 5,  val        & 0xFF)


def get_phase_offset(spi, cs):
    """Read back signed phase offset from registers 4-5."""
    hi  = read_reg(spi, cs, 4)
    lo  = read_reg(spi, cs, 5)
    val = (hi << 8) | lo
    return val if val < 0x8000 else val - 0x10000


# ── Encoder step size (register 6) ──────────────────────────────────────────

def set_enc_step(spi, cs, enc_step):
    """Set encoder step size (register 6).

    enc_step (int, 0–255):
        Phase change per encoder click in 1/256-cycle units.
        e.g. enc_step=64  → 0.25 cycles/click  (80 clicks across ±10 cycles)
             enc_step=128 → 0.5  cycles/click  (40 clicks across ±10 cycles)
             enc_step=255 → ~1   cycle/click   (20 clicks across ±10 cycles)
    """
    _write_reg(spi, cs, 6, enc_step & 0xFF)


def get_enc_step(spi, cs):
    """Read back enc_step from register 6."""
    return read_reg(spi, cs, 6)


# ── Example ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    spi, cs = init_spi()
    silence(spi, cs)

    # ch0: 10 kHz, 20% duty cycle (on=1000, off=4000 cycles at 50 MHz)
    set_ch0(spi, cs, 10_000, duty=0.2)

    # ch1: static 500-cycle lag set via SPI; fine-tune with the encoder knob
    set_phase_offset(spi, cs, 500)

    # Encoder: 0.25 cycles per click (64/256), ui_in[4]=A, ui_in[5]=B
    # Range: ±32767 cycles
    set_enc_step(spi, cs, 64)

    print("ch0: 10 kHz, 20% duty  → uo_out[0]")
    print("ch1: 500-cycle lag, encoder fine-tunes via ui_in[4:5]")
