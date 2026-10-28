"""Owned Requests connections with an exact-host fallback, retaining TLS/SNI identity.

Decision: .agents/notes/implemented/desktop/2026-10-28-campus-ip-fallback.md
"""
from importlib.resources import files
import ipaddress
import json
import socket

from requests.adapters import HTTPAdapter
from urllib3.connection import HTTPSConnection
from urllib3.connectionpool import HTTPSConnectionPool
from urllib3.exceptions import NewConnectionError


def fallback_ip(host):
    data = json.loads(files(__package__).joinpath("campus-addresses.json").read_text(encoding="utf-8"))
    if data.get("version") != 1:
        return None
    value = data.get("addresses", {}).get(host)
    if value is None:
        return None
    return str(ipaddress.ip_address(value))


def _dns_failure(error):
    # urllib3 1.26 wraps gaierror in NewConnectionError; 2.x also uses the
    # NameResolutionError subclass. Never treat refusal, timeout or TLS as DNS.
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        if isinstance(error, socket.gaierror):
            return True
        error = error.__cause__ or error.__context__
    return False


class CampusHTTPSConnection(HTTPSConnection):
    def _new_conn(self):
        try:
            return super()._new_conn()
        except NewConnectionError as error:
            if not _dns_failure(error):
                raise
            address = fallback_ip(self.host)
            if address is None:
                raise
            original = self._dns_host
            try:
                # Only socket establishment sees the IP. The original hostname
                # is restored before urllib3 starts TLS or constructs HTTP Host.
                self._dns_host = address
                return super()._new_conn()
            finally:
                self._dns_host = original


class CampusHTTPSConnectionPool(HTTPSConnectionPool):
    ConnectionCls = CampusHTTPSConnection


class CampusDNSAdapter(HTTPAdapter):
    def init_poolmanager(self, connections, maxsize, block=False, **kwargs):
        super().init_poolmanager(connections, maxsize, block=block, **kwargs)
        # PoolManager starts with a shared class map; never change another
        # Session or a proxy manager while installing this owned adapter.
        classes = self.poolmanager.pool_classes_by_scheme.copy()
        classes["https"] = CampusHTTPSConnectionPool
        self.poolmanager.pool_classes_by_scheme = classes


def install_fallback(session):
    session.mount("https://", CampusDNSAdapter())
