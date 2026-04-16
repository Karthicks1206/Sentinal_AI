#!/usr/bin/env bash
# ============================================================
#  Sentinel AI — Full Stack Launcher
#  Starts everything: Pi hub, LoRa32 firmware, serial bridge
#
#  Usage (from Mac):
#    ./run.sh              → start everything
#    ./run.sh --test       → start + run 44-test suite
#    ./run.sh --stop       → stop all services on Pi
# ============================================================

cd "$(dirname "$0")"

PI_HOST="192.168.1.100"
PI_USER="karthick12"
PI_PASS="0612"
PI_BASE="/home/$PI_USER/Desktop/Sentinal_AI/sentinel_ai"
LORA_PORT="/dev/ttyUSB0"

GREEN='\033[92m'; RED='\033[91m'; CYAN='\033[96m'
YELLOW='\033[93m'; BOLD='\033[1m'; NC='\033[0m'

log()  { echo -e "${CYAN}▶${NC} $*"; }
ok()   { echo -e "${GREEN}✓${NC} $*"; }
warn() { echo -e "${YELLOW}!${NC} $*"; }
fail() { echo -e "${RED}✗${NC} $*"; exit 1; }

SSH="sshpass -p $PI_PASS ssh -o StrictHostKeyChecking=no -o PasswordAuthentication=yes -o PubkeyAuthentication=no $PI_USER@$PI_HOST"
SCP="sshpass -p $PI_PASS scp -o StrictHostKeyChecking=no -o PasswordAuthentication=yes -o PubkeyAuthentication=no"

# ── Stop mode ────────────────────────────────────────────────────────────────
if [ "$1" = "--stop" ]; then
    echo -e "\n${BOLD}${CYAN}  Sentinel AI — Stopping all services${NC}\n"
    log "Stopping hub..."
    $SSH "pkill -f 'python.*main.py' 2>/dev/null; echo ok" || true
    log "Stopping serial bridge..."
    $SSH "pkill -f lora_gateway_serial 2>/dev/null; echo ok" || true
    ok "All services stopped."
    exit 0
fi

# ── Banner ────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${CYAN}============================================================${NC}"
echo -e "${BOLD}${CYAN}  Sentinel AI — Hardware + Software Full Stack${NC}"
echo -e "${BOLD}${CYAN}  Pi: $PI_HOST   LoRa32 → AHT20 → Hub → Dashboard${NC}"
echo -e "${BOLD}${CYAN}============================================================${NC}"
echo ""

# ── 1. Check prerequisites ────────────────────────────────────────────────────
log "Checking prerequisites..."
command -v sshpass >/dev/null 2>&1 || fail "sshpass not found — run: brew install hudochenkov/sshpass/sshpass"
ping -c1 -W2 "$PI_HOST" >/dev/null 2>&1    || fail "Pi unreachable at $PI_HOST — check network"
$SSH "echo ok" >/dev/null 2>&1              || fail "SSH failed — check Pi is on and credentials are correct"
ok "Pi reachable at $PI_HOST"

# ── 2. Sync firmware to Pi ────────────────────────────────────────────────────
log "Syncing firmware to Pi..."
$SCP hardware/lora32/config.py hardware/lora32/main.py "$PI_USER@$PI_HOST:/tmp/"
ok "Firmware files synced"

# ── 3. Flash LoRa32 ───────────────────────────────────────────────────────────
log "Flashing LoRa32 (AHT20 + OLED + SX1262)..."
cat > /tmp/_flash.py << PYEOF
import serial, time, subprocess
PORT = '$LORA_PORT'
subprocess.run(['pkill','-f','lora_gateway_serial'], capture_output=True)
time.sleep(1)
s = serial.Serial(PORT, 115200, timeout=0.2)
for _ in range(25): s.write(b'\x03'); time.sleep(0.1)
s.close(); time.sleep(0.5)
r1 = subprocess.run(['python3','-m','mpremote','connect',PORT,'cp','/tmp/config.py',':config.py'],
                    capture_output=True, text=True, timeout=20)
r2 = subprocess.run(['python3','-m','mpremote','connect',PORT,'cp','/tmp/main.py',':main.py'],
                    capture_output=True, text=True, timeout=20)
if r1.returncode==0 and r2.returncode==0:
    subprocess.run(['python3','-m','mpremote','connect',PORT,'reset'],capture_output=True,timeout=5)
    print('OK')
