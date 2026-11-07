from fastapi.testclient import TestClient


def test_docs_describe_the_422_with_the_common_error_body(offline_client: TestClient):
    spec = offline_client.get("/openapi.json").json()

    responses = spec["paths"]["/api/v1/orders"]["post"]["responses"]
    schema = responses["422"]["content"]["application/json"]["schema"]
    assert schema["$ref"].endswith("/ErrorResponse")
    assert "error" in spec["components"]["schemas"]["ErrorResponse"]["properties"]


def test_docs_do_not_describe_fastapis_default_422(offline_client: TestClient):
    schemas = offline_client.get("/openapi.json").json()["components"]["schemas"]

    # FastAPI's {"detail": [...]} is not what this API returns, so it must not be documented.
    assert "HTTPValidationError" not in schemas


def test_every_schema_and_field_is_documented(offline_client: TestClient):
    schemas = offline_client.get("/openapi.json").json()["components"]["schemas"]

    undocumented = [name for name, schema in schemas.items() if "description" not in schema]
    assert undocumented == [], f"schemas without a description: {undocumented}"

    # A field must explain itself, unless it only points to another documented schema.
    for name, schema in schemas.items():
        for field, definition in schema.get("properties", {}).items():
            assert "description" in definition or "$ref" in definition, f"{name}.{field}"


def test_docs_do_not_expose_notes_for_developers(offline_client: TestClient):
    spec = offline_client.get("/openapi.json").text

    assert "PostgreSQL" not in spec
    assert "ALTER TYPE" not in spec


def test_docs_describe_the_404_of_a_document_with_the_common_error_body(
    offline_client: TestClient,
):
    spec = offline_client.get("/openapi.json").json()

    responses = spec["paths"]["/api/v1/documents/{document_id}"]["get"]["responses"]
    for status in ("404", "422"):
        schema = responses[status]["content"]["application/json"]["schema"]
        assert schema["$ref"].endswith("/ErrorResponse"), status


def test_docs_describe_the_422_of_the_list_and_its_filters(offline_client: TestClient):
    spec = offline_client.get("/openapi.json").json()

    operation = spec["paths"]["/api/v1/documents"]["get"]
    schema = operation["responses"]["422"]["content"]["application/json"]["schema"]
    assert schema["$ref"].endswith("/ErrorResponse")
    parameters = {parameter["name"]: parameter for parameter in operation["parameters"]}
    assert set(parameters) == {"type", "customer", "series", "status", "from", "to", "page", "size"}
    # Every filter says what it does, since /docs is how a client learns them.
    assert all("description" in parameter for parameter in parameters.values())


def test_docs_describe_the_errors_of_a_delivery_note_with_the_common_error_body(
    offline_client: TestClient,
):
    spec = offline_client.get("/openapi.json").json()

    responses = spec["paths"]["/api/v1/delivery-notes"]["post"]["responses"]
    for status in ("404", "422"):
        schema = responses[status]["content"]["application/json"]["schema"]
        assert schema["$ref"].endswith("/ErrorResponse"), status
