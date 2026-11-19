"""Proposed solutions when an agentic verification fails or is ambiguous.

Deterministic playbook: issue code -> action, owner, steps and a client-safe message.
The LLM never invents remediation steps; every proposal comes from this table, so it
is auditable and approved in advance by the business/compliance owners.

Issues come from three sources:
  - policy failures   (identity not verified, low confidence, high risk)
  - technical failures (LLM error, tool error, agent that produced no valid call)
  - ambiguities        (name-only watchlist match: possible homonym)
"""

from .state import OnboardingState

PLAYBOOK: dict[str, dict] = {
    "identity_not_verified": {
        "action": "reverificar_identidad",
        "owner": "cliente",
        "steps": [
            "Confirmar con el cliente el número de cédula ingresado",
            "Si el número es correcto, validar presencialmente en agencia con la cédula original",
            "Reiniciar el onboarding con el dato confirmado",
        ],
        "resume_from": "identity",
        "client_message": "No pudimos validar tu identidad. Confirma tu número de cédula o acércate a una agencia con tu cédula original.",
    },
    "identity_low_confidence": {
        "action": "verificacion_reforzada",
        "owner": "cliente",
        "steps": [
            "Solicitar verificación biométrica (selfie con prueba de vida)",
            "Alternativa: videollamada con un asesor",
            "Si la nueva confianza es >= 0.8, reanudar desde la evaluación de riesgo",
        ],
        "resume_from": "risk",
        "client_message": "Necesitamos una verificación adicional de tu identidad. Te enviaremos un enlace para una validación biométrica.",
    },
    "high_risk": {
        "action": "revision_cumplimiento",
        "owner": "oficial_cumplimiento",
        "steps": [
            "Derivar el caso al Oficial de Cumplimiento con las coincidencias encontradas",
            "Suspender la apertura hasta su dictamen",
            "No informar al cliente el motivo (confidencialidad de listas restrictivas)",
        ],
        "resume_from": None,
        # Deliberately generic: revealing a watchlist hit to the client is not allowed (tipping-off).
        "client_message": "Tu solicitud está en revisión. Te contactaremos en los próximos días.",
    },
    "possible_homonym": {
        "action": "descartar_homonimia",
        "owner": "oficial_cumplimiento",
        "steps": [
            "Comparar fecha de nacimiento y nacionalidad del cliente con la entrada de la lista",
            "Si la duda persiste, solicitar un segundo documento de identidad",
            "Registrar la justificación al descartar la coincidencia",
        ],
        "resume_from": None,
        "client_message": None,
    },
    "agent_error": {
        "action": "reintento_automatico",
        "owner": "sistema",
        "steps": [
            "Reintentar el caso con backoff exponencial (falla técnica, no atribuible al cliente)",
            "Si persiste, abrir incidente con el equipo de plataforma",
        ],
        "resume_from": "<failed_step>",
        "client_message": "Estamos procesando tu solicitud. Te notificaremos el resultado.",
    },
    "agent_no_result": {
        "action": "revision_manual",
        "owner": "operaciones",
        "steps": [
            "Un analista ejecuta manualmente la verificación del paso fallido",
            "Revisar el registro de auditoría del agente para ajustar el prompt",
        ],
        "resume_from": "<failed_step>",
        "client_message": "Estamos procesando tu solicitud. Te notificaremos el resultado.",
    },
}
PLAYBOOK["tool_error"] = PLAYBOOK["agent_error"]


def find_issues(state: OnboardingState) -> list[dict]:
    issues = []
    failed_codes = [c["reason_code"] for c in state.policy_checks if not c["passed"]]
    for code in failed_codes:
        # Low confidence is implied when the identity is not verified at all; one fix covers both.
        if code == "identity_low_confidence" and "identity_not_verified" in failed_codes:
            continue
        issues.append({"type": "policy_failure", "code": code})

    if state.escalation and state.escalation["reason"] not in failed_codes:
        issues.append({"type": "technical_failure", "code": state.escalation["reason"], "step": state.escalation["step"]})

    risk = state.results.get("risk")
    if risk and risk["risk_level"] != "high" and any(m["matched_on"] == "name" for m in risk["matches"]):
        issues.append({"type": "ambiguity", "code": "possible_homonym"})
    return issues


def propose_solutions(state: OnboardingState) -> list[dict]:
    proposals = []
    for issue in find_issues(state):
        entry = PLAYBOOK.get(issue["code"], PLAYBOOK["agent_no_result"])
        resume_from = issue.get("step") if entry["resume_from"] == "<failed_step>" else entry["resume_from"]
        proposals.append({"issue": issue, **entry, "resume_from": resume_from})
    return proposals
