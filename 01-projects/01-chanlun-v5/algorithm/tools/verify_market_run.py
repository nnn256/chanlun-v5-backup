#!/usr/bin/env python3
"""Independently verify cached full-market results without making network calls.

All current successful stocks get JSON, CSV and raw-response hash checks.
A deterministic exchange-stratified sample is normalized again and analyzed
with the installed engine when its fingerprint matches the recorded version.
The scanner's actual outputs and checkpoints are read-only; this tool writes
only verification.json and VERIFICATION.md in the selected run directory.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime
import gzip
import io
import json
import math
from pathlib import Path
import sqlite3
import sys
import time
import urllib.parse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from chanmodel.engine import analyze
from chanmodel.model import Config
from chanmodel.tdx_data import CN, atomic_bytes, atomic_json, normalize_daily, normalize_universe, now_iso, sha256, symbol
from market_scan import engine_fingerprint


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def span(values):
    times = [datetime.fromisoformat(value) for value in values if value]
    return {"first": min(times).isoformat() if times else None,
            "last": max(times).isoformat() if times else None,
            "seconds": (max(times)-min(times)).total_seconds() if times else None}


def samples(results, requested):
    """Choose reproducibly across all exchanges and history lengths."""
    if requested <= 0 or not results:
        return []
    requested = min(requested, len(results))
    chosen = {}
    # Cover each exchange before choosing the longest/shortest history pairs.
    # In particular --sample 3 should mean one stock per exchange, not two
    # Shanghai stocks and one Shenzhen stock with Beijing omitted.
    for exchange in ("sh", "sz", "bj"):
        group = sorted((r for r in results if r["exchange"] == exchange), key=lambda r: (r["bars"], r["symbol"]))
        if group and len(chosen) < requested:
            chosen[group[0]["symbol"]] = group[0]
    for exchange in ("sh", "sz", "bj"):
        group = sorted((r for r in results if r["exchange"] == exchange), key=lambda r: (r["bars"], r["symbol"]))
        if group and len(chosen) < requested:
            chosen[group[-1]["symbol"]] = group[-1]
    ordered = sorted(results, key=lambda r: (r["bars"], r["symbol"]))
    for index in range(requested):
        if len(chosen) >= requested:
            break
        row = ordered[round(index*(len(ordered)-1)/max(1, requested-1))]
        chosen[row["symbol"]] = row
    for row in ordered:
        if len(chosen) >= requested:
            break
        chosen[row["symbol"]] = row
    return sorted(chosen.values(), key=lambda r: r["symbol"])


def compare_csv(normalized, raw_csv):
    actual = list(csv.DictReader(io.StringIO(raw_csv.decode("utf-8-sig"))))
    if len(actual) != len(normalized):
        raise ValueError(f"CSV row count {len(actual)} != normalized raw row count {len(normalized)}")
    numeric = ("open", "high", "low", "close", "volume", "volume_lots", "amount_yuan")
    for index, (left, right) in enumerate(zip(normalized, actual), 2):
        for key in ("closed_at", "trade_date", "source_time_raw"):
            if left[key] != right.get(key):
                raise ValueError(f"CSV row {index} {key} differs from normalized raw data")
        if right.get("is_closed") != str(left["is_closed"]).lower():
            raise ValueError(f"CSV row {index} is_closed differs")
        for key in numeric:
            expected = left[key]
            if expected is None:
                if right.get(key) not in {"", None}:
                    raise ValueError(f"CSV row {index} {key} should be empty")
            elif not math.isclose(float(right[key]), float(expected), rel_tol=1e-12, abs_tol=1e-9):
                raise ValueError(f"CSV row {index} {key} differs")
    return len(actual)


def verified_empty_history(item, run_dir, cache_dir, settings):
    """Accept unavailable history only with a successful, provably empty API response.

    This deliberately does not relabel an unexpected failure as unavailable,
    and does not count an unavailable symbol as an analyzed success.
    """
    code, source = item['symbol'], settings['source']
    if item.get('status') != 'empty_history':
        raise ValueError('only an explicit empty_history result can be verified as unavailable')
    saved = load_json(run_dir / 'stocks' / f'{code}.json')
    for key in ('symbol', 'exchange', 'status', 'source', 'engine_sha256', 'quality'):
        if saved.get(key) != item.get(key):
            raise ValueError('empty-history stock file differs from checkpoint: '+key)
    folder = cache_dir / source / 'day'
    metadata = load_json(folder / 'metadata' / f'{code}.json')
    if metadata.get('cache_run_as_of') != settings['as_of'] or metadata.get('source') != source or metadata.get('symbol') != code:
        raise ValueError('empty-history cache identity differs from run')
    csv_path = folder / 'ohlcv' / f'{code}.csv'
    raw_path = folder / 'raw' / f'{code}.json.gz'
    if Path(metadata.get('csv_path', '')).resolve() != csv_path.resolve() or Path(metadata.get('raw_path', '')).resolve() != raw_path.resolve():
        raise ValueError('empty-history cache paths differ from requested symbol/source')
    storage = raw_path.read_bytes()
    csv_raw = csv_path.read_bytes()
    if sha256(storage) != metadata['raw_storage_sha256'] or sha256(csv_raw) != metadata['csv_sha256']:
        raise ValueError('empty-history raw/CSV storage hash mismatch')
    raw = gzip.decompress(storage)
    if sha256(raw) != metadata['response_sha256'] or len(raw) != metadata['response_bytes']:
        raise ValueError('empty-history raw API response hash/size mismatch')
    evidence = gzip.decompress((run_dir / 'responses' / f'{code}.json.gz').read_bytes())
    if sha256(evidence) != metadata['response_sha256']:
        raise ValueError('empty-history run evidence differs from raw cache')
    envelope = json.loads(raw)
    data = envelope.get('data')
    if envelope.get('code') != 0 or not isinstance(data, dict):
        raise ValueError('empty-history raw response is not a successful business envelope')
    count = data.get('count', data.get('Count'))
    rows = data.get('list', data.get('List'))
    if isinstance(count, bool) or count != 0 or rows not in (None, []):
        raise ValueError('unavailable history requires explicit count=0 and list=null/[] evidence')
    bars, normalized, quality = normalize_daily(data, datetime.fromisoformat(settings['as_of']), source)
    if bars or normalized or quality['closed_rows'] != 0 or item['quality'].get('closed_rows') != 0:
        raise ValueError('empty-history evidence contains usable bars')
    if compare_csv([], csv_raw) != 0:
        raise ValueError('empty-history CSV must be header-only')
    parsed = urllib.parse.urlsplit(metadata['url'])
    query = urllib.parse.parse_qs(parsed.query)
    if parsed.path != f'/api/kline-all/{source}' or query.get('code') != [code] or query.get('type') != ['day']:
        raise ValueError('empty-history URL does not match symbol/source/day')
    return {'symbol':code, 'name':item.get('name'), 'status':'provider_history_unavailable',
            'provider_count':0, 'provider_list':rows, 'closed_bars':0,
            'response_sha256':metadata['response_sha256'], 'raw_storage_sha256':metadata['raw_storage_sha256'],
            'csv_sha256':metadata['csv_sha256'], 'received_at':metadata['received_at'],
            'evidence_verified':True, 'counted_as_analyzed_success':False,
            'note':'provider supplied no history; no synthetic or zero-filled bars were created'}


def verify_run(run_dir: Path, cache_dir: Path, sample=20):
    started = time.monotonic()
    errors, warnings, sampled, file_checks = [], [], [], []
    metadata = load_json(run_dir / "run.json")
    settings = metadata["settings"]
    as_of = datetime.fromisoformat(settings["as_of"])
    source = settings["source"]
    expected_engine = settings["engine_sha256"]
    installed_engine = engine_fingerprint()
    version_match = expected_engine == installed_engine
    records = metadata["universe"]
    symbols = [row["symbol"] for row in records]
    wanted = set(symbols)
    exchanges = Counter(row["exchange"] for row in records)
    if len(wanted) != len(records):
        errors.append({"check": "universe", "error": "duplicate symbols in recorded universe"})
    for row in records:
        try:
            if symbol(row["symbol"]) != row["exchange"]+row["code"]:
                raise ValueError("symbol/exchange/code identity mismatch")
        except (ValueError, KeyError) as exc:
            errors.append({"check": "universe", "symbol": row.get("symbol"), "error": str(exc)})
    if any(exchanges[exchange] == 0 for exchange in ("sh", "sz", "bj")):
        errors.append({"check": "universe", "error": "full-market verification requires all three exchanges"})
    if dict(exchanges) != metadata["coverage"].get("exchanges"):
        errors.append({"check": "universe", "error": "coverage exchange counts differ from recorded run stock pool",
                       "actual": dict(exchanges), "coverage": metadata["coverage"].get("exchanges")})
    if metadata["coverage"].get("selection") != "all_provider_listed_a_shares":
        errors.append({"check": "universe", "error": "run selection is not the full provider-listed A-share pool"})
    try:
        original = json.loads(gzip.decompress((run_dir / "universe-response.json.gz").read_bytes()))
        if original.get("code") != 0:
            raise ValueError("universe response has a business error code")
        provider_rows, provider_coverage, _ = normalize_universe(original["data"])
        if {row["symbol"] for row in provider_rows} != wanted:
            raise ValueError("raw provider universe differs from run universe")
        if sha256(gzip.decompress((run_dir / "universe-response.json.gz").read_bytes())) != metadata["universe_receipt"]["response_sha256"]:
            raise ValueError("raw universe response hash differs from recorded receipt")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        errors.append({"check": "universe_raw", "error": f"{type(exc).__name__}: {exc}"})

    with sqlite3.connect("file:"+(run_dir / "checkpoint.sqlite3").resolve().as_posix()+"?mode=ro", uri=True) as db:
        db.execute("BEGIN")
        snapshot = list(db.execute("SELECT symbol,status,engine_sha256,result FROM stocks ORDER BY symbol"))
    current, stale, outside = [], [], []
    for code, status, engine, encoded in snapshot:
        if code not in wanted:
            outside.append(code)
            continue
        if engine != expected_engine:
            stale.append(code)
            continue
        try:
            item = json.loads(encoded)
            if item.get("symbol") != code or item.get("status") != status or item.get("engine_sha256") != engine:
                raise ValueError("checkpoint columns and result identity/status/fingerprint differ")
            current.append(item)
        except (ValueError, KeyError, TypeError) as exc:
            errors.append({"check": "checkpoint", "symbol": code, "error": str(exc)})
    successes = [r for r in current if r["status"] == "success"]
    bad = [r for r in current if r["status"] != "success"]
    missing = sorted(wanted-{r["symbol"] for r in current})
    unavailable = []
    for item in bad:
        if item['status'] == 'empty_history':
            try:
                unavailable.append(verified_empty_history(item, run_dir, cache_dir, settings))
                continue
            except Exception as exc:
                errors.append({'check':'unavailable_history_evidence','symbol':item['symbol'],
                               'error':f'{type(exc).__name__}: {exc}'})
        else:
            errors.append({"check": "stock_status", "symbol": item["symbol"], "status": item["status"], "error": item.get("error", "non-success state")})
    if not version_match:
        warnings.append({"check": "sample_analysis", "status": "different_version", "recorded_engine": expected_engine,
                         "installed_engine": installed_engine, "note": "raw normalization can be checked, but installed-engine output is not compared as equivalent"})
    selected = {row["symbol"] for row in samples(successes, sample)}
    for index, item in enumerate(successes, 1):
        code = item["symbol"]
        try:
            saved = load_json(run_dir / "stocks" / f"{code}.json")
            keys = ("symbol", "exchange", "status", "source", "adjustment", "first_date", "last_date", "bars",
                    "csv_path", "csv_sha256", "engine_sha256", "current_state", "merged_count", "fractal_count",
                    "stroke_count", "segment_count", "center_count", "active_candidate_count", "active_candidate_counts")
            differing = [key for key in keys if saved.get(key) != item.get(key)]
            if differing:
                raise ValueError("per-stock JSON disagrees with checkpoint fields: "+", ".join(differing))
            folder = cache_dir / source / "day"
            cache_meta = load_json(folder / "metadata" / f"{code}.json")
            csv_path = folder / "ohlcv" / f"{code}.csv"
            raw_path = folder / "raw" / f"{code}.json.gz"
            if Path(item["csv_path"]).resolve() != csv_path.resolve():
                raise ValueError("result CSV path is outside the requested symbol/source cache")
            if cache_meta.get("cache_run_as_of") != settings["as_of"] or cache_meta.get("source") != source or cache_meta.get("symbol") != code:
                raise ValueError("cache symbol/source/as_of identity differs from recorded run")
            csv_raw = csv_path.read_bytes()
            if sha256(csv_raw) != item["csv_sha256"] or sha256(csv_raw) != cache_meta["csv_sha256"]:
                raise ValueError("normalized CSV SHA-256 differs from checkpoint/metadata")
            storage = raw_path.read_bytes()
            if sha256(storage) != cache_meta["raw_storage_sha256"]:
                raise ValueError("compressed raw cache SHA-256 mismatch")
            raw = gzip.decompress(storage)
            if sha256(raw) != cache_meta["response_sha256"] or len(raw) != cache_meta["response_bytes"]:
                raise ValueError("uncompressed API response hash/size differs from receipt")
            envelope = json.loads(raw)
            if envelope.get("code") != 0 or "data" not in envelope:
                raise ValueError("cached API envelope is not successful")
            run_evidence = gzip.decompress((run_dir / "responses" / f"{code}.json.gz").read_bytes())
            if sha256(run_evidence) != cache_meta["response_sha256"]:
                raise ValueError("run evidence and shared raw cache responses differ")
            parsed = urllib.parse.urlsplit(cache_meta["url"])
            query = urllib.parse.parse_qs(parsed.query)
            if parsed.path != f"/api/kline-all/{source}" or query.get("code") != [code] or query.get("type") != ["day"]:
                raise ValueError("recorded provider URL does not match symbol/source/day")
            if item["quality"].get("closed_rows") != item["bars"]:
                raise ValueError("quality closed_rows differs from analyzed bars")
            if item.get("execution_allowed") is not False or item.get("definition_mode") != "structure_proxy":
                raise ValueError("result incorrectly claims strict/executable semantics")
            if item["quality"].get("coverage_claim") != "all bars returned by provider; listing-inception coverage not verified":
                raise ValueError("unexpected listing-inception coverage claim")
            if "synthetic" in json.dumps(envelope.get("data", {}).get("meta", {}), ensure_ascii=False).lower():
                raise ValueError("provider metadata marks synthetic data")
            checked = {"symbol": code, "csv_sha256": item["csv_sha256"],
                       "raw_storage_sha256": cache_meta["raw_storage_sha256"], "response_sha256": cache_meta["response_sha256"],
                       "bars": item["bars"], "status": "pass"}
            file_checks.append(checked)
            if code in selected:
                bars, normalized, quality = normalize_daily(envelope["data"], as_of, source)
                csv_rows = compare_csv(normalized, csv_raw)
                if len(bars) != item["bars"] or quality["first_date"] != item["first_date"] or quality["last_date"] != item["last_date"]:
                    raise ValueError("re-normalized raw data differs from recorded bar count/date range")
                sample_result = {"symbol": code, "normalization_status": "pass", "csv_rows": csv_rows,
                                 "closed_bars": len(bars), "first_date": quality["first_date"], "last_date": quality["last_date"],
                                 "analysis_status": "different_version" if not version_match else "pass"}
                if version_match:
                    report = analyze(bars, Config(**settings["config"]), "day")
                    actual = {"merged_count": len(report["merged"]), "fractal_count": len(report["fractals"]),
                              "stroke_count": len(report["strokes"]), "segment_count": len(report["segments"]),
                              "confirmed_segment_count": sum(s["state"] == "confirmed" for s in report["segments"]),
                              "center_count": len(report["centers"]), "layer_count": len(report["layers"]),
                              "current_state": report["current_state"], "all_historical_candidate_count": len(report["signal_candidates"]),
                              "active_candidate_count": sum(p["status"] == "candidate" for p in report["signal_candidates"])}
                    different = {key: {"recorded": item.get(key), "recomputed": value}
                                 for key, value in actual.items() if item.get(key) != value}
                    if different:
                        raise ValueError("sample analysis differs at same fingerprint: "+json.dumps(different, ensure_ascii=False))
                    sample_result["recomputed"] = actual
                sampled.append(sample_result)
        except Exception as exc:
            errors.append({"check": "stock_files_or_sample", "symbol": code, "error": f"{type(exc).__name__}: {exc}"})
        if index % 250 == 0:
            print(json.dumps({"verification_checked": index, "current_successes": len(successes), "errors": len(errors)}), file=sys.stderr, flush=True)

    quote_info = {"status": "not_available"}
    try:
        quote_report = load_json(run_dir / "quotes.json")
        quote_symbols = [quote["symbol"] for quote in quote_report["quotes"]]
        quote_missing = sorted(wanted-set(quote_symbols))
        quote_extra = sorted(set(quote_symbols)-wanted)
        quote_duplicate = sorted(code for code, count in Counter(quote_symbols).items() if count > 1)
        if quote_missing or quote_extra or quote_duplicate or quote_report["missing_symbols"] or quote_report["failures"]:
            errors.append({"check": "quotes", "missing": quote_missing, "extras": quote_extra,
                           "duplicates": quote_duplicate, "provider_failures": quote_report["failures"]})
        quote_info = {"status": "pass" if not quote_missing and not quote_extra and not quote_duplicate and not quote_report["failures"] else "fail",
                      "count": len(quote_symbols), "missing": quote_missing, "duplicate": quote_duplicate,
                      "received_span": span(quote.get("received_at") for quote in quote_report["quotes"]),
                      "trade_timestamp_verified": quote_report.get("trade_timestamp_verified"),
                      "freshness_counts": dict(Counter(quote.get("freshness") for quote in quote_report["quotes"])),
                      "note": "receiver times describe acquisition only; provider trade date and same-day freshness are not proven"}
    except Exception as exc:
        errors.append({"check": "quotes", "error": f"{type(exc).__name__}: {exc}"})

    last_dates = Counter(item["last_date"] for item in successes)
    ages = Counter(str(item.get("last_bar_calendar_age_days")) for item in successes)
    latest = max(last_dates, default=None)
    lagged = [{"symbol": item["symbol"], "name": item["name"], "last_date": item["last_date"],
               "calendar_age_days": item.get("last_bar_calendar_age_days")}
              for item in successes if latest and item["last_date"] < latest]
    if not successes:
        errors.append({"check": "results", "error": "no current successful analysis results are available"})
    if missing:
        warnings.append({"check": "run_completion", "status": "in_progress_or_stale", "pending_symbols": len(missing)})
    try:
        summary = load_json(run_dir / "summary.json")
        if summary.get("universe_count") != len(records):
            errors.append({"check": "summary", "error": "summary universe count differs"})
        if not missing:
            expected = {"processed": len(current), "success": len(successes), "failed_or_empty": len(bad), "pending": 0,
                        "total_history_bars": sum(item["bars"] for item in successes)}
            differences = {key: {"recorded": summary.get(key), "verified": val}
                           for key, val in expected.items() if summary.get(key) != val}
            if differences:
                errors.append({"check": "summary", "error": "completed summary differs from checkpoint", "differences": differences})
            if bad and summary.get('all_symbols_succeeded') is not False:
                errors.append({'check':'summary','error':'unavailable/failed symbols must keep all_symbols_succeeded=false'})
        if summary.get("history_inception_complete") is not False or summary.get("historical_delisted_universe_complete") is not False:
            errors.append({"check": "summary", "error": "summary overclaims inception or delisted-stock history coverage"})
    except Exception as exc:
        errors.append({"check": "summary", "error": f"{type(exc).__name__}: {exc}"})

    status = "fail" if errors else "in_progress" if missing else "pass_with_unavailable" if unavailable else "pass"
    verified_available_results = len(file_checks) == len(successes) and bool(successes) and len(sampled) == len(selected) and not any(
        error.get('check') in {'stock_files_or_sample', 'checkpoint'} for error in errors)
    report = {"verified_at": now_iso(), "status": status, "elapsed_seconds": round(time.monotonic()-started, 3),
              "run_dir": str(run_dir.resolve()), "cache_dir": str(cache_dir.resolve()), "as_of": settings["as_of"],
              "source": source, "adjustment": "unadjusted" if source == "tdx" else "qfq_current_vintage",
              "engine_version": {"recorded": expected_engine, "installed": installed_engine,
                                 "sample_analysis_comparison": "same_version" if version_match else "different_version"},
              "universe": {"count": len(records), "unique_symbols": len(wanted), "exchanges": dict(exchanges), "selection": metadata["coverage"].get("selection")},
              "checkpoint": {"all_rows": len(snapshot), "current_pool_and_version_rows": len(current), "success": len(successes),
                             "failed_or_empty": len(bad), 'verified_unavailable_history':len(unavailable),
                             'unexpected_failed_or_unverified_empty':len(bad)-len(unavailable),
                             'all_symbols_finished':not missing,'all_symbols_succeeded':not missing and not bad,
                             "pending": len(missing), "stale_engine_rows_excluded": stale,
                             "outside_pool_rows_excluded": outside, "missing_current_symbols": missing},
              "files": {"all_successful_stocks_checked": len(successes), "passed": len(file_checks), "hash_receipts": file_checks},
              "sample": {"requested": sample, "selected": len(selected), "completed": len(sampled), "checks": sampled},
              "history": {"total_closed_bars": sum(item["bars"] for item in successes),
                          "earliest_date": min((item["first_date"] for item in successes), default=None),
                          "latest_date": latest, "last_date_distribution": dict(sorted(last_dates.items())),
                          "calendar_age_distribution_days": dict(sorted(ages.items())),
                          "symbols_older_than_latest_session": lagged,
                          "stale_data_note": "older final bars can reflect suspension, delisting, provider gaps or other causes; this test does not infer suspension from absence alone",
                          "acquisition_span": span(item.get("received_at") for item in successes)},
              "quotes": quote_info, "errors": errors, "warnings": warnings,
              'verified_available_results':verified_available_results, 'unavailable':unavailable,
              "claims": {"data_origin": "archived provider responses, checked against receipts and normalized cache; no synthetic generation used by this verifier",
                         "strict_chanlun_proven": False, "listing_inception_complete": False,
                         "historical_delisted_universe_complete": False, "strategy_backtest": False, "execution_allowed": False}}
    atomic_json(run_dir / "verification.json", report)
    lines = ["# 全市场日线扫描核验", "", f"核验时间：{report['verified_at']}；结果：**{status.upper()}**。", "",
             f"固定截止：{settings['as_of']}；来源：{source}；复权：{report['adjustment']}。", "",
             f"股票池{len(records)}只：沪{exchanges['sh']}、深{exchanges['sz']}、京{exchanges['bj']}，唯一代码{len(wanted)}。",
             f"当前算法版本成功{len(successes)}只，经原始空响应佐证的历史不可用{len(unavailable)}只，其他失败/未核实空历史{len(bad)-len(unavailable)}只，待处理{len(missing)}只；旧版本行{len(stale)}、池外行{len(outside)}均隔离。", "",
             f"全量校验{len(successes)}份成功股票JSON、CSV及原始压缩响应，文件检查通过{len(file_checks)}份。",
             f"抽样{len(sampled)}/{len(selected)}只重新标准化；当前安装算法与记录版本：{'一致' if version_match else '不同，算法输出比较标为different_version'}。", "",
             f"闭合日线总数：{report['history']['total_closed_bars']}；日期范围：{report['history']['earliest_date']} 至 {latest}。",
             f"末日早于池内最新交易日的股票：{len(lagged)}只。日期缺失不能单独证明停牌，详见JSON的日期与age分布。", "",
             f"报价：{quote_info.get('count')}只；接收范围：{quote_info.get('received_span')}。接收时间不能证明成交日期或实时新鲜度。", "",
             "本工具没有发起网络取数，也没有生成合成行情；只校验已经落盘的来源响应、收据、标准化缓存和分析结果。哈希一致证明文件间一致性，不代替对上游提供者的独立真实性审计。", "",
             "本次是当前股票池在固定截止时点的历史结构扫描；不声称覆盖所有退市股票、全部上市以来历史或严格原文递归，不是无幸存者偏差的逐日策略回测。", "",
             f"可用分析结果核验：{verified_available_results}。全部股票分析成功：{not missing and not bad}。不可用历史不计入成功；只有明确count=0、list=null/[]、原始响应与缓存哈希一致且CSV无数据行时，才允许PASS_WITH_UNAVAILABLE。", "",
             '## 已核实的不可用历史','',
             *(['- '+json.dumps(item,ensure_ascii=False) for item in unavailable] or ['无。']), '',
             "## 错误", ""]
    lines += ["- "+json.dumps(error, ensure_ascii=False) for error in errors] or ["无。"]
    lines += ["", "## 提醒", ""]
    lines += ["- "+json.dumps(warning, ensure_ascii=False) for warning in warnings] or ["无。"]
    lines += ["", "完整机器记录：[verification.json](verification.json)。", ""]
    atomic_bytes(run_dir / "VERIFICATION.md", "\n".join(lines).encode("utf-8"))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--sample", type=int, default=20)
    args = parser.parse_args()
    if args.sample < 0:
        parser.error("--sample must be nonnegative")
    try:
        report = verify_run(args.run_dir.resolve(), args.cache_dir.resolve(), args.sample)
    except Exception as exc:
        parser.exit(2, f"verification error: {type(exc).__name__}: {exc}\n")
    print(json.dumps({"status": report["status"], "universe": report["universe"]["count"],
                      "success": report["checkpoint"]["success"], "pending": report["checkpoint"]["pending"],
                      "hash_checks": report["files"]["passed"], "sample_completed": report["sample"]["completed"],
                      "errors": len(report["errors"]), "output": str(args.run_dir.resolve()/"verification.json")}, ensure_ascii=False))
    return 0 if report["status"] in {'pass','pass_with_unavailable'} else 3 if report["status"] == "in_progress" else 1


if __name__ == "__main__":
    raise SystemExit(main())
