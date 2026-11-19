"""Onboarding eligibility policies: a single source of truth for gates and the final verdict.

Policies (from the tool contracts):
  POL-ID-01   Identity must be verified by the civil registry.
  POL-ID-02   Identity confidence must be >= 0.8; below that, escalate.
  POL-RISK-01 Risk level must not be "high"; high risk, escalate.
  POL-RISK-02 Medium risk is allowed, but requires enhanced due diligence (a condition, not a failure).

Verdict:
  apto           every policy evaluated and passed (possibly with conditions).
  no_apto        at least one policy failed; per policy the case goes to human review.
  no_determinado the flow could not evaluate the policies (technical failure). It is
                 never reported as "no_apto": an outage is not a reason to reject a client.

Every verdict carries `proposed_solutions` (see remediation.py) for each failure or ambiguity.
"""

from dataclasses import asdict, dataclass
from enum import Enum

from .remediation import propose_solutions
from .state import OnboardingState, Status
from .tools import CONFIDENCE_THRESHOLD


class Verdict(str, Enum):
    APTO = "apto"
    NO_APTO = "no_apto"
    NO_DETERMINADO = "no_determinado"


@dataclass(frozen=True)
class PolicyCheck:
    policy_id: str
    description: str
    passed: bool
    reason_code: str  # used as the escalation reason when the check fails
    observed: dict


POLICY_CATALOG: dict[str, str] = {
    "POL-ID-01": "Identidad verificada en el registro civil",
    "POL-ID-02": f"Confianza de identidad >= {CONFIDENCE_THRESHOLD}",
    "POL-RISK-01": "Nivel de riesgo distinto de alto",
}


def check_identity(result: dict) -> list[PolicyCheck]:
    return [
        PolicyCheck(
            "POL-ID-01",
            POLICY_CATALOG["POL-ID-01"],
            passed=result["verified"],
            reason_code="identity_not_verified",
            observed={"verified": result["verified"]},
        ),
        PolicyCheck(
            "POL-ID-02",
            POLICY_CATALOG["POL-ID-02"],
            passed=result["confidence"] >= CONFIDENCE_THRESHOLD,
            reason_code="identity_low_confidence",
            observed={"confidence": result["confidence"], "threshold": CONFIDENCE_THRESHOLD},
        ),
    ]


def check_risk(result: dict) -> list[PolicyCheck]:
    return [
        PolicyCheck(
            "POL-RISK-01",
            POLICY_CATALOG["POL-RISK-01"],
            passed=result["risk_level"] != "high",
            reason_code="high_risk",
            observed={"risk_level": result["risk_level"], "matches": result["matches"]},
        )
    ]


def decide(state: OnboardingState) -> dict:
    """Final eligibility verdict, derived only from the recorded policy checks and case status."""
    checks = state.policy_checks
    failed = [c for c in checks if not c["passed"]]
    evaluated = {c["policy_id"] for c in checks}
    not_evaluated = [pid for pid in POLICY_CATALOG if pid not in evaluated]

    conditions = []
    if state.flags["enhanced_due_diligence"]:
        conditions.append("POL-RISK-02: debida diligencia reforzada (riesgo medio)")
    if state.flags["pep"]:
        conditions.append("Presentar declaración de Persona Expuesta Políticamente")

    if failed:
        verdict, review = Verdict.NO_APTO, True
        summary = "No apto: incumple " + ", ".join(f"{c['policy_id']} ({c['description']})" for c in failed)
        summary += ". Se escala a revisión humana."
    elif state.status is Status.COMPLETED and not not_evaluated:
        verdict, review = Verdict.APTO, False
        summary = "Apto: cumple todas las políticas" + (" con condiciones." if conditions else ".")
    else:
        verdict, review = Verdict.NO_DETERMINADO, True
        reason = (state.escalation or {}).get("reason", "unknown")
        summary = f"No determinado: el flujo no pudo evaluar las políticas ({reason}). Se escala a revisión humana."

    return {
        "verdict": verdict.value,
        "requires_human_review": review,
        "summary": summary,
        "failed_policies": [c["policy_id"] for c in failed],
        "not_evaluated_policies": not_evaluated,
        "conditions": conditions,
        "proposed_solutions": propose_solutions(state),
        "checks": checks,
    }


def as_dict(check: PolicyCheck) -> dict:
    return asdict(check)
