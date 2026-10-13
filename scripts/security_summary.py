#!/usr/bin/env python3
"""
security_summary.py
-------------------
Reads scanner JSON output from the reports/ directory produced by a Jenkins build
and writes two outputs:

  reports/security-summary.md   - human-readable one-page summary of all findings
  /var/jenkins_home/security-trends.csv - one appended row per build for trend tracking

Usage (called from Jenkinsfile post block):
    python3 scripts/security_summary.py \
        --build-number  ${env.BUILD_NUMBER} \
        --build-url     ${env.BUILD_URL} \
        --reports-dir   reports/

Exit code is always 0. This script never fails a build; it only reports.
"""

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_json(path: Path) -> dict | list | None:
    """Load JSON from path, return None if missing or unparseable."""
    if not path.exists():
        return None
    try:
        with path.open() as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def severity_counts(findings: list[dict], severity_key: str = "Severity") -> dict:
    """Count findings by severity label, case-insensitive."""
    counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "UNKNOWN": 0}
    for f in findings:
        sev = str(f.get(severity_key, "UNKNOWN")).upper()
        if sev in counts:
            counts[sev] += 1
        else:
            counts["UNKNOWN"] += 1
    return counts


# ---------------------------------------------------------------------------
# Parser functions — one per scanner
# ---------------------------------------------------------------------------

def parse_trivy_secrets(data: dict | None) -> dict:
    """
    trivy fs --scanners secret --format json
    Results[].Secrets[] each have a RuleID and Severity.
    """
    result = {"total": 0, "findings": []}
    if not data:
        return result
    for target in data.get("Results", []) or []:
        for secret in target.get("Secrets", []) or []:
            result["total"] += 1
            result["findings"].append({
                "file": target.get("Target", ""),
                "rule": secret.get("RuleID", ""),
                "title": secret.get("Title", ""),
                "severity": secret.get("Severity", "UNKNOWN"),
            })
    return result


def parse_trivy_config(data: dict | None) -> dict:
    """
    trivy config --format json
    Results[].Misconfigurations[] each have a Severity and Status.
    """
    result = {"total": 0, "counts": {}, "findings": []}
    if not data:
        return result
    all_findings = []
    for target in data.get("Results", []) or []:
        for m in target.get("Misconfigurations", []) or []:
            all_findings.append({
                "file": target.get("Target", ""),
                "id": m.get("ID", ""),
                "title": m.get("Title", ""),
                "severity": m.get("Severity", "UNKNOWN"),
                "status": m.get("Status", ""),
            })
    result["counts"] = severity_counts(all_findings)
    result["total"] = len(all_findings)
    result["findings"] = all_findings
    return result


def parse_trivy_image(data: dict | None) -> dict:
    """
    trivy image --format json
    Results[].Vulnerabilities[] each have a VulnerabilityID, Severity, FixedVersion.
    """
    result = {"total": 0, "fixable": 0, "counts": {}, "findings": []}
    if not data:
        return result
    all_findings = []
    for target in data.get("Results", []) or []:
        for v in target.get("Vulnerabilities", []) or []:
            all_findings.append({
                "pkg": v.get("PkgName", ""),
                "cve": v.get("VulnerabilityID", ""),
                "severity": v.get("Severity", "UNKNOWN"),
                "installed": v.get("InstalledVersion", ""),
                "fixed": v.get("FixedVersion", ""),
            })
    result["counts"] = severity_counts(all_findings)
    result["total"] = len(all_findings)
    result["fixable"] = sum(1 for f in all_findings if f["fixed"])
    result["findings"] = all_findings
    return result


