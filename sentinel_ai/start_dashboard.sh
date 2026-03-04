#!/bin/bash
# Sentinel AI - Dashboard Startup Script

echo "========================================="
echo "Sentinel AI - Starting Dashboard"
echo "========================================="
echo ""

# Check if running from correct directory
if [ ! -f "dashboard/app.py" ]; then
    echo "Error: Please run from sentinel_ai directory"
    echo "Usage: ./start_dashboard.sh"
    exit 1
fi

# Check Python dependencies
echo "Checking dependencies..."
python3 -c "import flask" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "Flask not found. Installing dependencies..."
    pip3 install -r requirements.txt
fi

# Create necessary directories
mkdir -p data logs

# Export environment variables
export FLASK_ENV=production
export DEVICE_ID="${DEVICE_ID:-sentinel-dashboard-$(hostname)}"
export AWS_ENABLED=false

echo "Configuration:"
echo "  Device ID: $DEVICE_ID"
echo "  AWS: Disabled (local mode)"
echo ""

# Start dashboard
echo "Starting dashboard server..."
echo "Open your browser: http://localhost:5000"
echo ""
echo "Press Ctrl+C to stop"
echo ""

python3 dashboard/app.py
