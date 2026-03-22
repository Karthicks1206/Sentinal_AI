================================================================================
  SENTINEL AI — REMOTE MONITOR
================================================================================

This folder contains everything needed to monitor this machine with Sentinel AI.

QUICK START (one-time setup + run):
------------------------------------

  Step 1 — install the dependency (only once):
    pip install -r requirements.txt

  Step 2 — start monitoring:
    python sentinel_client.py

That's it.  The client auto-discovers the Sentinel AI hub on your network.

OPTIONAL — give this machine a custom name on the dashboard:
    python sentinel_client.py --device my-laptop

OPTIONAL — if auto-discovery fails (different subnet):
    python sentinel_client.py --hub http://<HUB_IP>:5001

================================================================================
