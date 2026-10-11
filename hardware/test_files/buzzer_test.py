from time import sleep
from gpiozero import Buzzer, TonalBuzzer
from gpiozero.tones import Tone

PIN = 27   # GPIO27 = header pin 13

print("Test 1: steady power for half a second")
b = Buzzer(PIN)
b.on()
sleep(0.5)
b.off()
b.close()
sleep(1)

print("Test 2: three rising notes")
t = TonalBuzzer(PIN)
for note in ("C5", "E5", "G5"):
    t.play(Tone(note))
    sleep(0.3)
t.stop()
t.close()
print("Done.")