"""Async HTTP + WebSocket client for the koto FastAPI server.

Independent of Textual: can be used standalone (e.g. for smoke tests).
"""

from __future__ import annotations

import asyncio
import json
import random
from typing import Any, AsyncIterator, Optional

import httpx
import websockets


class KotoApiError(Exception):
    def __init__(self, status: int, detail: Any):
        self.status = status
        self.detail = detail
        super().__init__(f"{status}: {detail}")


class KotoClient:
    def __init__(self, base_url: str, token: str, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.client_id: Optional[str] = None
        self._client_id_ready = asyncio.Event()
        self._http = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    # ----- internal -----

    def _headers(self, *, mutating: bool) -> dict:
        h = {"Authorization": f"Bearer {self.token}"}
        if mutating and self.client_id:
            h["X-Client-Id"] = self.client_id
        return h

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        mutating: bool = False,
    ) -> Any:
        # For mutations, wait briefly for the WS hello so we can include
        # X-Client-Id and avoid being broadcast our own change. Bounded so
        # we never block when the WS is unavailable.
        if mutating and not self.client_id:
            try:
                await asyncio.wait_for(self._client_id_ready.wait(), timeout=0.5)
            except asyncio.TimeoutError:
                pass  # proceed without client_id; harmless echo
        try:
            r = await self._http.request(
                method, path, json=json_body, headers=self._headers(mutating=mutating)
            )
        except httpx.HTTPError as e:
            raise KotoApiError(0, f"network error: {e}") from e
        if r.status_code == 204:
            return None
        if not r.is_success:
            try:
                detail = r.json().get("detail", r.text)
            except Exception:
                detail = r.text
            raise KotoApiError(r.status_code, detail)
        return r.json()

    # ----- workspaces -----

    async def list_workspaces(self) -> list[dict]:
        return await self._request("GET", "/api/workspaces")

    async def create_workspace(
        self, description: str, parent_id: Optional[int] = None
    ) -> dict:
        body = {"description": description}
        if parent_id is not None:
            body["parent_id"] = parent_id
        return await self._request(
            "POST", "/api/workspaces", json_body=body, mutating=True
        )

    async def update_workspace(self, workspace_id: int, **fields) -> dict:
        return await self._request(
            "PATCH",
            f"/api/workspaces/{workspace_id}",
            json_body=fields,
            mutating=True,
        )

    async def delete_workspace(self, workspace_id: int) -> None:
        await self._request(
            "DELETE", f"/api/workspaces/{workspace_id}", mutating=True
        )

    async def reorder_workspace(self, workspace_id: int, direction: str) -> None:
        await self._request(
            "POST",
            f"/api/workspaces/{workspace_id}/reorder",
            json_body={"direction": direction},
            mutating=True,
        )

    # ----- todos -----

    async def list_todos(self, workspace_id: int) -> list[dict]:
        return await self._request("GET", f"/api/todos/workspace/{workspace_id}")

    async def get_todo(self, todo_id: int) -> dict:
        return await self._request("GET", f"/api/todos/{todo_id}")

    async def create_todo(
        self,
        description: str,
        *,
        parent_workspace_id: Optional[int] = None,
        parent_todo_id: Optional[int] = None,
    ) -> dict:
        body = {"description": description}
        if parent_workspace_id is not None:
            body["parent_workspace_id"] = parent_workspace_id
        if parent_todo_id is not None:
            body["parent_todo_id"] = parent_todo_id
        return await self._request("POST", "/api/todos", json_body=body, mutating=True)

    async def update_todo(self, todo_id: int, fields: dict) -> dict:
        """`fields` should contain only keys the user actually changed.
        Use `None` for nullable fields the user wants to clear (e.g. `due`)."""
        return await self._request(
            "PATCH", f"/api/todos/{todo_id}", json_body=fields, mutating=True
        )

    async def delete_todo(self, todo_id: int) -> None:
        await self._request("DELETE", f"/api/todos/{todo_id}", mutating=True)

    async def toggle_todo(self, todo_id: int) -> dict:
        return await self._request(
            "POST", f"/api/todos/{todo_id}/toggle", mutating=True
        )

    async def reorder_todo(self, todo_id: int, direction: str) -> None:
        await self._request(
            "POST",
            f"/api/todos/{todo_id}/reorder",
            json_body={"direction": direction},
            mutating=True,
        )

    async def sort_workspace_completed(self, workspace_id: int) -> None:
        await self._request(
            "POST",
            f"/api/todos/workspace/{workspace_id}/sort_completed",
            mutating=True,
        )

    async def sort_todo_completed(self, todo_id: int) -> None:
        await self._request(
            "POST", f"/api/todos/{todo_id}/sort_completed", mutating=True
        )

    # ----- websocket -----

    def _ws_url(self) -> str:
        scheme = "wss" if self.base_url.startswith("https") else "ws"
        host = self.base_url.split("://", 1)[1]
        params = f"token={self.token}"
        if self.client_id:
            params += f"&client_id={self.client_id}"
        return f"{scheme}://{host}/ws?{params}"

    async def watch_refresh(
        self, on_connect=None, on_disconnect=None
    ) -> AsyncIterator[None]:
        """Connect to the WS endpoint and yield once per `refresh` push.

        Auto-reconnects with exponential backoff (matches the web client:
        base*2^attempt capped at 30s + 30% jitter). Sets `self.client_id`
        from the initial `hello` message.

        `on_disconnect` is edge-triggered: it fires only on the connected→
        disconnected transition, not on every retry attempt during a long
        outage. Initial-connect failures (no prior connect) don't toast.
        """
        attempt = 0
        currently_connected = False
        while True:
            try:
                async with websockets.connect(self._ws_url()) as ws:
                    attempt = 0
                    currently_connected = True
                    if on_connect:
                        on_connect()
                    async for raw in ws:
                        msg = json.loads(raw)
                        t = msg.get("type")
                        if t == "hello":
                            self.client_id = msg.get("client_id")
                            self._client_id_ready.set()
                        elif t == "refresh":
                            yield
            except (
                websockets.ConnectionClosed,
                OSError,
                asyncio.TimeoutError,
            ):
                pass
            # Edge-trigger: only fire on_disconnect on the first failure
            # after a successful connect.
            if currently_connected and on_disconnect:
                on_disconnect()
            currently_connected = False
            base = min(2 ** attempt, 30)
            jitter = random.random() * 0.3 * base
            await asyncio.sleep(base + jitter)
            attempt += 1
