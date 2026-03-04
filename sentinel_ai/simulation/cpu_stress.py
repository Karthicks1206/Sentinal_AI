#!/usr/bin/env python3
"""
CPU Stress Script — Sentinel AI Simulation
Runs as a separate subprocess. Burns CPU across multiple cores for a fixed duration.
The recovery agent kills this process by PID to resolve the simulated CPU anomaly.
"""
import sys
import time
import os
import multiprocessing


def burn_cpu(duration: float):
    """Burn one CPU core for the given duration."""
    end = time.time() + duration
    while time.time() < end:
        # Pure computation — no sleep, no I/O
        _ = sum(i * i for i in range(10_000))


def main():
    duration = float(sys.argv[1]) if len(sys.argv) > 1 else 60.0
    cores = int(sys.argv[2]) if len(sys.argv) > 2 else max(1, multiprocessing.cpu_count() - 2)

    print(f"[sentinel-cpu-stress] PID={os.getpid()} burning {cores} cores for {duration}s", flush=True)

    workers = []
    for _ in range(cores):
        p = multiprocessing.Process(target=burn_cpu, args=(duration,), daemon=True)
        p.start()
        workers.append(p)

    for w in workers:
        w.join()

    print(f"[sentinel-cpu-stress] Done", flush=True)


if __name__ == '__main__':
    main()
