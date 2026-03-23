================================================================================
  SENTINEL AI — REMOTE MONITOR  (v1.2)
================================================================================

This folder contains everything needed to monitor this machine with Sentinel AI.

QUICK START (one-time setup + run):
------------------------------------

  Step 1 — install the dependency (only once):
    pip install -r requirements.txt

  Step 2 — start monitoring:
    python sentinel_client.py

That's it.  The client auto-discovers the Sentinel AI hub on your network.

--------------------------------------------------------------------------------
OPTIONAL ARGUMENTS
--------------------------------------------------------------------------------

  Give this machine a custom name on the dashboard:
    python sentinel_client.py --device my-laptop

  If auto-discovery fails (different subnet or AP isolation):
    python sentinel_client.py --hub http://<HUB_IP>:5001

  Test connectivity before streaming (use this to diagnose problems):
    python sentinel_client.py --hub http://<HUB_IP>:5001 --test

  Change the push interval (default 5 seconds):
    python sentinel_client.py --interval 10

--------------------------------------------------------------------------------
FIND THE HUB IP
--------------------------------------------------------------------------------

  macOS / Linux hub:
    ipconfig getifaddr en0        (macOS)
    hostname -I | awk '{print $1}'  (Linux)

  Windows hub:
    ipconfig | findstr IPv4

--------------------------------------------------------------------------------
TROUBLESHOOTING
--------------------------------------------------------------------------------

  Run --test first — it tells you exactly where the connection breaks:

    python sentinel_client.py --hub http://192.168.1.x:5001 --test

  Output example:
    Step 1 — DNS/IP resolve .......... PASS
    Step 2 — TCP connect port 5001 ... FAIL  ← problem here
    Step 3 — HTTP /api/status ........ skipped

  Common causes of failure:

  AP ISOLATION (most common on WiFi)
    Your router may be blocking device-to-device traffic.
    Fix: Disable "AP Isolation" / "Client Isolation" in your router settings
    (usually under Wireless → Advanced).
    Alternative: Use Ethernet instead of WiFi.

  FIREWALL ON HUB MACHINE
    macOS: System Settings → Network → Firewall → Allow Python incoming.
    Linux: sudo ufw allow 5001/tcp

  WRONG IP / HUB NOT RUNNING
    Confirm the hub is running (python main.py) and the IP is correct.
    Test: ping <HUB_IP>  — if this fails, it's a network issue.

  WINDOWS ONLY — No output / script exits immediately
    This was a Python version compatibility bug fixed in v1.2.
    Ensure you have the latest sentinel_client.py.
    Requires Python 3.7+.  Check: python --version

--------------------------------------------------------------------------------
WHAT GETS MONITORED
--------------------------------------------------------------------------------

  Every 5 seconds the client collects and pushes:
    • CPU usage (%)
    • Memory usage (%)
    • Disk usage (%)
    • Network bytes sent/received
    • Platform and OS info

  On the hub dashboard (http://<HUB_IP>:5001) you'll see this device listed
  under "Connected Devices" with live metrics and any anomaly alerts.

================================================================================
