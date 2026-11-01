"""`mcp`: a read-only Model Context Protocol server over stdio, in the standard library. It writes nothing, and no tool can.

JSON-RPC 2.0, one message per line. Each tool takes an optional `project`: a folder or a plan file, default the folder the
server started in. For a coding agent that would rather call a tool than run a command.
"""
import json
import pathlib
import sys

from . import __version__, focus, forecast, gate, history, portfolio, render, report, table as tables, trace
from .discover import POINTER, find_plan
from .plan import Plan, PlanError

SUPPORTED = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
PROJECT = {"project": {"type": "string", "description": f"A project folder or a plan file. Default: found from the server's folder through {POINTER}."}}
OFFLINE = {"offline": {"type": "boolean", "description": "Do not call gh or glab; a pull request stays unverified."}}
READ_ONLY = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True}


def _tool(name, description, properties=None):
    return {"name": name, "description": description, "annotations": READ_ONLY,
            "inputSchema": {"type": "object", "properties": {**PROJECT, **(properties or {})}, "additionalProperties": False}}


TOOLS = [
    _tool("status", "Where the project stands: strict and weighted percent per group, the next workstream, what it needs."),
    _tool("rows", "The rows of the status table, optionally only the ones not yet at the strict kind.",
          {"open": {"type": "boolean", "description": "Only rows not yet at the strict kind."}}),
    _tool("evidence", "Every row with what it claims as evidence, and what git and gh say about each claim.", OFFLINE),
    _tool("check", "Run the gate: is the view true, do the counts sum, does each status have its evidence. Writes nothing.", OFFLINE),
    _tool("week", "What moved since a date, a span like '2 weeks', or a commit, from the table's git history. Default: 7 days.",
          {"since": {"type": "string"}}),
    _tool("eta", "When it will be done if the work goes on as it has: a line through the table's git history, with a range, the scope's effect and the deadline. Experimental: give a date only when asked when it will be done, quote its words, and say it is a line."),
    _tool("focus", "Where the recent commits went: on plan, upkeep or off plan, with the reason for each. A signal, never a gate.",
          {"days": {"type": "integer", "description": "How many days to read. Default: 14."}}),
    _tool("next", "What to work on now: the next workstream's open rows. Anything else is a change of scope, so say so before starting it."),
    _tool("matrix", "A traceability matrix: each requirement, the row that holds it, its evidence and the tests on record. A test listed exists; passing is CI's word.", OFFLINE),
    {"name": "portfolio", "description": "Every tracked project under a folder: strict, weighted, next, and the gate read offline.",
     "annotations": READ_ONLY,
     "inputSchema": {"type": "object", "properties": {"folder": {"type": "string", "description": "Default: the server's folder."}},
                     "additionalProperties": False}},
]


def _plan(arguments):
    project = arguments.get("project")
    if project:
        path = pathlib.Path(project).expanduser()
        if path.is_file():
            return Plan(path)
        found = find_plan(path)
    else:
        found = find_plan()
    if found is None:
        raise PlanError(f"no {POINTER} here or above: run `gitdone init`, or pass project")
    return Plan(found)


def _status(arguments):
    plan = _plan(arguments)
    table = tables.load_clean(plan)
    return {"line": render.opener(plan, table), **render.opener_data(plan, table), "view": str(plan.out), "table": str(plan.doc)}


def _rows(arguments):
    plan = _plan(arguments)
    table = tables.load_clean(plan)
    rows = [{"row": r.num, "name": r.name, "kind": r.kind, "note": r.note, "domain": d.name} for d in table.domains for r in d.rows]
    if arguments.get("open"):
        rows = [r for r in rows if r["kind"] != plan.strict_kind.name]
    return rows


HANDLERS = {
    "status": _status,
    "rows": _rows,
    "evidence": lambda a: report.rows_data(_plan(a), offline=bool(a.get("offline"))),
    "check": lambda a: gate.report(_plan(a), offline=bool(a.get("offline"))).data(),
    "week": lambda a: history.delta_data(_plan(a), since=a.get("since")),
    "portfolio": lambda a: portfolio.scan([a.get("folder") or "."]),
    "eta": lambda a: forecast.data(_plan(a)),
    "focus": lambda a: focus.data(_plan(a), days=_days(a)),
    "next": lambda a: focus.next_data(_plan(a)),
    "matrix": lambda a: trace.data(_plan(a), offline=bool(a.get("offline"))),
}


def _days(arguments):
    days = arguments.get("days")
    if days is None:
        return focus.WINDOW
    if isinstance(days, bool) or not isinstance(days, int):
        raise PlanError(f"days: expected a whole number, got {days!r}")
    return days


def _call(params):
    name = params.get("name") if isinstance(params, dict) else None
    arguments = (params.get("arguments") or {}) if isinstance(params, dict) else {}
    if not isinstance(name, str) or name not in HANDLERS:
        return {"isError": True, "content": [{"type": "text", "text": f"no tool is named {name!r}"}]}
    if not isinstance(arguments, dict):
        return {"isError": True, "content": [{"type": "text", "text": "arguments must be an object"}]}
    try:
        result = HANDLERS[name](arguments)
    except PlanError as err:
        return {"isError": True, "content": [{"type": "text", "text": str(err)}]}
    except Exception as err:  # one bad call must not end the server
        return {"isError": True, "content": [{"type": "text", "text": f"could not run: {type(err).__name__}: {err}"}]}
    return {"content": [{"type": "text", "text": json.dumps(result, indent=2, ensure_ascii=False)}]}


def handle(message):
    """The response to one message, or None for a notification."""
    method = message.get("method")
    identifier = message.get("id")
    if identifier is None:
        return None

    def answer(result):
        return {"jsonrpc": "2.0", "id": identifier, "result": result}
    if method == "initialize":
        params = message.get("params")
        wanted = params.get("protocolVersion") if isinstance(params, dict) else None
        return answer({"protocolVersion": wanted if wanted in SUPPORTED else SUPPORTED[0],
                       "capabilities": {"tools": {"listChanged": False}},
                       "serverInfo": {"name": "gitdone", "version": __version__},
                       "instructions": "Read-only status of a project tracked by gitdone. Every number traces to git. Writes nothing."})
    if method == "ping":
        return answer({})
    if method == "tools/list":
        return answer({"tools": TOOLS})
    if method == "tools/call":
        return answer(_call(message.get("params")))
    return {"jsonrpc": "2.0", "id": identifier, "error": {"code": -32601, "message": f"no method {method}"}}


def serve(stdin=None, stdout=None):
    stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
    for line in stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except ValueError:
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "not JSON"}}
        else:
            try:
                response = handle(message) if isinstance(message, dict) else {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "not a request"}}
            except Exception as err:  # one bad message must not end the server
                response = {"jsonrpc": "2.0", "id": message.get("id") if isinstance(message, dict) else None,
                            "error": {"code": -32603, "message": f"{type(err).__name__}: {err}"}}
        if response is not None:
            stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            stdout.flush()
    return 0
