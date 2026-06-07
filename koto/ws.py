import asyncio
import json
import secrets
from typing import List, Optional, Tuple

from fastapi import WebSocket


class ConnectionManager:
    """Manages WebSocket connections and broadcasts.

    `broadcast_threadsafe` lets sync code (FastAPI sync routes running in the
    threadpool) schedule a broadcast on the running event loop without blocking.
    """

    def __init__(self):
        self._connections: List[Tuple[str, WebSocket]] = []
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    @staticmethod
    def new_client_id() -> str:
        return secrets.token_urlsafe(16)

    async def connect(self, websocket: WebSocket, client_id: str) -> None:
        await websocket.accept()
        self._connections.append((client_id, websocket))

    def disconnect(self, websocket: WebSocket) -> None:
        self._connections = [
            (cid, ws) for cid, ws in self._connections if ws is not websocket
        ]

    async def broadcast(self, message: dict, skip_client_id: Optional[str] = None) -> None:
        data = json.dumps(message)
        dead = []
        for cid, ws in self._connections:
            if skip_client_id and cid == skip_client_id:
                continue
            try:
                await ws.send_text(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    def broadcast_threadsafe(
        self, message: dict, skip_client_id: Optional[str] = None
    ) -> None:
        """Schedule a broadcast on the event loop from a sync context."""
        loop = self._loop
        if loop is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(
                self.broadcast(message, skip_client_id=skip_client_id), loop
            )
        except RuntimeError:
            # Loop closed between check and submit — ignore.
            pass


ws_manager = ConnectionManager()
