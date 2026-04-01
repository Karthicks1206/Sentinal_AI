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
echo "[1/6] Stopping any existing Sentinel instances..."
kill $(lsof -ti :5001) 2>/dev/null && echo "      Killed Flask server on :5001" || true
pkill -f "python.*main.py"      2>/dev/null && echo "      Killed background main.py" || true
pkill -f "cpu_stress\|memory_stress\|disk_stress" 2>/dev/null && echo "      Killed stress simulations" || true
sleep 1

# ── 2. Clear Python cache (avoids stale bytecode issues) ────────────
echo "[2/6] Clearing Python cache..."
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
find . -name "*.pyc" -delete 2>/dev/null || true

# ── 3. Start PostgreSQL ──────────────────────────────────────────────
echo "[3/6] Starting PostgreSQL..."
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
echo "[4/6] Starting Ollama (llama3.2:3b)..."
if command -v brew &>/dev/null; then
    brew services start ollama 2>/dev/null || true
else
    ollama serve &>/dev/null &
fi
sleep 2

# ── 5. Activate virtual environment ─────────────────────────────────
echo "[5/6] Activating virtual environment..."
if [ -d "venv" ]; then
    source venv/bin/activate
else
    echo "      ERROR: venv/ not found. Run: python3 -m venv venv && pip install -r requirements.txt"
    exit 1
fi

# ── 6. Launch Sentinel AI ────────────────────────────────────────────
echo "[6/6] Launching Sentinel AI..."
echo ""
echo "================================================================"
echo "  Dashboard → http://localhost:5001"
echo "  Stop      → Ctrl+C"
echo "================================================================"
echo ""
python main.py
