import asyncio
import hmac
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from .config import settings
from .database import init_db
from .routes.todos import router as todos_router
from .routes.workspaces import router as workspaces_router
from .ws import ws_manager


def _ws_token_ok(presented: str) -> bool:
    expected = settings.token
    if not expected:
        return False
    return hmac.compare_digest(presented.encode("utf-8"), expected.encode("utf-8"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    ws_manager.set_loop(asyncio.get_running_loop())
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="koto", lifespan=lifespan)

    app.include_router(workspaces_router)
    app.include_router(todos_router)

    @app.websocket("/ws")
    async def websocket_endpoint(
        websocket: WebSocket,
        token: str = Query(...),
        client_id: Optional[str] = Query(default=None),
    ):
        if not _ws_token_ok(token):
            # Accept first so the close code (4001) is delivered to the
            # client. Closing pre-accept makes Starlette return HTTP 403
            # and the close code is lost.
            await websocket.accept()
            await websocket.close(code=4001, reason="Invalid token")
            return
        cid = client_id or ws_manager.new_client_id()
        await ws_manager.connect(websocket, cid)
        try:
            # Send the assigned id so the client can echo it back on mutations.
            await websocket.send_text(
                json.dumps({"type": "hello", "client_id": cid})
            )
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            ws_manager.disconnect(websocket)

    static_dir = Path(__file__).parent / "static"
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app