def parse_pip_audit(data: list | None) -> dict:
    """
    pip-audit --format json
    Top-level list of {name, version, vulns: [{id, fix_versions, description}]}.
    """
    result = {"total": 0, "findings": []}
    if not data:
        return result
    for pkg in data or []:
        for vuln in pkg.get("vulns", []) or []:
            result["total"] += 1
            result["findings"].append({
                "pkg": pkg.get("name", ""),
                "version": pkg.get("version", ""),
                "id": vuln.get("id", ""),
                "fix": ", ".join(vuln.get("fix_versions", [])) or "none",
                "description": vuln.get("description", "")[:120],
            })
    return result


def parse_semgrep(data: dict | None) -> dict:
    """
    semgrep --json
    results[] each have a severity (ERROR, WARNING, INFO) and extra.message.
    """
    result = {"total": 0, "errors": 0, "findings": []}
    if not data:
        return result
    for r in data.get("results", []) or []:
        sev = r.get("extra", {}).get("severity", "INFO").upper()
        result["total"] += 1
        if sev == "ERROR":
            result["errors"] += 1
        result["findings"].append({
            "file": r.get("path", ""),
            "line": r.get("start", {}).get("line", ""),
            "rule": r.get("check_id", ""),
            "severity": sev,
            "message": r.get("extra", {}).get("message", "")[:120],
        })
    return result


# ---------------------------------------------------------------------------
# Report writers
# ---------------------------------------------------------------------------

