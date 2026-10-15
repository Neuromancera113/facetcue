"""Export schemas from the actual native MCP server, rather than a separate draft."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from agent_mcp.server import build_server


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="Fail on schema drift without writing files"
    )
    options = parser.parse_args()
    tools = await build_server().list_tools()
    path = root / "contracts" / "live_mcp_tools.json"
    content = (
        json.dumps(
            {"tools": [t.model_dump(mode="json", exclude_none=True) for t in tools]},
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    if options.check:
        if not path.exists() or path.read_text(encoding="utf-8") != content:
            raise SystemExit(
                "MCP contract changed: run python scripts/export_mcp_catalog.py and review it"
            )
    else:
        path.parent.mkdir(exist_ok=True)
        path.write_text(content, encoding="utf-8")
    print(path)


asyncio.run(main())
