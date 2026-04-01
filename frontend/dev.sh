#!/bin/zsh
# ZenFlow Verity — one command dev launcher (USB only, no WiFi needed)
#
# Usage: ./dev.sh
# Requires: phone plugged in via USB with USB debugging on

ADB=/Users/pratikbarman/Library/Android/sdk/platform-tools/adb
BACKEND_DIR=/Users/pratikbarman/Desktop/ZenFlow_Verity
FRONTEND_DIR=/Users/pratikbarman/Desktop/ZenFlowVerity

# ── Check phone is connected ─────────────────────────────────────────────────
if ! $ADB devices | grep -q "device$"; then
  echo "❌  No Android device found. Plug in your phone and enable USB debugging."
  exit 1
fi
echo "✓  Phone detected"

# ── Tunnel ports over USB ────────────────────────────────────────────────────
$ADB reverse tcp:8081 tcp:8081
$ADB reverse tcp:8000 tcp:8000
echo "✓  Ports 8081 + 8000 tunnelled over USB"

# ── Start backend (if not already running) ───────────────────────────────────
if ! lsof -iTCP:8000 -sTCP:LISTEN -t &>/dev/null; then
  echo "▶  Starting backend..."
  cd "$BACKEND_DIR" && .venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 8000 --reload &>/tmp/zenflow_backend.log &
  sleep 3
fi
echo "✓  Backend on 127.0.0.1:8000"

# ── Start Expo Metro (if not already running) ────────────────────────────────
if ! lsof -iTCP:8081 -sTCP:LISTEN -t &>/dev/null; then
  echo "▶  Starting Expo..."
  cd "$FRONTEND_DIR" && npx expo start --port 8081 &>/tmp/zenflow_metro.log &
  sleep 5
fi
echo "✓  Metro on port 8081"

# ── Open app on phone ────────────────────────────────────────────────────────
$ADB shell am start -a android.intent.action.VIEW -d "exp://127.0.0.1:8081" host.exp.exponent
echo "✓  App launched on phone"
echo ""
echo "Logs: tail -f /tmp/zenflow_backend.log"
echo "       tail -f /tmp/zenflow_metro.log"
