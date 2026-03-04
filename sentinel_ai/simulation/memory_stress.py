#!/usr/bin/env python3
"""
Memory Stress Script — Sentinel AI Simulation
Allocates a large chunk of RAM for a fixed duration, then releases it.
The recovery agent kills this process by PID to resolve the memory anomaly.
"""
import sys
import time
import os


def main():
    mb = int(sys.argv[1]) if len(sys.argv) > 1 else 1024
    duration = float(sys.argv[2]) if len(sys.argv) > 2 else 60.0

    print(f"[sentinel-memory-stress] PID={os.getpid()} allocating {mb}MB for {duration}s", flush=True)

    # Allocate memory and touch every page so the OS actually maps it
    chunk_size = 1024 * 1024  # 1 MB
    blocks = []
    for i in range(mb):
        block = bytearray(chunk_size)
        # Write to each page to force physical allocation
        for j in range(0, chunk_size, 4096):
            block[j] = i % 256
        blocks.append(block)

    print(f"[sentinel-memory-stress] {mb}MB allocated. Holding for {duration}s...", flush=True)
    time.sleep(duration)

    del blocks
    print(f"[sentinel-memory-stress] Done. Memory released.", flush=True)


if __name__ == '__main__':
    main()
