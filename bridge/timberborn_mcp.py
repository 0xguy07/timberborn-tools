#!/usr/bin/env python3
"""Timberborn bridge - an MCP server that reads .timber saves.

Stdlib only, no pip install. Speaks MCP over stdio (newline-delimited JSON-RPC).

    python3 timberborn_mcp.py

Set TIMBERBORN_DIR to override the save folder (default ~/Documents/Timberborn).
"""

import json
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import tb_reports as R          # noqa: E402
import tb_save                  # noqa: E402

VERSION = "0.1.0"

SAVE_ARGS = {
    "save": {"type": "string", "description":
             "Save name, partial name, or full path. Omit for the most recent save."},
    "settlement": {"type": "string", "description":
                   "Limit the search to one settlement folder, e.g. 'Denniston Easy'."},
}


def _tool(name, desc, props=None, required=None, with_save=True):
    p = dict(SAVE_ARGS) if with_save else {}
    p.update(props or {})
    return {
        "name": name,
        "description": desc,
        "inputSchema": {"type": "object", "properties": p, "required": required or []},
    }


TOOLS = [
    _tool("list_saves",
          "List every Timberborn save on disk, newest first, with settlement, file "
          "size and modification time. Start here when unsure which save to read.",
          {"settlement": SAVE_ARGS["settlement"]}, with_save=False),
    _tool("overview",
          "Settlement summary: cycle and day, current weather, population by type, "
          "the district list, drought history and lifetime statistics."),
    _tool("district_report",
          "Per district: population, housing capacity and occupancy, filled vs open "
          "jobs (with the list of understaffed buildings), average need satisfaction, "
          "and this cycle's production/consumption per good.",
          {"district": {"type": "string", "description":
                        "District name or partial name. Omit for all districts."}}),
    _tool("food_water_report",
          "Food and water balance per district and settlement-wide: stock, capacity, "
          "measured production and consumption per day, days of buffer left, plus "
          "drought exposure and the state of the map's water, dams and floodgates.",
          {"district": {"type": "string"},
           "days": {"type": "integer", "description":
                    "How many recent days to average rates over (default 10)."}}),
    _tool("water_report",
          "Just the map's water: stored volume, contamination share, volume by floor "
          "height, deepest columns, water sources and floodgate settings."),
    _tool("power_report",
          "Generators by type and district with nominal ratings, transmission and "
          "battery inventory, and the buildings with the lowest actual productivity "
          "(the real signal for power or input starvation)."),
    _tool("logistics_report",
          "Hauling posts and district crossings with staffing and cargo, every storage "
          "building and what it is allocated to, workplaces furthest from storage, and "
          "each district's import/export policy.",
          {"district": {"type": "string"}}),
    _tool("workplace_report",
          "Every workplace ranked by yesterday's productivity (work done vs work "
          "possible), with staffing, priority and held goods.",
          {"district": {"type": "string"},
           "limit": {"type": "integer", "description": "Rows to return (default 60)."}}),
    _tool("construction_report",
          "Unfinished buildings: what they are, where, build progress, materials "
          "delivered so far, and how well the builders' huts are staffed."),
    _tool("find_buildings",
          "Find buildings whose template or name matches a string, with location, "
          "staffing, contents and district.",
          {"query": {"type": "string", "description": "e.g. 'Warehouse', 'Pump', 'Lodge'."},
           "limit": {"type": "integer"}},
          required=["query"]),
    _tool("good_history",
          "Day-by-day stock, capacity, production and consumption for one good, from "
          "the game's own sampling registry. Use this for trends.",
          {"good": {"type": "string", "description": "e.g. 'Water', 'Bread', 'Log'."},
           "district": {"type": "string"},
           "days": {"type": "integer", "description": "Days back (default 40)."}},
          required=["good"]),
    _tool("raw",
          "Escape hatch: walk the save's singleton JSON by dotted path, e.g. "
          "'Singletons.WindService'. Large values are summarised; descend to see them.",
          {"path": {"type": "string"}}),
]


def call(name, args):
    if name == "list_saves":
        rows = tb_save.list_saves(args.get("settlement"))
        if not rows:
            return "No saves found under %s" % tb_save.saves_root()
        import datetime
        out = ["| settlement | save | when | MB |", "|---|---|---|---|"]
        for r in rows[:60]:
            out.append("| %s | %s | %s | %.1f |" % (
                r["settlement"], r["save"],
                datetime.datetime.fromtimestamp(r["mtime"]).strftime("%Y-%m-%d %H:%M"),
                r["bytes"] / 1e6))
        return "\n".join(out)

    s = tb_save.load(args.get("save"), args.get("settlement"))
    header = "_source: %s / %s (cycle %s day %s)_\n\n" % (
        s.settlement, s.name,
        s.singletons.get("GameCycleService", {}).get("Cycle"),
        s.singletons.get("GameCycleService", {}).get("CycleDay"))

    if name == "overview":
        body = R.overview(s)
    elif name == "district_report":
        body = R.districts(s, args.get("district"))
    elif name == "food_water_report":
        body = R.food_water(s, args.get("district"), int(args.get("days") or 10))
    elif name == "water_report":
        body = R.reservoir(s)
    elif name == "power_report":
        body = R.power(s)
    elif name == "logistics_report":
        body = R.logistics(s, args.get("district"))
    elif name == "workplace_report":
        body = R.workplaces(s, args.get("district"), int(args.get("limit") or 60))
    elif name == "construction_report":
        body = R.construction(s)
    elif name == "find_buildings":
        body = R.find_buildings(s, args["query"], int(args.get("limit") or 60))
    elif name == "good_history":
        body = R.good_history(s, args["good"], args.get("district"), int(args.get("days") or 40))
    elif name == "raw":
        body = R.raw(s, args.get("path", ""))
    else:
        raise ValueError("unknown tool %r" % name)
    return header + body


def main():
    out = sys.stdout
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}

        if method == "initialize":
            result = {
                "protocolVersion": params.get("protocolVersion", "2024-11-05"),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "timberborn", "version": VERSION},
            }
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            try:
                text = call(params.get("name"), params.get("arguments") or {})
                result = {"content": [{"type": "text", "text": text}]}
            except Exception:
                result = {"content": [{"type": "text", "text": traceback.format_exc()}],
                          "isError": True}
        elif method == "ping":
            result = {}
        elif method and method.startswith("notifications/"):
            continue
        else:
            if mid is not None:
                out.write(json.dumps({"jsonrpc": "2.0", "id": mid,
                                      "error": {"code": -32601,
                                                "message": "method not found: %s" % method}}) + "\n")
                out.flush()
            continue

        if mid is not None:
            out.write(json.dumps({"jsonrpc": "2.0", "id": mid, "result": result}) + "\n")
            out.flush()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--selftest":
        try:
            s = tb_save.load(sys.argv[2] if len(sys.argv) > 2 else None)
        except FileNotFoundError as e:
            sys.exit("timberborn bridge: %s" % e)
        for fn in (R.overview, R.districts, R.food_water, R.power, R.logistics,
                   R.workplaces, R.construction, R.reservoir):
            print("\n" + "=" * 70 + "\n" + fn.__name__ + "\n")
            print(fn(s))
        sys.exit(0)
    main()
