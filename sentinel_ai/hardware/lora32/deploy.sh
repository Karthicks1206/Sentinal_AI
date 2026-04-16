#!/usr/bin/env bash
# ============================================================
#  Sentinel AI — One-Line Deploy
#  Flashes LoRa32, starts hub + bridge on Pi, runs 30+ tests
#
#  Run from Mac:
#    bash /Users/karthi/Desktop/Sentinal_AI/sentinel_ai/hardware/lora32/deploy.sh
# ============================================================
set -e

PI_HOST="192.168.1.100"
PI_USER="karthick12"
PI_PASS="0612"
PI_BASE="/home/karthick12/Desktop/Sentinal_AI/sentinel_ai"
LORA_PORT="/dev/ttyUSB0"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

GREEN='\033[92m'; RED='\033[91m'; CYAN='\033[96m'; BOLD='\033[1m'; NC='\033[0m'
log()  { echo -e "${CYAN}[deploy]${NC} $*"; }
ok()   { echo -e "${GREEN}[  OK  ]${NC} $*"; }
fail() { echo -e "${RED}[ FAIL ]${NC} $*"; exit 1; }

SSH="sshpass -p $PI_PASS ssh -o StrictHostKeyChecking=no -o PasswordAuthentication=yes -o PubkeyAuthentication=no $PI_USER@$PI_HOST"
SCP="sshpass -p $PI_PASS scp -o StrictHostKeyChecking=no -o PasswordAuthentication=yes -o PubkeyAuthentication=no"

echo -e "\n${BOLD}${CYAN}============================================================${NC}"
echo -e "${BOLD}${CYAN}  Sentinel AI — Full Deploy & Test${NC}"
echo -e "${BOLD}${CYAN}  Pi: $PI_HOST   LoRa32: $LORA_PORT${NC}"
echo -e "${BOLD}${CYAN}============================================================${NC}\n"

# ── 1. Check prerequisites ────────────────────────────────────────────────────
log "Checking prerequisites..."
command -v sshpass >/dev/null || fail "sshpass not found — brew install hudochenkov/sshpass/sshpass"
command -v python3  >/dev/null || fail "python3 not found"
ping -c1 -W2 "$PI_HOST" >/dev/null 2>&1 || fail "Cannot reach Pi at $PI_HOST"
ok "Prerequisites OK"

# ── 2. Copy firmware to Pi ────────────────────────────────────────────────────
log "Copying firmware files to Pi..."
$SCP "$SCRIPT_DIR/config.py" "$SCRIPT_DIR/main.py" "$PI_USER@$PI_HOST:/tmp/"
ok "Files copied"

# ── 3. Stop serial bridge (free the USB port) ─────────────────────────────────
log "Stopping serial bridge on Pi..."
$SSH "pkill -f lora_gateway_serial 2>/dev/null; pkill -f lora_bridge 2>/dev/null; sleep 1; echo ok" || true

# ── 4. Flash LoRa32 ───────────────────────────────────────────────────────────
log "Flashing LoRa32 (interrupting main.py + mpremote cp)..."
FLASH_RESULT=$($SSH "python3 - << 'PYEOF'
import serial, time, subprocess

PORT = '$LORA_PORT'
s = serial.Serial(PORT, 115200, timeout=0.2)
for _ in range(25):
    s.write(b'\x03')
    time.sleep(0.1)
s.close()
time.sleep(0.6)

r1 = subprocess.run(['python3','-m','mpremote','connect',PORT,'cp','/tmp/config.py',':config.py'],
                    capture_output=True, text=True, timeout=20)
r2 = subprocess.run(['python3','-m','mpremote','connect',PORT,'cp','/tmp/main.py',':main.py'],
                    capture_output=True, text=True, timeout=20)
if r1.returncode == 0 and r2.returncode == 0:
    subprocess.run(['python3','-m','mpremote','connect',PORT,'reset'], capture_output=True, timeout=5)
    print('FLASH_OK')
else:
    print('FLASH_FAIL', r1.stderr[:80], r2.stderr[:80])
PYEOF" 2>&1)

echo "$FLASH_RESULT" | grep -q "FLASH_OK" && ok "LoRa32 flashed OK" || { echo "$FLASH_RESULT"; log "Flash failed — device may already be running latest firmware"; }

# ── 5. Start Sentinel hub (if not running) ────────────────────────────────────
log "Starting Sentinel hub..."
$SSH "
if pgrep -f 'python.*main.py' > /dev/null 2>&1; then
    echo 'Hub already running'
else
    cd $PI_BASE
    source venv/bin/activate
    nohup python main.py > /tmp/sentinel_hub.log 2>&1 &
    echo 'Hub started PID:'\$!
fi
" 2>&1 | grep -v "^$" | while read line; do log "$line"; done

sleep 6  # Let hub initialise

# ── 6. Start serial bridge ────────────────────────────────────────────────────
log "Starting serial bridge..."
$SSH "
kill \$(fuser $LORA_PORT 2>/dev/null) 2>/dev/null || true
sleep 1
nohup python3 $PI_BASE/hardware/lora32/lora_gateway_serial.py --hub http://localhost:5001 > /tmp/bridge.log 2>&1 &
echo 'Bridge PID:'\$!
" 2>&1 | grep -v "^$" | while read line; do log "$line"; done

sleep 8  # Let data flow in

# ── 7. Run test suite ─────────────────────────────────────────────────────────
log "Running test suite..."
echo ""
python3 "$SCRIPT_DIR/test_sentinel.py" --pi "$PI_HOST" --user "$PI_USER" --password "$PI_PASS"
