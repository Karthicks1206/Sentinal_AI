#!/usr/bin/env python3
"""
Sentinel AI - Anomaly Trigger Script
Use this to trigger anomalies for testing the dashboard
"""

import sys
import time
import threading
import psutil
import argparse


def trigger_cpu_overload(duration=60, intensity=4):
    """
    Trigger CPU overload

    Args:
        duration: How long to run (seconds)
        intensity: Number of CPU-burning threads
    """
    print(f" Triggering CPU overload...")
    print(f" Duration: {duration}s")
    print(f" Threads: {intensity}")

    stop_event = threading.Event()

    def cpu_burner():
        """Burn CPU cycles"""
        while not stop_event.is_set():
            _ = sum(i * i for i in range(100000))

    threads = []
    for i in range(intensity):
        t = threading.Thread(target=cpu_burner, daemon=True)
        t.start()
        threads.append(t)
        print(f" Started thread {i+1}/{intensity}")

    print(f"\n⏱ Running for {duration} seconds...")
    print(f" Current CPU: {psutil.cpu_percent(interval=1):.1f}%")

    for i in range(duration):
        time.sleep(1)
        if i % 5 == 0:
            cpu = psutil.cpu_percent(interval=0.1)
            print(f" [{i+1}/{duration}s] CPU: {cpu:.1f}%", end='\r')

    print(f"\n\n Stopping CPU stress...")
    stop_event.set()

    for t in threads:
        t.join(timeout=1)

    print(f" CPU stress test complete!")
    print(f" Final CPU: {psutil.cpu_percent(interval=1):.1f}%")


def trigger_memory_spike(percent=30, duration=60):
    """
    Trigger memory spike

    Args:
        percent: Percentage of available memory to allocate (0-100)
        duration: How long to hold memory (seconds)
    """
    print(f" Triggering memory spike...")

    mem = psutil.virtual_memory()
    available_mb = mem.available / (1024 * 1024)
    target_mb = int(available_mb * (percent / 100))

    print(f" Available: {available_mb:.0f}MB")
    print(f" Target: {target_mb}MB ({percent}% of available)")
    print(f" Duration: {duration}s")

    print(f"\n⏱ Allocating memory...")

    memory_hog = []
    chunk_size = 1024 * 1024

    try:
        for i in range(target_mb):
            memory_hog.append(' ' * chunk_size)

            if i % 100 == 0:
                current_mem = psutil.virtual_memory()
                print(f" Allocated: {i}MB / {target_mb}MB | Usage: {current_mem.percent:.1f}%", end='\r')

        current_mem = psutil.virtual_memory()
        print(f"\n\n Memory allocated!")
        print(f" Memory usage: {current_mem.percent:.1f}%")
        print(f" Used: {current_mem.used / (1024**3):.2f}GB / {current_mem.total / (1024**3):.2f}GB")

        print(f"\n⏱ Holding for {duration} seconds...")

        for i in range(duration):
            time.sleep(1)
            if i % 5 == 0:
                mem = psutil.virtual_memory()
                print(f" [{i+1}/{duration}s] Memory: {mem.percent:.1f}%", end='\r')

        print(f"\n\n Releasing memory...")
        memory_hog.clear()
        del memory_hog

        time.sleep(1)
        final_mem = psutil.virtual_memory()
        print(f" Memory released!")
        print(f" Final usage: {final_mem.percent:.1f}%")

    except MemoryError:
        print(f"\n MemoryError: System ran out of memory (expected on constrained systems)")
        memory_hog.clear()


def trigger_combo(cpu_duration=30, mem_duration=30):
    """
    Trigger both CPU and memory stress simultaneously

    Args:
        cpu_duration: CPU stress duration
        mem_duration: Memory stress duration
    """
    print(f" Triggering COMBO stress test...")
    print(f" This will stress both CPU and memory!")
    print()

    cpu_thread = threading.Thread(
        target=trigger_cpu_overload,
        args=(cpu_duration, 4),
        daemon=True
    )
    cpu_thread.start()

    time.sleep(2)

    trigger_memory_spike(percent=25, duration=mem_duration)

    cpu_thread.join()

    print(f"\n COMBO stress test complete!")


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='Trigger anomalies for Sentinel AI testing',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Trigger CPU overload for 60 seconds
  python3 trigger_anomaly.py cpu

  # Trigger CPU overload for 30 seconds
  python3 trigger_anomaly.py cpu --duration 30

  # Trigger memory spike (30% of available)
  python3 trigger_anomaly.py memory

  # Trigger memory spike (50% for 45 seconds)
  python3 trigger_anomaly.py memory --percent 50 --duration 45

  # Trigger both CPU and memory
  python3 trigger_anomaly.py combo

Use this while the dashboard is running to see anomaly detection in action!
        """
    )

    parser.add_argument(
        'type',
        choices=['cpu', 'memory', 'combo'],
        help='Type of anomaly to trigger'
    )

    parser.add_argument(
        '--duration',
        type=int,
        default=60,
        help='Duration in seconds (default: 60)'
    )

    parser.add_argument(
        '--percent',
        type=int,
        default=30,
        help='Memory percentage to allocate (default: 30)'
    )

    parser.add_argument(
        '--intensity',
        type=int,
        default=None,
        help='CPU stress intensity (number of threads, default: CPU count)'
    )

    args = parser.parse_args()

    print("="*60)
    print("SENTINEL AI - ANOMALY TRIGGER")
    print("="*60)
    print()

    if args.type == 'cpu':
        intensity = args.intensity if args.intensity else psutil.cpu_count()
        trigger_cpu_overload(duration=args.duration, intensity=intensity)

    elif args.type == 'memory':
        trigger_memory_spike(percent=args.percent, duration=args.duration)

    elif args.type == 'combo':
        trigger_combo(cpu_duration=args.duration, mem_duration=args.duration)

    print()
    print("="*60)
    print("Check the dashboard to see the anomaly detection!")
    print("="*60)


if __name__ == '__main__':
    main()
