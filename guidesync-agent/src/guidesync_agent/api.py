from __future__ import annotations

import argparse
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import Response

from guidesync_agent.app_logging import configure_logging
from guidesync_agent.auth import basic_auth_response, request_is_authorized
from guidesync_agent.config import cors_config
from guidesync_agent.routes import router
from guidesync_agent.storage import initialize_storage


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    initialize_storage()
    yield


app = FastAPI(title="GuideSync Agent", version="0.1.0", lifespan=lifespan)


@app.middleware("http")
async def protect_deployed_app(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    if request.method == "OPTIONS":
        return await call_next(request)
    if request.url.path != "/health" and not request_is_authorized(request):
        return basic_auth_response()
    return await call_next(request)


cors = cors_config()
if cors.origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors.origins,
        allow_credentials=cors.allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )


app.include_router(router)


def main() -> None:
    parser = argparse.ArgumentParser(description="Start the GuideSync Agent FastAPI app.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8770, type=int)
    args = parser.parse_args()
    uvicorn.run("guidesync_agent.api:app", host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    main()
