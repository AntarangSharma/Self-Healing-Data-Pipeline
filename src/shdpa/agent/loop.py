"""The agent loop.

Plain function-calling, ~150 LOC, defensible in interviews:
  triage  →  diagnose  →  plan  →  guardrails  →  act  →  report

We deliberately avoid LangGraph for v0. Migration trigger:
  - durable state between calls (resume after crash), OR
  - parallel tool branches.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import structlog

from shdpa.agent.guardrails import (
    AUTO_FIX_WHITELIST,
    Guardrails,
    GuardrailViolation,
)
from shdpa.agent.prompts import load_prompt
from shdpa.llm.provider import LLMProvider, get_provider
from shdpa.middleware.cost_meter import CostBudgetExceeded, CostMeter
from shdpa.models import Action, Incident, LLMCall
from shdpa.tools.registry import ToolRegistry

log = structlog.get_logger()


def _build_registry() -> ToolRegistry:
    from shdpa.tools import git_diff, logs, pr, schema_diff
    reg = ToolRegistry()
    reg.register(logs.TOOL)
    reg.register(schema_diff.TOOL)
    reg.register(git_diff.TOOL)
    reg.register(pr.TOOL)
    return reg


def _triage(incident: Incident, llm: LLMProvider, meter: CostMeter) -> None:
    system = load_prompt("triage")
    user_parts = [
        f"exception_type: {incident.exception_type or 'unknown'}",
        f"exception_message: {incident.exception_message or ''}",
        "log (tail 80):",
        "\n".join(incident.log_text.splitlines()[-80:]),
    ]
    data, resp = llm.complete_json(
        system=system,
        user="\n".join(user_parts),
        schema_hint='Required keys: failure_class, confidence, rationale.',
        purpose="triage",
        max_tokens=256,
    )
    meter.record(resp)
    incident.llm_calls.append(LLMCall(
        model=resp.model, provider=resp.provider,
        prompt_tokens=resp.prompt_tokens, completion_tokens=resp.completion_tokens,
        cost_usd=resp.cost_usd, latency_ms=resp.latency_ms, purpose="triage",
    ))
    incident.predicted_class = data.get("failure_class", "unknown") or "unknown"
    incident.predicted_class_confidence = float(data.get("confidence", 0.0) or 0.0)


def _diagnose(
    incident: Incident,
    llm: LLMProvider,
    meter: CostMeter,
    registry: ToolRegistry,
    *,
    must_include_hint: list[str] | None = None,
    attempt: int = 1,
) -> dict:
    # Call schema_diff and (if repo) git_diff up-front; let the LLM see results.
    schema_summary = ""
    schema_data = None
    if incident.schema_before or incident.schema_after:
        r = registry.call(
            "diff_schema", incident,
            schema_before=incident.schema_before,
            schema_after=incident.schema_after,
        )
        schema_summary = r.summary
        schema_data = r.data

    diff_summary = ""
    if incident.repo_path and Path(incident.repo_path).exists():
        r = registry.call("get_recent_diff", incident, repo_path=incident.repo_path)
        if r.ok and r.data:
            diff_summary = r.data[:2000]

    # Inject schema_diff inferred renames into the prompt as a strong hint
    rename_hint = ""
    if schema_data and schema_data.get("renames"):
        rn = schema_data["renames"][0]
        rename_hint = (
            f'\nSchema diff inferred a likely rename: {rn["from"]} → {rn["to"]} '
            f'in table {rn["table"]}. '
            f'"missing_column": "{rn["from"]}", "suggested_column": "{rn["to"]}".'
        )

    system = load_prompt("diagnose")
    # listing of repo files (helps the model propose patches to the right path)
    repo_files: list[str] = []
    if incident.repo_path and Path(incident.repo_path).exists():
        for p_ in Path(incident.repo_path).rglob("*"):
            if p_.is_file() and p_.suffix in {".sql", ".py", ".txt", ".yml", ".yaml"}:
                repo_files.append(str(p_.relative_to(incident.repo_path)))

    hint_block = ""
    if must_include_hint:
        hint_block = (
            "must_include_strings_hint: "
            + str(must_include_hint)
            + "  (your patches MUST produce a diff containing every one of these tokens)"
        )

    user = "\n\n".join([
        f"failure_class: {incident.predicted_class}",
        f"triage_confidence: {incident.predicted_class_confidence:.2f}",
        f"dag_id: {incident.dag_id}",
        f"task_id: {incident.task_id}",
        f"exception_type: {incident.exception_type or ''}",
        f"exception_message: {incident.exception_message or ''}",
        f"repo_files: {repo_files}",
        f"log (tail 60):\n" + "\n".join(incident.log_text.splitlines()[-60:]),
        f"schema_diff_summary: {schema_summary}{rename_hint}",
        f"git_diff (truncated):\n{diff_summary}" if diff_summary else "",
        hint_block,
    ])
    purpose = "diagnose" if attempt == 1 else f"diagnose_retry_{attempt}"
    data, resp = llm.complete_json(
        system=system, user=user, purpose=purpose, max_tokens=600,
    )
    meter.record(resp)
    incident.llm_calls.append(LLMCall(
        model=resp.model, provider=resp.provider,
        prompt_tokens=resp.prompt_tokens, completion_tokens=resp.completion_tokens,
        cost_usd=resp.cost_usd, latency_ms=resp.latency_ms, purpose=purpose,
    ))
    # update confidence if diagnose returned one
    if "confidence" in data:
        try:
            incident.predicted_class_confidence = max(
                incident.predicted_class_confidence, float(data["confidence"])
            )
        except (TypeError, ValueError):
            pass
    incident.root_cause_summary = (data.get("root_cause") or "")[:280]
    return data


def _plan_files(incident: Incident, diagnosis: dict) -> tuple[dict[str, str], str]:
    """Build {filepath: new_content} from the diagnosis.

    Supports two diagnosis shapes:
      1) sql_replace: {find, replace}  -- rewrite all *.sql files in the repo.
      2) patches: [{kind, file, text?, find?, replace?}]
         kind in {sql_replace, sql_remove, prepend, append, create}
    """
    files: dict[str, str] = {}
    diff_text = ""

    if not incident.repo_path:
        return files, diff_text
    repo = Path(incident.repo_path)
    if not repo.exists():
        return files, diff_text

    NL = chr(10)

    def emit_diff(rel: str, before: str, after: str) -> None:
        nonlocal diff_text
        diff_text += "--- a/" + rel + NL + "+++ b/" + rel + NL
        b_lines = before.splitlines()
        a_lines = after.splitlines()
        max_len = max(len(b_lines), len(a_lines))
        for i in range(max_len):
            bl = b_lines[i] if i < len(b_lines) else None
            al = a_lines[i] if i < len(a_lines) else None
            if bl is None and al is not None:
                diff_text += "+" + al + NL
            elif al is None and bl is not None:
                diff_text += "-" + bl + NL
            elif bl != al:
                diff_text += "-" + (bl or "") + NL + "+" + (al or "") + NL

    def _ci_replace(src: str, find: str, replace: str) -> tuple[str, bool]:
        """Case-insensitive find/replace.

        SQL keywords are conventionally lowercase in our fixtures but LLMs
        love to emit uppercase. We match case-insensitively but preserve
        the *replacement* string exactly as the model produced it (the
        model is responsible for matching surrounding conventions).
        Returns (new_text, changed).
        """
        new, n = re.subn(re.escape(find), lambda _m: replace, src, flags=re.IGNORECASE)
        return new, n > 0

    def _ci_contains(src: str, needle: str) -> bool:
        return re.search(re.escape(needle), src, flags=re.IGNORECASE) is not None

    sql_replace = diagnosis.get("sql_replace") or {}
    find_top = sql_replace.get("find")
    replace_top = sql_replace.get("replace")
    if find_top and replace_top:
        for sql_file in repo.rglob("*.sql"):
            text = sql_file.read_text(encoding="utf-8", errors="replace")
            new, changed = _ci_replace(text, find_top, replace_top)
            if changed:
                rel = str(sql_file.relative_to(repo))
                files[rel] = new
                emit_diff(rel, text, new)

    for patch in diagnosis.get("patches") or []:
        kind = patch.get("kind")
        rel = patch.get("file", "")
        text = patch.get("text", "")
        find_p = patch.get("find")
        replace_p = patch.get("replace")

        if kind == "sql_replace" and find_p and replace_p:
            for sql_file in repo.rglob("*.sql"):
                src = sql_file.read_text(encoding="utf-8", errors="replace")
                new, changed = _ci_replace(src, find_p, replace_p)
                if changed:
                    relp = str(sql_file.relative_to(repo))
                    files[relp] = new
                    emit_diff(relp, src, new)

        elif kind == "sql_remove" and find_p:
            for sql_file in repo.rglob("*.sql"):
                src = sql_file.read_text(encoding="utf-8", errors="replace")
                if _ci_contains(src, find_p):
                    kept = [ln for ln in src.splitlines() if not _ci_contains(ln, find_p)]
                    new = NL.join(kept)
                    relp = str(sql_file.relative_to(repo))
                    files[relp] = new
                    emit_diff(relp, src, new)

        elif kind == "prepend" and rel:
            target = repo / rel
            src = target.read_text(encoding="utf-8") if target.exists() else ""
            new = text + src
            files[rel] = new
            emit_diff(rel, src, new)

        elif kind == "append" and rel:
            target = repo / rel
            src = target.read_text(encoding="utf-8") if target.exists() else ""
            new = src + text
            files[rel] = new
            emit_diff(rel, src, new)

        elif kind == "create" and rel:
            target = repo / rel
            if not target.exists():
                files[rel] = text
                emit_diff(rel, "", text)
            else:
                src = target.read_text(encoding="utf-8")
                if text not in src:
                    new = src + text
                    files[rel] = new
                    emit_diff(rel, src, new)

    return files, diff_text


def _make_pr(
    incident: Incident,
    diagnosis: dict,
    registry: ToolRegistry,
    files: dict[str, str],
    diff_text: str,
) -> Action:
    branch = f"shdpa/fix-{incident.id.hex[:8]}"
    title = f"[shdpa] fix: {diagnosis.get('root_cause', 'pipeline failure')[:64]}"
    must_include = diagnosis.get("must_include_strings") or []
    body_lines = [
        f"**Detected class:** `{incident.predicted_class}` "
        f"(confidence {incident.predicted_class_confidence:.2f})",
        "",
        f"**Root cause:** {diagnosis.get('root_cause', 'n/a')}",
        "",
        f"**Fix kind:** `{diagnosis.get('fix_kind', 'noop')}`",
        "",
        "**Must include strings:** " + ", ".join(f"`{s}`" for s in must_include),
        "",
        "**Diff preview:**",
        "```diff",
        diff_text[:4000],
        "```",
        "",
        "_Generated by Self-Healing Data Pipeline Agent. Reviewer keeps merge rights._",
    ]
    body = "\n".join(body_lines)

    if not files:
        return Action(kind="noop", payload={"reason": "no file changes produced"}, dry_run=True)

    r = registry.call(
        "open_pr",
        incident,
        repo_path=incident.repo_path,
        branch=branch,
        title=title,
        body=body,
        files=files,
    )
    return Action(
        kind="pr" if r.ok else "noop",
        payload=r.data or {"error": r.error},
        dry_run=False,
        executed_at=None,
    )


def run_agent(
    incident: Incident,
    *,
    llm: LLMProvider | None = None,
    meter: CostMeter | None = None,
    guardrails: Guardrails | None = None,
) -> Incident:
    t0 = time.time()
    llm = llm or get_provider()
    meter = meter or CostMeter()
    meter.reset_incident()
    guardrails = guardrails or Guardrails()
    registry = _build_registry()

    try:
        _triage(incident, llm, meter)
        # Diagnose is required to produce structured patches. Special cases:
        #   - upstream_5xx: short-circuit to retry (no patches needed).
        #   - unknown: triage couldn't classify with confidence; do NOT
        #     guess a fix. Skip diagnose, emit a noop with full context so a
        #     human can pick it up. This is deliberate: silently auto-fixing
        #     an unknown failure is exactly how an agent causes an outage.
        if incident.predicted_class == "upstream_5xx":
            diagnosis = {"fix_kind": "retry", "root_cause": "transient upstream 5xx"}
        elif incident.predicted_class == "unknown":
            diagnosis = {
                "fix_kind": "noop",
                "root_cause": (
                    "triage could not classify failure with confidence; "
                    "escalating to human review."
                ),
            }
        else:
            diagnosis = _diagnose(incident, llm, meter, registry)

        # Regenerate-on-incomplete loop:
        # If diagnose declared `must_include_strings` but the resulting diff
        # doesn't contain them, re-prompt with that explicit hint. Cap at 3
        # total attempts so cost stays bounded. This catches LLMs that produce
        # a structurally correct patch missing required tokens (the #1 failure
        # mode for idempotency / null_spike in the v2 prompt set).
        max_attempts = 3
        files, diff_text = _plan_files(incident, diagnosis)
        if diagnosis.get("fix_kind") == "code_patch":
            for attempt in range(2, max_attempts + 1):
                required = [
                    s for s in (diagnosis.get("must_include_strings") or [])
                    if s
                ]
                if not required:
                    break
                missing = [
                    s for s in required
                    if s.lower() not in diff_text.lower()
                ]
                if not missing:
                    break
                # Re-prompt with the missing tokens as a hard requirement.
                diagnosis = _diagnose(
                    incident, llm, meter, registry,
                    must_include_hint=missing,
                    attempt=attempt,
                )
                files, diff_text = _plan_files(incident, diagnosis)

        incident.proposed_fix_kind = diagnosis.get("fix_kind", "noop")
        incident.proposed_fix_diff = diff_text
        incident.proposed_files_changed = list(files.keys())

        # Build action
        action = _make_pr(incident, diagnosis, registry, files, diff_text)

        # Guardrail check (even for PR — guards against forbidden_paths etc.)
        try:
            guardrails.check_action(
                action,
                predicted_class=incident.predicted_class,
                confidence=incident.predicted_class_confidence,
                diff=diff_text,
                files_changed=list(files.keys()),
            )
        except GuardrailViolation as gv:
            action.blocked_by_guardrail = gv.rule
            action.kind = "noop"
            action.payload = {"reason": str(gv), "would_have_been": "pr"}

        incident.actions.append(action)
        incident.resolved = action.kind == "pr"
        incident.resolution_kind = (
            "auto" if (action.kind == "pr"
                       and incident.predicted_class in AUTO_FIX_WHITELIST
                       and incident.predicted_class_confidence >= 0.85)
            else "pr" if action.kind == "pr"
            else "unresolved"
        )
    except CostBudgetExceeded as e:
        incident.error = f"cost_budget: {e}"
        incident.resolved = False
        incident.resolution_kind = "unresolved"
    except Exception as e:  # noqa: BLE001
        incident.error = f"agent_error: {e!r}"
        incident.resolved = False
        incident.resolution_kind = "unresolved"

    incident.total_cost_usd = sum(c.cost_usd for c in incident.llm_calls)
    incident.total_latency_s = time.time() - t0
    return incident
