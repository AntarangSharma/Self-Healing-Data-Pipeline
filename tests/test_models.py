from shdpa.models import Incident, GroundTruth, GroundTruthFix


def test_incident_default_fields():
    i = Incident()
    assert i.id is not None
    assert i.resolved is False
    assert i.predicted_class is None


def test_ground_truth_roundtrip():
    gt = GroundTruth(
        failure_class="schema_drift",
        root_cause_summary="renamed",
        fix=GroundTruthFix(kind="code_patch", files_changed=["a.sql"], must_include_strings=["x"]),
        severity="P2",
        auto_fixable=True,
    )
    assert gt.fix.kind == "code_patch"
    assert "x" in gt.fix.must_include_strings