def write_summary(
    build_number: str,
    build_url: str,
    timestamp: str,
    secrets: dict,
    config: dict,
    pip: dict,
    semgrep: dict,
    image: dict,
    out_path: Path,
) -> None:
    """Write reports/security-summary.md."""
    lines = []
    a = lines.append

    a(f"# Security Summary — Build #{build_number}")
    a(f"")
    a(f"**Generated:** {timestamp}  ")
    a(f"**Build URL:** {build_url}  ")
    a(f"")
    a(f"---")
    a(f"")

    # Quick status table
    a(f"## Status at a Glance")
    a(f"")
    a(f"| Stage | Findings | Gate result |")
    a(f"|-------|----------|-------------|")

    def gate(count, threshold=0):
        return "🔴 FAIL" if count > threshold else "🟢 PASS"

    a(f"| Secrets scan | {secrets['total']} secrets | {gate(secrets['total'])} |")
    a(f"| SAST (Semgrep) | {semgrep['total']} findings, {semgrep['errors']} ERROR | {gate(semgrep['errors'])} |")
    a(f"| Dependency scan (pip-audit) | {pip['total']} CVEs | {gate(pip['total'])} |")

    config_high_crit = (config['counts'].get('HIGH', 0) + config['counts'].get('CRITICAL', 0)) if config['counts'] else 0
    a(f"| Config scan (Trivy) | HIGH/CRITICAL: {config_high_crit} | {gate(config_high_crit)} |")

    image_fixable_hc = sum(
        1 for f in image.get('findings', [])
        if f['severity'] in ('HIGH', 'CRITICAL') and f['fixed']
    )
    a(f"| Image scan (Trivy) | Fixable HIGH/CRITICAL: {image_fixable_hc} | {gate(image_fixable_hc)} |")
    a(f"")
    a(f"---")
    a(f"")

    # Secrets
    a(f"## 1. Secrets Scan")
    a(f"")
    if not secrets['findings']:
        a(f"No secrets detected.")
    else:
        a(f"**{secrets['total']} secret(s) found — build should have failed.**")
        a(f"")
        a(f"| File | Rule | Severity |")
        a(f"|------|------|----------|")
        for s in secrets['findings'][:20]:
            a(f"| `{s['file']}` | {s['rule']} | {s['severity']} |")
    a(f"")

    # SAST
    a(f"## 2. SAST — Semgrep")
    a(f"")
    if not semgrep['findings']:
        a(f"No findings.")
    else:
        a(f"**{semgrep['total']} finding(s), {semgrep['errors']} ERROR-level.**")
        a(f"")
        a(f"| File | Line | Rule | Severity | Message |")
        a(f"|------|------|------|----------|---------|")
        for s in semgrep['findings'][:20]:
            a(f"| `{s['file']}` | {s['line']} | `{s['rule']}` | {s['severity']} | {s['message']} |")
    a(f"")

    # pip-audit
    a(f"## 3. Dependency Scan — pip-audit")
    a(f"")
    if not pip['findings']:
        a(f"No known vulnerabilities in dependencies.")
    else:
        a(f"**{pip['total']} vulnerability(s) found.**")
        a(f"")
        a(f"| Package | Version | CVE | Fix available | Description |")
        a(f"|---------|---------|-----|---------------|-------------|")
        for p in pip['findings'][:20]:
            a(f"| {p['pkg']} | {p['version']} | {p['id']} | {p['fix']} | {p['description']} |")
    a(f"")

    # Config scan
    a(f"## 4. Config Scan — Trivy")
    a(f"")
    if not config['findings']:
        a(f"No misconfigurations found.")
    else:
        counts = config['counts']
        a(f"**{config['total']} misconfiguration(s): "
          f"CRITICAL={counts.get('CRITICAL',0)}, HIGH={counts.get('HIGH',0)}, "
          f"MEDIUM={counts.get('MEDIUM',0)}, LOW={counts.get('LOW',0)}**")
        a(f"")
        a(f"| File | ID | Title | Severity |")
        a(f"|------|----|-------|----------|")
        for c in config['findings'][:20]:
            a(f"| `{c['file']}` | {c['id']} | {c['title']} | {c['severity']} |")
    a(f"")

    # Image scan
    a(f"## 5. Image Scan — Trivy")
    a(f"")
    if not image['findings']:
        a(f"No vulnerabilities found in image.")
    else:
        counts = image['counts']
        a(f"**{image['total']} CVE(s): "
          f"CRITICAL={counts.get('CRITICAL',0)}, HIGH={counts.get('HIGH',0)}, "
          f"MEDIUM={counts.get('MEDIUM',0)}, LOW={counts.get('LOW',0)} — "
          f"{image['fixable']} fixable**")
        a(f"")
        a(f"| Package | CVE | Severity | Installed | Fixed |")
        a(f"|---------|-----|----------|-----------|-------|")
        # Show HIGH/CRITICAL fixable first, cap at 30 rows
        prioritized = sorted(
            image['findings'],
            key=lambda x: (
                0 if x['severity'] in ('CRITICAL', 'HIGH') and x['fixed'] else 1,
                x['severity']
            )
        )
        for v in prioritized[:30]:
            a(f"| {v['pkg']} | {v['cve']} | {v['severity']} | {v['installed']} | {v['fixed'] or '—'} |")
        if len(image['findings']) > 30:
            a(f"")
            a(f"*... and {len(image['findings']) - 30} more. See `trivy-image.json` for full list.*")
    a(f"")
    a(f"---")
    a(f"")
    a(f"*Report generated by `scripts/security_summary.py`. "
      f"Source data: `trivy-secrets.json`, `semgrep.json`, `pip-audit.json`, "
      f"`trivy-config.json`, `trivy-image.json`.*")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n")
    print(f"[summary] Written: {out_path}")


