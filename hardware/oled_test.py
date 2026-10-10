from luma.core.interface.serial import i2c
from luma.oled.device import ssd1306
from luma.core.render import canvas

serial = i2c(port=1, address=0x3C)
device = ssd1306(serial)          # 128x64 by default

import time

text = "Hello TrailBuddy"
x = device.width
try:
    while True:
        with canvas(device) as draw:
            w = draw.textlength(text)
            draw.text((x, 25), text, fill="white")
        x -= 2
        if x < -w:            # fully off the left edge
            x = device.width  # wrap to the right edge
        time.sleep(0.002)
except KeyboardInterrupt:
    pass