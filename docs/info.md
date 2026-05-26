## How it works

Four independent square wave generators drive `uo[3:0]`. Each channel's high-time
(`on_count`) and low-time (`off_count`) are programmed independently via SPI, giving
full control over frequency and duty cycle per channel.

At 50 MHz, the formula for a 50% duty cycle square wave at frequency F is:
`on_count = off_count = 25_000_000 // F`

Setting `on_count=0` silences the channel (output held LOW regardless of `off_count`).
Setting `off_count=0` with `on_count>0` holds the output continuously HIGH.

## How to test

The SPI master (e.g. RP2350 running MicroPython) programs each channel using
`machine.SPI`. Each SPI frame is 2 bytes:

- Byte 0: `0x80 | reg_addr` (write), or `reg_addr` (read)
- Byte 1: data

Register map (6 registers per channel, big-endian):

| Reg  | Ch | Field                        |
|------|----|------------------------------|
| 0–2  | 0  | on_count [23:16], [15:8], [7:0]  |
| 3–5  | 0  | off_count [23:16], [15:8], [7:0] |
| 6–11 | 1  | on_count, off_count          |
| 12–17| 2  | on_count, off_count          |
| 18–23| 3  | on_count, off_count          |

SPI mode: CPOL and CPHA set via `ui[0]` and `ui[1]` respectively.

MicroPython example — 1 kHz square wave on channel 0:

```python
from machine import SPI, Pin

spi = SPI(0, baudrate=1_000_000, polarity=0, phase=1)
cs  = Pin(5, Pin.OUT, value=1)

def write_reg(reg, val):
    cs.value(0)
    spi.write(bytes([0x80 | reg, val]))
    cs.value(1)

# 1 kHz: on = off = 25_000_000 // 1_000 = 25_000
on = off = 25_000
for i, v in enumerate([(on>>16)&0xFF, (on>>8)&0xFF, on&0xFF,
                        (off>>16)&0xFF, (off>>8)&0xFF, off&0xFF]):
    write_reg(i, v)
```

## External hardware

- RP2350 (or any SPI master) connected to `uio[6:4]` (MOSI, CLK, CS_N) and `uio[3]` (MISO)
- Oscilloscope or frequency counter on `uo[3:0]`
