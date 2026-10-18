"""Bounded UTF-8 JSON-lines transport. Only this writer touches protocol stdout."""
import json
import queue
import threading

from .core import COMMANDS, DesktopError, ERRORS

MAX_LINE_BYTES = 64 * 1024
_EOF = object()


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate field")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError("non-finite number")


def parse_request(line):
    try:
        if isinstance(line, bytes):
            line = line.decode("utf-8")
        request = json.loads(line, object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
    except (UnicodeError, ValueError, TypeError, RecursionError):
        raise DesktopError("invalid_request") from None
    if not isinstance(request, dict):
        raise DesktopError("invalid_request")
    request_id = request.get("id")
    if type(request_id) is not int:
        raise DesktopError("invalid_request")
    if set(request) != {"id", "command", "args"}:
        error = DesktopError("invalid_request")
        error.request_id = request_id
        raise error
    command = request["command"]
    if not isinstance(command, str) or command not in COMMANDS:
        error = DesktopError("invalid_command")
        error.request_id = request_id
        raise error
    if not isinstance(request["args"], dict):
        error = DesktopError("invalid_args")
        error.request_id = request_id
        raise error
    return request_id, command, request["args"]


class ProtocolWriter:
    def __init__(self, stream):
        self.stream = stream
        self._lock = threading.RLock()
        self.failed = threading.Event()

    def _write(self, message):
        with self._lock:
            if self.failed.is_set():
                return
            try:
                self.stream.write(json.dumps(message, ensure_ascii=False, allow_nan=False,
                                             separators=(",", ":")) + "\n")
                self.stream.flush()
            except (OSError, ValueError):
                self.failed.set()

    def event(self, name, payload):
        self._write({"kind": "event", "name": name, "payload": payload})

    def response(self, request_id, *, data=None, error=None):
        message = {"kind": "response", "id": request_id, "ok": error is None}
        if error is None:
            message["data"] = data
        else:
            message["error"] = ERRORS.get(error, ERRORS["operation_failed"])
        self._write(message)


def read_requests(stream, incoming, stop):
    """Bound memory while draining overlong lines; a pipe may block only this daemon."""
    def enqueue(item):
        while not stop.is_set():
            try:
                incoming.put(item, timeout=0.1)
                return
            except queue.Full:
                continue

    try:
        while not stop.is_set():
            line = stream.readline(MAX_LINE_BYTES + 1)
            if not line:
                enqueue(_EOF)
                return
            size = len(line) if isinstance(line, bytes) else len(line.encode("utf-8"))
            if size > MAX_LINE_BYTES:
                newline = b"\n" if isinstance(line, bytes) else "\n"
                while line and not line.endswith(newline) and not stop.is_set():
                    line = stream.readline(MAX_LINE_BYTES + 1)
                enqueue(DesktopError("line_too_long"))
            else:
                enqueue(line)
    except (OSError, ValueError, UnicodeError):
        enqueue(_EOF)


class ProtocolServer:
    def __init__(self, core, stream, writer):
        self.core = core
        self.stream = stream
        self.writer = writer
        self.stop = threading.Event()
        self.incoming = queue.Queue(maxsize=64)
        self.reader = threading.Thread(target=read_requests, args=(stream, self.incoming, self.stop),
                                       name="ysu-desktop-input", daemon=True)
        self.core.set_event_sink(writer.event)

    def request_stop(self):
        self.stop.set()
        self.core.request_stop()

    def run(self):
        try:
            self.reader.start()
            self.core.start()
            while not self.stop.is_set() and not self.writer.failed.is_set():
                try:
                    item = self.incoming.get(timeout=0.1)
                except queue.Empty:
                    continue
                if item is _EOF:
                    break
                request_id = None
                try:
                    if isinstance(item, DesktopError):
                        raise item
                    request_id, command, args = parse_request(item)
                    data = self.core.handle(command, args)
                except DesktopError as exc:
                    self.writer.response(getattr(exc, "request_id", request_id), error=exc.code)
                    continue
                except Exception:
                    self.writer.response(request_id, error="operation_failed")
                    continue
                self.writer.response(request_id, data=data)
                if command == "shutdown":
                    break
            return 0
        finally:
            self.request_stop()
            self.core.close()
            if self.reader.is_alive():
                self.reader.join(timeout=0.2)
