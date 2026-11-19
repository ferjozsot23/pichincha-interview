import pytest

from onboarding_agent.llm import OfflineLLM, text_response, tool_use_response
from onboarding_agent.orchestrator import Orchestrator
from onboarding_agent.state import ClientProfile, Status


class ScriptedLLM(OfflineLLM):
    """OfflineLLM, except the first responses for a given tool are scripted (to simulate a misbehaving model)."""

    def __init__(self, scripts: dict[str, list] | None = None):
        self.scripts = {tool: list(responses) for tool, responses in (scripts or {}).items()}

    def converse(self, system, messages, tools):
        queue = self.scripts.get(tools[0]["name"])
        if queue and len(messages) == 1:  # only the agent's opening turn is scripted
            response = queue.pop(0)
            if isinstance(response, Exception):
                raise response
            return response
        return super().converse(system, messages, tools)


def _client(**overrides) -> ClientProfile:
    return ClientProfile(**{"name": "Ana Torres", "document_id": "1712345675", "product": "cuenta_ahorros", **overrides})


def _run(llm=None, **overrides):
    return Orchestrator(llm or OfflineLLM()).run(_client(**overrides))


def _events(state, event):
    return [e for e in state.audit if e.event == event]


def _executed_tools(state):
    return [e.detail["tool"] for e in _events(state, "tool_executed")]


def _actions(state):
    return [p["action"] for p in state.eligibility["proposed_solutions"]]


# --- flow control -------------------------------------------------------------

def test_happy_path_runs_every_step_in_order():
    state = _run()
    assert state.status is Status.COMPLETED
    assert _executed_tools(state) == ["verify_identity", "check_risk_lists", "prepare_documentation"]
    assert state.escalation is None
    assert state.eligibility["proposed_solutions"] == []


@pytest.mark.parametrize(
    ("document_id", "reason"),
    [("0912345675", "identity_low_confidence"), ("0102030400", "identity_not_verified"), ("1712345670", "identity_not_verified")],
)
def test_identity_is_a_gate_risk_never_runs(document_id, reason):
    state = _run(document_id=document_id)
    assert state.status is Status.ESCALATED
    assert state.escalation["step"] == "identity" and state.escalation["reason"] == reason
    assert "check_risk_lists" not in _executed_tools(state)


def test_high_risk_escalates_before_documentation():
    state = _run(document_id="1711111110")
    assert state.status is Status.ESCALATED
    assert state.escalation["reason"] == "high_risk"
    assert "prepare_documentation" not in _executed_tools(state)


def test_pep_flag_flows_from_risk_into_documentation():
    state = _run(document_id="0923456784", product="credito_consumo")
    assert state.status is Status.COMPLETED
    assert state.flags == {"enhanced_due_diligence": True, "pep": True}
    codes = [d["code"] for d in state.results["documentation"]["required_documents"]]
    assert "PEP_DECLARATION" in codes


# --- guardrails ---------------------------------------------------------------

def test_agent_cannot_use_a_tool_outside_its_allow_list():
    llm = ScriptedLLM({"verify_identity": [tool_use_response("check_risk_lists", {"name": "x", "document_id": "1712345675"})]})
    state = _run(llm)
    blocked = _events(state, "tool_blocked")
    assert blocked and blocked[0].detail["tool"] == "check_risk_lists"
    # The blocked call never executed: risk ran once, in its own step, after identity passed.
    assert _executed_tools(state).count("check_risk_lists") == 1
    assert state.status is Status.COMPLETED


def test_hallucinated_document_id_is_rejected_then_corrected():
    llm = ScriptedLLM({"verify_identity": [tool_use_response("verify_identity", {"document_id": "1700000019"})]})
    state = _run(llm)
    assert _events(state, "args_rejected")[0].detail["fields"] == ["document_id"]
    assert state.results["identity"] == {"verified": True, "confidence": 0.97}
    assert state.status is Status.COMPLETED


def test_agent_that_never_calls_its_tool_escalates_after_retries():
    llm = ScriptedLLM({"check_risk_lists": [text_response("El cliente parece de bajo riesgo.")] * 2})
    state = Orchestrator(llm, max_attempts=2).run(_client())
    assert state.status is Status.ESCALATED
    assert state.escalation == {"step": "risk", "reason": "agent_no_result", "detail": {"attempts": 2}}
    assert len(_events(state, "no_valid_tool_call")) == 2


def test_llm_failure_fails_closed_and_is_never_no_apto():
    state = _run(ScriptedLLM({"verify_identity": [RuntimeError("ThrottlingException")]}))
    assert state.status is Status.ESCALATED
    assert state.escalation["reason"] == "agent_error"
    assert state.eligibility["verdict"] == "no_determinado"
    assert state.eligibility["requires_human_review"] is True


def test_tool_exception_escalates_without_retry(monkeypatch):
    from onboarding_agent.agents import TOOLS

    def broken(args):
        raise ConnectionError("registry unavailable")

    monkeypatch.setitem(TOOLS, "verify_identity", {**TOOLS["verify_identity"], "handler": broken})
    state = _run()
    assert state.status is Status.ESCALATED
    assert state.escalation == {"step": "identity", "reason": "tool_error", "detail": {"error": "registry unavailable"}}
    assert len(_events(state, "tool_failed")) == 1


# --- proposed solutions (failure or ambiguity) --------------------------------

def test_low_confidence_proposes_reinforced_verification_and_resumes_at_risk():
    state = _run(document_id="0912345675")
    [proposal] = state.eligibility["proposed_solutions"]
    assert proposal["action"] == "verificacion_reforzada"
    assert proposal["owner"] == "cliente"
    assert proposal["resume_from"] == "risk"
    assert state.client_message == proposal["client_message"]


def test_not_verified_proposes_a_single_reverification():
    # Both identity policies fail, but one remediation covers them.
    state = _run(document_id="0102030400")
    assert _actions(state) == ["reverificar_identidad"]


def test_high_risk_goes_to_compliance_without_revealing_the_reason_to_the_client():
    state = _run(document_id="1700000019")
    assert _actions(state) == ["revision_cumplimiento"]
    message = state.client_message.lower()
    assert "lista" not in message and "ofac" not in message and "riesgo" not in message


def test_name_only_match_is_ambiguous_and_gets_a_proposal_while_still_apto():
    state = _run(name="Carlos Andres Mendoza Rivera")
    assert state.eligibility["verdict"] == "apto"
    assert state.flags == {"enhanced_due_diligence": True, "pep": False}
    [proposal] = state.eligibility["proposed_solutions"]
    assert proposal["issue"] == {"type": "ambiguity", "code": "possible_homonym"}
    assert proposal["owner"] == "oficial_cumplimiento"


def test_technical_failure_proposes_retry_from_the_failed_step():
    state = _run(ScriptedLLM({"check_risk_lists": [RuntimeError("ThrottlingException")]}))
    [proposal] = state.eligibility["proposed_solutions"]
    assert proposal["action"] == "reintento_automatico"
    assert proposal["resume_from"] == "risk"
    assert proposal["issue"]["type"] == "technical_failure"
