from __future__ import annotations

import time
from typing import Any

import requests

from app.config import settings


class ApiError(RuntimeError):
    def __init__(self, status_code: int, message: str, *, payload: Any | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


class ClashApiClient:
    def __init__(self, token: str, base_url: str) -> None:
        self.token = token.strip()
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/json",
                "Authorization": f"Bearer {self.token}",
            }
        )

    def _request(self, path: str, params: dict[str, Any] | None = None) -> Any:
        if not self.token:
            raise ApiError(500, "API_TOKEN is not configured")

        url = f"{self.base_url}/{path.lstrip('/')}"
        delay = settings.request_initial_delay_seconds
        attempts = max(1, settings.max_retries)

        for attempt in range(1, attempts + 1):
            try:
                response = self.session.get(url, params=params, timeout=settings.request_timeout_seconds)
            except requests.RequestException as exc:
                if attempt < attempts:
                    time.sleep(min(delay, settings.max_backoff_seconds))
                    delay = max(settings.retry_min_delay_seconds, min(delay * 2, settings.max_backoff_seconds))
                    continue
                raise ApiError(502, str(exc)) from exc
            if response.ok:
                if not response.text.strip():
                    return {}
                return response.json()

            if response.status_code in {429, 500, 502, 503, 504} and attempt < attempts:
                retry_after = response.headers.get("Retry-After")
                if retry_after and retry_after.isdigit():
                    delay = max(delay, float(retry_after))
                time.sleep(min(delay, settings.max_backoff_seconds))
                delay = max(settings.retry_min_delay_seconds, min(delay * 2, settings.max_backoff_seconds))
                continue

            snippet_limit = (
                settings.api_error_snippet_server
                if response.status_code >= 500
                else settings.api_error_snippet_generic
            )
            payload: Any | None = None
            message = ""
            try:
                payload = response.json()
            except ValueError:
                payload = None
            if isinstance(payload, dict):
                message_value = payload.get("message")
                if isinstance(message_value, str):
                    message = message_value.strip()
            if not message:
                message = response.text[:snippet_limit] or response.reason
            raise ApiError(response.status_code, message, payload=payload)

        raise ApiError(500, "Request failed after retries")

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return self._request(path, params=params)

    def get_items_paginated(self, path: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        merged_params = dict(params or {})
        merged_params.setdefault("limit", settings.api_page_limit)
        items: list[dict[str, Any]] = []
        after: str | None = None

        while True:
            current_params = dict(merged_params)
            if after:
                current_params["after"] = after

            payload = self.get(path, params=current_params)
            page_items = payload.get("items", []) if isinstance(payload, dict) else payload
            if not isinstance(page_items, list):
                break
            items.extend(item for item in page_items if isinstance(item, dict))

            paging = payload.get("paging", {}) if isinstance(payload, dict) else {}
            cursors = paging.get("cursors", {}) if isinstance(paging, dict) else {}
            after = cursors.get("after") if isinstance(cursors, dict) else None
            if not after:
                break

        return items
