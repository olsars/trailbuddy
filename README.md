# TrailBuddy hardware (Raspberry Pi)

The device is a Raspberry Pi 5 with a 128×64 OLED, one button and a GPS module. `menu.py` runs the
pet, records walks and streams them live to the backend.

## Wiring

| Part | Connects to |
|---|---|
| OLED (SSD1306, I2C, address `0x3C`) | VCC → pin 1 (3.3 V) · GND → pin 6 · SDA → pin 3 · SCL → pin 5 |
| Button | one leg → pin 11 (GPIO17), the other leg → any GND pin |
| GPS (ATGM336H) | VCC → 3.3 V · GND → GND · GPS **TX → pin 10** (RXD) · GPS **RX → pin 8** (TXD) |
| MPU-6050 IMU | on the same I2C pins as the OLED; not used by the program yet |

TX and RX cross over (the GPS's TX goes to the Pi's RX). A blinking light on the GPS means it has a fix.

## First-time Pi setup

1. Flash **Raspberry Pi OS Lite (64-bit)** with Raspberry Pi Imager. Set hostname `trailbuddy`, enable SSH,
   and add your phone's hotspot as the Wi-Fi network.
2. Enable I2C and the serial port, then reboot:
   ```bash
   sudo raspi-config nonint do_i2c 0
   sudo raspi-config nonint do_serial_hw 0
   sudo raspi-config nonint do_serial_cons 1
   sudo reboot
   ```
3. Install the code and its Python packages:
   ```bash
   sudo apt update && sudo apt install -y python3-venv python3-lgpio i2c-tools git
   python3 -m venv --system-site-packages ~/tb-env
   git clone https://github.com/olsars/trailbuddy.git ~/trailbuddy
   ~/tb-env/bin/pip install -r ~/trailbuddy/backend/requirements.txt
   ~/tb-env/bin/pip install pynmea2 pyserial requests gpiozero luma.oled pillow smbus2
   ```
4. Check the hardware: `i2cdetect -y 1` should show `3c`, and `ls /dev/ttyAMA0` should exist.
   (The GPS is read from `/dev/ttyAMA0`. On the Pi 5, `/dev/serial0` points to the wrong port.)

## Copy the web page to the Pi (from your laptop)

The Pi cannot build the web page (the build tool needs a newer Node than Raspberry Pi OS ships) and
`frontend/dist` is not in git. Build it on your laptop and copy it over, and repeat whenever the frontend changes:

```bash
bash hardware/deploy-frontend.sh                   # pi@trailbuddy.local, repo in ~/trailbuddy
bash hardware/deploy-frontend.sh pi@<pi-address>   # if trailbuddy.local does not resolve
```

Or by hand: `cd frontend && npm ci && npm run build`, then `scp -r dist pi@trailbuddy.local:~/trailbuddy/frontend/`.

## Run it

### Option A: everything on the Pi (recommended for demos, no laptop needed)

Once, on the Pi:
```bash
cd ~/trailbuddy
sudo bash hardware/install-autostart.sh
```
From then on, powering the Pi starts the backend and the device program by themselves.

1. Power the Pi (a phone hotspot must be on, and the Pi joins it automatically).
2. On the Pi's screen, short-press to **Phone link** and long-press. It shows an address like `172.20.10.4:8000`.
3. On a phone connected to the same hotspot, open `http://<that address>/app/?user=pablo`.

Handy commands:
```bash
sudo systemctl status trailbuddy-backend trailbuddy-menu   # are they running?
journalctl -u trailbuddy-menu -f                           # live log of the device program
sudo systemctl restart trailbuddy-backend trailbuddy-menu  # after `git pull`
sudo systemctl stop trailbuddy-menu                        # before running menu.py by hand
sudo systemctl disable --now trailbuddy-menu trailbuddy-backend   # turn auto-start off
```
Walks are stored on the Pi in `backend/trailbuddy.db`. To start clean, stop the backend, delete that file, and start it again.

### Option B: backend on a laptop

Start the backend on the laptop (`python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8000`),
stop the Pi's services if they are installed, and on the Pi run:
```bash
source ~/tb-env/bin/activate
TRAILBUDDY_API=http://<laptop-ip>:8000 python ~/trailbuddy/hardware/menu.py
```
Both must be on the same hotspot.

## Using the device

Short press moves to the next option. Hold for about a second to select.

| Screen | What it does |
|---|---|
| Buddy | Feed and pet the cat. Walking cheers it up and makes it hungry. |
| Start Walk | "Ready?" screen. Click to start, hold to cancel. Hold during a walk to end it. |
| Phone link | Shows the address to open on a phone. |

GPS label: **Locked** = good fix, **Weak** = a fix that is too poor to record, **Searching** = no fix.
During a walk, `Live: ok` means points are reaching the backend. `Live: -- (12)` means 12 are queued and will
upload by themselves.

Settings (environment variables): `TRAILBUDDY_API` (backend address), `TRAILBUDDY_USER` (default `pablo`; the page's
`?user=` must match), `TRAILBUDDY_VISIBILITY` (`private`, `friends` or `public`), `TRAILBUDDY_DEBUG=1` (prints why GPS fixes
are kept or dropped).

## Demo-day checklist

- Hotspot on. On an iPhone, turn on **Maximize Compatibility** so the Pi can join.
- Power the Pi outside a few minutes early and wait for **GPS: Locked** before starting.
- Indoors, GPS drifts and the trail will not draw. Use the simulator instead (run it on the Pi or any machine that can reach it):
  ```bash
  python gps/simulator.py --api http://<pi-address>:8000 --user pablo --latitude 28.6013 --longitude -81.1990
  ```

## Troubleshooting

- `ModuleNotFoundError: No module named 'pynmea2'`: you are not in the virtualenv. Use `~/tb-env/bin/python`.
- Screen says `Net: --`: the backend is not running. Check `sudo systemctl status trailbuddy-backend`.
- The phone cannot open the page: both must be on the same hotspot. Use the numeric address, not `trailbuddy.local`.
  A blank or 404 page means `frontend/dist` was never copied (see above).
- Two copies fighting over the screen, button or GPS: the auto-start service is still running while you launch `menu.py` by hand.
  Run `sudo systemctl stop trailbuddy-menu` first.
- GPS always says Searching with the GPS light blinking: run with `TRAILBUDDY_DEBUG=1` and look at `sats` and `hdop`.