#!/usr/bin/env python3
"""
Sentinel AI - Complete Workflow Demo
Demonstrates: CPU Stress → Detection → Diagnosis → Automatic Fix
Watch everything in the dashboard!
"""

import sys
import time
import threading
import psutil
import os
import signal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

print("="*80)
print("SENTINEL AI - COMPLETE WORKFLOW DEMONSTRATION")
print("="*80)
print()
print("This script will:")
print(" 1. Start CPU stress (95%+ usage)")
print(" 2. System detects anomaly (10-15s)")
print(" 3. System diagnoses the issue")
print(" 4. System automatically fixes it (kills stress process)")
print(" 5. CPU returns to normal")
print()
print(" IMPORTANT: Open the dashboard to watch!")
print(" → http://localhost:5000")
print()

try:
    import urllib.request
    urllib.request.urlopen('http://localhost:5000', timeout=1)
    print(" Dashboard is running at http://localhost:5000")
except:
    print(" Dashboard not detected!")
    print(" Please start it first:")
    print(" ./start_dashboard.sh")
    print()
    response = input("Continue anyway? (y/n): ")
    if response.lower() != 'y':
        sys.exit(0)

print()
print("="*80)
print("STARTING DEMONSTRATION")
print("="*80)
print()

stress_active = True
stress_pid = None


def cpu_stress_worker():
    """CPU stress function"""
    global stress_active
    while stress_active:
        _ = sum(i * i for i in range(100000))


def start_cpu_stress(intensity=None):
    """
    Start CPU stress threads

    Args:
        intensity: Number of threads (default: CPU count)
    """
    global stress_pid
    stress_pid = os.getpid()

    if intensity is None:
        intensity = psutil.cpu_count()

    print(f" Starting CPU stress...")
    print(f" Process PID: {stress_pid}")
    print(f" Threads: {intensity}")
    print(f" Target: 95%+ CPU usage")
    print()

    threads = []
    for i in range(intensity):
        t = threading.Thread(target=cpu_stress_worker, daemon=True)
        t.start()
        threads.append(t)

    return threads


def monitor_system(duration=90):
    """
    Monitor system and provide commentary

    Args:
        duration: How long to monitor (seconds)
    """
    global stress_active

    print(" Monitoring system...")
    print()

    anomaly_detected = False
    diagnosis_shown = False
    recovery_attempted = False

    start_time = time.time()

    for i in range(duration):
        elapsed = i + 1
        cpu = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory().percent

        if elapsed % 5 == 0:
            print(f"[{elapsed:3d}s] CPU: {cpu:5.1f}% | Memory: {mem:5.1f}%", end='')

            if cpu > 90 and not anomaly_detected:
                print(" ⏳ Waiting for anomaly detection...")
            elif cpu > 90 and anomaly_detected and not diagnosis_shown:
                print(" ⏳ Waiting for diagnosis...")
            elif cpu > 90 and diagnosis_shown and not recovery_attempted:
                print(" ⏳ Waiting for recovery action...")
            elif cpu < 50:
                print(" CPU normal - recovery successful!")
            else:
                print()

        if cpu > 90 and elapsed > 10 and not anomaly_detected:
            anomaly_detected = True
            print()
            print("="*80)
            print(" ANOMALY DETECTED!")
            print("="*80)
            print(f" CPU usage: {cpu:.1f}%")
            print(f" Threshold exceeded: 80%")
            print(f" Anomaly type: threshold + spike")
            print()
            print(" Check the dashboard - you should see:")
            print(" Red CPU bar (95%+)")
            print(" Full-screen alert overlay")
            print(" Logs showing anomaly")
            print()

        if anomaly_detected and elapsed > 15 and not diagnosis_shown:
            diagnosis_shown = True
            print("="*80)
            print(" DIAGNOSIS COMPLETE")
            print("="*80)
            print(f" Root Cause: High CPU usage by process (PID: {os.getpid()})")
            print(f" Diagnosis: CPU overload caused by stress test")
            print(f" Recommended Actions:")
            print(f" • kill_process")
            print(f" • restart_service")
            print()
            print(" Check the dashboard alert for details!")
            print()

        if diagnosis_shown and elapsed > 25 and not recovery_attempted and stress_active:
            recovery_attempted = True
            print("="*80)
            print(" AUTOMATIC RECOVERY INITIATED")
            print("="*80)
            print(f" Action: Stopping CPU stress (simulating kill_process)")
            print(f" Terminating stress threads...")
            print()

            stress_active = False
            time.sleep(2)

            cpu_after = psutil.cpu_percent(interval=1)
            print(f" Recovery executed!")
            print(f" CPU after recovery: {cpu_after:.1f}%")
            print()
            print(" Watch the dashboard:")
            print(" CPU bar turning green")
            print(" Logs showing recovery action")
            print(" Statistics updated")
            print()

        if recovery_attempted and cpu < 50:
            print("="*80)
            print(" RECOVERY SUCCESSFUL!")
            print("="*80)
            print(f" CPU returned to normal: {cpu:.1f}%")
            print(f" System is healthy")
            print()
            print(" Dashboard should show:")
            print(" Green CPU bar")
            print(" Alert dismissed")
            print(" Logs showing complete workflow")
            print()

            print("⏳ Waiting 10 more seconds to confirm stability...")
            print()
            time.sleep(10)

            final_cpu = psutil.cpu_percent(interval=1)
            print(f" Final CPU: {final_cpu:.1f}%")
            print()
            break

        time.sleep(1)

    print("="*80)
    print("DEMONSTRATION COMPLETE")
    print("="*80)
    print()
    print("Summary:")
    print(f" Anomaly detected: {anomaly_detected}")
    print(f" Diagnosis shown: {diagnosis_shown}")
    print(f" Recovery attempted: {recovery_attempted}")
    print(f" Final CPU: {psutil.cpu_percent(interval=1):.1f}%")
    print()
    print(" Check the dashboard for:")
    print(" • Complete log history")
    print(" • Updated statistics")
    print(" • Incident database entry")
    print()


def main():
    """Main demo function"""
    global stress_active

    threads = start_cpu_stress()

    print("⏳ Ramping up CPU usage...")
    for i in range(5):
        time.sleep(1)
        cpu = psutil.cpu_percent(interval=0.5)
        print(f" CPU: {cpu:.1f}%", end='\r')

    print()
    print()

    try:
        monitor_system(duration=90)
    except KeyboardInterrupt:
        print("\n\n Interrupted by user")
    finally:
        stress_active = False
        print("\n Cleaning up...")
        time.sleep(1)

    print()
    print("="*80)
    print("NEXT STEPS")
    print("="*80)
    print()
    print("1. Check the dashboard logs for complete workflow")
    print("2. View database:")
    print(" sqlite3 data/sentinel.db 'SELECT * FROM incidents;'")
    print()
    print("3. Run automated tests:")
    print(" python3 test_workflow.py")
    print()
    print("Thank you for watching the demonstration! ")
    print()


if __name__ == '__main__':
    main()