def append_trend_row(
    build_number: str,
    build_url: str,
    timestamp: str,
    secrets: dict,
    config: dict,
    pip: dict,
    semgrep: dict,
    image: dict,
    trend_path: Path,
) -> None:
    """Append one CSV row to the trend file. Creates the file with a header if missing."""
    fieldnames = [
        "timestamp", "build_number", "build_url",
        "secrets_total",
        "semgrep_total", "semgrep_errors",
        "pip_audit_total",
        "config_critical", "config_high", "config_medium", "config_low",
        "image_total", "image_critical", "image_high", "image_medium", "image_low",
        "image_fixable_high_crit",
    ]

    image_fixable_hc = sum(
        1 for f in image.get("findings", [])
        if f["severity"] in ("HIGH", "CRITICAL") and f["fixed"]
    )

    row = {
        "timestamp": timestamp,
        "build_number": build_number,
        "build_url": build_url,
        "secrets_total": secrets["total"],
        "semgrep_total": semgrep["total"],
        "semgrep_errors": semgrep["errors"],
        "pip_audit_total": pip["total"],
        "config_critical": config["counts"].get("CRITICAL", 0) if config["counts"] else 0,
        "config_high": config["counts"].get("HIGH", 0) if config["counts"] else 0,
        "config_medium": config["counts"].get("MEDIUM", 0) if config["counts"] else 0,
        "config_low": config["counts"].get("LOW", 0) if config["counts"] else 0,
        "image_total": image["total"],
        "image_critical": image["counts"].get("CRITICAL", 0) if image["counts"] else 0,
        "image_high": image["counts"].get("HIGH", 0) if image["counts"] else 0,
        "image_medium": image["counts"].get("MEDIUM", 0) if image["counts"] else 0,
        "image_low": image["counts"].get("LOW", 0) if image["counts"] else 0,
        "image_fixable_high_crit": image_fixable_hc,
    }

    write_header = not trend_path.exists() or trend_path.stat().st_size == 0
    trend_path.parent.mkdir(parents=True, exist_ok=True)

    with trend_path.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        writer.writerow(row)

    print(f"[summary] Trend row appended: {trend_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Generate security summary and trend row.")
    parser.add_argument("--build-number", default=os.environ.get("BUILD_NUMBER", "0"))
    parser.add_argument("--build-url", default=os.environ.get("BUILD_URL", ""))
    parser.add_argument("--reports-dir", default="reports")
    parser.add_argument(
        "--trend-file",
        default=os.environ.get(
            "SECURITY_TREND_FILE",
            "/var/jenkins_home/security-trends.csv"
        ),
    )
    args = parser.parse_args()

    reports = Path(args.reports_dir)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    print(f"[summary] Build #{args.build_number} — {timestamp}")
    print(f"[summary] Reading reports from: {reports.resolve()}")

    # Load each scanner's output
    secrets_data  = load_json(reports / "trivy-secrets.json")
    config_data   = load_json(reports / "trivy-config.json")
    image_data    = load_json(reports / "trivy-image.json")
    pip_data      = load_json(reports / "pip-audit.json")
    semgrep_data  = load_json(reports / "semgrep.json")

    if secrets_data is None:
        print("[summary] WARNING: trivy-secrets.json not found — secrets section will be empty")
    if config_data is None:
        print("[summary] WARNING: trivy-config.json not found — config section will be empty")
    if image_data is None:
        print("[summary] WARNING: trivy-image.json not found — image section will be empty")
    if pip_data is None:
        print("[summary] WARNING: pip-audit.json not found — dependency section will be empty")
    if semgrep_data is None:
        print("[summary] WARNING: semgrep.json not found — SAST section will be empty")

    # Parse each scanner's format
    secrets  = parse_trivy_secrets(secrets_data)
    config   = parse_trivy_config(config_data)
    image    = parse_trivy_image(image_data)
    pip      = parse_pip_audit(pip_data)
    semgrep  = parse_semgrep(semgrep_data)

    # Write outputs
    write_summary(
        build_number=args.build_number,
        build_url=args.build_url,
        timestamp=timestamp,
        secrets=secrets,
        config=config,
        pip=pip,
        semgrep=semgrep,
        image=image,
        out_path=reports / "security-summary.md",
    )

    append_trend_row(
        build_number=args.build_number,
        build_url=args.build_url,
        timestamp=timestamp,
        secrets=secrets,
        config=config,
        pip=pip,
        semgrep=semgrep,
        image=image,
        trend_path=Path(args.trend_file),
    )

    print("[summary] Done.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Never crash a build
        print(f"[summary] ERROR: {exc}", file=sys.stderr)
        sys.exit(0)
