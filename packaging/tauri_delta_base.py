#!/usr/bin/env python3
"""Fetch only canonical PUBLIC updater bases from the fixed upstream latest release.

No token, signing key, installer execution or arbitrary repository/URL is accepted.
The producer reauthenticates these captured public files before generating deltas.
"""
from __future__ import annotations

import argparse
import importlib.util
from http.client import HTTPException
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

_SPEC = importlib.util.spec_from_file_location("_ysu_base_manifest", Path(__file__).with_name("tauri_update_manifest.py"))
manifest = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(manifest)
REPOSITORY = "wide-sky-with-me/ysu_net"
LATEST_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
METADATA_LIMIT = 1024 * 1024
SIGNATURE_LIMIT = 16 * 1024
FULL_LIMIT = 64 * 1024 * 1024
MAX_REDIRECTS = 5
USER_AGENT = "ysu-net-public-delta-base"
ASSET_HOSTS = frozenset(("github.com", "release-assets.githubusercontent.com",
                         "objects.githubusercontent.com", "github-releases.githubusercontent.com"))


class BaseError(ValueError):
    """Fixed public error only: never interpolate remote content or exceptions."""


def permitted_url(url: str, *, metadata: bool = False) -> bool:
    try:
        parsed = urlsplit(url)
        hosts = ASSET_HOSTS | {"api.github.com"} if metadata else ASSET_HOSTS
        return (len(url) <= 16 * 1024 and parsed.scheme == "https"
                and parsed.hostname in hosts and parsed.port is None
                and parsed.username is None and parsed.password is None
                and not parsed.fragment
                and (not parsed.query or parsed.hostname not in ("github.com", "api.github.com")))
    except (TypeError, ValueError):
        return False


class PublicRedirect(HTTPRedirectHandler):
    def __init__(self, *, metadata: bool = False):
        super().__init__()
        self.metadata = metadata
        self.hops = 0

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.hops += 1
        if self.hops > MAX_REDIRECTS or not permitted_url(newurl, metadata=self.metadata):
            raise BaseError("public base redirect rejected")
        # Do not inherit authorization, cookies, referer or arbitrary request headers.
        return Request(newurl, headers={"User-Agent": USER_AGENT,
                                       "Accept": req.get_header("Accept", "application/octet-stream")})


def read_bounded(response, limit: int, deadline: float) -> bytes:
    declared = response.headers.get("Content-Length")
    if declared is not None:
        try:
            declared = int(declared)
        except (TypeError, ValueError):
            raise BaseError("public base response length is invalid") from None
        if declared < 0 or declared > limit:
            raise BaseError("public base response exceeds size limit")
    data = bytearray()
    while True:
        if time.monotonic() > deadline:
            raise BaseError("public base request exceeded its budget")
        chunk = response.read(min(64 * 1024, limit - len(data) + 1))
        if not chunk:
            break
        if len(data) + len(chunk) > limit:
            raise BaseError("public base response exceeds size limit")
        data.extend(chunk)
    return bytes(data)


def fetch_public(url: str, limit: int, *, metadata: bool = False, missing_ok: bool = False):
    if not permitted_url(url, metadata=metadata):
        raise BaseError("public base URL rejected")
    timeout = 30 if metadata else 300
    deadline = time.monotonic() + timeout
    request = Request(url, headers={"User-Agent": USER_AGENT,
                                   "Accept": "application/vnd.github+json" if metadata else "application/octet-stream"})
    try:
        with build_opener(PublicRedirect(metadata=metadata)).open(request, timeout=timeout) as response:
            if response.status != 200 or not permitted_url(response.geturl(), metadata=metadata):
                raise BaseError("public base response rejected")
            return read_bounded(response, limit, deadline)
    except HTTPError as error:
        if error.code == 404 and missing_ok:
            return None
        raise BaseError("public base request failed") from None
    except BaseError:
        raise
    except (OSError, URLError, ValueError, HTTPException):
        raise BaseError("public base request failed") from None