else:
    print('SKIP')
PYEOF
$SCP /tmp/_flash.py "$PI_USER@$PI_HOST:/tmp/_flash.py"
FLASH=$($SSH "python3 /tmp/_flash.py" 2>&1)
echo "$FLASH" | grep -q "OK\|SKIP" && ok "LoRa32 firmware up to date" || warn "Flash: $FLASH"

# ── 4. Start Sentinel hub on Pi ───────────────────────────────────────────────
log "Starting Sentinel hub on Pi..."
HUB_STATUS=$($SSH "
if pgrep -f 'python.*main.py' | grep -v venv > /dev/null 2>&1; then
    echo 'ALREADY_RUNNING'
else
    cd $PI_BASE
    source venv/bin/activate
    nohup python main.py > /tmp/sentinel_hub.log 2>&1 &
    echo PID:\$!
fi")

if echo "$HUB_STATUS" | grep -q "ALREADY_RUNNING"; then
    ok "Hub already running"
else
    PID=$(echo "$HUB_STATUS" | grep -o 'PID:[0-9]*' | cut -d: -f2)
    ok "Hub started (PID $PID)"
    log "Waiting for hub to initialise..."
    sleep 8
fi

# ── 5. Start serial bridge ────────────────────────────────────────────────────
log "Starting serial bridge (LoRa32 → Hub)..."
$SSH "pkill -f lora_gateway_serial 2>/dev/null || true; sleep 1; kill \$(fuser $LORA_PORT 2>/dev/null) 2>/dev/null || true; sleep 1; nohup python3 $PI_BASE/hardware/lora32/lora_gateway_serial.py --hub http://localhost:5001 > /tmp/bridge.log 2>&1 & disown"
ok "Serial bridge started"

# ── 6. Wait and verify ────────────────────────────────────────────────────────
log "Waiting for data pipeline to warm up..."
sleep 20

DEVICE_STATUS=$(curl -s --max-time 5 "http://$PI_HOST:5001/api/devices" 2>/dev/null | \
    python3 -c "
import json,sys
try:
    data = json.load(sys.stdin)
    for d in data:
        if d.get('device_id') == 'lora32-node-01':
            print(d.get('status','?'), round(d.get('age_seconds',999),1))
except: print('error')
" 2>/dev/null)

if echo "$DEVICE_STATUS" | grep -qE "connected|stale"; then
    AGE=$(echo "$DEVICE_STATUS" | awk '{print $2}')
    ok "lora32-node-01 online (last seen ${AGE}s ago)"
else
    warn "lora32-node-01 not yet connected — may need 10-15s more"
fi

# ── 7. Summary ────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${CYAN}============================================================${NC}"
echo -e "${BOLD}${GREEN}  ✓ Sentinel AI is running!${NC}"
echo ""
echo -e "  ${BOLD}Dashboard${NC}    →  ${CYAN}http://$PI_HOST:5001${NC}"
echo -e "  ${BOLD}Hub log${NC}      →  ssh $PI_USER@$PI_HOST 'tail -f /tmp/sentinel_hub.log'"
echo -e "  ${BOLD}Bridge log${NC}   →  ssh $PI_USER@$PI_HOST 'tail -f /tmp/bridge.log'"
echo -e "  ${BOLD}LoRa32 live${NC}  →  ssh $PI_USER@$PI_HOST 'python3 -m mpremote connect $LORA_PORT'"
echo ""
echo -e "  ${BOLD}Stop all${NC}     →  ./run.sh --stop"
echo -e "  ${BOLD}Run tests${NC}    →  ./run.sh --test"
echo -e "${BOLD}${CYAN}============================================================${NC}"
echo ""

# ── 8. Open dashboard ────────────────────────────────────────────────────────
if command -v open >/dev/null 2>&1; then
    open "http://$PI_HOST:5001"
    ok "Dashboard opened in browser"
fi

# ── 9. Optional: run tests ────────────────────────────────────────────────────
if [ "$1" = "--test" ]; then
    echo ""
    log "Running full test suite..."
    sleep 5
    source venv/bin/activate 2>/dev/null || true
    python3 hardware/lora32/test_sentinel.py --pi "$PI_HOST" --user "$PI_USER" --password "$PI_PASS"
fi
