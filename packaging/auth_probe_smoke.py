"""Cloud-only input/redaction acceptance for the actual headless Rust binary."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "desktop/crates/ysu-auth/Cargo.toml"


def main():
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise SystemExit("Headless probe acceptance runs only on an Actions runner")
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    executable = "auth_probe.exe" if os.name == "nt" else "auth_probe"
    binary = MANIFEST.parent / "target/release/examples" / executable
    if binary.is_symlink() or not binary.is_file():
        raise SystemExit("Expected the ordinary release example binary")
    commit = os.environ.get("GITHUB_SHA", "")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise SystemExit("Expected an exact cloud source commit")
    # Even a guard regression must not need campus DNS or real credentials.
    loopback = {"base": "https://127.0.0.1:9", "cas_host": "https://127.0.0.1:9",
                "operation_timeout": 1, "password": "synthetic-secret"}
    encode = lambda fields: json.dumps(fields).encode()
    cases = [
        ("missing_action", [], encode(loopback)),
        ("extra_argument", ["status", "synthetic-argument"], encode(loopback)),
        ("unknown_field", ["status"], encode({**loopback, "unknown": "synthetic-secret"})),
        ("tls_disabled", ["status"], encode({**loopback, "verify_tls": False})),
        ("http_address", ["status"], encode({**loopback, "base": "http://127.0.0.1:9"})),
        ("missing_login_credentials", ["login"], encode(loopback)),
        ("missing_logout_credentials", ["logout"], encode(loopback)),
        ("oversized_input", ["status"], encode(loopback) + b" " * (64 * 1024)),
    ]
    results = []
    for name, arguments, payload in cases:
        result = subprocess.run([str(binary), *arguments], input=payload,
                                capture_output=True, timeout=5, cwd=ROOT)
        if result.returncode != 2 or result.stderr:
            raise SystemExit("Probe rejected-input acceptance failed: " + name)
        try:
            report = json.loads(result.stdout)
        except ValueError:
            raise SystemExit("Probe did not produce a fixed JSON report: " + name) from None
        if not (report.get("schema") == 1 and report.get("code") == 2
                and report.get("outcome") == "invalid_input" and report.get("phase") == "input"
                and report.get("before") is None and report.get("after") is None
                and report.get("diagnostic") is None):
            raise SystemExit("Probe accepted invalid input or reached its network path: " + name)
        if b"synthetic-secret" in result.stdout or b"synthetic-argument" in result.stdout:
            raise SystemExit("Probe leaked a synthetic private value")
        results.append({"case": name, "passed": True})
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / "build") or output.exists():
        raise SystemExit("Expected a new directory under build")
    output.mkdir(parents=True)
    destination = output / ("ysu-auth-probe.exe" if os.name == "nt" else "ysu-auth-probe")
    shutil.copy2(binary, destination)
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    metadata = {"schema": 1, "commit": commit, "platform": platform.system(),
                "machine": platform.machine(), "profile": "release", "cargo_features": [],
                "auth_lock_sha256": hashlib.sha256(MANIFEST.with_name("Cargo.lock").read_bytes()).hexdigest(),
                "campus_addresses_sha256": hashlib.sha256((ROOT / "src/ysu_net/auth/campus-addresses.json").read_bytes()).hexdigest(),
                "binary": {"name": destination.name, "bytes": destination.stat().st_size, "sha256": digest},
                "input_acceptance": results}
    (output / "manifest.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    (output / "SHA256SUMS").write_text(digest + "  " + destination.name + "\n", encoding="utf-8")
    print(f"Headless probe acceptance passed: {len(results)} cases; source {commit}.")


if __name__ == "__main__":
    main()
