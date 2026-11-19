"""HTTP API.

POST /api/v1/onboarding/start
    {"prospect_name": "Juan Perez", "document_id": "1712345678", "product": "cuenta_ahorros"}

Run: uv run uvicorn onboarding_agent.api:app --reload
"""

from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict, Field

from . import config
from .llm import BedrockConverseClient, OfflineLLM
from .orchestrator import Orchestrator
from .state import ClientProfile, OnboardingState
from .tools import SUPPORTED_PRODUCTS

Product = Literal[SUPPORTED_PRODUCTS]  # type: ignore[valid-type]


class OnboardingStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prospect_name: str = Field(min_length=3, max_length=120, examples=["Juan Perez"])
    document_id: str = Field(pattern=r"^\d{10}$", examples=["1712345675"])
    product: Product = Field(examples=["cuenta_ahorros"])


class Eligibility(BaseModel):
    verdict: Literal["apto", "no_apto", "no_determinado"]
    requires_human_review: bool
    summary: str
    failed_policies: list[str]
    not_evaluated_policies: list[str]
    conditions: list[str]
    proposed_solutions: list[dict]
    checks: list[dict]


class OnboardingStartResponse(BaseModel):
    case_id: str
    eligibility: Eligibility
    status: Literal["completed", "escalated"]
    last_step: str | None
    escalation: dict | None = None
    flags: dict[str, bool]
    required_documents: list[dict] | None = None
    client_message: str | None = None


def _to_response(state: OnboardingState) -> OnboardingStartResponse:
    documentation = state.results.get("documentation")
    return OnboardingStartResponse(
        case_id=state.case_id,
        eligibility=Eligibility.model_validate(state.eligibility),
        status=state.status.value,
        last_step=state.current_step,
        escalation=state.escalation,
        flags=state.flags,
        required_documents=documentation["required_documents"] if documentation else None,
        client_message=state.client_message,
    )


def _default_orchestrator() -> Orchestrator:
    llm = OfflineLLM() if config.LLM_PROVIDER == "offline" else BedrockConverseClient()
    return Orchestrator(llm)


def create_app(orchestrator: Orchestrator | None = None) -> FastAPI:
    app = FastAPI(title="Digital Onboarding API", version="1.0.0")
    app.state.orchestrator = orchestrator or _default_orchestrator()

    # Plain `def`: the orchestrator makes blocking LLM calls, so FastAPI runs it in its threadpool.
    @app.post("/api/v1/onboarding/start", response_model=OnboardingStartResponse)
    def start_onboarding(body: OnboardingStartRequest) -> OnboardingStartResponse:
        client = ClientProfile(name=body.prospect_name.strip(), document_id=body.document_id, product=body.product)
        state = app.state.orchestrator.run(client)
        return _to_response(state)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
