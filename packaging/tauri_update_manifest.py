#!/usr/bin/env python3
"""Assemble fixed-repository Tauri release assets and a static updater feed.

prepare_release() validates structure/version metadata for assembly and synthetic tests.
The CLI additionally requires the maintained Minisign verifier to authenticate all three
updater payloads and their signed versions against the client's pinned PUBLIC key.
Decision: .agents/notes/implemented/desktop/2026-10-24-first-signed-release-trust-anchor.md
"""
from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import subprocess
import tempfile
import tomllib
from datetime import datetime, timezone
from urllib.parse import quote

REPOSITORY = "wide-sky-with-me/ysu_net"
MATRICES = ("linux-x64", "windows-x64", "macos-arm64", "macos-x64")
TARGETS = {"windows-x64": "windows-x86_64", "macos-arm64": "darwin-aarch64", "macos-x64": "darwin-x86_64"}
SEMVER = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?")


def release_version(tag: str) -> str:
    if not tag.startswith("v"):
        raise ValueError("release tag must start with v")
    version = tag[1:]
    match = SEMVER.fullmatch(version)
    if not match or (match[4] and any(part.isdigit() and len(part) > 1 and part[0] == "0" for part in match[4].split("."))):
        raise ValueError("release tag is not a canonical semantic version")
    return version


def validate_versions(root: Path, version: str) -> None:
    metadata = [
        json.loads((root / "desktop/package.json").read_text())["version"],
        json.loads((root / "desktop/src-tauri/tauri.conf.json").read_text())["version"],
        tomllib.loads((root / "desktop/src-tauri/Cargo.toml").read_text())["package"]["version"],
        tomllib.loads((root / "desktop/crates/ysu-auth/Cargo.toml").read_text())["package"]["version"],
        tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"],
    ]
    if any(item != version for item in metadata):
        raise ValueError("release tag and package versions differ")


def regular_file(path: Path, root: Path) -> Path:
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("artifact must be a regular contained file")
    # Reject symlinked directories too, even when their final target stays contained.
    if any(parent.is_symlink() for parent in path.parents if parent == root or parent.is_relative_to(root)):
        raise ValueError("artifact directories must not be symlinks")
    if path.stat().st_size == 0:
        raise ValueError("release artifact is empty")
    return path


def signature_text(path: Path, root: Path, version: str) -> str:
    regular_file(path, root)
    if path.stat().st_size > 16 * 1024:
        raise ValueError("signature exceeds size limit")
    try:
        encoded = path.read_text(encoding="ascii").strip()
        lines = base64.b64decode(encoded, validate=True).decode("utf-8").splitlines()
        if len(lines) != 4 or not lines[0].startswith("untrusted comment: ") or not lines[2].startswith("trusted comment: "):
            raise ValueError("signature is not an official minisign envelope")
        packet = base64.b64decode(lines[1], validate=True)
        global_signature = base64.b64decode(lines[3], validate=True)
        if len(packet) != 74 or packet[:2] not in (b"ED", b"Ed") or len(global_signature) != 64:
            raise ValueError("signature packet structure is invalid")
        fields = lines[2][len("trusted comment: "):].split("\t")
        versions = [field[len("version:"):] for field in fields if field.startswith("version:")]
        names = [field[len("file:"):] for field in fields if field.startswith("file:")]
        timestamps = [field[len("timestamp:"):] for field in fields if field.startswith("timestamp:")]
        if versions != [version]:
            raise ValueError("signature version metadata is missing or mismatched")
        if len(names) != 1 or not re.fullmatch(r"[A-Za-z0-9 _+.\-]+", names[0]) or names[0] in (".", ".."):
            raise ValueError("signature file metadata is invalid")
        if len(timestamps) != 1 or not timestamps[0].isascii() or not timestamps[0].isdigit():
            raise ValueError("signature timestamp metadata is invalid")
    except (UnicodeError, binascii.Error) as error:
        raise ValueError("signature encoding is invalid") from error
    return encoded


def matrix_files(root: Path, matrix: str) -> list[Path]:
    directory = root / f"rust-desktop-bundle-{matrix}"
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("required matrix artifact directory is missing")
    paths = []
    for path in directory.rglob("*"):
        if path.is_symlink():
            raise ValueError("symlinked artifacts are not accepted")
        if path.is_file():
            paths.append(regular_file(path, root))
    return paths


def one(paths: list[Path], suffix: str) -> Path:
    matches = [path for path in paths if path.name.endswith(suffix)]
    if len(matches) != 1:
        raise ValueError("required release artifact is missing or ambiguous")
    return matches[0]


