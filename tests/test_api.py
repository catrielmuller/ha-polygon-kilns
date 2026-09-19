"""Tests for the Polygon Kilns API client."""

from __future__ import annotations

import json

import httpx
import pytest

from custom_components.polygon_kilns.api import (
    AuthSession,
    PolygonAuthError,
    PolygonKilnsClient,
    PolygonKilnsApiError,
    PolygonPermissionError,
    _decode_document,
    _decode_value,
    _encode_fields,
)
from custom_components.polygon_kilns.const import FIREBASE_API_KEY

from datetime import UTC, datetime, timedelta


def future_session() -> AuthSession:
    """Return a session whose ID token is still valid."""
    return AuthSession(
        uid="uid123",
        id_token="id-token",
        refresh_token="refresh-token",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )


def make_client(handler) -> PolygonKilnsClient:
    """Build a client backed by an httpx mock transport."""
    transport = httpx.MockTransport(handler)
    return PolygonKilnsClient(future_session(), httpx.AsyncClient(transport=transport))


def test_value_decode_encode_roundtrip() -> None:
    """Firestore values decode and encode symmetrically."""
    fields = {
        "name": "gar_Kilnn",
        "temperature": 117,
        "setpoint": 802.9,
        "stopRequested": False,
        "stages": [{"ramp": 120, "temp": 600, "hold": 0}],
        "missing": None,
    }
    encoded = _encode_fields(fields)
    decoded = {k: _decode_value(v) for k, v in encoded.items()}
    assert decoded == fields


def test_decode_document_adds_id() -> None:
    """The document id is extracted from the resource name."""
    doc = {
        "name": "projects/polygonkilns/databases/(default)/documents/kilns/K1117",
        "fields": {"state": {"stringValue": "Enfriamiento"}},
    }
    decoded = _decode_document(doc)
    assert decoded["_id"] == "K1117"
    assert decoded["state"] == "Enfriamiento"


async def test_authenticate_success() -> None:
    """A successful login maps the response into a session."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["key"] == FIREBASE_API_KEY
        body = json.loads(request.content)
        assert body["email"] == "user@example.com"
        return httpx.Response(
            200,
            json={
                "localId": "uid123",
                "idToken": "id-token",
                "refreshToken": "refresh-token",
                "expiresIn": "3600",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = await PolygonKilnsClient.async_authenticate(
            http_client, "user@example.com", "secret"
        )
    assert client.uid == "uid123"
    assert client.refresh_token == "refresh-token"


async def test_authenticate_invalid_password() -> None:
    """Bad credentials raise PolygonAuthError."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "INVALID_PASSWORD"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        with pytest.raises(PolygonAuthError):
            await PolygonKilnsClient.async_authenticate(
                http_client, "user@example.com", "wrong"
            )


async def test_refresh_token_when_expired() -> None:
    """An expired ID token is refreshed before the request."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if "securetoken" in str(request.url):
            return httpx.Response(
                200,
                json={
                    "user_id": "uid123",
                    "id_token": "fresh-token",
                    "refresh_token": "new-refresh",
                    "expires_in": "3600",
                },
            )
        assert request.headers["Authorization"] == "Bearer fresh-token"
        return httpx.Response(200, json=[])

    transport = httpx.MockTransport(handler)
    session = AuthSession(
        uid="uid123",
        id_token="stale",
        refresh_token="refresh-token",
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = PolygonKilnsClient(session, http_client)
        kilns = await client.async_get_kilns()
    assert kilns == []
    assert any("securetoken" in url for url in calls)
    assert client.refresh_token == "new-refresh"


async def test_get_kilns_merges_owned_and_shared() -> None:
    """Owned and shared kilns are merged by document id."""
    kiln = {
        "name": "projects/x/databases/(default)/documents/kilns/K1117",
        "fields": {
            "name": {"stringValue": "gar_Kilnn"},
            "state": {"stringValue": "Enfriamiento"},
            "temperature": {"integerValue": "117"},
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        query = json.loads(request.content)["structuredQuery"]
        if "fieldFilter" in query["where"]:
            return httpx.Response(200, json=[])
        return httpx.Response(200, json=[{"document": kiln}])

    client = make_client(handler)
    async with client._client:
        kilns = await client.async_get_kilns()
    assert len(kilns) == 1
    assert kilns[0]["_id"] == "K1117"
    assert kilns[0]["temperature"] == 117


async def test_permission_denied_maps_to_permission_error() -> None:
    """A 403 from Firestore raises PolygonPermissionError."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": {"status": "PERMISSION_DENIED"}})

    client = make_client(handler)
    async with client._client:
        with pytest.raises(PolygonPermissionError):
            await client.async_get_schedules("K1117")


async def test_request_start_success() -> None:
    """A 200 from the Cloud Function completes silently."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body == {"kilnId": "K1117", "schedNum": 10}
        assert request.headers["Authorization"] == "Bearer id-token"
        return httpx.Response(200, json={"ok": True})

    client = make_client(handler)
    async with client._client:
        await client.async_request_start("K1117", 10)


async def test_request_start_business_error() -> None:
    """Backend errors surface the message from the response body."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"ok": False, "error": "Kiln not found"})

    client = make_client(handler)
    async with client._client:
        with pytest.raises(PolygonKilnsApiError, match="Kiln not found"):
            await client.async_request_start("K9999", 1)


async def test_stop_kiln_writes_stop_requested() -> None:
    """Stopping patches stopRequested=true on the kiln document."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PATCH"
        assert request.url.path.endswith("/documents/kilns/K1117")
        assert request.url.params["updateMask.fieldPaths"] == "stopRequested"
        body = json.loads(request.content)
        assert body["fields"]["stopRequested"] == {"booleanValue": True}
        return httpx.Response(200, json={"name": "kilns/K1117", "fields": {}})

    client = make_client(handler)
    async with client._client:
        await client.async_stop_kiln("K1117")


async def test_create_schedule_payload() -> None:
    """Creating a program posts the documented field layout."""
    stages = [{"ramp": 120, "temp": 600, "hold": 0}]

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)["fields"]
        assert body["kilnId"] == {"stringValue": "K1117"}
        assert body["schedNum"] == {"integerValue": "10"}
        assert body["name"] == {"stringValue": "GRES CONO 6"}
        assert body["stageCount"] == {"integerValue": "1"}
        assert body["maxTemp"] == {"integerValue": "600"}
        assert body["createdBy"] == {"stringValue": "home_assistant"}
        assert body["stages"]["arrayValue"]["values"][0]["mapValue"]["fields"][
            "ramp"
        ] == {"integerValue": "120"}
        return httpx.Response(
            200,
            json={
                "name": "projects/x/databases/(default)/documents/schedules/abc",
                "fields": {},
            },
        )

    client = make_client(handler)
    async with client._client:
        doc = await client.async_create_schedule("K1117", "GRES CONO 6", 10, stages)
    assert doc["_id"] == "abc"