def selected_pairs(metadata: dict, target_version: str):
    if not isinstance(metadata, dict) or metadata.get("draft") is not False or metadata.get("prerelease") is not False:
        raise BaseError("latest public release is not a stable release")
    tag = metadata.get("tag_name")
    if not isinstance(tag, str) or not re.fullmatch(r"v(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)", tag):
        raise BaseError("latest public release version is invalid")
    version = tag[1:]
    try:
        manifest.validate_base_version(version, target_version)
    except (ValueError, TypeError):
        # Latest may already be the target or newer; do not search older releases.
        return "", []
    assets = metadata.get("assets")
    if not isinstance(assets, list) or len(assets) > 2048:
        raise BaseError("latest public release assets are invalid")
    expected = {name for matrix in manifest.TARGETS for name in
                (manifest.payload_name(version, matrix), manifest.payload_name(version, matrix) + ".sig")}
    indexed = {}
    for asset in assets:
        if not isinstance(asset, dict) or not isinstance(asset.get("name"), str):
            raise BaseError("latest public release assets are invalid")
        name = asset["name"]
        if name not in expected:
            continue  # Never request unrelated assets, including keys or configuration.
        if name in indexed:
            raise BaseError("latest public release asset is ambiguous")
        size = asset.get("size")
        limit = SIGNATURE_LIMIT if name.endswith(".sig") else FULL_LIMIT
        url = f"https://github.com/{REPOSITORY}/releases/download/{tag}/{name}"
        if (type(size) is not int or not 0 < size <= limit or asset.get("state") != "uploaded"
                or asset.get("browser_download_url") != url or not permitted_url(url)):
            raise BaseError("latest public release asset is invalid")
        indexed[name] = (url, size, limit)
    pairs = []
    for matrix in manifest.TARGETS:
        name = manifest.payload_name(version, matrix)
        if name not in indexed and name + ".sig" not in indexed:
            continue
        if name not in indexed or name + ".sig" not in indexed:
            raise BaseError("latest public release base pair is incomplete")
        pairs.append((name, indexed[name], indexed[name + ".sig"]))
    return (version, pairs) if pairs else ("", [])


def download_latest(target_version: str, output: Path, source_root: Path, *, fetch=None, public_verifier=None) -> str:
    try:
        manifest.release_version("v" + target_version)
    except (ValueError, TypeError):
        raise BaseError("target release version is invalid") from None
    fetch = fetch or fetch_public
    raw = fetch(LATEST_URL, METADATA_LIMIT, metadata=True, missing_ok=True)
    if raw is None:
        return ""
    if len(raw) > METADATA_LIMIT:
        raise BaseError("public base response exceeds size limit")
    try:
        metadata = json.loads(raw)
    except (ValueError, UnicodeError, RecursionError):
        raise BaseError("latest public release metadata is invalid") from None
    version, pairs = selected_pairs(metadata, target_version)
    if not pairs:
        return ""
    if output.is_symlink() or any(parent.is_symlink() for parent in output.absolute().parents):
        raise BaseError("public base output directory is invalid")
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise BaseError("public base output must be a fresh or empty directory")
    output.mkdir(parents=True, exist_ok=True)
    gate = public_verifier if public_verifier is not None else manifest.PublicVerifier(source_root)
    for name, payload, signature in pairs:
        for destination, (url, size, limit) in ((name, payload), (name + ".sig", signature)):
            data = fetch(url, limit)
            if not isinstance(data, bytes) or len(data) != size or len(data) > limit:
                raise BaseError("public base asset size differs from metadata")
            with (output / destination).open("xb") as stream:
                stream.write(data)
        try:
            gate.verify(output / name, output / (name + ".sig"), output, version)
        except (ValueError, OSError):
            raise BaseError("public base signature verification failed") from None
    return version


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-version", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    try:
        version = download_latest(args.target_version, args.output, args.source_root)
        destination = os.environ.get("GITHUB_OUTPUT")
        if destination:
            with open(destination, "a", encoding="utf-8") as stream:
                stream.write(f"base_version={version}\n")
    except (ValueError, OSError, TypeError, HTTPException, RecursionError):
        print("public delta base preparation failed", file=sys.stderr)
        return 1
    print("Verified public base pairs." if version else "No eligible latest public base; retaining complete packages.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
