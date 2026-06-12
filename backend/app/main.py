import asyncio

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger

from app.api.routes import router
from app.core.exceptions import MediBotException
from app.core.logging import setup_logging
from app.ingestion.embedder import _get_model as _load_embedder
from app.retrieval.reranker import _get_model as _load_reranker

setup_logging()

app = FastAPI(
    title="MediBot API",
    description="Advanced RAG backend for MediAssist Health Network",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(MediBotException)
async def mediBot_exception_handler(request: Request, exc: MediBotException):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.on_event("startup")
async def warm_models():
    logger.info("Pre-loading embedding model...")
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _load_embedder)
    logger.info("Embedding model loaded")

    logger.info("Pre-loading reranker model...")
    await loop.run_in_executor(None, _load_reranker)
    logger.info("Reranker model loaded — server ready")

    logger.info("Starting conversation cleanup task...")
    from app.core.cleanup import cleanup_old_conversations
    asyncio.create_task(cleanup_old_conversations())
    logger.info("Cleanup task started")


app.include_router(router, prefix="/api/v1")
