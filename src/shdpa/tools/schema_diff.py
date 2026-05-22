"""Schema diff tool. Diffs information_schema-shaped JSON before/after."""

from __future__ import annotations

from typing import Any

from shdpa.tools.registry import Tool, ToolResult


def _columns(schema: dict[str, Any], table: str) -> dict[str, str]:
    """Return {column_name: data_type} for `table`."""
    if not schema:
        return {}
    if table in schema:
        cols = schema[table]
    elif "tables" in schema and table in schema["tables"]:
        cols = schema["tables"][table]
    else:
        return {}
    if isinstance(cols, list):
        return {c if isinstance(c, str) else c.get("name", ""): "unknown" for c in cols}
    return dict(cols)


def _diff_schema(
    schema_before: dict[str, Any],
    schema_after: dict[str, Any],
    table: str = "",
) -> ToolResult:
    tables = set(schema_before) | set(schema_after)
    if table:
        tables = {table}
    additions: list[str] = []
    removals: list[str] = []
    renames: list[tuple[str, str, str]] = []  # (table, removed, added) heuristic
    retypes: list[tuple[str, str, str, str]] = []

    for t in tables:
        before = _columns(schema_before, t)
        after = _columns(schema_after, t)
        added = sorted(set(after) - set(before))
        removed = sorted(set(before) - set(after))
        for c in added:
            additions.append(f"{t}.{c}")
        for c in removed:
            removals.append(f"{t}.{c}")
        # naive rename inference: pair similar columns (one removed, one added)
        if len(added) == 1 and len(removed) == 1:
            renames.append((t, removed[0], added[0]))
        # retype
        for c in set(before) & set(after):
            if before[c] != after[c]:
                retypes.append((t, c, before[c], after[c]))

    parts = []
    if additions:
        parts.append(f"added: {additions}")
    if removals:
        parts.append(f"removed: {removals}")
    if renames:
        parts.append("likely renames: " + ", ".join(f"{t}.{r}->{a}" for t, r, a in renames))
    if retypes:
        parts.append("retyped: " + ", ".join(f"{t}.{c} {b}->{a}" for t, c, b, a in retypes))
    summary = "; ".join(parts) or "no schema differences"

    return ToolResult(
        ok=True,
        summary=summary,
        data={
            "added": additions,
            "removed": removals,
            "renames": [{"table": t, "from": r, "to": a} for t, r, a in renames],
            "retypes": [{"table": t, "column": c, "from": b, "to": a} for t, c, b, a in retypes],
        },
    )


TOOL = Tool(
    name="diff_schema",
    description="Diff information_schema-shaped JSON snapshots; infer adds/removes/renames/retypes.",
    schema={
        "type": "object",
        "properties": {
            "schema_before": {"type": "object"},
            "schema_after": {"type": "object"},
            "table": {"type": "string"},
        },
        "required": ["schema_before", "schema_after"],
    },
    fn=_diff_schema,
)
