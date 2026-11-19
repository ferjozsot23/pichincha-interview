"""Tool 3: prepare_documentation(product, client_data) -> required documents."""

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class Document:
    code: str
    name: str
    reason: str


@dataclass(frozen=True)
class DocumentationResult:
    product: str
    required_documents: list[Document] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


_BASE_DOCUMENTS = [
    Document("ID_COPY", "Copia de cédula de identidad", "Requisito KYC para todo producto"),
    Document("PROOF_OF_ADDRESS", "Planilla de servicio básico (últimos 3 meses)", "Verificación de domicilio"),
]

_PRODUCT_DOCUMENTS: dict[str, list[Document]] = {
    "cuenta_ahorros": [
        Document("ACCOUNT_AGREEMENT", "Contrato de cuenta de ahorros", "Apertura de cuenta"),
    ],
    "cuenta_corriente": [
        Document("ACCOUNT_AGREEMENT", "Contrato de cuenta corriente", "Apertura de cuenta"),
        Document("BANK_REFERENCE", "Referencia bancaria", "Requisito para emisión de chequera"),
    ],
    "tarjeta_credito": [
        Document("CREDIT_BUREAU_AUTH", "Autorización de consulta al buró de crédito", "Evaluación crediticia"),
        Document("CARD_AGREEMENT", "Contrato de tarjeta de crédito", "Emisión de tarjeta"),
    ],
    "credito_consumo": [
        Document("CREDIT_BUREAU_AUTH", "Autorización de consulta al buró de crédito", "Evaluación crediticia"),
        Document("LOAN_APPLICATION", "Solicitud de crédito firmada", "Originación del crédito"),
    ],
    "credito_hipotecario": [
        Document("CREDIT_BUREAU_AUTH", "Autorización de consulta al buró de crédito", "Evaluación crediticia"),
        Document("LOAN_APPLICATION", "Solicitud de crédito firmada", "Originación del crédito"),
        Document("PROPERTY_APPRAISAL", "Avalúo del inmueble", "Garantía hipotecaria"),
        Document("PROPERTY_DEED", "Escritura o promesa de compraventa", "Garantía hipotecaria"),
    ],
}

_CREDIT_PRODUCTS = {"tarjeta_credito", "credito_consumo", "credito_hipotecario"}

SUPPORTED_PRODUCTS = tuple(_PRODUCT_DOCUMENTS)


def _income_documents(client_data: dict) -> list[Document]:
    if client_data.get("employment_type") == "independiente":
        return [
            Document("RUC", "Registro Único de Contribuyentes (RUC)", "Cliente independiente"),
            Document("TAX_RETURNS", "Declaraciones de impuesto a la renta (últimos 2 años)", "Sustento de ingresos"),
        ]
    return [Document("PAYROLL_SLIPS", "Roles de pago (últimos 3 meses)", "Sustento de ingresos")]


def prepare_documentation(product: str, client_data: dict | None = None) -> DocumentationResult:
    """Mock checklist builder: base KYC docs + product docs + docs triggered by the client profile.

    Recognized client_data keys (all optional):
      - employment_type: "dependiente" | "independiente" (credit products only)
      - is_pep: bool -> PEP declaration
      - is_foreign: bool -> passport + migratory status instead of cédula
    """
    client_data = client_data or {}
    product_key = (product or "").strip().lower()
    if product_key not in _PRODUCT_DOCUMENTS:
        raise ValueError(f"Unsupported product '{product}'. Supported: {', '.join(SUPPORTED_PRODUCTS)}")

    documents = list(_BASE_DOCUMENTS)
    if client_data.get("is_foreign"):
        documents[0] = Document("PASSPORT_COPY", "Copia de pasaporte", "Cliente extranjero")
        documents.append(Document("MIGRATORY_STATUS", "Certificado de movimiento migratorio", "Cliente extranjero"))

    documents += _PRODUCT_DOCUMENTS[product_key]

    if product_key in _CREDIT_PRODUCTS:
        documents += _income_documents(client_data)

    if client_data.get("is_pep"):
        documents.append(
            Document("PEP_DECLARATION", "Declaración de Persona Expuesta Políticamente", "Debida diligencia reforzada")
        )

    return DocumentationResult(product=product_key, required_documents=documents)


SCHEMA = {
    "name": "prepare_documentation",
    "description": "Returns the documents the client must provide to contract the given banking product.",
    "input_schema": {
        "type": "object",
        "properties": {
            "product": {"type": "string", "enum": list(SUPPORTED_PRODUCTS)},
            "client_data": {
                "type": "object",
                "description": "Client profile; drives income, PEP and foreign-client documents",
                "properties": {
                    "employment_type": {"type": "string", "enum": ["dependiente", "independiente"]},
                    "is_pep": {"type": "boolean"},
                    "is_foreign": {"type": "boolean"},
                },
            },
        },
        "required": ["product"],
        "additionalProperties": False,
    },
    "output_schema": {
        "type": "object",
        "properties": {
            "product": {"type": "string"},
            "required_documents": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "code": {"type": "string"},
                        "name": {"type": "string"},
                        "reason": {"type": "string"},
                    },
                    "required": ["code", "name", "reason"],
                },
            },
        },
        "required": ["product", "required_documents"],
    },
}
