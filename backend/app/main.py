from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.api.analysis import router as analysis_router
from app.api.projects import router
from app.body_limit import BodyLimitMiddleware
from app.config import get_settings
from app.services.ollama import LLMError

app = FastAPI(title="BA Agent", version="0.1.0")
app.add_middleware(BodyLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
app.include_router(router, prefix="/api")
app.include_router(analysis_router, prefix="/api")


@app.exception_handler(LLMError)
async def llm_error(request: Request, exc: LLMError) -> JSONResponse:
    return JSONResponse(status_code=exc.status, content={"detail": exc.message, "code": exc.code})


@app.exception_handler(RequestValidationError)
async def invalid_request(request: Request, exc: RequestValidationError) -> JSONResponse:
    # Do not echo submitted requirements or credentials from validation inputs.
    return JSONResponse(status_code=422, content={"detail": "Invalid request data"})


@app.exception_handler(SQLAlchemyError)
async def database_error(request: Request, exc: SQLAlchemyError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": "Database unavailable"})


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
