"""Async client for the Polygon Kilns Firebase backend.

Talks to Firebase Auth (Identity Toolkit), the Firestore REST API and the
``requestStart`` Cloud Function using nothing but HTTP, so the integration has
no external dependencies beyond httpx (bundled with Home Assistant).

Endpoint details come from the official Polygon backend.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import logging
from typing import Any

import httpx

from .const import (
    FIREBASE_API_KEY,
    FIREBASE_AUTH_URL,
    FIREBASE_REFRESH_URL,
    FIRESTORE_BASE_URL,
    REQUEST_START_URL,
    TOKEN_REFRESH_MARGIN,
)

_LOGGER = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 20.0


class PolygonKilnsApiError(Exception):
    """Base error for the Polygon Kilns API."""


class PolygonAuthError(PolygonKilnsApiError):
    """Authentication failed or the session can no longer be refreshed."""


class PolygonPermissionError(PolygonKilnsApiError):
    """Firestore security rules denied the operation."""


class PolygonConnectionError(PolygonKilnsApiError):
    """The backend could not be reached."""


def _decode_value(value: dict[str, Any]) -> Any:
    """Decode a Firestore REST value into a plain Python object."""
    if "nullValue" in value:
        return None
    if "booleanValue" in value:
        return value["booleanValue"]
    if "integerValue" in value:
        return int(value["integerValue"])
    if "doubleValue" in value:
        return float(value["doubleValue"])
    if "stringValue" in value:
        return value["stringValue"]
    if "timestampValue" in value:
        return value["timestampValue"]
    if "referenceValue" in value:
        return value["referenceValue"]
    if "arrayValue" in value:
        return [_decode_value(v) for v in value["arrayValue"].get("values", [])]
    if "mapValue" in value:
        return {
            k: _decode_value(v) for k, v in value["mapValue"].get("fields", {}).items()
        }
    if "geoPointValue" in value:
        return value["geoPointValue"]
    if "bytesValue" in value:
        return value["bytesValue"]
    return None


def _encode_value(value: Any) -> dict[str, Any]:
    """Encode a plain Python object as a Firestore REST value."""
    if value is None:
        return {"nullValue": None}
    if isinstance(value, bool):
        return {"booleanValue": value}
    if isinstance(value, int):
        return {"integerValue": str(value)}
    if isinstance(value, float):
        return {"doubleValue": value}
    if isinstance(value, str):
        return {"stringValue": value}
    if isinstance(value, list):
        return {"arrayValue": {"values": [_encode_value(v) for v in value]}}
    if isinstance(value, dict):
        return {"mapValue": {"fields": _encode_fields(value)}}
    raise TypeError(f"Unsupported Firestore value type: {type(value)!r}")


def _encode_fields(fields: dict[str, Any]) -> dict[str, Any]:
    """Encode a dict of fields as Firestore REST fields."""
    return {key: _encode_value(value) for key, value in fields.items()}


def _decode_document(document: dict[str, Any]) -> dict[str, Any]:
    """Decode a Firestore document, adding ``_id`` with the document id."""
    decoded = {
        key: _decode_value(value) for key, value in document.get("fields", {}).items()
    }
    decoded["_id"] = document["name"].rsplit("/", 1)[-1]
    return decoded


@dataclass
class AuthSession:
    """Firebase Auth session data."""

    uid: str
    id_token: str
    refresh_token: str
    expires_at: datetime


class PolygonKilnsClient:
    """Client for the Polygon Kilns Firebase backend."""

    def __init__(
        self,
        session: AuthSession,
        httpx_client: httpx.AsyncClient,
    ) -> None:
        """Initialize the client with an existing session."""
        self._session = session
        self._client = httpx_client

    @property
    def uid(self) -> str:
        """Return the authenticated user's UID."""
        return self._session.uid

    @property
    def refresh_token(self) -> str:
        """Return the current refresh token (may change after refreshes)."""
        return self._session.refresh_token

    @classmethod
    async def async_authenticate(
        cls,
        httpx_client: httpx.AsyncClient,
        email: str,
        password: str,
    ) -> PolygonKilnsClient:
        """Sign in with email/password and return an authenticated client."""
        payload = {
            "email": email,
            "password": password,
            "returnSecureToken": True,
        }
        try:
            resp = await httpx_client.post(
                FIREBASE_AUTH_URL,
                params={"key": FIREBASE_API_KEY},
                json=payload,
                timeout=DEFAULT_TIMEOUT,
            )
        except httpx.HTTPError as err:
            raise PolygonConnectionError("No se pudo contactar Firebase Auth") from err

        if resp.status_code != 200:
            message = _firebase_error_message(resp)
            raise PolygonAuthError(f"Error de autenticación: {message}")

        return cls(_session_from_auth_response(resp.json()), httpx_client)

    @classmethod
    async def async_from_refresh_token(
        cls,
        httpx_client: httpx.AsyncClient,
        refresh_token: str,
    ) -> PolygonKilnsClient:
        """Restore a client from a stored refresh token."""
        session = AuthSession(
            uid="",
            id_token="",
            refresh_token=refresh_token,
            expires_at=datetime.now(UTC),
        )
        client = cls(session, httpx_client)
        await client._async_refresh_token()
        return client

    async def _async_refresh_token(self) -> None:
        """Exchange the refresh token for a fresh ID token."""
        try:
            resp = await self._client.post(
                FIREBASE_REFRESH_URL,
                params={"key": FIREBASE_API_KEY},
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": self._session.refresh_token,
                },
                timeout=DEFAULT_TIMEOUT,
            )
        except httpx.HTTPError as err:
            raise PolygonConnectionError("No se pudo contactar Firebase Auth") from err

        if resp.status_code != 200:
            raise PolygonAuthError(
                f"La sesión expiró y no pudo renovarse: {_firebase_error_message(resp)}"
            )

        data = resp.json()
        self._session = AuthSession(
            uid=data["user_id"],
            id_token=data["id_token"],
            refresh_token=data["refresh_token"],
            expires_at=datetime.now(UTC) + timedelta(seconds=int(data["expires_in"])),
        )

    async def _async_ensure_token(self) -> str:
        """Return a valid ID token, refreshing it when needed."""
        margin = datetime.now(UTC) + TOKEN_REFRESH_MARGIN
        if not self._session.id_token or self._session.expires_at <= margin:
            await self._async_refresh_token()
        return self._session.id_token

    async def _async_headers(self) -> dict[str, str]:
        """Return authorization headers with a fresh ID token."""
        token = await self._async_ensure_token()
        return {"Authorization": f"Bearer {token}"}

    async def _async_request(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> httpx.Response:
        """Perform an authenticated request and map errors to exceptions."""
        headers = await self._async_headers()
        try:
            resp = await self._client.request(
                method, url, headers=headers, timeout=DEFAULT_TIMEOUT, **kwargs
            )
        except PolygonKilnsApiError:
            raise
        except httpx.HTTPError as err:
            raise PolygonConnectionError(f"Error de red: {err}") from err

        if resp.status_code in (401, 403):
            raise PolygonPermissionError(
                "Permiso denegado por las reglas de Firestore. "
                "Es posible que esta operación requiera ser propietario del horno."
            )
        return resp

    async def _async_run_query(
        self, structured_query: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Run a Firestore structured query and decode the documents."""
        resp = await self._async_request(
            "POST",
            f"{FIRESTORE_BASE_URL}:runQuery",
            json={"structuredQuery": structured_query},
        )
        if resp.status_code != 200:
            raise PolygonKilnsApiError(
                f"Consulta Firestore falló con estado {resp.status_code}: {resp.text}"
            )
        return [
            _decode_document(item["document"])
            for item in resp.json()
            if "document" in item
        ]

    async def async_get_kilns(self) -> list[dict[str, Any]]:
        """Return kilns owned by or shared with the authenticated user."""
        token_uid = self.uid
        queries = [
            {
                "from": [{"collectionId": "kilns"}],
                "where": {
                    "fieldFilter": {
                        "field": {"fieldPath": "ownerId"},
                        "op": "EQUAL",
                        "value": {"stringValue": token_uid},
                    }
                },
                "limit": 50,
            },
            {
                "from": [{"collectionId": "kilns"}],
                "where": {
                    "unaryFilter": {
                        "field": {"fieldPath": f"sharedWith.{token_uid}"},
                        "op": "IS_NOT_NULL",
                    }
                },
                "orderBy": [
                    {
                        "field": {"fieldPath": f"sharedWith.{token_uid}"},
                        "direction": "ASCENDING",
                    }
                ],
                "limit": 50,
            },
        ]
        kilns: dict[str, dict[str, Any]] = {}
        results = await asyncio.gather(
            *(self._async_run_query(query) for query in queries)
        )
        for result in results:
            for kiln in result:
                kilns[kiln["_id"]] = kiln
        return list(kilns.values())

    async def async_get_schedules(self, kiln_id: str) -> list[dict[str, Any]]:
        """Return firing schedules for a kiln from the top-level collection."""
        return await self._async_run_query(
            {
                "from": [{"collectionId": "schedules"}],
                "where": {
                    "fieldFilter": {
                        "field": {"fieldPath": "kilnId"},
                        "op": "EQUAL",
                        "value": {"stringValue": kiln_id},
                    }
                },
                "limit": 50,
            }
        )

    async def async_get_firings(
        self, kiln_id: str, limit: int = 5
    ) -> list[dict[str, Any]]:
        """Return recent firings (history) for a kiln, newest first."""
        resp = await self._async_request(
            "POST",
            f"{FIRESTORE_BASE_URL}/kilns/{kiln_id}:runQuery",
            json={
                "structuredQuery": {
                    "from": [{"collectionId": "firings"}],
                    "orderBy": [
                        {
                            "field": {"fieldPath": "startTime"},
                            "direction": "DESCENDING",
                        }
                    ],
                    "limit": limit,
                }
            },
        )
        if resp.status_code != 200:
            raise PolygonKilnsApiError(
                f"Consulta de horneadas falló con estado {resp.status_code}: "
                f"{resp.text}"
            )
        return [
            _decode_document(item["document"])
            for item in resp.json()
            if "document" in item
        ]

    async def async_create_schedule(
        self,
        kiln_id: str,
        name: str,
        sched_num: int,
        stages: list[dict[str, Any]],
        max_temp: float | int | None = None,
    ) -> dict[str, Any]:
        """Create a firing schedule in the top-level ``schedules`` collection."""
        if max_temp is None:
            max_temp = max((stage.get("temp", 0) for stage in stages), default=0)
        fields = {
            "kilnId": kiln_id,
            "schedNum": sched_num,
            "name": name,
            "stageCount": len(stages),
            "maxTemp": max_temp,
            "version": 1,
            "createdBy": "home_assistant",
            "stages": stages,
        }
        resp = await self._async_request(
            "POST",
            f"{FIRESTORE_BASE_URL}/schedules",
            json={"fields": _encode_fields(fields)},
        )
        if resp.status_code != 200:
            raise PolygonKilnsApiError(
                f"No se pudo crear el programa ({resp.status_code}): {resp.text}"
            )
        return _decode_document(resp.json())

    async def async_update_schedule(
        self, doc_id: str, fields: dict[str, Any]
    ) -> dict[str, Any]:
        """Update fields of a schedule document."""
        params = [("updateMask.fieldPaths", key) for key in fields]
        resp = await self._async_request(
            "PATCH",
            f"{FIRESTORE_BASE_URL}/schedules/{doc_id}",
            params=params,
            json={"fields": _encode_fields(fields)},
        )
        if resp.status_code != 200:
            raise PolygonKilnsApiError(
                f"No se pudo actualizar el programa ({resp.status_code}): {resp.text}"
            )
        return _decode_document(resp.json())

    async def async_delete_schedule(self, doc_id: str) -> None:
        """Delete a schedule document."""
        resp = await self._async_request(
            "DELETE", f"{FIRESTORE_BASE_URL}/schedules/{doc_id}"
        )
        if resp.status_code != 200:
            raise PolygonKilnsApiError(
                f"No se pudo borrar el programa ({resp.status_code}): {resp.text}"
            )

    async def async_stop_kiln(self, kiln_id: str) -> None:
        """Request a stop by setting ``stopRequested`` on the kiln document."""
        resp = await self._async_request(
            "PATCH",
            f"{FIRESTORE_BASE_URL}/kilns/{kiln_id}",
            params=[("updateMask.fieldPaths", "stopRequested")],
            json={"fields": {"stopRequested": {"booleanValue": True}}},
        )
        if resp.status_code != 200:
            raise PolygonKilnsApiError(
                f"No se pudo detener el horno ({resp.status_code}): {resp.text}"
            )

    async def async_request_start(self, kiln_id: str, sched_num: int) -> None:
        """Ask the backend to start a program on a kiln.

        The Cloud Function answers 500 with ``{"ok": false, "error": ...}``
        for business errors, so the body is parsed even on failure.
        """
        resp = await self._async_request(
            "POST",
            REQUEST_START_URL,
            json={"kilnId": kiln_id, "schedNum": sched_num},
        )
        if resp.status_code == 200:
            return
        detail = resp.text
        try:
            detail = resp.json().get("error", resp.text)
        except ValueError:
            pass
        raise PolygonKilnsApiError(
            f"El backend rechazó el inicio ({resp.status_code}): {detail}"
        )


def _session_from_auth_response(data: dict[str, Any]) -> AuthSession:
    """Build a session from a signInWithPassword response."""
    return AuthSession(
        uid=data["localId"],
        id_token=data["idToken"],
        refresh_token=data["refreshToken"],
        expires_at=datetime.now(UTC) + timedelta(seconds=int(data["expiresIn"])),
    )


def _firebase_error_message(resp: httpx.Response) -> str:
    """Extract a human-readable error from a Firebase Auth response."""
    try:
        return resp.json()["error"]["message"]
    except (ValueError, KeyError):
        return f"HTTP {resp.status_code}"
