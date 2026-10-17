import logging

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from postgrest.exceptions import APIError
from storage3.exceptions import StorageApiError

from app import __version__
from app.api import amazon, cycles, export, files, invoices, matching, me, results, statement
from app.config import get_settings

settings = get_settings()
log = logging.getLogger("app")

app = FastAPI(
    title="Reconcile API",
    version=__version__,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(APIError)
@app.exception_handler(StorageApiError)
async def upstream_error(request: Request, exc: Exception) -> JSONResponse:
    # The database or storage service refused a call. Log the detail; show a generic message.
    log.error("Upstream error on %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(status_code=502, content={"detail": "The data service returned an error. Please try again."})


api = APIRouter(prefix="/api")


@api.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


api.include_router(me.router)
api.include_router(cycles.router)
api.include_router(files.router)
api.include_router(statement.router)
api.include_router(invoices.router)
api.include_router(amazon.router)
api.include_router(matching.router)
api.include_router(results.router)
api.include_router(export.router)

app.include_router(api)
