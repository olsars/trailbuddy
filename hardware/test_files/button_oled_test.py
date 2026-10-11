import time
from gpiozero import Button
from luma.core.interface.serial import i2c
from luma.oled.device import ssd1306
from luma.core.render import canvas

device = ssd1306(i2c(port=1, address=0x3C))
btn = Button(17)

def show(msg):
    with canvas(device) as draw:
        draw.text((10, 25), msg, fill="white")

show("Press to start")
while True:
    btn.wait_for_press()
    show("Walk started!")
    btn.wait_for_release()
    
    btn.wait_for_press()
    show("Walk Ended!!!")
    btn.wait_for_release()