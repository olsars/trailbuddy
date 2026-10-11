import time
from gpiozero import Button
from luma.core.interface.serial import i2c
from luma.oled.device import ssd1306
from luma.core.render import canvas

device = ssd1306(i2c(port=1, address=0x3C))

btn = Button(17, hold_time=0.8)
held = False

def show(msg):
    with canvas(device) as draw:
        draw.text((10, 25), msg, fill="white")

def on_held():
    global held
    held = True
    show("SELECT")

def on_released():
    global held
    if not held:
        show("NEXT")
    held = False

btn.when_held = on_held
btn.when_released = on_released

from signal import pause
show("Ready")
pause()