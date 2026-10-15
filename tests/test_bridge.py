"""Transport, discovery and error boundaries without a running Blender."""

import json
import os
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from agent_mcp.bridge import BridgeConfig, discover, exchange, read_annotations

ENDPOINT = {"protocol": 1, "instance_id": "a" * 32, "port": 12345, "token": "secret"}


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        env = patch.dict(
            os.environ,
            {"ASM_RUNTIME_DIR": self.directory.name, "ASM_INSTANCE": "", "ASM_READ_TIMEOUT": "15"},
        )
        env.start()
        self.addCleanup(env.stop)

    def read_chunks(self, chunks):
        stream = MagicMock()
        stream.__enter__.return_value = stream
        stream.recv.side_effect = chunks
        with (
            patch("agent_mcp.bridge.discover", return_value=(ENDPOINT, None)),
            patch("agent_mcp.bridge.socket.create_connection", return_value=stream),
        ):
            return read_annotations({})

    def test_named_rpc_never_transmits_code(self):
        stream = MagicMock()
        stream.__enter__.return_value = stream
        stream.recv.return_value = b'{"ok":true}\0'
        value = "'); __import__('os').system('bad'); #"
        with patch("agent_mcp.bridge.socket.create_connection", return_value=stream):
            exchange(ENDPOINT, "get_surface_annotations", {"scene_name": value}, 1)
        request = json.loads(stream.sendall.call_args.args[0].rstrip(b"\0"))
        self.assertEqual(request["arguments"], {"scene_name": value})
        self.assertNotIn("code", request)

    def test_split_frame(self):
        self.assertEqual(self.read_chunks([b'{"ok":', b"true}\0"]), {"ok": True})

    def test_invalid_response_shapes(self):
        for data in (b"[]\0", b"{broken}\0", b"\xff\0", b'{"ok":1}\0'):
            with self.subTest(data=data):
                self.assertEqual(
                    self.read_chunks([data])["error"]["code"], "INVALID_BRIDGE_RESPONSE"
                )

    def test_timeout_and_closed_connection(self):
        for chunks, code in (
            ([socket.timeout()], "BLENDER_BUSY_OR_TIMEOUT"),
            ([b""], "BLENDER_UNAVAILABLE"),
        ):
            self.assertEqual(self.read_chunks(chunks)["error"]["code"], code)

    def test_config_validation(self):
        for fields in (
            {"timeout_seconds": True},
            {"timeout_seconds": float("nan")},
            {"timeout_seconds": float("inf")},
            {"timeout_seconds": 0},
            {"instance_id": "../../secret"},
        ):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                BridgeConfig(**fields)

    def test_invalid_environment(self):
        with patch.dict(os.environ, {"ASM_READ_TIMEOUT": "bad"}):
            self.assertEqual(read_annotations({})["error"]["code"], "INVALID_BRIDGE_CONFIG")

    def test_missing_blender_is_error(self):
        self.assertEqual(read_annotations({})["error"]["code"], "BLENDER_UNAVAILABLE")

    def write_endpoint(self, value):
        Path(self.directory.name, value["instance_id"] + ".json").write_text(
            json.dumps(value), encoding="utf-8"
        )

    def test_discovery_and_instance_selection(self):
        second = {**ENDPOINT, "instance_id": "b" * 32}
        self.write_endpoint(ENDPOINT)
        self.write_endpoint(second)

        def ping(endpoint, *args):
            return {"ok": True, "instance_id": endpoint["instance_id"]}

        with patch("agent_mcp.bridge.exchange", side_effect=ping):
            self.assertEqual(
                discover(BridgeConfig())[1]["error"]["code"], "MULTIPLE_BLENDER_INSTANCES"
            )
            self.assertEqual(discover(BridgeConfig(instance_id=second["instance_id"]))[0], second)

    def test_stale_or_invalid_discovery_ignored(self):
        self.write_endpoint(ENDPOINT)
        Path(self.directory.name, "broken.json").write_text("broken", encoding="utf-8")
        with patch("agent_mcp.bridge.exchange", side_effect=ConnectionRefusedError()):
            self.assertEqual(discover(BridgeConfig())[1]["error"]["code"], "BLENDER_UNAVAILABLE")

    def test_live_instance_after_many_stale_descriptors(self):
        for index in range(40):
            self.write_endpoint({**ENDPOINT, "instance_id": f"{index:032x}"})
        self.write_endpoint(ENDPOINT)

        def ping(endpoint, *args):
            if endpoint == ENDPOINT:
                return {"ok": True, "instance_id": endpoint["instance_id"]}
            raise ConnectionRefusedError()

        with patch("agent_mcp.bridge.exchange", side_effect=ping):
            self.assertEqual(discover(BridgeConfig()), (ENDPOINT, None))

    def test_incomplete_discovery_never_selects_a_partial_result(self):
        second = {**ENDPOINT, "instance_id": "b" * 32}
        self.write_endpoint(ENDPOINT)
        self.write_endpoint(second)

        def ping(endpoint, *args):
            clock.return_value = 2
            return {"ok": True, "instance_id": endpoint["instance_id"]}

        with (
            patch("agent_mcp.bridge.time.monotonic", return_value=0) as clock,
            patch("agent_mcp.bridge.exchange", side_effect=ping),
        ):
            endpoint, error = discover(BridgeConfig(timeout_seconds=1))
        self.assertIsNone(endpoint)
        self.assertEqual(error["error"]["code"], "BLENDER_BUSY_OR_TIMEOUT")
        self.assertEqual(len(list(Path(self.directory.name).glob("*.json"))), 2)

    def test_busy_descriptor_is_preserved_and_can_recover(self):
        self.write_endpoint(ENDPOINT)
        with patch("agent_mcp.bridge.exchange", side_effect=TimeoutError()):
            discover(BridgeConfig())
        self.assertTrue(Path(self.directory.name, ENDPOINT["instance_id"] + ".json").exists())
        with patch(
            "agent_mcp.bridge.exchange",
            return_value={"ok": True, "instance_id": ENDPOINT["instance_id"]},
        ):
            self.assertEqual(discover(BridgeConfig()), (ENDPOINT, None))

    def test_logs_do_not_expose_notes_or_tokens(self):
        note = "private annotation content"
        with self.assertLogs("agent_mcp.bridge", level="DEBUG") as captured:
            result = self.read_chunks([json.dumps({"ok": True, "note": note}).encode() + b"\0"])
        self.assertEqual(result["note"], note)
        self.assertNotIn(note, "\n".join(captured.output))
        self.assertNotIn(ENDPOINT["token"], "\n".join(captured.output))


if __name__ == "__main__":
    unittest.main()
