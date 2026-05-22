from shdpa.eval.metrics import score_incident, aggregate
from shdpa.models import Incident, GroundTruth, GroundTruthFix


def _make(predicted_class, gt_class, fix_kind_pred, fix_kind_gt, diff="", must=()):
    i = Incident(
        predicted_class=predicted_class,
        proposed_fix_kind=fix_kind_pred,
        proposed_fix_diff=diff,
        ground_truth=GroundTruth(
            failure_class=gt_class,
            root_cause_summary="",
            fix=GroundTruthFix(
                kind=fix_kind_gt,
                must_include_strings=list(must),
            ),
        ),
    )
    return i


def test_retry_class_match_is_resolved():
    i = _make("upstream_5xx", "upstream_5xx", "retry", "retry")
    s = score_incident(i)
    assert s.resolved


def test_code_patch_needs_must_include():
    i = _make(
        "schema_drift",
        "schema_drift",
        "code_patch",
        "code_patch",
        diff="+ priority\n- o_priority\n",
        must=["o_priority", "priority"],
    )
    s = score_incident(i)
    assert s.resolved


def test_code_patch_missing_string_fails():
    i = _make(
        "schema_drift",
        "schema_drift",
        "code_patch",
        "code_patch",
        diff="+ x\n",
        must=["o_priority", "priority"],
    )
    s = score_incident(i)
    assert not s.resolved


def test_aggregate_macro_f1_perfect():
    items = []
    for cls in ("schema_drift", "upstream_5xx", "oom"):
        items.append(_make(cls, cls, "code_patch", "code_patch", "+x\n", ["x"]))
    scores = [score_incident(i) for i in items]
    a = aggregate(scores)
    assert a.class_accuracy == 1.0
    assert 0.9 <= a.macro_f1 <= 1.0


def test_sandbox_failure_is_hallucinated():
    i = _make(
        "schema_drift",
        "schema_drift",
        "code_patch",
        "code_patch",
        diff="+ x\n",
        must=["o_priority", "priority"],
    )
    i.error = "guardrail: sandbox_validation_failed: compilation failed with code 1"
    s = score_incident(i)
    assert not s.resolved
    assert s.hallucinated
