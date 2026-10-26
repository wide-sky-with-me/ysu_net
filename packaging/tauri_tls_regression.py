"""Cloud-only before/after mutation proof for update HTTPS startup; no requests."""
from pathlib import Path
import os
import subprocess


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "desktop/src-tauri/src/updater_delta.rs"
TEST = "updater::delta::tests::http_client_initializes_tls_in_fresh_process"
CALL = "    initialize_tls_provider()?;\n"
PANIC = "No rustls crypto provider is configured"


def main() -> None:
    if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("RUNNER_OS") != "Linux":
        raise SystemExit("TLS mutation proof runs only on a Linux Actions runner")
    if SOURCE.is_symlink() or not SOURCE.is_file():
        raise SystemExit("Expected the fixed desktop source file")
    original = SOURCE.read_bytes()
    needle = CALL.encode()
    if original.count(needle) != 1:
        raise SystemExit("Expected exactly one guarded production client constructor")
    command = ["cargo", "test", "--locked", "--manifest-path", "desktop/src-tauri/Cargo.toml",
               TEST, "--", "--exact", "--nocapture", "--test-threads=1"]
    try:
        # Reproduce the old path without touching TLS verification, dependencies,
        # test assertions or the HTTPS builder. Always restore exact source bytes.
        SOURCE.write_bytes(original.replace(needle, b"", 1))
        broken = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=600)
    finally:
        SOURCE.write_bytes(original)
    output = broken.stdout + broken.stderr
    if broken.returncode == 0 or PANIC not in output or TEST not in output:
        raise SystemExit("The uninitialized constructor did not reproduce the expected panic")
    print("Uninitialized real update client reproduced the missing-provider panic.", flush=True)
    fixed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=600)
    if fixed.returncode or "1 passed" not in fixed.stdout:
        print(fixed.stdout)
        print(fixed.stderr)
        raise SystemExit("Fixed fresh-process constructor regression did not pass")
    if SOURCE.read_bytes() != original:
        raise SystemExit("Mutation proof left altered source")
    print("Fixed real update client passed fresh empty/existing/racing provider cases.", flush=True)


if __name__ == "__main__":
    main()
