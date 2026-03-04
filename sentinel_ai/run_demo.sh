#!/bin/bash
# Sentinel AI - One-Command Complete Demo

clear

echo "╔════════════════════════════════════════════════════════════════╗"
echo "║                                                                ║"
echo "║           🛡️  SENTINEL AI - COMPLETE DEMONSTRATION            ║"
echo "║                                                                ║"
echo "║          Autonomous Self-Healing IoT Infrastructure            ║"
echo "║                                                                ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""
echo "This demo shows the COMPLETE workflow:"
echo ""
echo "  1. 🔥 CPU Stress Applied (95%+ usage)"
echo "  2. 🚨 System Detects Anomaly (10-15s)"
echo "  3. 🔍 System Diagnoses Root Cause"
echo "  4. 🔧 System Automatically Fixes Issue"
echo "  5. ✅ CPU Returns to Normal"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Check if in correct directory
if [ ! -f "dashboard/app.py" ]; then
    echo "❌ Error: Please run from sentinel_ai directory"
    echo ""
    echo "Usage:"
    echo "  cd sentinel_ai"
    echo "  ./run_demo.sh"
    echo ""
    exit 1
fi

# Check dependencies
echo "Checking dependencies..."
python3 -c "import flask, psutil, pyyaml" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "⚠️  Missing dependencies. Installing..."
    pip3 install -r requirements.txt --quiet
    echo "✅ Dependencies installed"
fi
echo ""

# Check if dashboard is already running
echo "Checking for running dashboard..."
curl -s http://localhost:5000 > /dev/null 2>&1
DASHBOARD_RUNNING=$?

if [ $DASHBOARD_RUNNING -eq 0 ]; then
    echo "✅ Dashboard already running at http://localhost:5000"
    echo ""
else
    echo "📺 Dashboard not running. Please start it:"
    echo ""
    echo "   Open a NEW terminal and run:"
    echo "   cd sentinel_ai"
    echo "   ./start_dashboard.sh"
    echo ""
    echo "   Then open browser: http://localhost:5000"
    echo ""
    echo -n "Press ENTER when dashboard is ready..."
    read
    echo ""

    # Check again
    curl -s http://localhost:5000 > /dev/null 2>&1
    if [ $? -ne 0 ]; then
        echo "⚠️  Dashboard still not detected"
        echo ""
        echo "Continue anyway? (demo will work, but won't show in dashboard)"
        echo -n "(y/n): "
        read answer
        if [ "$answer" != "y" ]; then
            echo "Exiting..."
            exit 0
        fi
    else
        echo "✅ Dashboard detected!"
    fi
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "📺 IMPORTANT: Keep your browser open at http://localhost:5000"
echo ""
echo "   You will see:"
echo "   • CPU bar turn RED when stress starts"
echo "   • Full-screen ALERT when anomaly detected"
echo "   • Diagnosis details in the alert"
echo "   • Recovery action in logs"
echo "   • CPU bar turn GREEN when fixed"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo -n "Ready to start? Press ENTER..."
read
echo ""

# Run the demo
python3 demo_complete_workflow.py

# Summary
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "📊 DEMO COMPLETE!"
echo ""
echo "Next steps:"
echo ""
echo "  1. Check dashboard statistics (Anomalies, Diagnoses, Recoveries)"
echo ""
echo "  2. View database:"
echo "     sqlite3 data/sentinel.db 'SELECT * FROM incidents;'"
echo ""
echo "  3. Run other tests:"
echo "     python3 trigger_anomaly.py memory"
echo "     python3 trigger_anomaly.py combo"
echo ""
echo "  4. Run full test suite:"
echo "     python3 test_workflow.py"
echo ""
echo "  5. Read documentation:"
echo "     cat COMPLETE_DEMO.md"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Thank you for watching Sentinel AI in action! 🎉"
echo ""
