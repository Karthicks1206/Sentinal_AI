#!/usr/bin/env bash
set -e

CONFIG_FILE="$HOME/.sentinel_hub"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DEVICE_NAME=$(hostname -s)

GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; NC='\033[0m'
ok()  { echo -e "${GREEN}[OK]${NC}  $*"; }
err() { echo -e "${RED}[ERR]${NC} $*"; }
info(){ echo -e "${YELLOW}---${NC}  $*"; }

echo "======================================"
echo "  Sentinel AI — Remote Connect"
echo "======================================"

if [ -n "$1" ]; then
    HUB_IP="$1"
elif [ -f "$CONFIG_FILE" ]; then
    HUB_IP=$(cat "$CONFIG_FILE")
    info "Using saved hub IP: $HUB_IP"
    read -rp "  Press Enter to use it, or type a new IP: " NEW_IP
    [ -n "$NEW_IP" ] && HUB_IP="$NEW_IP"
else
    read -rp "  Enter hub IP address (e.g. 104.194.100.19): " HUB_IP
fi

HUB_URL="http://${HUB_IP}:5001"
echo "$HUB_IP" > "$CONFIG_FILE"
ok "Hub URL: $HUB_URL"

read -rp "  Device name [${DEVICE_NAME}]: " CUSTOM_NAME
[ -n "$CUSTOM_NAME" ] && DEVICE_NAME="$CUSTOM_NAME"

echo ""
info "Installing dependencies..."
pip3 install psutil requests -q 2>/dev/null \
    || pip install psutil requests -q 2>/dev/null \
    || { err "pip not found — install Python 3 first"; exit 1; }
ok "Dependencies ready"

echo ""
info "Testing connectivity to $HUB_URL ..."
if curl -sf --max-time 3 "$HUB_URL/api/devices" > /dev/null 2>&1; then
    ok "Hub is reachable"
else
    err "Cannot reach hub at $HUB_URL"
    echo ""
    echo "  Possible fixes:"
    echo "  1. Make sure main.py is running on the hub Mac"
    echo "  2. Check both machines are on the same WiFi network"
    echo "  3. Disable AP/Client Isolation on your router"
    echo ""
    read -rp "  Try anyway? [y/N]: " TRY
    [ "${TRY,,}" != "y" ] && exit 1
fi

echo ""
echo "======================================"
ok "Connecting as '$DEVICE_NAME' ..."
echo "  Press Ctrl+C to disconnect"
echo "======================================"
echo ""

while true; do
    python3 "$SCRIPT_DIR/sentinel_client.py" \
        --hub "$HUB_URL" \
        --device "$DEVICE_NAME" \
        --interval 5
    echo ""
    err "Disconnected. Reconnecting in 5s... (Ctrl+C to stop)"
    sleep 5
done
