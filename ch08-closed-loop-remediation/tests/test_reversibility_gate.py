"""The gate's contract: tier baseline + per-call upgrades + ceiling refusal."""

from remediator.reversibility import (
    GateDecision,
    Reversibility,
    evaluate,
    reversibility,
)


@reversibility(Reversibility.REVERSIBLE)
def fake_handler(params, ctx):
    pass


def test_baseline_proceeds_when_call_site_clean():
    decision = evaluate(
        fake_handler, {"replicas": 3, "has_readiness_probe": True}
    )
    assert decision.proceed
    assert decision.tier == Reversibility.REVERSIBLE


def test_low_replicas_upgrades_to_recoverable():
    decision = evaluate(
        fake_handler, {"replicas": 1, "has_readiness_probe": True}
    )
    assert decision.tier == Reversibility.RECOVERABLE
    assert decision.proceed  # ceiling default is RECOVERABLE


def test_missing_readiness_upgrades():
    decision = evaluate(
        fake_handler, {"replicas": 3, "has_readiness_probe": False}
    )
    assert decision.tier == Reversibility.RECOVERABLE


def test_stateful_upgrades_to_irreversible_and_refuses():
    decision = evaluate(
        fake_handler, {"replicas": 3, "has_readiness_probe": True, "stateful": True}
    )
    assert decision.tier == Reversibility.IRREVERSIBLE
    assert not decision.proceed
    assert decision.requires_human


def test_ceiling_lower_than_baseline_refuses():
    decision = evaluate(
        fake_handler,
        {"replicas": 3, "has_readiness_probe": True},
        autonomy_ceiling=Reversibility.REVERSIBLE,
    )
    # Realized REVERSIBLE within REVERSIBLE ceiling → proceeds.
    assert decision.proceed

    decision2 = evaluate(
        fake_handler,
        {"replicas": 1, "has_readiness_probe": True},
        autonomy_ceiling=Reversibility.REVERSIBLE,
    )
    # Realized RECOVERABLE exceeds REVERSIBLE ceiling → refused, requires human.
    assert not decision2.proceed
    assert decision2.requires_human


def test_undecorated_handler_is_irreversible():
    def naked(params, ctx):
        pass

    decision = evaluate(naked, {})
    assert decision.tier == Reversibility.IRREVERSIBLE
    assert not decision.proceed
