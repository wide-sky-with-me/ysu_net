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
MAX_FULL_SIZE = 64 * 1024 * 1024
MAX_PATCH_SIZE = 32 * 1024 * 1024
DELTA_FIELDS = frozenset(("format", "base_version", "base_sha256", "base_size", "target_version",
                          "target_sha256", "target_size", "full_url", "full_signature", "url",
                          "signature", "sha256", "size"))


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
    return signature_value(read_signature(path, root), version)


def read_signature(path: Path, root: Path) -> str:
    regular_file(path, root)
    if path.stat().st_size > 16 * 1024:
        raise ValueError("signature exceeds size limit")
    try:
        return path.read_text(encoding="ascii").strip()
    except UnicodeError as error:
        raise ValueError("signature encoding is invalid") from error


def signature_value(encoded: str, version: str) -> str:
    """Parse an envelope, but never mistake this structure check for authentication."""
    try:
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
            bounded_file(payload, artifacts, MAX_FULL_SIZE)
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
    write_checksums(output)
    return manifest


class PublicVerifier:
    """One public-only, maintained verifier for full payloads, bases and patches.

    The runner is injectable for structural tests. Production always calls minisign;
    no handwritten cryptography and no private-key access belongs in this class.
    """

    def __init__(self, source_root: Path, verifier: str = "minisign", *, runner=None):
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
        self.executable = shutil.which(verifier)
        if self.executable is None:
            raise ValueError("minisign verifier is required before publication")
        self.public_key = key_lines[1]
        self.runner = runner or subprocess.run

    def verify(self, payload: Path, signature: Path, root: Path, version: str) -> str:
        regular_file(payload, root)
        encoded = read_signature(signature, root)
        try:
            envelope = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as error:
            raise ValueError("signature encoding is invalid") from error
        with tempfile.TemporaryDirectory(prefix="ysu-public-verify-") as temporary:
            detached = Path(temporary) / "payload.minisig"
            detached.write_bytes(envelope)
            try:
                result = self.runner([self.executable, "-V", "-m", str(payload), "-x", str(detached),
                                      "-P", self.public_key], capture_output=True, timeout=60, check=False)
            except (OSError, subprocess.TimeoutExpired) as error:
                raise ValueError("public signature verifier failed") from error
            if result.returncode != 0:
                raise ValueError("update payload does not verify against the pinned public key")
        # Interpret only the exact authenticated envelope, never a second file read.
        return signature_value(encoded, version)


def bounded_file(path: Path, root: Path, limit: int) -> Path:
    regular_file(path, root)
    if path.stat().st_size > limit:
        raise ValueError("update artifact exceeds size limit")
    return path


def payload_name(version: str, matrix: str) -> str:
    return f"YSU-Net_{version}_{matrix}{'-setup.exe' if matrix == 'windows-x64' else '.app.tar.gz'}"


def patch_name(version: str, matrix: str, base_version: str) -> str:
    return f"YSU-Net_{version}_{matrix}_from_{base_version}.bsdiff"


def asset_url(version: str, name: str) -> str:
    return f"https://github.com/{REPOSITORY}/releases/download/v{quote(version, safe='')}/{quote(name, safe='')}"


def validate_base_version(base_version: str, version: str) -> None:
    if not isinstance(base_version, str):
        raise ValueError("base must be a strictly older stable version")
    release_version("v" + version)
    release_version("v" + base_version)
    base, target = SEMVER.fullmatch(base_version), SEMVER.fullmatch(version)
    if base[4] or tuple(map(int, base.group(1, 2, 3))) >= tuple(map(int, target.group(1, 2, 3))):
        raise ValueError("base must be a strictly older stable version")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_checksums(output: Path) -> None:
    # WindowsPath orders case-insensitively; release inventories use exact names.
    paths = sorted(output.iterdir(), key=lambda path: path.name)
    lines = [f"{sha256_file(path)}  {path.name}\n" for path in paths if path.name != "SHA256SUMS"]
    (output / "SHA256SUMS").write_text("".join(lines), encoding="ascii", newline="\n")


def release_feed(output: Path, version: str) -> dict:
    release_version("v" + version)
    feed_path = bounded_file(output / "latest.json", output, 256 * 1024)
    feed = json.loads(feed_path.read_text(encoding="utf-8"))
    if not isinstance(feed, dict) or feed.get("version") != version or not isinstance(feed.get("platforms"), dict) or set(feed["platforms"]) != set(TARGETS.values()):
        raise ValueError("release feed version or targets differ")
    return feed


