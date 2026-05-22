import pytest
from shdpa.agent.guardrails import Guardrails, GuardrailViolation
from shdpa.models import Action


def test_forbidden_path_blocks():
    g = Guardrails()
    a = Action(kind="pr")
    with pytest.raises(GuardrailViolation) as e:
        g.check_action(
            a,
            predicted_class="schema_drift",
            confidence=0.9,
            diff="--- a/infra/main.tf\n+++ b/infra/main.tf\n",
            files_changed=["infra/main.tf"],
        )
    assert "forbidden_path" in str(e.value)


def test_blast_radius_files_blocks():
    g = Guardrails(max_files_touched=2)
    a = Action(kind="pr")
    with pytest.raises(GuardrailViolation):
        g.check_action(
            a,
            predicted_class="schema_drift",
            confidence=0.9,
            diff="",
            files_changed=["a.sql", "b.sql", "c.sql"],
        )


def test_destructive_op_blocks():
    g = Guardrails()
    a = Action(kind="pr")
    diff = "--- a/x.sql\n+++ b/x.sql\n+DROP TABLE orders;\n"
    with pytest.raises(GuardrailViolation) as e:
        g.check_action(
            a, predicted_class="schema_drift", confidence=0.95, diff=diff, files_changed=["x.sql"]
        )
    assert "destructive_op" in str(e.value)


def test_low_confidence_blocks_non_pr_action():
    g = Guardrails()
    a = Action(kind="retry")
    with pytest.raises(GuardrailViolation) as e:
        g.check_action(
            a, predicted_class="upstream_5xx", confidence=0.4, diff=None, files_changed=[]
        )
    assert "low_confidence" in str(e.value)


def test_pr_kind_bypasses_whitelist():
    """PR is allowed even for non-whitelisted classes (humans gate the merge)."""
    g = Guardrails()
    a = Action(kind="pr")
    g.check_action(
        a, predicted_class="auth_expiry", confidence=0.6, diff="", files_changed=["x.sql"]
    )
