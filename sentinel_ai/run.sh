#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# Sentinel AI — Single-command launcher
# Usage: ./run.sh
# ─────────────────────────────────────────────────────────────────────────────

set -e
cd "$(dirname "$0")"

echo "================================================================"
echo "  SENTINEL AI — Autonomous Self-Healing IoT Monitor"
echo "================================================================"

# ── 1. Kill any existing instances ──────────────────────────────────
echo ""
echo "[1/7] Stopping any existing Sentinel instances..."
kill $(lsof -ti :5001) 2>/dev/null && echo "      Killed Flask server on :5001" || true
pkill -f "python.*main.py"      2>/dev/null && echo "      Killed background main.py" || true
pkill -f "cpu_stress\|memory_stress\|disk_stress" 2>/dev/null && echo "      Killed stress simulations" || true
sleep 1

# ── 2. Open macOS firewall for remote clients ────────────────────────
echo "[2/7] Opening firewall on port 5001 for remote clients..."
FW=/usr/libexec/ApplicationFirewall/socketfilterfw
PY=$(which python3)
# Enable firewall rule without requiring sudo interactively —
# wrap in sudo; if it fails (no password), we warn and continue.
if sudo -n "$FW" --add "$PY" 2>/dev/null && \
   sudo -n "$FW" --unblockapp "$PY" 2>/dev/null; then
    echo "      Firewall: python3 allowed through."
else
    # Prompt once
    echo "      Enter sudo password to allow remote clients through macOS firewall:"
    sudo "$FW" --add "$PY"         2>/dev/null || true
    sudo "$FW" --unblockapp "$PY"  2>/dev/null || true
    echo "      Firewall rule applied (or already set)."
fi

# Also open port 5001 via pf if firewall is blocking at packet level
LOCAL_IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "unknown")
echo "      Hub IP for remote clients: $LOCAL_IP:5001"

# ── 3. Clear Python cache (avoids stale bytecode issues) ────────────
echo "[3/7] Clearing Python cache..."
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
find . -name "*.pyc" -delete 2>/dev/null || true

# ── 3. Start PostgreSQL ──────────────────────────────────────────────
echo "[4/7] Starting PostgreSQL..."
if command -v brew &>/dev/null; then
    brew services start postgresql@16 2>/dev/null || true
    # Wait until PostgreSQL accepts connections (up to 10s)
    for i in $(seq 1 10); do
        if /opt/homebrew/opt/postgresql@16/bin/pg_isready -q 2>/dev/null; then
            echo "      PostgreSQL ready."
            break
        fi
        sleep 1
    done
else
    echo "      WARNING: brew not found — ensure PostgreSQL is running manually."
fi

# ── 4. Start Ollama (local AI model for diagnosis) ──────────────────
echo "[5/7] Starting Ollama (llama3.2:3b)..."
if command -v brew &>/dev/null; then
    brew services start ollama 2>/dev/null || true
else
    ollama serve &>/dev/null &
fi
sleep 2

# ── 5. Activate virtual environment ─────────────────────────────────
echo "[6/7] Activating virtual environment..."
if [ -d "venv" ]; then
    source venv/bin/activate
else
    echo "      ERROR: venv/ not found. Run: python3 -m venv venv && pip install -r requirements.txt"
    exit 1
fi

# ── 6. Launch Sentinel AI ────────────────────────────────────────────
echo "[7/7] Launching Sentinel AI..."
echo ""
echo "================================================================"
echo "  Dashboard (local)   → http://localhost:5001"
echo "  Dashboard (network) → http://$LOCAL_IP:5001"
echo "  Remote client cmd   → python sentinel_client.py --hub http://$LOCAL_IP:5001 --device <name>"
echo "  Stop                → Ctrl+C"
echo "================================================================"
echo ""
python main.py
