#!/usr/bin/env bash
# Run on your LAPTOP (not the Pi): builds the web page and copies it to the Pi.
#   bash hardware/deploy-frontend.sh                        # pi@trailbuddy.local, repo in ~/trailbuddy
#   bash hardware/deploy-frontend.sh pi@192.168.43.20       # a different Pi address
#   bash hardware/deploy-frontend.sh pi@trailbuddy.local ~/code/trailbuddy   # repo somewhere else on the Pi
# The Pi cannot build the page itself (the build tool needs a newer Node than Raspberry Pi OS ships),
# and frontend/dist is not in git, so repeat this whenever the frontend changes.
set -euo pipefail

PI="${1:-pi@trailbuddy.local}"
PI_REPO="${2:-~/trailbuddy}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ROOT/frontend"
npm ci
npm run build
[ -f dist/index.html ] || { echo "The build did not produce dist/index.html"; exit 1; }

ssh "$PI" "mkdir -p $PI_REPO/frontend && rm -rf $PI_REPO/frontend/dist"
scp -r dist "$PI:$PI_REPO/frontend/"
echo "Copied. Reload the page on your phone; the backend needs no restart."