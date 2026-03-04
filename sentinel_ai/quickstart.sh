#!/bin/bash
# Sentinel AI - Quick Start Script

set -e

echo "========================================="
echo "Sentinel AI - Quick Start Setup"
echo "========================================="
echo ""

# Check Python version
echo "Checking Python version..."
PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
echo "Found Python $PYTHON_VERSION"

if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)'; then
    echo "ERROR: Python 3.8+ required"
    exit 1
fi
echo "✓ Python version OK"
echo ""

# Install dependencies
echo "Installing dependencies..."
pip3 install -r requirements.txt --quiet
echo "✓ Dependencies installed"
echo ""

# Create directories
echo "Creating directories..."
mkdir -p data logs certs
echo "✓ Directories created"
echo ""

# Set default environment variables
echo "Setting environment variables..."
export DEVICE_ID="${DEVICE_ID:-sentinel-quickstart-$(hostname)}"
export ENVIRONMENT="${ENVIRONMENT:-development}"
export AWS_REGION="${AWS_REGION:-us-east-1}"
export LOG_LEVEL="${LOG_LEVEL:-INFO}"

echo "  DEVICE_ID=$DEVICE_ID"
echo "  ENVIRONMENT=$ENVIRONMENT"
echo "  AWS_REGION=$AWS_REGION"
echo "✓ Environment configured"
echo ""

# Check MQTT (optional)
echo "Checking MQTT broker..."
if command -v mosquitto &> /dev/null; then
    echo "✓ Mosquitto found"
    if pgrep mosquitto > /dev/null; then
        echo "✓ Mosquitto is running"
    else
        echo "⚠ Mosquitto not running (optional for local testing)"
    fi
else
    echo "⚠ Mosquitto not installed (optional for local testing)"
fi
echo ""

# Verify configuration
echo "Verifying configuration..."
if [ ! -f "config/config.yaml" ]; then
    echo "ERROR: config/config.yaml not found"
    exit 1
fi
echo "✓ Configuration file found"
echo ""

# Test import
echo "Testing Python imports..."
python3 -c "
from core.config import get_config
from core.logging import setup_logging, get_logger
from core.event_bus import get_event_bus
print('✓ All imports successful')
"
echo ""

# Summary
echo "========================================="
echo "Setup Complete!"
echo "========================================="
echo ""
echo "To start Sentinel AI:"
echo ""
echo "  python3 main.py"
echo ""
echo "For simulation mode:"
echo ""
echo "  python3 main.py --simulate"
echo ""
echo "For custom config:"
echo ""
echo "  python3 main.py --config /path/to/config.yaml"
echo ""
echo "For production deployment, see:"
echo "  - docs/RASPBERRY_PI_DEPLOYMENT.md"
echo "  - docs/README.md"
echo ""
echo "Happy monitoring! 🚀"
echo ""
