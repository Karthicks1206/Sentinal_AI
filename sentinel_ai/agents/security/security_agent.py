"""
Security Agent — Sentinel AI Cybersecurity Monitor
Detects suspicious activity patterns on IoT/edge devices.

Threat checks (all real-data, run every scan):
  1.  _check_open_ports              — unexpected listening ports
  2.  _check_connection_anomaly      — connection flood / scan burst
  3.  _check_privileged_processes    — unexpected root/SYSTEM processes
  4.  _check_suspicious_outbound     — connections to unusual external IPs/ports
  5.  _check_brute_force             — repeated auth failures (SSH / login)
  6.  _check_data_exfiltration       — unusually high outbound data transfer
  7.  _check_malware_process_names   — processes matching known malware patterns
  8.  _check_critical_file_changes   — recent modifications to critical system files

Claude AI layer (claude-opus-4-6):
  Every raw finding is passed to Claude before being published.
  Claude determines: is_genuine, severity, analysis, recommended_action.
  Fail-OPEN — if Claude errors or key is missing, findings are published as-is.

Production path: replace check bodies with Suricata/Zeek/GuardDuty ingestion
and keep the Claude analysis layer as-is.
"""

import json
import os
import platform
import random
import socket
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import psutil

from agents.base_agent import BaseAgent
from core.event_bus import EventPriority


SEVERITY_INFO     = 'info'
SEVERITY_LOW      = 'low'
SEVERITY_MEDIUM   = 'medium'
SEVERITY_HIGH     = 'high'
SEVERITY_CRITICAL = 'critical'

_SEVERITY_RANK = {
    SEVERITY_INFO: 0, SEVERITY_LOW: 1,
    SEVERITY_MEDIUM: 2, SEVERITY_HIGH: 3, SEVERITY_CRITICAL: 4,
}

# Known malware / suspicious process name fragments (case-insensitive match)
_MALWARE_PATTERNS = {
    'xmrig', 'minerd', 'cryptominer', 'coinminer',      # crypto miners
    'mirai', 'bashlite', 'gafgyt', 'hajime',             # IoT botnets
    'masscan', 'zmap', 'nmap', 'nikto', 'sqlmap',        # scan tools
    'netcat', 'ncat', 'socat',                           # reverse-shell tools
    'meterpreter', 'cobalt', 'empire',                   # post-exploit frameworks
    'ngrok', 'frp', 'chisel',                            # tunnelling tools
    'backdoor', 'rootkit', 'keylogger',                  # generic malware
}

# Ports that external connections should NEVER come from on IoT devices
_SUSPICIOUS_EXTERNAL_PORTS = {
    4444, 4445,       # Metasploit default
    1337, 31337,      # classic backdoor ports
    6666, 6667, 6668, # IRC (often C2)
    9001, 9030,       # Tor
    8888, 9999,       # common C2 fallback
}

# Critical system files — any modification within the scan window is suspicious
_CRITICAL_FILES_LINUX  = ['/etc/passwd', '/etc/shadow', '/etc/sudoers', '/etc/hosts',
                           '/etc/crontab', '/etc/ld.so.preload']
_CRITICAL_FILES_MACOS  = ['/etc/hosts', '/etc/sudoers', '/private/etc/hosts',
                           '/Library/LaunchDaemons', '/System/Library/LaunchDaemons']
_CRITICAL_FILES_WINDOWS = ['C:\\Windows\\System32\\drivers\\etc\\hosts',
                            'C:\\Windows\\System32\\drivers\\etc\\networks']

# Safe root/SYSTEM process names
_SAFE_ROOT_NAMES = {
    'kernel_task', 'launchd', 'systemd', 'init', 'kthreadd',
    'python', 'python3', 'sshd', 'sentinel', 'sentinel_ai',
    'kworker', 'kswapd', 'rcu_sched', 'ksoftirqd',
    'WindowServer', 'loginwindow', 'com.apple',
}


