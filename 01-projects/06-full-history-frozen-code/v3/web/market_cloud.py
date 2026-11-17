"""Commercial-facing batch quote API over the existing market gateway."""
from __future__ import annotations

import asyncio
import base64
from contextlib import contextmanager
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import sqlite3
import time
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query, Request as HTTPRequest, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

log = logging.getLogger("liangce.market_cloud")
router = APIRouter(prefix="/api/v1", tags=["market-cloud"])
SYMBOL_RE = re.compile(r"^(?:\d{6}\.(?:SH|SZ|BJ)|(?:SH|SZ|BJ)\d{6})$", re.I)
MAX_BATCH = 200
MAX_UNIVERSE = 6000
MAX_CACHE_SYMBOLS = MAX_UNIVERSE + MAX_BATCH
_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_received_at: dict[str, str] = {}
_demand: dict[str, float] = {}
_collector_wakeup: asyncio.Event | None = None
_fetch_lock = asyncio.Lock()
_rates: dict[str, deque[float]] = defaultdict(deque)
_monthly_usage: dict[tuple[str, str], int] = defaultdict(int)
_tickets: dict[str, tuple[tuple[str, dict[str, Any]], float]] = {}
_stream_counts: dict[str, int] = defaultdict(int)
_collector: asyncio.Task | None = None
_history_writer: asyncio.Task | None = None
_history_queue: asyncio.Queue[tuple[str, dict[str, dict[str, Any]]]] | None = None
_history_dropped = 0
_history_written = 0
_history_failed = 0
_last_storage_error: str | None = None
_history_store_ready = False
_last_refresh_at = 0.0
_last_refresh_ms = 0.0
_last_provider_error: str | None = None
_stock_name_map: dict[str, str] | None = None
_market_symbols: list[str] | None = None
_stock_api_kline_cache: dict[tuple[str, str, int, str], tuple[float, dict[str, Any]]] = {}
_collection: dict[str, Any] = {"state": "not_started", "pass_id": 0, "requested": 0,
                               "returned": 0, "missing": [], "failed_shards": 0,
                               "duration_ms": None, "completed_at_utc": None}
_collection_progress: dict[str, int] = {"pass_id": 0, "processed": 0, "requested": 0}


class BatchRequest(BaseModel):
    symbols: list[str] = Field(min_length=1, max_length=MAX_BATCH)


class NewApiKeyRequest(BaseModel):
    key_id: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    plan: str = Field(min_length=1, max_length=40)
    rpm: int = Field(default=60, ge=1, le=600)
    max_symbols: int = Field(default=50, ge=1, le=MAX_BATCH)
    max_streams: int = Field(default=3, ge=1, le=20)
    monthly_symbols: int = Field(default=100_000, ge=1, le=100_000_000)
    expires_at: datetime | None = None


def _auth_db_path() -> Path:
    return Path(os.getenv("QUANT_AUTH_DB", str(Path(__file__).resolve().parents[1] / ".runtime/market-cloud/auth.sqlite3")))


def _auth_connect() -> sqlite3.Connection:
    path = _auth_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=5000")
    return connection


@contextmanager
def _auth_session():
    connection = _auth_connect()
    try:
        yield connection
    except Exception:
        connection.rollback()
        raise
    else:
        connection.commit()
    finally:
        connection.close()


def _init_auth_store() -> None:
    with _auth_session() as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("""CREATE TABLE IF NOT EXISTS api_keys (
            key_id TEXT PRIMARY KEY,
            secret_hash TEXT NOT NULL UNIQUE,
            plan TEXT NOT NULL,
            rpm INTEGER NOT NULL CHECK(rpm > 0),
            max_symbols INTEGER NOT NULL CHECK(max_symbols > 0),
            max_streams INTEGER NOT NULL DEFAULT 3 CHECK(max_streams > 0),
            monthly_symbols INTEGER NOT NULL CHECK(monthly_symbols > 0),
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            expires_at TEXT
        )""")
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(api_keys)")}
        if "max_streams" not in columns:
            connection.execute("ALTER TABLE api_keys ADD COLUMN max_streams INTEGER NOT NULL DEFAULT 3")
        connection.execute("""CREATE TABLE IF NOT EXISTS api_usage (
            key_id TEXT NOT NULL,
            month TEXT NOT NULL,
            symbols INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(key_id, month)
        )""")
        connection.execute("""CREATE TABLE IF NOT EXISTS api_rate_usage (
            key_id TEXT NOT NULL,
            minute_epoch INTEGER NOT NULL,
            requests INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(key_id, minute_epoch)
        )""")


def _api_keys() -> dict[str, dict[str, Any]]:
    raw = os.getenv("QUANT_API_KEYS_JSON", "").strip()
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("QUANT_API_KEYS_JSON must be valid JSON") from exc
    if not isinstance(value, dict):
        raise RuntimeError("QUANT_API_KEYS_JSON must be an object")
    records = {
        str(key_id): record
        for key_id, record in value.items()
        if isinstance(record, dict) and isinstance(record.get("secret"), str) and record["secret"]
    }
    if len(records) != len(value):
        raise RuntimeError("Each API key record must contain a non-empty secret")
    for key_id, record in records.items():
        if len(record["secret"]) < 32:
            raise RuntimeError(f"API key secret for {key_id} must be at least 32 characters")
        for field in ("rpm", "max_symbols", "max_streams", "monthly_symbols"):
            if field in record and (not isinstance(record[field], int) or record[field] < 1):
                raise RuntimeError(f"API key field {field} for {key_id} must be a positive integer")
        if "plan" in record and not isinstance(record["plan"], str):
            raise RuntimeError(f"API key plan for {key_id} must be a string")
    return records


def _principal(secret: str) -> tuple[str, dict[str, Any]] | None:
    supplied = hashlib.sha256(secret.encode("utf-8")).digest()
    for key_id, record in _api_keys().items():
        candidate = str(record["secret"])
        if hmac.compare_digest(supplied, hashlib.sha256(candidate.encode("utf-8")).digest()):
            if record.get("active", True):
                return key_id, record
    digest = supplied.hex()
    with _auth_session() as connection:
        record = connection.execute(
            "SELECT key_id, plan, rpm, max_symbols, max_streams, monthly_symbols, active, expires_at FROM api_keys WHERE secret_hash=?",
            (digest,),
        ).fetchone()
    if record and record["active"]:
        expiry = record["expires_at"]
        if not expiry or expiry > datetime.now(timezone.utc).isoformat():
            return record["key_id"], {
                "plan": record["plan"], "rpm": record["rpm"], "max_symbols": record["max_symbols"],
                "max_streams": record["max_streams"], "monthly_symbols": record["monthly_symbols"], "_source": "sqlite",
            }
    return None


