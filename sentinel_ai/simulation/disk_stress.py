#!/usr/bin/env python3
"""
Disk Stress Script — Sentinel AI Simulation
Creates large temp files to simulate disk I/O anomaly, then holds for duration.
Recovery agent clears /tmp/sentinel_stress/ to resolve the issue.
"""
import sys
import time
import os
import tempfile
import shutil


STRESS_DIR = '/tmp/sentinel_disk_stress'


def main():
    mb = int(sys.argv[1]) if len(sys.argv) > 1 else 512
    duration = float(sys.argv[2]) if len(sys.argv) > 2 else 60.0

    os.makedirs(STRESS_DIR, exist_ok=True)
    print(f"[sentinel-disk-stress] PID={os.getpid()} writing {mb}MB to {STRESS_DIR} for {duration}s", flush=True)

    chunk = b'X' * (1024 * 1024)
    files = []
    for i in range(mb):
        path = os.path.join(STRESS_DIR, f'stress_{i:04d}.bin')
        with open(path, 'wb') as f:
            f.write(chunk)
        files.append(path)

    print(f"[sentinel-disk-stress] {mb}MB written. Holding for {duration}s...", flush=True)
    time.sleep(duration)

    shutil.rmtree(STRESS_DIR, ignore_errors=True)
    print(f"[sentinel-disk-stress] Done. Files removed.", flush=True)


if __name__ == '__main__':
    main()
