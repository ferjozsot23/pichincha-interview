"""Deterministic orchestrator for the digital onboarding flow.

    identity (gate) -> risk (gate) -> documentation -> verdict + proposed solutions

The orchestrator, not the LLM, owns the control flow:
  - which agent runs at each step and which tools it may use (AgentSpec.allowed_tools);
  - the state passed between steps (OnboardingState), e.g. a PEP hit in risk adds the
    PEP declaration in documentation;
  - every approve/escalate decision, taken from the tool outputs it executed itself
    (policies.py), never from the agent's text.

Uncertainty is handled fail-closed: a failed policy, a tool error, an LLM error, or an
agent that cannot produce a valid tool call stops the flow and escalates, and every
failure or ambiguity gets a proposed solution (remediation.py).
"""

from collections.abc import Callable
from dataclasses import dataclass

from . import policies
from .agents import DOCUMENTATION_AGENT, IDENTITY_AGENT, RISK_AGENT, AgentRun, AgentSpec, ToolCall, run_agent
from .llm import LLMClient
from .state import ClientProfile, OnboardingState, Status


@dataclass(frozen=True)
class Step:
    name: str
    agent: AgentSpec
    tool: str  # the tool whose successful output completes this step
    build_case: Callable[[OnboardingState], dict]
    gate: Callable[[OnboardingState, ToolCall, AgentRun], None]


# --- case builders: the only data each agent gets to see ----------------------

def _identity_case(state: OnboardingState) -> dict:
    return {"document_id": state.client.document_id}


def _risk_case(state: OnboardingState) -> dict:
    return {"name": state.client.name, "document_id": state.client.document_id}


def _documentation_case(state: OnboardingState) -> dict:
    client_data: dict = {"is_pep": state.flags["pep"], "is_foreign": state.client.is_foreign}
    if state.client.employment_type:
        client_data["employment_type"] = state.client.employment_type
    return {"product": state.client.product, "client_data": client_data}


# --- gates: deterministic decisions on the tool output ------------------------

def _apply_policies(state: OnboardingState, step: str, checks: list[policies.PolicyCheck]) -> None:
    """Record every check (for the verdict and audit) and escalate on the first failure."""
    for check in checks:
        state.policy_checks.append(policies.as_dict(check))
        state.log(step, "policy_checked", policy_id=check.policy_id, passed=check.passed)
    failed = [check for check in checks if not check.passed]
    if failed:
        state.escalate(step, failed[0].reason_code, failed_policies=[c.policy_id for c in failed], **failed[0].observed)


def _identity_gate(state: OnboardingState, call: ToolCall, run: AgentRun) -> None:
    _apply_policies(state, "identity", policies.check_identity(call.output))


def _risk_gate(state: OnboardingState, call: ToolCall, run: AgentRun) -> None:
    result = call.output
    _apply_policies(state, "risk", policies.check_risk(result))
    if state.status is Status.IN_PROGRESS and result["risk_level"] == "medium":
        state.flags["enhanced_due_diligence"] = True
        state.flags["pep"] = any(m["list"] == "PEP" and m["matched_on"] == "document_id" for m in result["matches"])
        state.log("risk", "enhanced_due_diligence", matches=result["matches"])


def _documentation_gate(state: OnboardingState, call: ToolCall, run: AgentRun) -> None:
    state.client_message = run.final_text or None


PIPELINE: tuple[Step, ...] = (
    Step("identity", IDENTITY_AGENT, "verify_identity", _identity_case, _identity_gate),
    Step("risk", RISK_AGENT, "check_risk_lists", _risk_case, _risk_gate),
    Step("documentation", DOCUMENTATION_AGENT, "prepare_documentation", _documentation_case, _documentation_gate),
)


class Orchestrator:
    def __init__(self, llm: LLMClient, max_attempts: int = 2, pipeline: tuple[Step, ...] = PIPELINE):
        self.llm = llm
        self.max_attempts = max_attempts
        self.pipeline = pipeline

    def run(self, client: ClientProfile) -> OnboardingState:
        state = OnboardingState(client=client)
        state.log("orchestrator", "case_started")

        for step in self.pipeline:
            state.current_step = step.name
            state.log(step.name, "step_started", agent=step.agent.name)
            outcome = self._run_step(step, state)
            if outcome is None:
                break
            call, run = outcome
            state.results[step.name] = call.output
            step.gate(state, call, run)
            if state.status is not Status.IN_PROGRESS:
                break
            state.log(step.name, "step_passed")
        else:
            state.status = Status.COMPLETED

        state.eligibility = policies.decide(state)
        if state.status is not Status.COMPLETED:
            # Client-facing text comes from the playbook, never from the LLM (no tipping-off on watchlist hits).
            proposals = state.eligibility["proposed_solutions"]
            state.client_message = next((p["client_message"] for p in proposals if p["client_message"]), None)
        state.log("orchestrator", "case_finished", status=state.status.value, verdict=state.eligibility["verdict"])
        return state

    def _run_step(self, step: Step, state: OnboardingState) -> tuple[ToolCall, AgentRun] | None:
        """Run the step's agent until it yields a successful call to the step's tool.

        Retries only when guardrails rejected the agent's calls or it made none; a tool
        that actually executed and failed (or an LLM error) escalates immediately.
        """
        case = step.build_case(state)

        for attempt in range(1, self.max_attempts + 1):
            try:
                run = run_agent(step.agent, case, self.llm, log=state.log)
            except Exception as exc:  # noqa: BLE001 - LLM/transport failure: fail closed
                state.escalate(step.name, "agent_error", error=str(exc))
                return None

            calls = [c for c in run.tool_calls if c.name == step.tool and c.executed]
            if any(c.error is None for c in calls):
                return next(c for c in reversed(calls) if c.error is None), run
            if calls:
                state.escalate(step.name, "tool_error", error=calls[-1].error)
                return None
            state.log(step.name, "no_valid_tool_call", attempt=attempt, agent_text=run.final_text)

        state.escalate(step.name, "agent_no_result", attempts=self.max_attempts)
        return None