def _authenticate(authorization: str | None) -> tuple[str, dict[str, Any]]:
    if os.getenv("QUANT_AUTH_DISABLED") == "1":
        return "local-test", {"plan": "local", "rpm": 600, "max_symbols": MAX_BATCH, "max_streams": 20, "monthly_symbols": 10**9}
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Bearer API key required", headers={"WWW-Authenticate": "Bearer"})
    principal = _principal(authorization[7:].strip())
    if principal is None:
        raise HTTPException(401, "Invalid or inactive API key", headers={"WWW-Authenticate": "Bearer"})
    return principal


def _charge(key_id: str, record: dict[str, Any], symbol_count: int) -> None:
    if record.get("_source") == "sqlite":
        now = datetime.now(timezone.utc)
        minute_epoch = int(now.timestamp() // 60)
        month = now.astimezone(timezone(timedelta(hours=8))).strftime("%Y-%m")
        try:
            with _auth_session() as connection:
                connection.execute("BEGIN IMMEDIATE")
                key = connection.execute(
                    "SELECT active, rpm, monthly_symbols, expires_at FROM api_keys WHERE key_id=?", (key_id,)
                ).fetchone()
                if not key or not key["active"] or (key["expires_at"] and key["expires_at"] <= now.isoformat()):
                    connection.rollback()
                    raise HTTPException(401, "API key is inactive or expired")
                rate = connection.execute(
                    "SELECT requests FROM api_rate_usage WHERE key_id=? AND minute_epoch=?",
                    (key_id, minute_epoch),
                ).fetchone()
                requests = (rate["requests"] if rate else 0) + 1
                usage = connection.execute(
                    "SELECT symbols FROM api_usage WHERE key_id=? AND month=?", (key_id, month)
                ).fetchone()
                used_symbols = usage["symbols"] if usage else 0
                if requests > key["rpm"]:
                    connection.execute(
                        "INSERT INTO api_rate_usage(key_id,minute_epoch,requests) VALUES(?,?,?) "
                        "ON CONFLICT(key_id,minute_epoch) DO UPDATE SET requests=excluded.requests",
                        (key_id, minute_epoch, requests),
                    )
                    connection.commit()
                    raise HTTPException(429, "Rate limit exceeded", headers={"Retry-After": "60"})
                if used_symbols + symbol_count > key["monthly_symbols"]:
                    connection.execute(
                        "INSERT INTO api_rate_usage(key_id,minute_epoch,requests) VALUES(?,?,?) "
                        "ON CONFLICT(key_id,minute_epoch) DO UPDATE SET requests=excluded.requests",
                        (key_id, minute_epoch, requests),
                    )
                    connection.commit()
                    raise HTTPException(429, "Monthly symbol quota exceeded")
                connection.execute(
                    "INSERT INTO api_rate_usage(key_id,minute_epoch,requests) VALUES(?,?,?) "
                    "ON CONFLICT(key_id,minute_epoch) DO UPDATE SET requests=excluded.requests",
                    (key_id, minute_epoch, requests),
                )
                connection.execute(
                    "INSERT INTO api_usage(key_id,month,symbols) VALUES(?,?,?) "
                    "ON CONFLICT(key_id,month) DO UPDATE SET symbols=excluded.symbols",
                    (key_id, month, used_symbols + symbol_count),
                )
                connection.execute("DELETE FROM api_rate_usage WHERE minute_epoch < ?", (minute_epoch - 1440,))
                connection.commit()
            return
        except sqlite3.Error as exc:
            raise HTTPException(503, "API quota store is unavailable") from exc
    now = time.monotonic()
    window = _rates[key_id]
    while window and now - window[0] >= 60:
        window.popleft()
    rpm = max(1, min(int(record.get("rpm", 60)), 600))
    if len(window) >= rpm:
        raise HTTPException(429, "Rate limit exceeded", headers={"Retry-After": "60"})
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    usage_key = (key_id, month)
    monthly_limit = max(1, int(record.get("monthly_symbols", 100_000)))
    if _monthly_usage[usage_key] + symbol_count > monthly_limit:
        raise HTTPException(429, "Monthly symbol quota exceeded")
    window.append(now)
    _monthly_usage[usage_key] += symbol_count


def _normalize_symbols(symbols: list[str], record: dict[str, Any], *, hard_limit: int = MAX_BATCH) -> list[str]:
    maximum = max(1, min(int(record.get("max_symbols", 50)), hard_limit))
    unique = list(dict.fromkeys(symbol.strip().upper() for symbol in symbols))
    if len(unique) > maximum:
        raise HTTPException(413, f"This plan allows at most {maximum} symbols per batch")
    invalid = [symbol for symbol in unique if not SYMBOL_RE.fullmatch(symbol)]
    if invalid:
        raise HTTPException(422, f"Invalid symbols: {', '.join(invalid[:5])}")
    return list(dict.fromkeys(value if '.' in value else value[2:] + '.' + value[:2] for value in unique))


def _provider_name() -> str:
    configured = os.getenv("QUANT_PROVIDER", "auto").strip().lower()
    has_tdx = bool(os.getenv("LIANGCE_TDX_API") or os.getenv("LIANGCE_TDX_BINARY"))
    if configured == "auto":
        return "tdx" if has_tdx else "market-gateway"
    if configured not in {"tdx", "market-gateway", "stock-api"}:
        raise RuntimeError("QUANT_PROVIDER must be auto, tdx, market-gateway, or stock-api")
    return configured


def _provider_label() -> str:
    explicit = os.getenv("QUANT_PROVIDER_NAME", "").strip()
    if explicit:
        return explicit
    return {"tdx": "tdx-local", "stock-api": "stock-api/tencent", "market-gateway": "market-gateway"}[_provider_name()]


def _stock_api_origin() -> str:
    return os.getenv("STOCK_API_URL", "http://127.0.0.1:8812").strip().rstrip("/")


def _provider_supports_symbol(symbol: str) -> bool:
    if _provider_name() == "stock-api":
        return symbol.endswith((".SH", ".SZ"))
    return True


def _supported_universe(symbols: list[str]) -> list[str]:
    if _provider_name() == "stock-api":
        return [symbol for symbol in symbols if symbol.endswith((".SH", ".SZ"))]
    return symbols


def _stock_api_post(path: str, payload: dict[str, Any]) -> tuple[dict[str, Any], float]:
    body = json.dumps(payload, separators=(",", ":")).encode()
    request = Request(
        _stock_api_origin() + path,
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    timeout = max(.2, min(float(os.getenv("STOCK_API_TIMEOUT_SECONDS", "8")), 30))
    started = time.perf_counter()
    with urlopen(request, timeout=timeout) as response:
        result = json.loads(response.read())
    elapsed_ms = (time.perf_counter() - started) * 1000
    if not isinstance(result, dict):
        raise RuntimeError("stock-api bridge returned a non-object response")
    return result, elapsed_ms


def _stock_api_fetch_chunk(symbols: list[str]) -> dict[str, dict[str, Any]]:
    codes = [symbol.split(".")[1] + symbol.split(".")[0] for symbol in symbols]
    result, _ = _stock_api_post("/v1/quotes/batch", {"codes": codes})
    rows = result.get("quotes")
    if not isinstance(rows, list):
        raise RuntimeError("stock-api bridge response has no quotes list")
    requested = set(symbols)
    normalized: dict[str, dict[str, Any]] = {}
    received_ms = int(time.time() * 1000)
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = str(row.get("code", "")).upper()
        if len(code) < 3 or code[:2] not in {"SH", "SZ"}:
            continue
        symbol = code[2:] + "." + code[:2]
        if symbol not in requested or symbol in normalized:
            continue
        price = float(row.get("now") or 0)
        previous_close = float(row.get("yesterday") or 0)
        if price <= 0:
            continue
        bids = [{"level": index, "price": None, "volume": None} for index in range(1, 6)]
        asks = [{"level": index, "price": None, "volume": None} for index in range(1, 6)]
        normalized[symbol] = {
            "symbol": symbol, "code": code[2:], "market": code[:2], "name": row.get("name") or code[2:],
            "price": price, "prevClose": previous_close or None,
            "open": None, "high": float(row["high"]) if row.get("high") is not None else None,
            "low": float(row["low"]) if row.get("low") is not None else None,
            "change": round(price - previous_close, 4) if previous_close else None,
            "changePercent": round(float(row.get("percent") or 0) * 100, 4),
            "volume": None, "amount": None, "limitUpPrice": None, "limitDownPrice": None,
            "phase": "UNKNOWN", "orderBook": {"bids": bids, "asks": asks}, "recentTrades": [],
            "source": "stock-api/tencent", "sourceTimestamp": None,
            "sourceTimestampQuality": "not_provided_by_library", "exchangeTimestampVerified": False,
            "quoteTime": None, "updatedAt": received_ms,
        }
    return normalized


def _stock_api_fetch(symbols: list[str]) -> dict[str, dict[str, Any]]:
    chunks = [symbols[index:index + 50] for index in range(0, len(symbols), 50)]
    if len(chunks) < 2:
        return _stock_api_fetch_chunk(chunks[0]) if chunks else {}
    workers = max(1, min(int(os.getenv("STOCK_API_WORKERS", "3")), 3, len(chunks)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(_stock_api_fetch_chunk, chunks))
    merged: dict[str, dict[str, Any]] = {}
    for batch in results:
        merged.update(batch)
    return merged


def _stock_api_klines(code: str, period: str, count: int, adjust: str) -> dict[str, Any]:
    key = (code, period, count, adjust)
    cached = _stock_api_kline_cache.get(key)
    now = time.monotonic()
    ttl = 60 if period == "day" else 300
    if cached and now - cached[0] < ttl:
        return {**cached[1], "cache_age_ms": round((now - cached[0]) * 1000, 1)}
    request_code = code.split(".")[1] + code.split(".")[0]
    result, provider_ms = _stock_api_post(
        "/v1/klines", {"code": request_code, "period": period, "count": count, "adjust": adjust}
    )
    klines = result.get("klines")
    if not isinstance(klines, list):
        raise RuntimeError("stock-api bridge returned an invalid K-line payload")
    payload = {
        "symbol": code, "period": period, "adjust": adjust, "requested_count": count,
        "returned_count": len(klines), "history_complete": False,
        "coverage": "provider-returned rows only; listing-inception or complete-history coverage is not guaranteed",
        "provider": result.get("source", "stock-api/tencent"), "provider_latency_ms": round(provider_ms, 3),
        "received_at_utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "exchange_timestamp_verified": False, "klines": klines,
    }
    _stock_api_kline_cache[key] = (time.monotonic(), payload)
    _prune_stock_api_kline_cache()
    return {**payload, "cache_age_ms": 0}


def _prune_stock_api_kline_cache(limit: int = 512) -> None:
    now = time.monotonic()
    for key, (stamp, _) in list(_stock_api_kline_cache.items()):
        ttl = 60 if key[1] == "day" else 300
        if now - stamp > ttl:
            _stock_api_kline_cache.pop(key, None)
    if len(_stock_api_kline_cache) > limit:
        oldest = sorted(_stock_api_kline_cache, key=lambda key: _stock_api_kline_cache[key][0])
        for key in oldest[:len(_stock_api_kline_cache) - limit]:
            _stock_api_kline_cache.pop(key, None)


def _tdx_api_origin() -> str:
    origin = os.getenv("LIANGCE_TDX_API", "").strip().rstrip("/")
    if origin:
        return origin
    if os.getenv("LIANGCE_TDX_BINARY"):
        from web import tdx_provider
        return tdx_provider.rest_origin()
    raise RuntimeError("LIANGCE_TDX_API must point to a running local TDX quote bridge")


def _tdx_code(symbol: str) -> str:
    code, market = symbol.split(".")
    return market.lower() + code


def _tdx_price(value: Any) -> float | None:
    if value is None:
        return None
    result = float(value) / 1000
    return result if result > 0 else None


def _stock_name(code: str) -> str:
    global _stock_name_map
    if _stock_name_map is None:
        path = Path(__file__).resolve().parents[1] / "data/stock_names.json"
        try:
            names = json.loads(path.read_text(encoding="utf-8"))
            _stock_name_map = names if isinstance(names, dict) else {}
        except (OSError, json.JSONDecodeError):
            _stock_name_map = {}
    return str(_stock_name_map.get(code) or code).strip("\x00 ")


def _tdx_fetch_chunk(symbols: list[str]) -> dict[str, dict[str, Any]]:
    payload = json.dumps({"codes": [_tdx_code(symbol) for symbol in symbols]}, separators=(",", ":")).encode()
    request = Request(
        _tdx_api_origin() + "/api/batch-quote",
        data=payload,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    timeout = max(.2, min(float(os.getenv("QUANT_PROVIDER_TIMEOUT_SECONDS", "2.5")), 10))
    with urlopen(request, timeout=timeout) as response:
        envelope = json.loads(response.read())
    if not isinstance(envelope, dict) or envelope.get("code") != 0 or not isinstance(envelope.get("data"), list):
        raise RuntimeError("TDX quote bridge returned an invalid response envelope")
    result: dict[str, dict[str, Any]] = {}
    received_ms = int(time.time() * 1000)
    for row in envelope["data"]:
        if not isinstance(row, dict):
            continue
        market = {0: "SZ", 1: "SH", 2: "BJ"}.get(row.get("Exchange"))
        code = str(row.get("Code", ""))
        symbol = f"{code}.{market}" if market else None
        if symbol not in symbols or symbol in result:
            continue
        raw = row.get("K") or {}
        price = _tdx_price(raw.get("Close"))
        if price is None:
            continue
        prev_close = _tdx_price(raw.get("Last"))
        open_price = _tdx_price(raw.get("Open"))
        high = _tdx_price(raw.get("High"))
        low = _tdx_price(raw.get("Low"))
        change = price - prev_close if prev_close else 0.0
        change_percent = change / prev_close * 100 if prev_close else 0.0
        bids = [{"level": index + 1, "price": _tdx_price(item.get("Price")), "volume": int(item.get("Number", 0)) * 100}
                for index, item in enumerate((row.get("BuyLevel") or [])[:5])]
        asks = [{"level": index + 1, "price": _tdx_price(item.get("Price")), "volume": int(item.get("Number", 0)) * 100}
                for index, item in enumerate((row.get("SellLevel") or [])[:5])]
        bids.extend({"level": index + 1, "price": None, "volume": None} for index in range(len(bids), 5))
        asks.extend({"level": index + 1, "price": None, "volume": None} for index in range(len(asks), 5))
        result[symbol] = {
            "symbol": symbol, "code": code, "market": market, "name": _stock_name(code),
            "price": price, "prevClose": prev_close, "open": open_price, "high": high, "low": low,
            "change": round(change, 4), "changePercent": round(change_percent, 4),
            "volume": int(row.get("TotalHand") or 0) * 100, "amount": float(row.get("Amount") or 0),
            "limitUpPrice": None, "limitDownPrice": None, "phase": "TRADING",
            "orderBook": {"bids": bids, "asks": asks}, "recentTrades": [],
            "source": "tdx-local", "sourceServerTimeRaw": row.get("ServerTime"),
            "quoteTime": None, "updatedAt": received_ms,
        }
    return result


def _tdx_fetch(symbols: list[str]) -> dict[str, dict[str, Any]]:
    chunks = [symbols[index:index + 50] for index in range(0, len(symbols), 50)]
    if len(chunks) < 2:
        return _tdx_fetch_chunk(chunks[0]) if chunks else {}
    workers = max(1, min(int(os.getenv("QUANT_PROVIDER_WORKERS", "4")), 8, len(chunks)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(_tdx_fetch_chunk, chunks))
    merged: dict[str, dict[str, Any]] = {}
    for batch in results:
        merged.update(batch)
    return merged


def _provider_fetch(symbols: list[str]) -> dict[str, dict[str, Any]]:
    if _provider_name() == "stock-api":
        return _stock_api_fetch(symbols)
    if _provider_name() == "tdx":
        return _tdx_fetch(symbols)
    from web import market_gateway

    return market_gateway.fetch_level1_quotes(symbols) or {}


def _clickhouse_request(query: str, body: bytes | None = None) -> bytes:
    origin = os.getenv("QUANT_CLICKHOUSE_URL", "").rstrip("/")
    if not origin:
        raise RuntimeError("ClickHouse is not configured")
    parameters = {"database": os.getenv("QUANT_CLICKHOUSE_DATABASE", "quant"), "query": query}
    url = origin + "/?" + urlencode(parameters)
    request = Request(url, data=body if body is not None else b"", method="POST")
    user = os.getenv("QUANT_CLICKHOUSE_USER", "quant")
    password = os.getenv("QUANT_CLICKHOUSE_PASSWORD", "")
    if user:
        token = base64.b64encode(f"{user}:{password}".encode()).decode()
        request.add_header("Authorization", "Basic " + token)
    if body is not None:
        request.add_header("Content-Type", "application/x-ndjson")
    with urlopen(request, timeout=3) as response:
        return response.read()


def _init_history_store() -> None:
    _clickhouse_request(
        """CREATE TABLE IF NOT EXISTS quote_ticks (
            ts DateTime64(3, 'UTC') CODEC(Delta, ZSTD(3)),
            symbol LowCardinality(String),
            price Decimal(18, 6) CODEC(ZSTD(3)),
            volume UInt64 CODEC(Delta, ZSTD(3)),
            amount Decimal(24, 4) CODEC(ZSTD(3)),
            source_time LowCardinality(String),
            payload String CODEC(ZSTD(3))
        ) ENGINE=MergeTree
        PARTITION BY toYYYYMM(ts)
        ORDER BY (symbol, ts)
        TTL ts + INTERVAL 365 DAY DELETE
        SETTINGS index_granularity=8192"""
    )


def _persist_history_batches(batches: list[tuple[str, dict[str, dict[str, Any]]]]) -> None:
    if not os.getenv("QUANT_CLICKHOUSE_URL"):
        return
    rows = []
    for received, quotes in batches:
        for symbol, quote in quotes.items():
            try:
                price = float(quote.get("price") or 0)
                volume = max(0, int(float(quote.get("volume") or 0)))
                amount = float(quote.get("amount") or 0)
                if price <= 0:
                    continue
                rows.append(json.dumps({
                    "ts": received, "symbol": symbol, "price": price, "volume": volume,
                    "amount": amount, "source_time": str(quote.get("quoteTime") or ""),
                    "payload": json.dumps(quote, ensure_ascii=False, separators=(",", ":")),
                }, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
            except (TypeError, ValueError, OverflowError):
                continue
    if rows:
        _clickhouse_request("INSERT INTO quote_ticks FORMAT JSONEachRow", ("\n".join(rows) + "\n").encode())


def _cached_quote(symbol: str) -> dict[str, Any] | None:
    item = _cache.get(symbol)
    ttl = max(50, min(int(os.getenv("QUANT_CACHE_MS", "250")), 5000)) / 1000
    if item and time.monotonic() - item[0] <= ttl:
        return item[1]
    return None


def _prune_cache() -> None:
    if len(_cache) <= MAX_CACHE_SYMBOLS:
        return
    # A stale snapshot remains useful during an upstream outage. Evict only
    # when capacity is exceeded, instead of expiring an entire market pass.
    oldest = sorted(_cache, key=lambda symbol: _cache[symbol][0])[:len(_cache) - MAX_CACHE_SYMBOLS]
    for symbol in oldest:
        _cache.pop(symbol, None)
        _received_at.pop(symbol, None)


def _snapshot_quote(symbol: str) -> dict[str, Any] | None:
    item = _cache.get(symbol)
    return item[1] if item else None


def _quote_age_ms(symbol: str) -> float | None:
    item = _cache.get(symbol)
    if not item:
        return None
    return max(0.0, (time.monotonic() - item[0]) * 1000)


def _enqueue_persist(quotes: dict[str, dict[str, Any]], received: str) -> None:
    global _history_dropped
    if not quotes or _history_queue is None or not os.getenv("QUANT_CLICKHOUSE_URL"):
        return
    try:
        _history_queue.put_nowait((received, quotes))
    except asyncio.QueueFull:
        _history_dropped += len(quotes)


async def _history_writer_loop() -> None:
    global _last_storage_error, _history_store_ready, _history_written, _history_failed
    queue = _history_queue
    if queue is None:
        return
    while True:
        batches = [await queue.get()]
        row_count = len(batches[0][1])
        flush_seconds = max(.01, min(float(os.getenv("QUANT_HISTORY_FLUSH_SECONDS", "1")), 5))
        deadline = time.monotonic() + flush_seconds
        try:
            while row_count < 1000:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    item = await asyncio.wait_for(queue.get(), remaining)
                except asyncio.TimeoutError:
                    break
                batches.append(item)
                row_count += len(item[1])
            try:
                await run_in_threadpool(_persist_history_batches, batches)
                _last_storage_error = None
                _history_store_ready = True
                _history_written += row_count
            except Exception as exc:
                _last_storage_error = type(exc).__name__
                _history_store_ready = False
                _history_failed += row_count
                log.exception("quote history writer failed")
        finally:
            for _ in batches:
                queue.task_done()


async def _refresh_quotes(symbols: list[str], *, persist: bool = True) -> tuple[dict[str, dict[str, Any]], float]:
    """Fetch from the provider outside the HTTP response path."""
    global _last_refresh_at, _last_refresh_ms, _last_provider_error
    async with _fetch_lock:
        fetch_started = time.perf_counter()
        try:
            result = await run_in_threadpool(_provider_fetch, symbols)
        except Exception as exc:
            _last_provider_error = type(exc).__name__
            raise HTTPException(503, "Market provider is unavailable") from exc
        upstream_ms = (time.perf_counter() - fetch_started) * 1000
        received = time.monotonic()
        received_text = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        normalized = {str(key).upper(): dict(value) for key, value in result.items()
                      if str(key).upper() in symbols and isinstance(value, dict)}
        _cache.update({symbol: (received, quote) for symbol, quote in normalized.items()})
        _received_at.update({symbol: received_text for symbol in normalized})
        _prune_cache()
        _last_refresh_ms = upstream_ms
        _last_provider_error = None if normalized else "EmptyProviderResponse"
        if normalized:
            _last_refresh_at = time.time()
        if persist:
            _enqueue_persist(normalized, received_text)
        return normalized, upstream_ms


async def _get_quotes(symbols: list[str], *, persist: bool = True) -> tuple[dict[str, dict[str, Any]], float]:
    """Read memory only. Demand registration wakes the shared background collector."""
    symbols = [symbol for symbol in symbols if _provider_supports_symbol(symbol)]
    now = time.monotonic()
    new_demand = any(symbol not in _demand for symbol in symbols)
    for symbol in symbols:
        _demand[symbol] = now + 300
    if len(_demand) > MAX_BATCH:
        expired_first = sorted(_demand, key=_demand.get)[:len(_demand) - MAX_BATCH]
        for symbol in expired_first:
            _demand.pop(symbol, None)
    if _collector_wakeup is not None and new_demand:
        _collector_wakeup.set()
    cached = {symbol: quote for symbol in symbols if (quote := _snapshot_quote(symbol)) is not None}
    return cached, 0.0


def _freshness(symbols: list[str]) -> dict[str, dict[str, Any]]:
    configured_stale_ms = max(100, float(os.getenv("QUANT_STALE_AFTER_MS", "5000")))
    provider_stale_ms = _collector_interval_seconds() * 1500 if _provider_name() == "stock-api" else configured_stale_ms
    stale_ms = max(configured_stale_ms, provider_stale_ms)
    result = {}
    for symbol in symbols:
        if not _provider_supports_symbol(symbol):
            result[symbol] = {"state": "unsupported", "cache_age_ms": None,
                              "server_received_at_utc": None, "source_time": None,
                              "exchange_timestamp_verified": False}
            continue
        age = _quote_age_ms(symbol)
        result[symbol] = {
            "state": "warming" if age is None else "stale" if age > stale_ms else "fresh",
            "cache_age_ms": round(age, 1) if age is not None else None,
            "server_received_at_utc": _received_at.get(symbol),
            "source_time": _cache[symbol][1].get("quoteTime") if age is not None else None,
            "exchange_timestamp_verified": False,
        }
    return result


def _snapshot_status(missing: list[str], freshness: dict[str, dict[str, Any]]) -> str:
    supported = [item for item in freshness.values() if item["state"] != "unsupported"]
    if not supported:
        return "unsupported"
    if any(item["state"] == "unsupported" for item in freshness.values()):
        return "partial"
    if missing:
        return "warming" if len(missing) == len(freshness) else "partial"
    return "stale" if any(item["state"] == "stale" for item in freshness.values()) else "ok"


def _universe_symbols() -> list[str]:
    global _market_symbols
    if _market_symbols is None:
        from web.research_api import local_symbols
        raw = [item["symbol"].upper() for item in local_symbols()]
        normalized = _normalize_symbols(raw, {"max_symbols": MAX_UNIVERSE}, hard_limit=MAX_UNIVERSE)
        _market_symbols = _supported_universe(normalized)
    return _market_symbols


def _require_origin(origin: str | None) -> None:
    if not origin:
        return
    allowed = {item.strip().rstrip("/") for item in os.getenv("LIANGCE_ALLOWED_ORIGINS", "").split(",") if item.strip()}
    if origin.rstrip("/") not in allowed:
        raise HTTPException(403, "Origin is not allowed")


def _require_admin(authorization: str | None) -> None:
    secret = os.getenv("QUANT_ADMIN_TOKEN", "")
    if not secret:
        raise HTTPException(503, "Admin key management is not configured")
    if not authorization or not authorization.lower().startswith("bearer ") or not hmac.compare_digest(authorization[7:].strip(), secret):
        raise HTTPException(401, "Admin bearer token required", headers={"WWW-Authenticate": "Bearer"})


@router.post("/admin/keys", status_code=201)
def create_api_key(body: NewApiKeyRequest, authorization: str | None = Header(default=None)):
    _require_admin(authorization)
    secret = "qsk_" + secrets.token_urlsafe(36)
    created_at = datetime.now(timezone.utc).isoformat()
    expires_at = body.expires_at
    if expires_at and expires_at.tzinfo is None:
        raise HTTPException(422, "expires_at must include a timezone")
    expiry_text = expires_at.astimezone(timezone.utc).isoformat() if expires_at else None
    try:
        with _auth_session() as connection:
            connection.execute(
                "INSERT INTO api_keys(key_id,secret_hash,plan,rpm,max_symbols,max_streams,monthly_symbols,created_at,expires_at) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (body.key_id, hashlib.sha256(secret.encode()).hexdigest(), body.plan, body.rpm,
                 body.max_symbols, body.max_streams, body.monthly_symbols, created_at, expiry_text),
            )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, "API key id already exists") from exc
    return {"key_id": body.key_id, "secret": secret, "plan": body.plan, "rpm": body.rpm,
            "max_symbols": body.max_symbols, "max_streams": body.max_streams, "monthly_symbols": body.monthly_symbols,
            "created_at": created_at, "expires_at": expiry_text}


@router.get("/admin/keys")
def list_api_keys(authorization: str | None = Header(default=None)):
    _require_admin(authorization)
    with _auth_session() as connection:
        rows = connection.execute(
            "SELECT key_id,plan,rpm,max_symbols,max_streams,monthly_symbols,active,created_at,expires_at FROM api_keys ORDER BY created_at DESC"
        ).fetchall()
    return {"keys": [dict(row) for row in rows]}


@router.delete("/admin/keys/{key_id}")
def revoke_api_key(key_id: str, authorization: str | None = Header(default=None)):
    _require_admin(authorization)
    with _auth_session() as connection:
        result = connection.execute("UPDATE api_keys SET active=0 WHERE key_id=?", (key_id,))
    if result.rowcount == 0:
        raise HTTPException(404, "API key not found")
    return {"key_id": key_id, "active": False}


@router.get("/health")
def cloud_health():
    provider = _provider_name()
    return {
        "status": "ok",
        "provider": os.getenv("QUANT_PROVIDER_NAME", provider),
        "provider_markets": ["SH", "SZ"] if provider == "stock-api" else ["SH", "SZ", "BJ"],
        "provider_timestamp": "not_provided" if provider == "stock-api" else "source_specific_unverified",
        "provider_historical_periods": ["day", "week", "month"] if provider == "stock-api" else None,
        "history_store": "available" if _history_store_ready else "unavailable" if os.getenv("QUANT_CLICKHOUSE_URL") else "disabled",
        "collector_running": bool(_collector and not _collector.done()),
        "refresh_interval_ms": round(_collector_interval_seconds() * 1000),
        "last_refresh_at_utc": datetime.fromtimestamp(_last_refresh_at, timezone.utc).isoformat(timespec="milliseconds") if _last_refresh_at else None,
        "last_refresh_upstream_ms": round(_last_refresh_ms, 3),
        "last_provider_error": _last_provider_error,
        "collection": _collection,
        "collection_progress": _collection_progress,
        "snapshot_scope": "rolling per-symbol snapshots; cache freshness describes receipt age",
        "history_queue_depth": _history_queue.qsize() if _history_queue is not None else 0,
        "history_dropped_symbols": _history_dropped,
        "history_written_symbols": _history_written,
        "history_failed_symbols": _history_failed,
        "last_history_error": _last_storage_error,
        "cached_symbols": len(_cache),
        "compute_acceleration": {"hardware_url":"/api/v1/compute/hardware",
            "batch_macd_url":"/api/v1/compute/macd-batch","selection":"auto_cpu_or_cuda_by_batch",
            "recursive_structure_backend":"cpu","upstream_network_accelerated":False},
    }


@router.get('/compute/hardware')
def compute_hardware(authorization: str | None = Header(default=None)):
    _authenticate(authorization)
    from web.hardware_service import resources
    return resources()


@router.post('/compute/macd-batch')
def compute_macd_batch(payload:dict,request:HTTPRequest,authorization: str | None = Header(default=None)):
    key_id,plan=_authenticate(authorization)
    _require_origin(request.headers.get('origin'))
    rows=payload.get('prices',[])
    if not isinstance(rows,list):raise HTTPException(422,'prices must be a list')
    if not rows or len(rows)>min(plan.get('max_symbols',MAX_BATCH),MAX_BATCH):
        raise HTTPException(422,'indicator batch exceeds current plan symbol limit')
    _charge(key_id,plan,len(rows))
    from web.hardware_service import compute,CudaUnavailable
    try:return compute(payload)
    except ValueError as error:raise HTTPException(422,str(error))
    except CudaUnavailable as error:raise HTTPException(503,str(error))
    except RuntimeError as error:raise HTTPException(429,str(error))


@router.post("/quotes/batch")
async def batch_quotes(
    body: BatchRequest,
    request: HTTPRequest,
    authorization: str | None = Header(default=None),
):
    started = time.perf_counter()
    key_id, plan = await run_in_threadpool(_authenticate, authorization)
    _require_origin(request.headers.get("origin"))
    symbols = _normalize_symbols(body.symbols, plan)
    await run_in_threadpool(_charge, key_id, plan, len(symbols))
    quotes, upstream_ms = await _get_quotes(symbols)
    unsupported = [symbol for symbol in symbols if not _provider_supports_symbol(symbol)]
    missing = [symbol for symbol in symbols if symbol not in quotes and symbol not in unsupported]
    total_ms = (time.perf_counter() - started) * 1000
    server_ms = max(0.0, total_ms - upstream_ms)
    freshness = _freshness(symbols)
    status = _snapshot_status(missing, freshness)
    log.info("quote_batch key_id=%s requested=%d returned=%d upstream_ms=%.3f server_ms=%.3f total_ms=%.3f", key_id, len(symbols), len(quotes), upstream_ms, server_ms, total_ms)
    return {
        "status": status,
        "plan": plan.get("plan", "standard"),
        "as_of": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "provider": _provider_label(),
        "requested": len(symbols),
        "returned": len(quotes),
        "missing": missing,
        "unsupported": unsupported,
        "refresh": {"collector_running": bool(_collector and not _collector.done()), "last_refresh_at_utc": datetime.fromtimestamp(_last_refresh_at, timezone.utc).isoformat(timespec="milliseconds") if _last_refresh_at else None, "last_refresh_upstream_ms": round(_last_refresh_ms, 3)},
        "latency_ms": {"upstream": round(upstream_ms, 3), "server_overhead": round(server_ms, 3), "server_total": round(total_ms, 3)},
        "freshness": freshness,
        "quotes": [quotes[symbol] for symbol in symbols if symbol in quotes],
    }


@router.get("/quotes/market")
async def market_quotes_page(
    request: HTTPRequest,
    page: int = Query(default=1, ge=1, le=1000),
    page_size: int = Query(default=200, ge=1, le=MAX_BATCH),
    authorization: str | None = Header(default=None),
):
    key_id, plan = await run_in_threadpool(_authenticate, authorization)
    _require_origin(request.headers.get("origin"))
    if page_size > int(plan.get("max_symbols", 50)):
        raise HTTPException(413, f"This plan allows at most {plan.get('max_symbols', 50)} symbols per page")
    universe = _universe_symbols()
    page_count = max(1, (len(universe) + page_size - 1) // page_size)
    if page > page_count:
        raise HTTPException(404, "Market page is outside the symbol universe")
    start = (page - 1) * page_size
    symbols = universe[start:start + page_size]
    await run_in_threadpool(_charge, key_id, plan, len(symbols))
    quotes, _ = await _get_quotes(symbols)
    missing = [symbol for symbol in symbols if symbol not in quotes]
    freshness = _freshness(symbols)
    return {
        "status": _snapshot_status(missing, freshness),
        "provider": _provider_label(),
        "page": page,
        "page_size": page_size,
        "page_count": page_count,
        "total_symbols": len(universe),
        "supported_markets": ["SH", "SZ"] if _provider_name() == "stock-api" else ["SH", "SZ", "BJ"],
        "as_of": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "collection": _collection,
        "snapshot_scope": "rolling; pages can span collection passes",
        "returned": len(quotes),
        "missing": missing,
        "quotes": [quotes[symbol] for symbol in symbols if symbol in quotes],
        "freshness": freshness,
    }


@router.get("/quotes/{symbol}/history")
async def quote_history(
    symbol: str,
    request: HTTPRequest,
    limit: int = Query(default=1000, ge=1, le=10000),
    authorization: str | None = Header(default=None),
):
    _, plan = await run_in_threadpool(_authenticate, authorization)
    _require_origin(request.headers.get("origin"))
    normalized = _normalize_symbols([symbol], plan)[0]
    if not os.getenv("QUANT_CLICKHOUSE_URL"):
        raise HTTPException(503, "Historical quote storage is not enabled")
    query = (
        "SELECT ts, symbol, price, volume, amount, source_time "
        f"FROM quote_ticks WHERE symbol = '{normalized}' "
        f"ORDER BY ts DESC LIMIT {limit} FORMAT JSON"
    )
    try:
        raw = await run_in_threadpool(_clickhouse_request, query)
        data = json.loads(raw)
    except Exception as exc:
        raise HTTPException(503, "Historical quote store is unavailable") from exc
    return {"symbol": normalized, "count": len(data.get("data", [])), "rows": data.get("data", [])}


@router.get("/stocks/{symbol}/klines")
async def stock_api_klines(
    symbol: str,
    request: HTTPRequest,
    period: str = Query(default="day", pattern="^(day|week|month)$"),
    count: int = Query(default=120, ge=1, le=2000),
    adjust: str = Query(default="none", pattern="^(none|qfq|hfq)$"),
    authorization: str | None = Header(default=None),
):
    key_id, plan = await run_in_threadpool(_authenticate, authorization)
    _require_origin(request.headers.get("origin"))
    code = _normalize_symbols([symbol], plan)[0]
    if not _provider_supports_symbol(code):
        raise HTTPException(422, "stock-api supports SH/SZ only; BJ is not covered")
    await run_in_threadpool(_charge, key_id, plan, 1)
    try:
        return await run_in_threadpool(_stock_api_klines, code, period, count, adjust)
    except Exception as exc:
        raise HTTPException(503, "stock-api K-line source unavailable") from exc


@router.post("/stream-ticket")
def create_stream_ticket(
    request: HTTPRequest,
    authorization: str | None = Header(default=None),
):
    key_id, plan = _authenticate(authorization)
    _require_origin(request.headers.get("origin"))
    _charge(key_id, plan, 0)
    now = time.monotonic()
    for expired in [ticket for ticket, (_, expiry) in _tickets.items() if expiry <= now]:
        _tickets.pop(expired, None)
    ticket = secrets.token_urlsafe(24)
    _tickets[ticket] = ((key_id, plan), now + 30)
    return {"ticket": ticket, "expires_in_seconds": 30, "websocket": "/api/v1/stream"}


@router.websocket("/stream")
async def quote_stream(websocket: WebSocket):
    origin = websocket.headers.get("origin")
    allowed = {item.strip().rstrip("/") for item in os.getenv("LIANGCE_ALLOWED_ORIGINS", "").split(",") if item.strip()}
    if origin and origin.rstrip("/") not in allowed:
        await websocket.close(code=4403, reason="Origin is not allowed")
        return
    protocols = [item.strip() for item in websocket.headers.get("sec-websocket-protocol", "").split(",")]
    ticket_protocol = next((item for item in protocols if item.startswith("ticket.")), "")
    ticket = ticket_protocol.removeprefix("ticket.")
    stored = _tickets.pop(ticket, None)
    if not stored or stored[1] < time.monotonic():
        await websocket.close(code=4401, reason="Valid stream ticket required")
        return
    key_id, plan = stored[0]
    raw_symbols = websocket.query_params.get("symbols", "")
    symbols = _normalize_symbols(raw_symbols.split(",") if raw_symbols else [], plan)
    if not symbols:
        await websocket.close(code=4400, reason="symbols required")
        return
    if _stream_counts[key_id] >= max(1, int(plan.get("max_streams", 3))):
        await websocket.close(code=4429, reason="WebSocket connection limit reached")
        return
    _stream_counts[key_id] += 1
    try:
        await websocket.accept(subprotocol="quant.v1" if "quant.v1" in protocols else None)
        while True:
            started = time.perf_counter()
            await run_in_threadpool(_charge, key_id, plan, len(symbols))
            quotes, upstream_ms = await _get_quotes(symbols)
            total_ms = (time.perf_counter() - started) * 1000
            missing = [symbol for symbol in symbols if symbol not in quotes]
            freshness = _freshness(symbols)
            await websocket.send_json({
                "type": "quotes",
                "status": _snapshot_status(missing, freshness),
                "as_of": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                "provider": _provider_label(),
                "latency_ms": {"upstream": round(upstream_ms, 3), "server_overhead": round(max(0.0, total_ms - upstream_ms), 3), "server_total": round(total_ms, 3)},
                "freshness": freshness,
                "quotes": [quotes[symbol] for symbol in symbols if symbol in quotes],
            })
            await asyncio.sleep(max(0.25, float(os.getenv("QUANT_STREAM_INTERVAL_SECONDS", "1"))))
    except WebSocketDisconnect:
        return
    except HTTPException as exc:
        await websocket.close(code=4429 if exc.status_code == 429 else 1011, reason=exc.detail[:120])
    finally:
        _stream_counts[key_id] = max(0, _stream_counts[key_id] - 1)


def _load_watchlist() -> list[str]:
    raw = os.getenv("QUANT_WATCHLIST", "").strip()
    if raw.lower() in {"all", "market", "full"}:
        from web.research_api import local_symbols
        configured = [item["symbol"].upper() for item in local_symbols()]
    else:
        configured = [value.strip().upper() for value in raw.split(",") if value.strip()]
    if not configured:
        from web.market_gateway import DEFAULT_WATCHLIST_SYMBOLS
        configured = DEFAULT_WATCHLIST_SYMBOLS
    if len(set(configured)) > MAX_UNIVERSE:
        raise RuntimeError(f"QUANT_WATCHLIST has {len(set(configured))} symbols; maximum is {MAX_UNIVERSE}")
    try:
        normalized = _normalize_symbols(configured, {"max_symbols": MAX_UNIVERSE}, hard_limit=MAX_UNIVERSE)
        return _supported_universe(normalized)
    except HTTPException as exc:
        raise RuntimeError("QUANT_WATCHLIST contains invalid symbols: " + str(exc.detail)) from exc


def _collector_interval_seconds() -> float:
    interval = max(.25, min(float(os.getenv("QUANT_POLL_INTERVAL_SECONDS", "1")), 30.0))
    if _provider_name() == "stock-api":
        minimum = max(.25, min(float(os.getenv("STOCK_API_MIN_POLL_INTERVAL_SECONDS", "10")), 120))
        return max(interval, minimum)
    return interval


async def _collect_market_once(symbols: list[str]) -> None:
    global _collection, _collection_progress, _last_provider_error
    active = list(dict.fromkeys(symbols))
    pass_id = _collection["pass_id"] + 1
    _collection_progress = {"pass_id": pass_id, "processed": 0, "requested": len(active)}
    started = time.perf_counter()
    returned: set[str] = set()
    failed_shards = 0
    for start in range(0, len(active), MAX_BATCH):
        shard = active[start:start + MAX_BATCH]
        try:
            quotes, _ = await _refresh_quotes(shard)
            returned.update(quotes)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # An unavailable batch must not prevent later exchanges/batches
            # from being refreshed. Missing rows retain their old cache age.
            failed_shards += 1
            log.warning("market collection pass=%d shard=%d failed: %s", pass_id, start // MAX_BATCH, type(exc).__name__)
        _collection_progress = {"pass_id": pass_id, "processed": start + len(shard), "requested": len(active)}
    missing = [symbol for symbol in active if symbol not in returned]
    _collection = {
        "state": "ok" if not missing else "partial" if returned else "unavailable",
        "pass_id": pass_id, "requested": len(active), "returned": len(returned),
        "missing": missing, "failed_shards": failed_shards,
        "duration_ms": round((time.perf_counter() - started) * 1000, 3),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
    }
    _last_provider_error = f"{failed_shards} shard(s) failed" if failed_shards else "MissingProviderRows" if missing else None


async def _collector_loop(symbols: list[str]) -> None:
    global _collector_wakeup, _last_provider_error
    _collector_wakeup = asyncio.Event()
    symbols = list(dict.fromkeys(symbols))[:MAX_UNIVERSE]
    interval = _collector_interval_seconds()
    while True:
        _collector_wakeup.clear()
        started = time.perf_counter()
        now = time.monotonic()
        for symbol, expiry in list(_demand.items()):
            if expiry <= now:
                _demand.pop(symbol, None)
        requested = sorted(_demand, key=lambda symbol: _demand[symbol], reverse=True)
        active = list(dict.fromkeys(requested[:MAX_BATCH] + symbols))
        try:
            await _collect_market_once(active)
        except asyncio.CancelledError:
            raise
        except HTTPException as exc:
            _last_provider_error = exc.detail
            log.exception("quote collector iteration failed")
        except Exception as exc:
            _last_provider_error = type(exc).__name__
            log.exception("quote collector iteration failed")
        timeout = max(0.05, interval - (time.perf_counter() - started))
        try:
            await asyncio.wait_for(_collector_wakeup.wait(), timeout)
        except asyncio.TimeoutError:
            pass


async def start_market_cloud() -> None:
    global _collector, _history_writer, _history_queue, _history_store_ready, _last_storage_error
    if os.getenv("QUANT_REQUIRE_API_KEYS") == "1" and len(os.getenv("QUANT_ADMIN_TOKEN", "")) < 32:
        raise RuntimeError("QUANT_ADMIN_TOKEN must contain at least 32 characters")
    _provider_name()
    _init_auth_store()
    watchlist = _load_watchlist() if os.getenv("QUANT_INGEST_ENABLED", "1") == "1" else []
    if os.getenv("QUANT_CLICKHOUSE_URL"):
        try:
            await run_in_threadpool(_init_history_store)
            _history_store_ready = True
            _last_storage_error = None
        except Exception:
            _history_store_ready = False
            _last_storage_error = "ClickHouseInitializationError"
            if os.getenv("QUANT_HISTORY_REQUIRED") == "1":
                raise
            log.exception("ClickHouse initialization failed; history persistence is unavailable")
    if os.getenv("QUANT_CLICKHOUSE_URL"):
        queue_size = max(1, min(int(os.getenv("QUANT_HISTORY_QUEUE_SIZE", "64")), 4096))
        _history_queue = asyncio.Queue(maxsize=queue_size)
        if _history_writer is None or _history_writer.done():
            _history_writer = asyncio.create_task(_history_writer_loop(), name="quant-history-writer")
    if os.getenv("QUANT_INGEST_ENABLED", "1") == "1":
        _collector = asyncio.create_task(_collector_loop(watchlist), name="quant-quote-collector")


async def stop_market_cloud() -> None:
    global _collector, _history_writer, _history_queue, _collector_wakeup, _history_dropped
    if _collector and not _collector.done():
        _collector.cancel()
        try:
            await _collector
        except asyncio.CancelledError:
            pass
    _collector = None
    _collector_wakeup = None
    if _history_writer and not _history_writer.done():
        try:
            await asyncio.wait_for(_history_queue.join(), timeout=2.0)
        except asyncio.TimeoutError:
            log.warning("history queue drain timed out; dropping %d queued batches", _history_queue.qsize())
        _history_writer.cancel()
        try:
            await _history_writer
        except asyncio.CancelledError:
            pass
        while not _history_queue.empty():
            try:
                _, pending = _history_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            _history_dropped += len(pending)
            _history_queue.task_done()
    _history_writer = None
    _history_queue = None


def reset_state_for_tests() -> None:
    global _history_queue, _history_writer, _collector, _collector_wakeup, _market_symbols
    global _collection, _collection_progress
    _cache.clear()
    _received_at.clear()
    _demand.clear()
    _rates.clear()
    _monthly_usage.clear()
    _tickets.clear()
    _stream_counts.clear()
    _demand.clear()
    _history_queue = None
    _history_writer = None
    _collector = None
    _collector_wakeup = None
    _market_symbols = None
    _stock_api_kline_cache.clear()
    _collection = {"state": "not_started", "pass_id": 0, "requested": 0,
                   "returned": 0, "missing": [], "failed_shards": 0,
                   "duration_ms": None, "completed_at_utc": None}
    _collection_progress = {"pass_id": 0, "processed": 0, "requested": 0}
