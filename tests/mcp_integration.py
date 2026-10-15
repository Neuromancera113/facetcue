"""Real MCP stdio client and packaged add-on connection in an isolated Blender."""

import argparse
import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from agent_mcp.bridge import BridgeConfig, discover, exchange

checks = []


def check(name, condition):
    if not condition:
        raise AssertionError(name)
    checks.append(name)


def send_deep_json(endpoint):
    with socket.create_connection(("127.0.0.1", endpoint["port"]), timeout=2) as stream:
        stream.sendall(b"[" * 10000 + b"]" * 10000 + b"\0")
        response = bytearray()
        while b"\0" not in response:
            chunk = stream.recv(4096)
            if not chunk:
                raise ConnectionError("Server closed before rejecting the malformed request")
            response.extend(chunk)
        return json.loads(response.partition(b"\0")[0])


async def exercise(out, process):
    ready = json.loads((out / "ready.json").read_text(encoding="utf-8"))
    endpoint = json.loads(
        (out / "connection" / (ready["instance_id"] + ".json")).read_text(encoding="utf-8")
    )
    rejected = await asyncio.to_thread(send_deep_json, endpoint)
    check("deep_json_request_isolated", rejected["error"]["code"] == "INVALID_REQUEST")
    alive = await asyncio.to_thread(exchange, endpoint, "ping", {}, 2)
    check("connection_survives_deep_json", alive.get("instance_id") == endpoint["instance_id"])
    rejected = await asyncio.to_thread(
        exchange, {**endpoint, "token": "wrong"}, "get_surface_annotations", {}, 2
    )
    check("unauthenticated_access_refused", rejected["error"]["code"] == "UNAUTHORIZED")
    rejected = await asyncio.to_thread(
        exchange, endpoint, "execute", {"code": "print('must not execute')"}, 2
    )
    check(
        "arbitrary_code_execution_not_available", rejected["error"]["code"] == "UNKNOWN_OPERATION"
    )
    rejected = await asyncio.to_thread(exchange, endpoint, "delete_mark", {}, 2)
    check("unexposed_mutations_refused", rejected["error"]["code"] == "UNKNOWN_OPERATION")
    with socket.socket() as unused_port:
        unused_port.bind(("127.0.0.1", 0))
        stale_paths = []
        try:
            for index in range(40):
                stale_id = f"{index:032x}"
                path = out / "connection" / (stale_id + ".json")
                path.write_text(
                    json.dumps(
                        {**endpoint, "instance_id": stale_id, "port": unused_port.getsockname()[1]}
                    ),
                    encoding="utf-8",
                )
                stale_paths.append(path)
            with patch.dict(os.environ, ASM_RUNTIME_DIR=str(out / "connection")):
                found, error = await asyncio.to_thread(discover, BridgeConfig(timeout_seconds=10))
            check("discovery_past_40_closed_ports", error is None and found == endpoint)
        finally:
            for path in stale_paths:
                path.unlink()
    env = dict(os.environ, ASM_RUNTIME_DIR=str(out / "connection"))
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(ROOT / "agent_mcp" / "server.py"), "--log-level", "DEBUG"],
        env=env,
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            initialized = await session.initialize()
            check("server_name", initialized.serverInfo.name == "FacetCue for Blender")
            check(
                "discovery_in_initialize", "get_surface_annotations()" in initialized.instructions
            )
            catalog = await session.list_tools()
            tool = next(t for t in catalog.tools if t.name == "get_surface_annotations")
            check("no_required_arguments", not tool.inputSchema.get("required"))
            check("read_only_tool", tool.annotations.readOnlyHint)
            result = await session.call_tool("get_surface_annotations", {})
            check("native_tool_success", not result.isError and result.structuredContent["ok"])
            data = result.structuredContent
            check("all_scenes_and_statuses", data["total"] == 3 and len(data["scenes"]) == 2)
            record = next(m for m in data["annotations"] if m["id"] == ready["first_id"])
            check(
                "unsaved_hidden_note_readable",
                record["note"] == "未保存的注释：修改此处圆角" and data["file_path"] is None,
            )
            check(
                "no_viewport_still_has_3d_position",
                record["viewport"]["state"] == "NO_VIEWPORT"
                and record["resolved"]["world_position"] is not None,
            )
            bad = next(m for m in data["annotations"] if m["id"] == ready["broken_id"])
            check(
                "corrupt_record_isolated",
                bad["resolved"]["state"] == "CORRUPT_ANNOTATION" and bad["note"],
            )
            archived = next(m for m in data["annotations"] if m["id"] == ready["archived_id"])
            check("archived_not_silently_omitted", archived["status"] == "ARCHIVED")
            page = (
                await session.call_tool("get_surface_annotations", {"limit": 1})
            ).structuredContent
            check(
                "pagination_explicit",
                page["returned"] == 1 and page["has_more"] and page["next_offset"] == 1,
            )
            next_page = (
                await session.call_tool("get_surface_annotations", {"offset": 1, "limit": 1})
            ).structuredContent
            check(
                "pagination_progress",
                next_page["annotations"][0]["id"] != page["annotations"][0]["id"],
            )
            invalid = await session.call_tool("get_surface_annotations", {"limit": 0})
            check(
                "typed_error",
                invalid.isError
                and invalid.structuredContent["error"]["code"] == "INVALID_ARGUMENTS",
            )
            resource = await session.read_resource("blender-marks://current")
            check("resource_optional_path", json.loads(resource.contents[0].text)["total"] == 3)
            (out / "update").touch()
            for _ in range(100):
                if (out / "updated").exists():
                    break
                await asyncio.sleep(0.02)
            fresh = (await session.call_tool("get_surface_annotations", {})).structuredContent
            updated = next(m for m in fresh["annotations"] if m["id"] == ready["first_id"])
            check(
                "next_read_is_live",
                updated["note"] == "实时修改后的注释" and updated["revision"] == 2,
            )
            (ROOT / "artifacts" / "agent_read_sample.json").write_text(
                json.dumps(fresh, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            change = {
                "scene_name": updated["scene_name"],
                "marker_id": updated["id"],
                "expected_revision": 2,
                "summary": "Finished model edits",
            }
            submitted = await session.call_tool("submit_annotation_changes", {"changes": [change]})
            check(
                "native_review_submission",
                not submitted.isError
                and submitted.structuredContent["annotations"][0]["status"] == "MODIFIED",
            )
            pending = submitted.structuredContent["annotations"][0]
            check(
                "badge_preserves_marker_color_and_note",
                pending["color_rgba"] == updated["color_rgba"]
                and pending["note"] == updated["note"]
                and pending["status_badge"] is not None,
            )
            repeated = await session.call_tool("submit_annotation_changes", {"changes": [change]})
            check(
                "submission_retry_idempotent",
                repeated.structuredContent == submitted.structuredContent,
            )
            invalid = await session.call_tool(
                "submit_annotation_changes", {"changes": [{**change, "expected_revision": 99}]}
            )
            check(
                "submission_revision_conflict",
                invalid.isError
                and invalid.structuredContent["error"]["code"] == "REVISION_CONFLICT",
            )
            (out / "stop").touch()
            await asyncio.to_thread(process.wait, 5)
            offline = await session.call_tool("get_surface_annotations", {})
            check(
                "disconnect_is_not_empty",
                offline.isError
                and offline.structuredContent["error"]["code"] == "BLENDER_UNAVAILABLE",
            )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--blender", default=os.environ.get("BLENDER_BIN") or shutil.which("blender")
    )
    options = parser.parse_args()
    if not options.blender:
        parser.error("Provide --blender or BLENDER_BIN")
    (ROOT / "artifacts").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="asm_mcp_", dir=ROOT / "artifacts") as tmp:
        out = Path(tmp)
        log_path = ROOT / "artifacts" / "mcp_blender_fixture.log"
        with log_path.open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                [
                    options.blender,
                    "--background",
                    "--factory-startup",
                    "--python-exit-code",
                    "1",
                    "--python",
                    str(ROOT / "tests" / "mcp_blender_fixture.py"),
                    "--",
                    str(out),
                ],
                stdout=log,
                stderr=subprocess.STDOUT,
                env=dict(
                    os.environ,
                    TMP=str(out),
                    TEMP=str(out),
                    TMPDIR=str(out),
                    BLENDER_USER_CONFIG=str(out),
                    ASM_RUNTIME_DIR=str(out / "connection"),
                ),
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            try:
                deadline = time.monotonic() + 15
                while not (out / "ready.json").exists():
                    if process.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError(
                            "Blender fixture did not start; inspect " + str(log_path)
                        )
                    time.sleep(0.1)
                asyncio.run(asyncio.wait_for(exercise(out, process), 30))
            finally:
                (out / "stop").touch()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    process.wait(timeout=3)
    report = {
        "checks_passed": len(checks),
        "checks": checks,
        "scope": "Real MCP SDK stdio client/server and real headless Blender; built-in annotation connection",
    }
    (ROOT / "artifacts" / "mcp_read_test_report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
