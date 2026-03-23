"""
Sentinel AI — Hub Discovery Beacon

Broadcasts the hub's URL on the local network via UDP so that
sentinel_client.py instances can find it automatically with zero
configuration — no IP addresses to look up or type.

How it works:
  1. The beacon thread listens on UDP port 47474 for SENTINEL_DISCOVER packets.
  2. It also broadcasts a SENTINEL_HUB announcement every 10 seconds.
  3. Any client that sends SENTINEL_DISCOVER gets an immediate reply with the
     hub's HTTP URL.

Start it once from main.py or dashboard/app.py:
    from core.discovery_beacon import DiscoveryBeacon
    beacon = DiscoveryBeacon(port=5001)
    beacon.start()
"""

import json
import socket
import threading
import time
from typing import Optional


DISCOVERY_PORT = 47474
DISCOVERY_MSG = b"SENTINEL_DISCOVER"
BEACON_INTERVAL = 10


class DiscoveryBeacon:
    """
    Dual-mode UDP beacon:
      • Listens for SENTINEL_DISCOVER requests and replies instantly.
      • Broadcasts SENTINEL_HUB announcements every 10 seconds so clients
        hear the hub even before sending a discovery request.
    """

    def __init__(self, http_port: int = 5001):
        self._http_port = http_port
        self._running = False
        self._threads: list[threading.Thread] = []


    def start(self):
        self._running = True

        listener = threading.Thread(
            target=self._listen_loop, daemon=True, name='DiscoveryListener'
        )
        broadcaster = threading.Thread(
            target=self._broadcast_loop, daemon=True, name='DiscoveryBroadcaster'
        )
        self._threads = [listener, broadcaster]
        for t in self._threads:
            t.start()

    def stop(self):
        self._running = False


    def _build_payload(self) -> bytes:
        """Build the JSON announcement payload containing this hub's URL."""
        local_ip = self._local_ip()
        payload = {
            'sentinel_hub': True,
            'url': f"http://{local_ip}:{self._http_port}",
            'version': '1.0',
        }
        return json.dumps(payload).encode()

    @staticmethod
    def _local_ip() -> str:
        """Return the machine's primary LAN IP address (not 127.0.0.1)."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('8.8.8.8', 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return '127.0.0.1'


    def _listen_loop(self):
        """Listen for SENTINEL_DISCOVER UDP packets and reply immediately."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(1.0)
        try:
            sock.bind(('', DISCOVERY_PORT))
        except OSError:
            return

        while self._running:
            try:
                data, addr = sock.recvfrom(256)
                if data == DISCOVERY_MSG:
                    sock.sendto(self._build_payload(), addr)
            except socket.timeout:
                pass
            except Exception:
                pass

        sock.close()


    def _broadcast_loop(self):
        """Broadcast hub presence every BEACON_INTERVAL seconds."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

        while self._running:
            try:
                payload = self._build_payload()
                sock.sendto(payload, ('<broadcast>', DISCOVERY_PORT))
            except OSError:
                try:
                    sock.sendto(payload, ('255.255.255.255', DISCOVERY_PORT))
                except Exception:
                    pass
            except Exception:
                pass

            for _ in range(BEACON_INTERVAL * 2):
                if not self._running:
                    break
                time.sleep(0.5)

        sock.close()
