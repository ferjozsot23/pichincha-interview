import pytest
from fastapi.testclient import TestClient

from onboarding_agent.api import create_app
from onboarding_agent.llm import OfflineLLM
from onboarding_agent.orchestrator import Orchestrator

URL = "/api/v1/onboarding/start"


@pytest.fixture
def client():
    return TestClient(create_app(Orchestrator(OfflineLLM())))


def _body(**overrides):
    return {"prospect_name": "Juan Perez", "document_id": "1712345675", "product": "cuenta_ahorros", **overrides}


def test_start_completed_returns_required_documents(client):
    response = client.post(URL, json=_body())
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    assert [d["code"] for d in data["required_documents"]] == ["ID_COPY", "PROOF_OF_ADDRESS", "ACCOUNT_AGREEMENT"]
    assert data["escalation"] is None


def test_contract_example_document_fails_checksum_and_escalates(client):
    # 1712345678 (the contract example) has an invalid check digit -> identity fails closed.
    data = client.post(URL, json=_body(document_id="1712345678")).json()
    assert data["status"] == "escalated"
    assert data["escalation"]["reason"] == "identity_not_verified"
    assert data["last_step"] == "identity"
    assert data["required_documents"] is None


def test_high_risk_escalates(client):
    data = client.post(URL, json=_body(document_id="1711111110")).json()
    assert data["status"] == "escalated" and data["escalation"]["reason"] == "high_risk"


def test_pep_gets_pep_declaration(client):
    data = client.post(URL, json=_body(document_id="0923456784")).json()
    assert data["status"] == "completed" and data["flags"]["pep"] is True
    assert "PEP_DECLARATION" in [d["code"] for d in data["required_documents"]]


@pytest.mark.parametrize(
    "body",
    [
        _body(product="crypto_wallet"),
        _body(document_id="17123"),
        _body(prospect_name=""),
        {"document_id": "1712345675", "product": "cuenta_ahorros"},
        _body(extra_field="x"),
    ],
)
def test_invalid_payload_is_rejected_with_422(client, body):
    assert client.post(URL, json=body).status_code == 422


@pytest.mark.parametrize(
    ("document_id", "name", "verdict", "review", "failed", "not_evaluated"),
    [
        ("1712345675", "Juan Perez", "apto", False, [], []),
        ("0923456784", "Juan Perez", "apto", False, [], []),  # PEP: apto with conditions
        ("0912345675", "Juan Perez", "no_apto", True, ["POL-ID-02"], ["POL-RISK-01"]),
        ("0102030400", "Juan Perez", "no_apto", True, ["POL-ID-01", "POL-ID-02"], ["POL-RISK-01"]),
        ("1712345678", "Juan Perez", "no_apto", True, ["POL-ID-01", "POL-ID-02"], ["POL-RISK-01"]),
        ("1700000019", "Juan Perez", "no_apto", True, ["POL-RISK-01"], []),
    ],
)
def test_eligibility_verdict_follows_policies(client, document_id, name, verdict, review, failed, not_evaluated):
    eligibility = client.post(URL, json=_body(document_id=document_id, prospect_name=name)).json()["eligibility"]
    assert eligibility["verdict"] == verdict
    assert eligibility["requires_human_review"] is review
    assert eligibility["failed_policies"] == failed
    assert eligibility["not_evaluated_policies"] == not_evaluated


def test_pep_is_apto_with_conditions(client):
    eligibility = client.post(URL, json=_body(document_id="0923456784")).json()["eligibility"]
    assert len(eligibility["conditions"]) == 2
    assert "con condiciones" in eligibility["summary"]


def test_failed_verification_returns_proposed_solution(client):
    data = client.post(URL, json=_body(document_id="0912345675")).json()
    [proposal] = data["eligibility"]["proposed_solutions"]
    assert proposal["action"] == "verificacion_reforzada"
    assert data["client_message"] == proposal["client_message"]