class SecurityAgent(BaseAgent):
    """
    Comprehensive cybersecurity monitor.
    Runs 8 threat-detection checks, passes each finding to Claude for
    intelligent analysis, and publishes genuine threats to the event bus.
    """

    def __init__(self, name: str, config, event_bus, logger, database=None):
        super().__init__(name, config, event_bus, logger)

        self.database      = database
        self.device_id     = config.device_id
        self.scan_interval = config.get('security.scan_interval_seconds', 30)
        self.demo_mode     = config.get('security.demo_mode', True)

        self._expected_ports: set = set(
            config.get('security.allowlist_ports',
                       [22, 80, 443, 1883, 5001, 8883])
        )

        # Rolling window for exfiltration baseline
        self._prev_net_bytes_sent: Optional[int] = None
        self._prev_scan_time: Optional[datetime] = None

        # Auth-failure baseline (unix only)
        self._prev_auth_log_size: int = 0

        self.threat_history: List[Dict] = []

        # ── Claude client ────────────────────────────────────────────────
        self._claude_client = None
        self._claude_model  = 'claude-opus-4-6'
        self._init_claude(config)

    # ------------------------------------------------------------------ init

    def _init_claude(self, config):
        api_key = os.environ.get('ANTHROPIC_API_KEY', '').strip()
        if not api_key:
            self.logger.info(
                "Security Agent: no ANTHROPIC_API_KEY — Claude gate bypassed "
                "(threats published as-is)"
            )
            return
        try:
            import anthropic
            self._claude_client = anthropic.Anthropic(api_key=api_key)
            model_cfg = config.get('security.claude.model', self._claude_model)
            if model_cfg:
                self._claude_model = model_cfg
            self.logger.info(
                f"Security Agent: Claude AI enabled (model={self._claude_model})"
            )
        except Exception as exc:
            self.logger.warning(
                f"Security Agent: Claude init failed ({exc}) — "
                "publishing without AI analysis"
            )

    # ------------------------------------------------------------------ main loop

    def _run(self):
        self.logger.info("Security Agent started (8 threat checks + Claude AI)")
        while self._running:
            try:
                findings = self._scan_raw()
                for threat in findings:
                    enriched = self._claude_analyse(threat)
                    self._publish_threat(enriched)
            except Exception as exc:
                self.logger.error(f"Security scan error: {exc}", exc_info=True)
            if not self.wait(self.scan_interval):
                break

    # ================================================================== checks

    # ── 1. Unexpected open ports ─────────────────────────────────────────────

    def _check_open_ports(self) -> Optional[Dict]:
        """Unexpected listening ports — possible backdoor or rogue service."""
        try:
            listening = {
                conn.laddr.port
                for conn in psutil.net_connections(kind='inet')
                if conn.status == 'LISTEN'
            }
            unexpected = listening - self._expected_ports
            if unexpected:
                # Try to resolve owning processes
                port_owners: Dict[int, str] = {}
                for conn in psutil.net_connections(kind='inet'):
                    if conn.status == 'LISTEN' and conn.laddr.port in unexpected:
                        try:
                            p = psutil.Process(conn.pid)
                            port_owners[conn.laddr.port] = p.name()
                        except Exception:
                            port_owners[conn.laddr.port] = 'unknown'

                return self._make_threat(
                    category  = 'unexpected_port',
                    severity  = SEVERITY_HIGH if any(p in _SUSPICIOUS_EXTERNAL_PORTS
                                                     for p in unexpected) else SEVERITY_MEDIUM,
                    title     = 'Unexpected listening port(s)',
                    detail    = f"Ports not in allowlist: {sorted(unexpected)}",
                    indicators= {'ports': sorted(unexpected), 'owners': port_owners},
                    raw_data  = {
                        'unexpected_ports': sorted(unexpected),
                        'port_owners'     : port_owners,
                        'allowlisted'     : sorted(self._expected_ports),
                    },
                )
        except Exception as exc:
            self.logger.debug(f"Port check error: {exc}")
        return None

    # ── 2. Connection flood / port scan ──────────────────────────────────────

    def _check_connection_anomaly(self) -> Optional[Dict]:
        """High concurrent connection count — scan or flood indicator."""
        try:
            conns = psutil.net_connections(kind='inet')
            total = len(conns)
            if total > 200:
                established = sum(1 for c in conns if c.status == 'ESTABLISHED')
                time_wait   = sum(1 for c in conns if c.status == 'TIME_WAIT')
                remotes = [
                    f"{c.raddr.ip}:{c.raddr.port}"
                    for c in conns if c.raddr
                ][:15]
                # Check for concentration — many conns from single source = scan
                from collections import Counter
                source_counts = Counter(
                    c.raddr.ip for c in conns if c.raddr
                )
                top_source, top_count = source_counts.most_common(1)[0] \
                    if source_counts else ('unknown', 0)

                severity = SEVERITY_CRITICAL if total > 1000 \
                    else SEVERITY_HIGH if total > 500 else SEVERITY_MEDIUM

                return self._make_threat(
                    category  = 'connection_flood',
                    severity  = severity,
                    title     = 'High connection count',
                    detail    = f"{total} concurrent connections (top source: {top_source} × {top_count})",
                    indicators= {'connection_count': total, 'top_source': top_source},
                    raw_data  = {
                        'total_connections': total,
                        'established'      : established,
                        'time_wait'        : time_wait,
                        'top_source'       : top_source,
                        'top_source_count' : top_count,
                        'sample_remotes'   : remotes,
                    },
                )
        except Exception as exc:
            self.logger.debug(f"Connection check error: {exc}")
        return None

    # ── 3. Privileged processes ───────────────────────────────────────────────

    def _check_privileged_processes(self) -> Optional[Dict]:
        """Unexpected root/SYSTEM processes — possible privilege escalation."""
        try:
            suspicious = []
            details = []
            for proc in psutil.process_iter(['pid', 'name', 'username', 'cmdline', 'create_time']):
                try:
                    if proc.info['username'] in ('root', 'SYSTEM'):
                        name = (proc.info['name'] or '').lower()
                        if not any(s in name for s in _SAFE_ROOT_NAMES):
                            suspicious.append(proc.info['name'])
                            details.append({
                                'pid'    : proc.info['pid'],
                                'name'   : proc.info['name'],
                                'cmd'    : ' '.join((proc.info.get('cmdline') or [])[:4]),
                                'age_s'  : int(time.time() - (proc.info.get('create_time') or 0)),
                            })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            if suspicious:
                return self._make_threat(
                    category  = 'privileged_process',
                    severity  = SEVERITY_MEDIUM if len(suspicious) > 2 else SEVERITY_LOW,
                    title     = 'Unexpected privileged process(es)',
                    detail    = f"Root process(es): {', '.join(suspicious[:5])}",
                    indicators= {'processes': suspicious[:5]},
                    raw_data  = {
                        'count'           : len(suspicious),
                        'process_details' : details[:5],
                    },
                )
        except Exception as exc:
            self.logger.debug(f"Privilege check error: {exc}")
        return None

    # ── 4. Suspicious outbound connections ───────────────────────────────────

    def _check_suspicious_outbound(self) -> Optional[Dict]:
        """Connections from/to known-suspicious ports (C2, reverse shells, tunnels)."""
        try:
            hits = []
            for conn in psutil.net_connections(kind='inet'):
                if conn.status != 'ESTABLISHED' or not conn.raddr:
                    continue
                rport = conn.raddr.port
                rip   = conn.raddr.ip
                # Skip loopback
                if rip.startswith('127.') or rip == '::1':
                    continue
                if rport in _SUSPICIOUS_EXTERNAL_PORTS:
                    owner = 'unknown'
                    try:
                        owner = psutil.Process(conn.pid).name()
                    except Exception:
                        pass
                    hits.append({
                        'local' : f"{conn.laddr.ip}:{conn.laddr.port}",
                        'remote': f"{rip}:{rport}",
                        'owner' : owner,
                    })
            if hits:
                return self._make_threat(
                    category  = 'suspicious_outbound',
                    severity  = SEVERITY_HIGH,
                    title     = 'Suspicious outbound connection(s)',
                    detail    = (f"{len(hits)} connection(s) to known-suspicious ports "
                                 f"(e.g. {hits[0]['remote']} via {hits[0]['owner']})"),
                    indicators= {'hit_count': len(hits), 'sample': hits[:3]},
                    raw_data  = {'connections': hits[:10]},
                )
        except Exception as exc:
            self.logger.debug(f"Outbound check error: {exc}")
        return None

    # ── 5. Brute-force / auth failure ────────────────────────────────────────

    def _check_brute_force(self) -> Optional[Dict]:
        """
        Count recent failed SSH / auth attempts by reading system log.
        Works on Linux (auth.log / secure) and macOS (system.log).
        """
        log_paths = [
            '/var/log/auth.log',          # Debian/Ubuntu
            '/var/log/secure',            # RHEL/CentOS
            '/var/log/system.log',        # macOS
            '/private/var/log/system.log',
        ]
        try:
            for path in log_paths:
                if not os.path.exists(path):
                    continue
                size = os.path.getsize(path)
                if size == self._prev_auth_log_size:
                    continue  # no new entries
                self._prev_auth_log_size = size

                # Read last 4 KB — enough to catch recent bursts
                with open(path, 'rb') as fh:
                    fh.seek(max(0, size - 4096))
                    tail = fh.read().decode('utf-8', errors='replace')

                failure_keywords = [
                    'Failed password', 'authentication failure',
                    'Invalid user', 'Connection closed by invalid user',
                    'pam_unix.*failure',
                ]
                failures = [line for line in tail.splitlines()
                            if any(kw.lower() in line.lower()
                                   for kw in failure_keywords)]
                if len(failures) >= 5:
                    # Extract source IPs
                    import re
                    ips = re.findall(r'\b(?:\d{1,3}\.){3}\d{1,3}\b',
                                     '\n'.join(failures))
                    from collections import Counter
                    top_ips = Counter(ips).most_common(3)
                    return self._make_threat(
                        category  = 'brute_force',
                        severity  = SEVERITY_HIGH if len(failures) >= 20 else SEVERITY_MEDIUM,
                        title     = 'Auth failure burst detected',
                        detail    = (f"{len(failures)} recent auth failures in {path}; "
                                     f"top source: {top_ips[0][0] if top_ips else 'unknown'}"),
                        indicators= {'failure_count': len(failures), 'top_sources': top_ips},
                        raw_data  = {
                            'log_path'    : path,
                            'failure_count': len(failures),
                            'top_ips'     : top_ips,
                            'sample_lines': failures[-5:],
                        },
                    )
                break  # found + checked first available log
        except Exception as exc:
            self.logger.debug(f"Brute-force check error: {exc}")
        return None

    # ── 6. Data exfiltration ─────────────────────────────────────────────────

    def _check_data_exfiltration(self) -> Optional[Dict]:
        """
        Detect abnormally high outbound data transfer between scans.
        Baseline: rolling comparison across scan intervals.
        """
        try:
            net   = psutil.net_io_counters()
            now   = datetime.now(timezone.utc)
            sent  = net.bytes_sent

            if self._prev_net_bytes_sent is None:
                self._prev_net_bytes_sent = sent
                self._prev_scan_time      = now
                return None

            elapsed_s    = (now - self._prev_scan_time).total_seconds()
            delta_bytes  = sent - self._prev_net_bytes_sent
            self._prev_net_bytes_sent = sent
            self._prev_scan_time      = now

            if elapsed_s <= 0:
                return None

            delta_mb   = delta_bytes / (1024 * 1024)
            rate_mbps  = (delta_bytes * 8 / 1_000_000) / elapsed_s  # Mbps

            # Alert if >50 MB sent in one scan window OR >10 Mbps sustained
            if delta_mb > 50 or rate_mbps > 10:
                return self._make_threat(
                    category  = 'data_exfiltration',
                    severity  = SEVERITY_CRITICAL if delta_mb > 200 else SEVERITY_HIGH,
                    title     = 'Unusual outbound data transfer',
                    detail    = (f"{delta_mb:.1f} MB sent in {elapsed_s:.0f}s "
                                 f"({rate_mbps:.1f} Mbps)"),
                    indicators= {'delta_mb': round(delta_mb, 1), 'rate_mbps': round(rate_mbps, 2)},
                    raw_data  = {
                        'delta_bytes' : delta_bytes,
                        'delta_mb'    : round(delta_mb, 2),
                        'elapsed_s'   : round(elapsed_s, 1),
                        'rate_mbps'   : round(rate_mbps, 2),
                        'total_sent'  : sent,
                    },
                )
        except Exception as exc:
            self.logger.debug(f"Exfiltration check error: {exc}")
        return None

    # ── 7. Malware process name matching ─────────────────────────────────────

    def _check_malware_process_names(self) -> Optional[Dict]:
        """Scan running processes for names matching known malware patterns."""
        try:
            matches = []
            for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'username']):
                try:
                    name = (proc.info['name'] or '').lower()
                    cmd  = ' '.join(proc.info.get('cmdline') or []).lower()
                    for pattern in _MALWARE_PATTERNS:
                        if pattern in name or pattern in cmd:
                            matches.append({
                                'pid'    : proc.info['pid'],
                                'name'   : proc.info['name'],
                                'pattern': pattern,
                                'user'   : proc.info.get('username', 'unknown'),
                            })
                            break
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            if matches:
                names = [m['name'] for m in matches]
                return self._make_threat(
                    category  = 'malware_signature',
                    severity  = SEVERITY_CRITICAL,
                    title     = 'Malware-pattern process detected',
                    detail    = (f"Process(es) matching known malware patterns: "
                                 f"{', '.join(names[:3])}"),
                    indicators= {'matched': matches[:5]},
                    raw_data  = {'matches': matches[:10]},
                )
        except Exception as exc:
            self.logger.debug(f"Malware name check error: {exc}")
        return None

    # ── 8. Critical file modifications ───────────────────────────────────────

    def _check_critical_file_changes(self) -> Optional[Dict]:
        """Detect recent modifications to critical system files."""
        sys_platform = platform.system()
        if sys_platform == 'Linux':
            paths = _CRITICAL_FILES_LINUX
        elif sys_platform == 'Darwin':
            paths = _CRITICAL_FILES_MACOS
        elif sys_platform == 'Windows':
            paths = _CRITICAL_FILES_WINDOWS
        else:
            return None

        window_s = self.scan_interval * 3  # 3 scan windows = recent
        cutoff   = time.time() - window_s
        modified = []
        try:
            for path in paths:
                p = Path(path)
                if p.exists() and p.is_file():
                    mtime = p.stat().st_mtime
                    if mtime >= cutoff:
                        modified.append({
                            'path' : str(path),
                            'mtime': datetime.fromtimestamp(mtime).isoformat(),
                            'age_s': int(time.time() - mtime),
                        })
            if modified:
                return self._make_threat(
                    category  = 'critical_file_change',
                    severity  = SEVERITY_HIGH,
                    title     = 'Critical system file recently modified',
                    detail    = (f"{len(modified)} critical file(s) changed: "
                                 f"{', '.join(m['path'] for m in modified[:3])}"),
                    indicators= {'files': [m['path'] for m in modified]},
                    raw_data  = {'modified_files': modified},
                )
        except Exception as exc:
            self.logger.debug(f"File-change check error: {exc}")
        return None

    # ================================================================== orchestration

    def _scan_raw(self) -> List[Dict]:
        """Run all 8 checks and return raw findings list."""
        findings: List[Dict] = []
        for check in (
            self._check_open_ports,
            self._check_connection_anomaly,
            self._check_privileged_processes,
            self._check_suspicious_outbound,
            self._check_brute_force,
            self._check_data_exfiltration,
            self._check_malware_process_names,
            self._check_critical_file_changes,
        ):
            t = check()
            if t:
                findings.append(t)

        if self.demo_mode and random.random() < 0.04:
            findings.append(self._synthetic_threat())

        return findings

    # ================================================================== Claude AI gate

    def _claude_analyse(self, threat: Dict) -> Dict:
        """
        Pass a raw finding to Claude for intelligent analysis.

        • is_genuine=False  → threat marked suppressed, not published
        • is_genuine=True   → severity may be escalated, analysis appended
        • Any error / no key → original threat returned unchanged (fail-OPEN)
        """
        if self._claude_client is None:
            return threat

        try:
            raw    = threat.get('raw_data', {})
            prompt = (
                f"You are a senior cybersecurity analyst for an IoT / edge-computing "
                f"device (device_id={self.device_id}, platform={platform.system()}).\n"
                f"Analyse this security finding and decide if it is a genuine threat "
                f"or expected / benign behaviour on a typical IoT device.\n\n"
                f"Category: {threat['category']}\n"
                f"Severity (initial): {threat['severity']}\n"
                f"Title: {threat['title']}\n"
                f"Detail: {threat['detail']}\n"
                f"Raw indicators: {json.dumps(raw, default=str)}\n\n"
                f"Consider: Is this explainable by normal IoT/server operation? "
                f"Is the severity appropriate? What is the most likely cause?\n\n"
                f"Respond ONLY with valid JSON — no markdown, no extra text:\n"
                f'{{"is_genuine": true_or_false, '
                f'"severity": "low|medium|high|critical", '
                f'"analysis": "concise one-sentence explanation", '
                f'"recommended_action": "immediate action for the operator", '
                f'"confidence": "low|medium|high"}}'
            )

            response = self._claude_client.messages.create(
                model      = self._claude_model,
                max_tokens = 512,
                messages   = [{"role": "user", "content": prompt}],
            )

            text = response.content[0].text.strip() if response.content else "{}"

            # Strip markdown fences if present
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            text = text.strip()

            result = json.loads(text)

            is_genuine = bool(result.get('is_genuine', True))
            severity   = result.get('severity', threat['severity'])
            if severity not in _SEVERITY_RANK:
                severity = threat['severity']

            threat = dict(threat)
            threat['claude_analysis'] = {
                'is_genuine'        : is_genuine,
                'severity_suggested': severity,
                'analysis'          : result.get('analysis', ''),
                'recommended_action': result.get('recommended_action', ''),
                'confidence'        : result.get('confidence', 'medium'),
                'model'             : self._claude_model,
            }

            if not is_genuine:
                threat['suppressed'] = True
                self.logger.debug(
                    f"[SECURITY] Claude suppressed {threat['category']}: "
                    f"{result.get('analysis', 'not a genuine threat')}"
                )
            else:
                # Escalate severity if Claude rates it higher
                if _SEVERITY_RANK.get(severity, 0) > _SEVERITY_RANK.get(threat['severity'], 0):
                    threat['severity'] = severity

            return threat

        except Exception as exc:
            self.logger.warning(
                f"[SECURITY] Claude analysis error ({exc}) — "
                f"publishing {threat['category']} as-is (fail-open)"
            )
            return threat

    # ================================================================== helpers

    def _synthetic_threat(self) -> Dict:
        """Demo synthetic threat — still passes through Claude analysis."""
        templates = [
            dict(category='brute_force', severity=SEVERITY_HIGH,
                 title='SSH brute-force attempt',
                 detail='24 failed login attempts from 203.0.113.42 in 60s',
                 raw_data={'source': '203.0.113.42', 'count': 24, 'demo': True}),
            dict(category='data_exfiltration', severity=SEVERITY_CRITICAL,
                 title='Unusual data egress',
                 detail='Outbound transfer spike: 48 MB to unknown IP',
                 raw_data={'delta_mb': 48, 'demo': True}),
            dict(category='port_scan', severity=SEVERITY_MEDIUM,
                 title='Port scan detected',
                 detail='192.168.1.77 probed 312 ports in 5s',
                 raw_data={'source': '192.168.1.77', 'ports_probed': 312, 'demo': True}),
            dict(category='malware_signature', severity=SEVERITY_CRITICAL,
                 title='Suspicious payload pattern',
                 detail='Network packet matched known C2 beacon signature',
                 raw_data={'pattern': 'c2_beacon', 'demo': True}),
            dict(category='auth_anomaly', severity=SEVERITY_HIGH,
                 title='Auth anomaly',
                 detail='Login from new geographic location',
                 raw_data={'demo': True}),
        ]
        t = random.choice(templates)
        indicators = {'synthetic': True, 'demo': True}
        return self._make_threat(
            category  = t['category'],
            severity  = t['severity'],
            title     = t['title'],
            detail    = t['detail'],
            indicators= indicators,
            raw_data  = t.get('raw_data', {}),
        )

    def _make_threat(self, category: str, severity: str, title: str,
                     detail: str, indicators: Dict = None,
                     raw_data: Dict = None) -> Dict:
        return {
            'threat_id' : f"sec-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{random.randint(1000,9999)}",
            'timestamp' : datetime.utcnow().isoformat(),
            'device_id' : self.device_id,
            'category'  : category,
            'severity'  : severity,
            'title'     : title,
            'detail'    : detail,
            'indicators': indicators or {},
            'raw_data'  : raw_data or {},
            'suppressed': False,
        }

    def _publish_threat(self, threat: Dict):
        if threat.get('suppressed'):
            return

        pub = {k: v for k, v in threat.items()
               if k not in ('raw_data', 'suppressed')}

        self.threat_history.append(pub)
        if len(self.threat_history) > 100:
            self.threat_history.pop(0)

        self.publish_event(
            event_type = 'security.threat',
            data       = {'threat': pub, 'device_id': self.device_id},
            priority   = EventPriority.HIGH,
        )
        ai_tag = " [Claude]" if 'claude_analysis' in pub else ""
        self.logger.warning(
            f"[SECURITY]{ai_tag} {pub['severity'].upper()} — "
            f"{pub['title']}: {pub['detail']}"
        )

    def force_scan(self) -> list:
        """
        Run an immediate on-demand scan outside the regular interval.
        Returns list of published threats (already sent to event bus).
        """
        published = []
        try:
            findings = self._scan_raw()
            for threat in findings:
                enriched = self._claude_analyse(threat)
                self._publish_threat(enriched)
                if not enriched.get('suppressed'):
                    published.append({k: v for k, v in enriched.items()
                                      if k not in ('raw_data', 'suppressed')})
        except Exception as exc:
            self.logger.error(f"Force scan error: {exc}", exc_info=True)
        return published

    def get_status(self) -> dict:
        """Return current security agent status for API."""
        return {
            'demo_mode': self.demo_mode,
            'claude_enabled': self._claude_client is not None,
            'claude_model': self._claude_model if self._claude_client else None,
            'scan_interval': self.scan_interval,
            'threat_count': len(self.threat_history),
            'allowlist_ports': sorted(self._expected_ports),
        }

    def set_demo_mode(self, enabled: bool):
        """Toggle demo mode at runtime."""
        self.demo_mode = enabled
        self.logger.info(f"Security demo_mode set to {enabled}")

    def process_event(self, event):
        pass
