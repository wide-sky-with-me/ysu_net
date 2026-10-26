#!/usr/bin/env python3
"""Add optional authenticated BSDIFF40 attachments to an already verified release.

Cloud release-tag use only; this module does not download, install or build anything.
Input is prepare_release's unchanged 13-asset output and an optional flat directory
of canonical public base updater payload/.sig pairs (any complete target subset).
No base arguments means an authenticated, exact-inventory no-op. Invalid supplied
bases/signatures/tools fail closed; only insufficient patch savings omit a delta.

qbsdiff/qbspatch must both be 1.4.4. The default signer is the existing locked
Tauri CLI 2.12.2, invoked only for a worthwhile, verified patch in a release-tag
GitHub Actions job. Private key/password values never enter argv, logs or files.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

# Also supports importlib-based unit tests without changing the caller's sys.path.
_SPEC = importlib.util.spec_from_file_location("_ysu_delta_manifest", Path(__file__).with_name("tauri_update_manifest.py"))
manifest = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(manifest)
TOOL_VERSION = "1.4.4"
TAURI_VERSION = "2.12.2"


def run_checked(runner, arguments: list[str], *, timeout: int = 600, env=None):
    options = dict(capture_output=True, timeout=timeout, check=False)
    if env is not None:
        options["env"] = env
    try:
        result = runner(arguments, **options)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError("release delta tool failed") from error
    if result.returncode != 0:
        # Deliberately suppress child stdout/stderr, especially signing diagnostics.
        raise ValueError("release delta tool failed")
    return result


def require_tools(runner, *names: str) -> None:
    for name in names:
        result = run_checked(runner, [name, "--version"], timeout=30)
        try:
            version = result.stdout.decode("ascii").strip()
        except (AttributeError, UnicodeError) as error:
            raise ValueError("invalid qbsdiff tool version output") from error
        if version != f"{name} {TOOL_VERSION}":
            raise ValueError("qbsdiff and qbspatch must be pinned to 1.4.4")


class TauriSigner:
    def __init__(self, source_root: Path, *, runner=None):
        self.source_root = source_root
        self.runner = runner or subprocess.run

    def __call__(self, patch: Path, version: str) -> None:
        # This branch is never touched by imports, verification-only or no-base runs.
        if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("GITHUB_REF") != f"refs/tags/v{version}":
            raise ValueError("patch signing is restricted to the matching cloud release tag")
        cli_root = self.source_root / "desktop/node_modules/@tauri-apps/cli"
        package = manifest.regular_file(cli_root / "package.json", self.source_root)
        if json.loads(package.read_text())["version"] != TAURI_VERSION:
            raise ValueError("patch signing requires locked Tauri CLI 2.12.2")
        cli = manifest.regular_file(cli_root / "tauri.js", self.source_root)
        # Tauri 2 also restores deprecated TAURI_PRIVATE_KEY* values, including a
        # path that takes precedence over the literal key. Exclude both families.
        environment = {key: value for key, value in os.environ.items()
                       if not key.startswith(("TAURI_SIGNING_", "TAURI_PRIVATE_KEY"))}
        key = os.environ.get("TAURI_SIGNING_PRIVATE_KEY")
        if not key:
            raise ValueError("cloud release patch signing key is unavailable")
        environment["TAURI_SIGNING_PRIVATE_KEY"] = key
        environment["TAURI_SIGNING_PRIVATE_KEY_PASSWORD"] = os.environ.get("TAURI_SIGNING_PRIVATE_KEY_PASSWORD", "")
        run_checked(self.runner, ["node", str(cli), "signer", "sign", "--app-version", version, str(patch)],
                    timeout=120, env=environment)


def base_pairs(base_dir: Path, base_version: str) -> dict[str, tuple[Path, Path]]:
    if base_dir.is_symlink() or not base_dir.is_dir():
        raise ValueError("base directory must be a regular directory")
    expected = set()
    pairs = {}
    for matrix in manifest.TARGETS:
        name = manifest.payload_name(base_version, matrix)
        payload, signature = base_dir / name, base_dir / (name + ".sig")
        if payload.exists() or signature.exists() or payload.is_symlink() or signature.is_symlink():
            manifest.bounded_file(payload, base_dir, manifest.MAX_FULL_SIZE)
            manifest.read_signature(signature, base_dir)
            pairs[matrix] = (payload, signature)
            expected.update((name, name + ".sig"))
    if {path.name for path in base_dir.iterdir()} != expected:
        raise ValueError("base directory contains unexpected or noncanonical files")
    return pairs


def same_bytes(left: Path, right: Path) -> bool:
    if left.stat().st_size != right.stat().st_size:
        return False
    with left.open("rb") as first, right.open("rb") as second:
        while True:
            chunk = first.read(1024 * 1024)
            if chunk != second.read(1024 * 1024):
                return False
            if not chunk:
                return True


def reconstruct(base: Path, patch: Path, target: Path, target_signature: Path,
                work: Path, version: str, gate, runner) -> None:
    # A separate directory per invocation ensures a patcher cannot reuse an output.
    with tempfile.TemporaryDirectory(prefix="reconstruct-", dir=work) as temporary:
        root = Path(temporary)
        rebuilt = root / target.name
        run_checked(runner, ["qbspatch", str(base), str(rebuilt), str(patch)])
        manifest.bounded_file(rebuilt, root, manifest.MAX_FULL_SIZE)
        if not same_bytes(rebuilt, target):
            raise ValueError("delta reconstruction differs byte-for-byte from target")
        # Hash equality alone is explicitly NOT authentication of the reconstructed file.
        signature = root / (target.name + ".sig")
        shutil.copyfile(target_signature, signature)
        if gate.verify(rebuilt, signature, root, version) != manifest.read_signature(target_signature, target_signature.parent):
            raise ValueError("reconstructed full signature differs")


def checked_bases(base_dir: Path, base_version: str, work: Path, gate) -> dict:
    snapshots = {}
    for matrix, (payload, signature) in base_pairs(base_dir, base_version).items():
        copied, copied_signature = work / payload.name, work / signature.name
        shutil.copyfile(payload, copied)
        shutil.copyfile(signature, copied_signature)
        manifest.bounded_file(copied, work, manifest.MAX_FULL_SIZE)
        encoded = gate.verify(copied, copied_signature, work, base_version)
        if encoded != manifest.read_signature(copied_signature, work):
            raise ValueError("verified base signature differs")
        snapshots[matrix] = copied
    return snapshots


def verify_delta_release(output: Path, source_root: Path, version: str, *, base_dir: Path | None = None,
                         base_version: str | None = None, public_verifier=None, runner=None) -> dict:
    """Final cloud gate: 13+2N exact assets, all signatures, bases and reconstruction."""
    if (base_dir is None) != (base_version is None):
        raise ValueError("base directory and base version must be supplied together")
    if base_version is not None:
        manifest.validate_base_version(base_version, version)
    gate = public_verifier if public_verifier is not None else manifest.PublicVerifier(source_root)
    feed = manifest.verify_release_assets(output, source_root, version, public_verifier=gate)
    entries = list(manifest.delta_entries(feed, version))
    if not entries:
        return feed
    if base_dir is None:
        raise ValueError("final delta verification requires the authenticated public base directory")
    runner = runner or subprocess.run
    require_tools(runner, "qbspatch")
    with tempfile.TemporaryDirectory(prefix="ysu-delta-final-") as temporary:
        work = Path(temporary)
        bases = checked_bases(base_dir, base_version, work, gate)
        for matrix, target, descriptor, name in entries:
            if descriptor["base_version"] != base_version or matrix not in bases:
                raise ValueError("delta base version or target differs from supplied base")
            base = bases[matrix]
            if base.stat().st_size != descriptor["base_size"] or manifest.sha256_file(base) != descriptor["base_sha256"]:
                raise ValueError("delta base size or sha256 differs")
            full = output / manifest.payload_name(version, matrix)
            reconstruct(base, output / name, full, Path(str(full) + ".sig"), work, version, gate, runner)
    return feed


def add_deltas(output: Path, source_root: Path, version: str, *, base_dir: Path | None = None,
               base_version: str | None = None, public_verifier=None, runner=None, signer=None) -> dict:
    """Stage, authenticate and reconstruct before exposing ANY new release assets.

    Dependency injection is for tests only: gate.verify returns the authenticated
    inline envelope; runner has subprocess.run's contract; signer(path, version)
    writes path+'.sig' with the official, version-bound Tauri envelope.
    """
    if (base_dir is None) != (base_version is None):
        raise ValueError("base directory and base version must be supplied together")
    if base_version is not None:
        manifest.validate_base_version(base_version, version)
    gate = public_verifier if public_verifier is not None else manifest.PublicVerifier(source_root)
    feed = manifest.verify_release_assets(output, source_root, version, public_verifier=gate)
    if "deltas" in feed:
        raise ValueError("delta generation requires the original prepared release; use --verify-only to recheck")
    if base_dir is None:
        return feed
    runner = runner or subprocess.run
    # Keep the candidate on the release filesystem so metadata replacement cannot
    # fail with EXDEV when a cloud runner mounts /tmp separately from its checkout.
    with tempfile.TemporaryDirectory(prefix="ysu-delta-stage-", dir=output.parent) as temporary:
        work = Path(temporary)
        assets = work / "assets"
        assets.mkdir()
        for path in output.iterdir():
            shutil.copyfile(path, assets / path.name)
        # Reauthenticate the captured target snapshot, not mutable original inputs.
        manifest.verify_release_assets(assets, source_root, version, public_verifier=gate)
        bases = checked_bases(base_dir, base_version, work, gate)
        if not bases:
            return feed
        require_tools(runner, "qbsdiff", "qbspatch")
        signer = signer if signer is not None else TauriSigner(source_root, runner=runner)
        deltas, additions = {}, []
        for matrix, base in bases.items():
            target = assets / manifest.payload_name(version, matrix)
            target_signature = Path(str(target) + ".sig")
            name = manifest.patch_name(version, matrix, base_version)
            # The patch stays outside the candidate inventory until worth publishing.
            patch = work / name
            run_checked(runner, ["qbsdiff", str(base), str(target), str(patch)])
            manifest.regular_file(patch, work)
            size = patch.stat().st_size
            if size > manifest.MAX_PATCH_SIZE or size * 5 >= target.stat().st_size * 4:
                continue
            with patch.open("rb") as stream:
                if stream.read(8) != b"BSDIFF40":
                    raise ValueError("qbsdiff output is not BSDIFF40")
            reconstruct(base, patch, target, target_signature, work, version, gate, runner)
            before = manifest.sha256_file(patch)
            signer(patch, version)
            manifest.bounded_file(patch, work, manifest.MAX_PATCH_SIZE)
            signature = Path(str(patch) + ".sig")
            # A signer may not mutate the patch that was just reconstructed.
            if patch.stat().st_size != size or manifest.sha256_file(patch) != before:
                raise ValueError("patch changed during signing")
            encoded = gate.verify(patch, signature, work, version)
            if encoded != manifest.read_signature(signature, work):
                raise ValueError("verified patch signature differs")
            full = feed["platforms"][manifest.TARGETS[matrix]]
            descriptor = {"format": "bsdiff40", "base_version": base_version,
                          "base_sha256": manifest.sha256_file(base), "base_size": base.stat().st_size,
                          "target_version": version, "target_sha256": manifest.sha256_file(target),
                          "target_size": target.stat().st_size, "full_url": full["url"],
                          "full_signature": full["signature"], "url": manifest.asset_url(version, name),
                          "signature": encoded, "sha256": before, "size": size}
            deltas[manifest.TARGETS[matrix]] = [descriptor]
            for path in (patch, signature):
                shutil.copyfile(path, assets / path.name)
                additions.append(path.name)
        if not deltas:
            return feed
        candidate = dict(feed, deltas=deltas)
        (assets / "latest.json").write_text(json.dumps(candidate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        manifest.write_checksums(assets)
        verify_delta_release(assets, source_root, version, base_dir=base_dir, base_version=base_version,
                             public_verifier=gate, runner=runner)
        # Check the original baseline again before changing its feed/checksums. The
        # only writes are declared, already verified patch pairs and these two files.
        if manifest.verify_release_assets(output, source_root, version, public_verifier=gate) != feed:
            raise ValueError("original release changed during delta assembly")
        for name in additions:
            shutil.copyfile(assets / name, output / name)
        for name in ("latest.json", "SHA256SUMS"):
            os.replace(assets / name, output / name)
        return verify_delta_release(output, source_root, version, base_dir=base_dir, base_version=base_version,
                                    public_verifier=gate, runner=runner)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--version", required=True, help="canonical version without leading v")
    parser.add_argument("--base-dir", type=Path)
    parser.add_argument("--base-version")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        operation = verify_delta_release if args.verify_only else add_deltas
        feed = operation(args.output.absolute(), args.source_root.resolve(), args.version,
                         base_dir=args.base_dir, base_version=args.base_version)
    except (ValueError, KeyError, OSError, TypeError) as error:
        print(f"release delta validation failed: {error if isinstance(error, ValueError) else 'metadata or artifact I/O failure'}", file=sys.stderr)
        return 1
    count = sum(len(entries) for entries in feed.get("deltas", {}).values())
    print(f"Verified {13 + 2 * count} release assets; {count} authenticated delta(s); original full payloads retained.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
