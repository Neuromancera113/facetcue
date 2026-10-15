"""Authenticated loopback RPC, serviced exclusively by Blender's main thread."""

import atexit
import json
import logging
import os
import secrets
import socket
import time
from dataclasses import dataclass, field

import bpy

from . import api, runtime
from .protocol import MAX_REQUEST_BYTES, MAX_RESPONSE_BYTES, PROTOCOL_VERSION, runtime_directory

LOGGER = logging.getLogger(__name__)
_server = None
LAST_ERROR = ""


@dataclass
class Client:
    stream: socket.socket
    deadline: float
    incoming: bytearray = field(default_factory=bytearray)
    outgoing: bytes = b""


class AnnotationServer:
    def __init__(self):
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.clients = []
        self.path = None
        try:
            self.listener.bind(("127.0.0.1", 0))
            self.listener.listen(8)
            self.listener.setblocking(False)
            self.instance_id = secrets.token_hex(16)
            self.token = secrets.token_hex(32)
            self.port = self.listener.getsockname()[1]
            directory = runtime_directory()
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            self.path = directory / f"{self.instance_id}.json"
            descriptor = {
                "protocol": PROTOCOL_VERSION,
                "instance_id": self.instance_id,
                "port": self.port,
                "token": self.token,
                "pid": os.getpid(),
            }
            with self.path.open("x", encoding="utf-8") as stream:
                os.chmod(self.path, 0o600)
                json.dump(descriptor, stream)
        except Exception:
            self.close()
            raise

    def dispatch(self, request):
        if not isinstance(request, dict) or request.get("protocol") != PROTOCOL_VERSION:
            return failure("INVALID_REQUEST", "Unsupported annotation protocol")
        token = request.get("token")
        if not isinstance(token, str) or not secrets.compare_digest(token, self.token):
            return failure("UNAUTHORIZED", "Invalid connection token")
        operation = request.get("operation")
        if operation == "ping":
            return {"ok": True, "instance_id": self.instance_id}
        if operation not in {"get_surface_annotations", "submit_annotation_changes"}:
            return failure("UNKNOWN_OPERATION", "Only annotation reads and submissions are allowed")
        arguments = request.get("arguments", {})
        if not isinstance(arguments, dict):
            return failure("INVALID_ARGUMENTS", "Arguments must be an object")
        result = api.dispatch(operation, arguments)
        if operation == "get_surface_annotations" and result.get("ok"):
            runtime.record_agent_read(result)
        return result

    def poll(self):
        for _ in range(8):
            try:
                stream, _ = self.listener.accept()
            except BlockingIOError:
                break
            if len(self.clients) >= 8:
                stream.close()
            else:
                stream.setblocking(False)
                self.clients.append(Client(stream, time.monotonic() + 15))
        for client in self.clients[:]:
            try:
                if time.monotonic() >= client.deadline:
                    self.drop(client)
                    continue
                if not client.outgoing:
                    chunk = client.stream.recv(262144)
                    if not chunk:
                        self.drop(client)
                        continue
                    client.incoming.extend(chunk)
                    if len(client.incoming) > MAX_REQUEST_BYTES:
                        self.drop(client)
                        continue
                    if b"\0" not in client.incoming:
                        continue
                    try:
                        result = self.dispatch(json.loads(client.incoming.partition(b"\0")[0]))
                    except (ValueError, TypeError, UnicodeError, RecursionError):
                        result = failure("INVALID_REQUEST", "Invalid JSON request")
                    raw = json.dumps(result, ensure_ascii=False).encode()
                    if len(raw) > MAX_RESPONSE_BYTES:
                        raw = json.dumps(
                            failure("RESPONSE_TOO_LARGE", "Use a smaller page size")
                        ).encode()
                    client.outgoing = raw + b"\0"
                count = client.stream.send(client.outgoing)
                client.outgoing = client.outgoing[count:]
                if not client.outgoing:
                    self.drop(client)
            except BlockingIOError:
                continue
            except OSError:
                self.drop(client)

    def drop(self, client):
        client.stream.close()
        self.clients.remove(client)

    def close(self):
        for client in self.clients[:]:
            self.drop(client)
        self.listener.close()
        if self.path:
            self.path.unlink(missing_ok=True)


def failure(code, message):
    return {"ok": False, "error": {"code": code, "message": message}}


def poll():
    if _server is None:
        return None
    try:
        _server.poll()
    except Exception:
        LOGGER.exception("Annotation connection stopped")
        stop()
        return None
    return 0.05


def start():
    global _server, LAST_ERROR
    if _server is not None:
        return
    try:
        _server = AnnotationServer()
        bpy.app.timers.register(poll, first_interval=0.05, persistent=True)
        atexit.register(stop)
        LAST_ERROR = ""
    except OSError as exc:
        LAST_ERROR = str(exc)
        LOGGER.error("Cannot start annotation connection: %s", exc)


def stop():
    global _server
    if bpy.app.timers.is_registered(poll):
        bpy.app.timers.unregister(poll)
    if _server is not None:
        _server.close()
        _server = None
    atexit.unregister(stop)
