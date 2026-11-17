"""Dedicated public entry point for metered quote APIs."""
from contextlib import asynccontextmanager
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from web import market_cloud


@asynccontextmanager
async def lifespan(app: FastAPI):
    await market_cloud.start_market_cloud()
    try:
        yield
    finally:
        await market_cloud.stop_market_cloud()


app = FastAPI(title="量测实时行情 API", version="1.0.0", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1024)
origins = [value.strip().rstrip("/") for value in os.getenv("LIANGCE_ALLOWED_ORIGINS", "").split(",") if value.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
    allow_credentials=False,
)
app.include_router(market_cloud.router)


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/")
def root():
    return {"service": "quant-market-api", "status": "ok", "docs": "/docs", "health": "/api/v1/health"}
