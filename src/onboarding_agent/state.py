"""Shared case state that the orchestrator carries between steps."""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4


class Status(str, Enum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ESCALATED = "escalated"  # needs human review: the flow stopped, nothing was approved


@dataclass
class ClientProfile:
    name: str
    document_id: str
    product: str
    employment_type: str | None = None
    is_foreign: bool = False


@dataclass
class AuditEvent:
    step: str
    event: str
    detail: dict
    at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class OnboardingState:
    client: ClientProfile
    case_id: str = field(default_factory=lambda: str(uuid4()))
    status: Status = Status.IN_PROGRESS
    current_step: str | None = None
    results: dict[str, dict] = field(default_factory=dict)  # step -> output of the step's tool
    flags: dict[str, bool] = field(default_factory=lambda: {"enhanced_due_diligence": False, "pep": False})
    escalation: dict | None = None  # {"step", "reason", "detail"}
    policy_checks: list[dict] = field(default_factory=list)  # every policy evaluated, passed or not
    eligibility: dict | None = None  # final verdict + proposed solutions, set when the case ends
    client_message: str | None = None
    audit: list[AuditEvent] = field(default_factory=list)

    def log(self, step: str, event: str, **detail) -> None:
        self.audit.append(AuditEvent(step=step, event=event, detail=detail))

    def escalate(self, step: str, reason: str, **detail) -> None:
        self.status = Status.ESCALATED
        self.escalation = {"step": step, "reason": reason, "detail": detail}
        self.log(step, "escalated", reason=reason, **detail)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["status"] = self.status.value
        return data