def prepare_release(artifacts: Path, distributions: Path, output: Path, tag: str,
                    source_root: Path, repository: str = REPOSITORY,
                    published: datetime | None = None) -> dict:
    if repository != REPOSITORY:
        raise ValueError("release repository is not the fixed upstream")
    version = release_version(tag)
    validate_versions(source_root, version)
    if output.exists() and (output.is_symlink() or not output.is_dir() or any(output.iterdir())):
        raise ValueError("release output must be a new or empty directory")
    plans: dict[str, Path] = {}
    platforms = {}
    for matrix in MATRICES:
        paths = matrix_files(artifacts, matrix)
        suffix = ".deb" if matrix == "linux-x64" else "-setup.exe" if matrix == "windows-x64" else ".dmg"
        installer = one(paths, suffix)
        canonical = f"YSU-Net_{version}_{matrix}{'-setup.exe' if matrix == 'windows-x64' else suffix}"
        plans[canonical] = installer
        consumed = {installer}
        if matrix in TARGETS:
            payload = installer if matrix == "windows-x64" else one(paths, ".app.tar.gz")
            signature = Path(str(payload) + ".sig")
            if signature not in paths:
                raise ValueError("updater payload signature is missing")
            encoded = signature_text(signature, artifacts, version)
            payload_name = canonical if matrix == "windows-x64" else f"YSU-Net_{version}_{matrix}.app.tar.gz"
            plans[payload_name] = payload
            plans[payload_name + ".sig"] = signature
            consumed.update((payload, signature))
            platforms[TARGETS[matrix]] = {
                "url": f"https://github.com/{REPOSITORY}/releases/download/{quote(tag, safe='')}/{quote(payload_name, safe='')}",
                "signature": encoded,
            }
        if consumed != set(paths):
            raise ValueError("matrix artifact directory contains unexpected files")
    for suffix, name in [(".whl", f"ysu_net_login-{version}-py3-none-any.whl"), (".tar.gz", f"ysu_net_login-{version}.tar.gz")]:
        candidates = list(distributions.glob("*" + suffix))
        if len(candidates) != 1 or candidates[0].name != name:
            raise ValueError("Python distribution filename or version differs")
        plans[name] = regular_file(candidates[0], distributions)
    if len(plans) != 11 or set(platforms) != set(TARGETS.values()):
        raise ValueError("release asset or updater target set is incomplete")
    date = published or datetime.now(timezone.utc)
    if date.tzinfo is None or date.utcoffset() is None:
        raise ValueError("publication time must include a timezone")
    manifest = {"version": version, "notes": "详见对应版本发布说明。",
                "pub_date": date.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"), "platforms": platforms}
    output.mkdir(parents=True, exist_ok=True)
    for name, path in plans.items():
        shutil.copyfile(path, output / name)
    (output / "latest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    sums = []
    for path in sorted(output.iterdir()):
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        sums.append(f"{digest.hexdigest()}  {path.name}\n")
    (output / "SHA256SUMS").write_text("".join(sums), encoding="ascii")
    return manifest


def verify_release_signatures(output: Path, source_root: Path, version: str,
                              verifier: str = "minisign") -> None:
    """Verify the actual update payloads against the client's pinned PUBLIC key.

    minisign verifies both payload and trusted-comment signatures. Version/URL checks
    remain mandatory too; a valid signature for a different release is not enough.
    No private key or installer execution is involved.
    """
    updater = json.loads((source_root / "desktop/src-tauri/tauri.conf.json").read_text())["plugins"]["updater"]
    if updater.get("requireSignedVersion") is not True:
        raise ValueError("release requires signed-version verification")
    try:
        encoded_key = updater["pubkey"]
        if not isinstance(encoded_key, str) or len(encoded_key) > 16 * 1024:
            raise ValueError("invalid updater public key")
        key_lines = base64.b64decode(encoded_key, validate=True).decode("utf-8").splitlines()
        if len(key_lines) != 2 or not key_lines[0].startswith("untrusted comment: "):
            raise ValueError("invalid updater public key")
        public_packet = base64.b64decode(key_lines[1], validate=True)
        if len(public_packet) != 42 or public_packet[:2] != b"Ed":
            raise ValueError("invalid updater public key")
    except (KeyError, TypeError, UnicodeError, binascii.Error) as error:
        raise ValueError("invalid updater public key") from error
    executable = shutil.which(verifier)
    if executable is None:
        raise ValueError("minisign verifier is required before publication")
    feed = json.loads(regular_file(output / "latest.json", output).read_text())
    if feed.get("version") != version or set(feed.get("platforms", {})) != set(TARGETS.values()):
        raise ValueError("release feed version or targets differ")
    for matrix, target in TARGETS.items():
        name = f"YSU-Net_{version}_{matrix}{'-setup.exe' if matrix == 'windows-x64' else '.app.tar.gz'}"
        payload = regular_file(output / name, output)
        signature = output / (name + ".sig")
        regular_file(signature, output)
        if signature.stat().st_size > 16 * 1024:
            raise ValueError("signature exceeds size limit")
        encoded = signature.read_text(encoding="ascii").strip()
        expected = {"url": f"https://github.com/{REPOSITORY}/releases/download/v{quote(version, safe='')}/{quote(name, safe='')}",
                    "signature": encoded}
        if feed["platforms"][target] != expected:
            raise ValueError("release feed URL or inline signature differs")
        with tempfile.TemporaryDirectory(prefix="ysu-public-verify-") as temporary:
            detached = Path(temporary) / "payload.minisig"
            detached.write_bytes(base64.b64decode(encoded, validate=True))
            try:
                result = subprocess.run([executable, "-V", "-m", str(payload), "-x", str(detached),
                                         "-P", key_lines[1]], capture_output=True, timeout=60, check=False)
            except (OSError, subprocess.TimeoutExpired) as error:
                raise ValueError("public signature verifier failed") from error
            if result.returncode != 0:
                raise ValueError("update payload does not verify against the pinned public key")
            # Only interpret the authenticated trusted comment after cryptographic success.
            # Parse the exact captured envelope, not a second read of a mutable input file.
            captured = Path(temporary) / "verified.tauri.sig"
            captured.write_text(encoded, encoding="ascii")
            signature_text(captured, Path(temporary), version)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--dist", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--repository", default=REPOSITORY)
    args = parser.parse_args(argv)
    try:
        source_root = Path(__file__).resolve().parents[1]
        version = release_version(args.tag)
        prepare_release(args.artifacts, args.dist, args.output, args.tag, source_root, args.repository)
        verify_release_signatures(args.output, source_root, version)
    except (ValueError, KeyError, OSError) as error:
        print(f"release asset validation failed: {error if isinstance(error, ValueError) else 'metadata or artifact I/O failure'}", file=sys.stderr)
        return 1
    print("Prepared 13 assets; all 3 updater payload signatures and signed versions verified against the pinned public key.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
