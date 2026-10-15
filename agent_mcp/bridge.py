"""Discover the add-on's authenticated local endpoint; never send Python code."""

import json
import logging
import math
import os
import socket
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from blender_agent_marks.protocol import MAX_RESPONSE_BYTES, PROTOCOL_VERSION, runtime_directory

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class BridgeConfig:
    instance_id: str | None = None
    timeout_seconds: float = 15.0

    def __post_init__(self):
        if self.instance_id is not None and (
            not isinstance(self.instance_id, str)
            or len(self.instance_id) != 32
            or any(char not in "0123456789abcdef" for char in self.instance_id)
        ):
            raise ValueError("Instance ID must be the 32-character ID shown in Blender")
        if (
            type(self.timeout_seconds) not in (int, float)
            or not math.isfinite(self.timeout_seconds)
            or not 0 < self.timeout_seconds <= 300
        ):
            raise ValueError("Timeout must be in (0, 300] seconds")

    @classmethod
    def from_env(cls):
        return cls(
            os.environ.get("ASM_INSTANCE") or None, float(os.environ.get("ASM_READ_TIMEOUT", "15"))
        )


def failure(code, message):
    return {"ok": False, "error": {"code": code, "message": message}}


def exchange(endpoint, operation, arguments, timeout):
    request = {
        "protocol": PROTOCOL_VERSION,
        "token": endpoint["token"],
        "operation": operation,
        "arguments": arguments,
    }
    deadline = time.monotonic() + timeout
    with socket.create_connection(("127.0.0.1", endpoint["port"]), timeout=timeout) as stream:
        stream.sendall(json.dumps(request, ensure_ascii=True, allow_nan=False).encode() + b"\0")
        incoming = bytearray()
        while b"\0" not in incoming:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError()
            stream.settimeout(remaining)
            chunk = stream.recv(65536)
            if not chunk:
                raise ConnectionError("Blender closed the connection")
            incoming.extend(chunk)
            if len(incoming) > MAX_RESPONSE_BYTES:
                raise ValueError("Response exceeds the size limit; use a smaller page")
    LOGGER.debug("bridge_response bytes=%d", len(incoming))
    result = json.loads(incoming.partition(b"\0")[0])
    if not isinstance(result, dict) or type(result.get("ok")) is not bool:
        raise ValueError("Invalid annotation response")
    return result


def probe_instance(path, deadline):
    try:
        if path.stat().st_size > 4096:
            return None
        endpoint = json.loads(path.read_text(encoding="utf-8"))
        if (
            endpoint.get("protocol") != PROTOCOL_VERSION
            or type(endpoint.get("port")) is not int
            or not 1 <= endpoint["port"] <= 65535
            or not isinstance(endpoint.get("token"), str)
            or endpoint.get("instance_id") != path.stem
        ):
            return None
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        result = exchange(endpoint, "ping", {}, min(remaining, 0.5))
        if result.get("ok") and result.get("instance_id") == path.stem:
            return endpoint
    except (OSError, ValueError, TypeError, AttributeError, RecursionError):
        pass
    return None


def discover(config):
    deadline = time.monotonic() + config.timeout_seconds
    paths = sorted(runtime_directory().glob("*.json"))
    if config.instance_id:
        paths = [runtime_directory() / f"{config.instance_id}.json"]
    with ThreadPoolExecutor(max_workers=8) as executor:
        live = [
            endpoint
            for endpoint in executor.map(lambda path: probe_instance(path, deadline), paths)
            if endpoint is not None
        ]
    if time.monotonic() >= deadline:
        return None, failure(
            "BLENDER_BUSY_OR_TIMEOUT",
            "Instance discovery timed out. Retry or set ASM_INSTANCE to the ID shown in Blender.",
        )
    if not live:
        return None, failure(
            "BLENDER_UNAVAILABLE",
            "Open Blender and enable FacetCue for Blender. If busy, retry when Blender is responsive.",
        )
    if len(live) > 1:
        return None, failure(
            "MULTIPLE_BLENDER_INSTANCES",
            "Set ASM_INSTANCE to the desired ID shown in Blender: "
            + ", ".join(item["instance_id"] for item in live),
        )
    return live[0], None


def request(operation, arguments, config=None):
    started = time.monotonic()
    try:
        try:
            config = config or BridgeConfig.from_env()
        except ValueError as exc:
            return failure("INVALID_BRIDGE_CONFIG", str(exc))
        endpoint, error = discover(config)
        if error:
            return error
        return exchange(endpoint, operation, arguments, config.timeout_seconds)
    except TimeoutError:
        return failure(
            "BLENDER_BUSY_OR_TIMEOUT", "Blender did not answer in time; retry when responsive"
        )
    except OSError as exc:
        return failure("BLENDER_UNAVAILABLE", str(exc))
    except (ValueError, UnicodeError, TypeError) as exc:
        return failure("INVALID_BRIDGE_RESPONSE", str(exc))
    finally:
        LOGGER.debug("annotation_request duration_ms=%.1f", (time.monotonic() - started) * 1000)


def read_annotations(arguments, *, config=None):
    return request("get_surface_annotations", arguments, config)


def submit_annotations(arguments, *, config=None):
    return request("submit_annotation_changes", arguments, config)