def delta_entries(feed: dict, version: str):
    """Publisher emits at most ONE descriptor per target (clients may accept three)."""
    deltas = feed.get("deltas", {})
    if not isinstance(deltas, dict) or not set(deltas).issubset(TARGETS.values()):
        raise ValueError("release delta target set differs")
    for matrix, target in TARGETS.items():
        if target not in deltas:
            continue
        entries = deltas[target]
        if not isinstance(entries, list) or len(entries) != 1 or not isinstance(entries[0], dict):
            raise ValueError("publisher requires exactly one delta per advertised target")
        descriptor = entries[0]
        if set(descriptor) != DELTA_FIELDS or descriptor["format"] != "bsdiff40" or descriptor["target_version"] != version:
            raise ValueError("delta format, fields or target version differ")
        validate_base_version(descriptor["base_version"], version)
        for field, limit in (("base_size", MAX_FULL_SIZE), ("target_size", MAX_FULL_SIZE), ("size", MAX_PATCH_SIZE)):
            if type(descriptor[field]) is not int or not 0 < descriptor[field] <= limit:
                raise ValueError("delta size is invalid or exceeds size limit")
        if descriptor["size"] * 5 >= descriptor["target_size"] * 4:
            raise ValueError("delta does not save more than twenty percent")
        for field in ("base_sha256", "target_sha256", "sha256"):
            if not isinstance(descriptor[field], str) or not re.fullmatch(r"[0-9a-f]{64}", descriptor[field]):
                raise ValueError("delta sha256 is invalid")
        full = feed["platforms"][target]
        if not isinstance(full, dict) or descriptor["full_url"] != full.get("url") or descriptor["full_signature"] != full.get("signature"):
            raise ValueError("delta full URL or signature differs from selected full payload")
        name = patch_name(version, matrix, descriptor["base_version"])
        if descriptor["url"] != asset_url(version, name):
            raise ValueError("delta URL is not the canonical current-release attachment")
        yield matrix, target, descriptor, name


def verify_release_signatures(output: Path, source_root: Path, version: str,
                              verifier: str = "minisign", *, public_verifier=None) -> None:
    """Authenticate all original full payloads AND any optional patch envelopes."""
    gate = public_verifier if public_verifier is not None else PublicVerifier(source_root, verifier)
    feed = release_feed(output, version)
    for matrix, target in TARGETS.items():
        name = payload_name(version, matrix)
        payload = bounded_file(output / name, output, MAX_FULL_SIZE)
        signature = output / (name + ".sig")
        encoded = read_signature(signature, output)
        expected = {"url": asset_url(version, name), "signature": encoded}
        if feed["platforms"][target] != expected:
            raise ValueError("release feed URL or inline signature differs")
        if gate.verify(payload, signature, output, version) != encoded:
            raise ValueError("verified signature changed during verification")
    for matrix, target, descriptor, name in delta_entries(feed, version):
        payload = bounded_file(output / name, output, MAX_PATCH_SIZE)
        signature = output / (name + ".sig")
        if descriptor["signature"] != read_signature(signature, output):
            raise ValueError("delta inline signature differs")
        if gate.verify(payload, signature, output, version) != descriptor["signature"]:
            raise ValueError("verified delta signature differs")


def validate_release_assets(output: Path, version: str) -> dict:
    """Strict inventory/checksum gate; hashes are diagnostics, NEVER a trust root."""
    feed = release_feed(output, version)
    expected = {"latest.json", "SHA256SUMS", f"YSU-Net_{version}_linux-x64.deb",
                f"ysu_net_login-{version}-py3-none-any.whl", f"ysu_net_login-{version}.tar.gz"}
    for matrix in TARGETS:
        name = payload_name(version, matrix)
        expected.update((name, name + ".sig"))
        if matrix.startswith("macos-"):
            expected.add(f"YSU-Net_{version}_{matrix}.dmg")
    for matrix, target, descriptor, name in delta_entries(feed, version):
        expected.update((name, name + ".sig"))
        patch = bounded_file(output / name, output, MAX_PATCH_SIZE)
        full = bounded_file(output / payload_name(version, matrix), output, MAX_FULL_SIZE)
        with patch.open("rb") as stream:
            if stream.read(8) != b"BSDIFF40":
                raise ValueError("delta is not BSDIFF40")
        for path, size, digest in ((patch, descriptor["size"], descriptor["sha256"]),
                                   (full, descriptor["target_size"], descriptor["target_sha256"])):
            if path.stat().st_size != size or sha256_file(path) != digest:
                raise ValueError("delta size or sha256 differs from artifact")
    paths = list(output.iterdir())
    if {path.name for path in paths} != expected:
        raise ValueError("release asset inventory differs from 13 baseline plus declared delta pairs")
    for path in paths:
        regular_file(path, output)
    sums = bounded_file(output / "SHA256SUMS", output, 64 * 1024).read_text(encoding="ascii")
    canonical = "".join(f"{sha256_file(output / name)}  {name}\n" for name in sorted(expected - {"SHA256SUMS"}))
    if sums != canonical:
        raise ValueError("release SHA256SUMS differs from exact asset inventory")
    return feed


def verify_release_assets(output: Path, source_root: Path, version: str, *, public_verifier=None) -> dict:
    feed = validate_release_assets(output, version)
    verify_release_signatures(output, source_root, version, public_verifier=public_verifier)
    return feed

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
        validate_release_assets(args.output, version)
    except (ValueError, KeyError, OSError) as error:
        print(f"release asset validation failed: {error if isinstance(error, ValueError) else 'metadata or artifact I/O failure'}", file=sys.stderr)
        return 1
    print("Prepared 13 assets; all 3 updater payload signatures and signed versions verified against the pinned public key.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
