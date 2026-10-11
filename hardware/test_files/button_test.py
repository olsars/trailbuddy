from gpiozero import Button
from signal import pause

btn = Button(17)
btn.when_pressed = lambda: print("pressed")
btn.when_released = lambda: print("released")
pause()