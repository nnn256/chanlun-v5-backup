# Data source review · 2026-11-13

## Local V4.4 follow-up

The Eastmoney security daily fund-flow endpoint returned HTTP 200 and 100 rows during one local probe on 2026-11-13; later probes disconnected. The adapter retains raw response hashes, capture receipts and explicit unavailable states. Historical publication time is unverified: every acquired record is available no earlier than that capture, and this vintage is excluded from historical signal generation. Actual holder-cost/chip distribution remains unavailable; volume-at-representative-price is a labelled proxy. The local 5,580-security study uses mixed cache tails ending November 5–12 and current-universe breadth, not uniform November 13 or historical membership. No GitHub update was made.

## Runtime selections

- TDX API already bundled in the project: daily/minute A-share OHLCV and benchmark-index K-lines. The deployed local endpoint returned six benchmark indices dated 2026-11-12. This remains the price and structure source so bar timestamps, units and unadjusted prices stay consistent with the V4 tests.
- TDX /api/index returned six tested benchmark series: 上证、深证成指、创业板、沪深300、中证500、中证1000. Constituent advance/decline values are scoped to the individual index and are not advertised as full-market breadth.
- Eastmoney industry-board REST adapter: implemented for ranking and snapshot display, with a 12-second timeout, a 120-second in-process cache, source and receive timestamps, and explicit unavailable/stale states. This environment's request to push2.eastmoney.com returned HTTP 502, so live sector rows were not verified here.
- AkShare: reviewed as a useful multi-source adapter and industry/constituent API catalogue. It is not installed in the self-contained desktop build; the existing executable therefore does not gain a new large Python dependency.

## Repositories reviewed

| Repository | Fit | Decision |
|---|---|---|
| oficcejo/tdx-api | Existing Go REST bridge; currently bundled and successfully used | Keep as the A-share/index source |
| injoyai/tdx | Underlying Go TDX protocol client | Already related to the bundled bridge; avoid adding another protocol stack |
| bensema/gotdx | Go client describes main/extended markets and MAC board data | Candidate if the bundled bridge later proves unable to expose sector members |
| clong365/easy_tdx | Python TDX client with sync/async APIs | Redundant with the bundled local bridge |
| aeroxw/easy_tdx_max | Related TDX Python client | Redundant; not installed |
| akfamily/akshare | Broad China financial-data adapter; includes industry boards and constituents | Useful optional provider; not installed into the EXE |
| chanzain/eastmoney-stock-system | Industry/concept board tracking and snapshots | Source-pattern reference; separate system and persistence model |
| roiding/shadowflow | Industry, concept and security flow snapshots with cache-first daily research | Candidate for a later board-history adapter |
| jing2uo/tdx2db | TDX history database materializer | Useful for archive storage, not a live increment path |
| zhangxiangliang/stock-api | Multi-market TypeScript service/API | No role in the Python fixed-engine process |
| simonlin1212/global-stock-data | Global data tooling focused mainly on US-market research | Does not replace the A-share TDX feed |
| simonlin1212/Vibe-Research | Broad multi-market research application with many endpoints | Larger product, not a narrow market-data adapter |
| acb6102/opentdx | Repository README could not be fetched during this review | Unverified; not a runtime dependency |

Public README retrieval succeeded for 12 repositories. The public GitHub API rate-limited repository metadata, and opentdx did not return a readable README. Repository review is therefore a fit comparison, not a license/security audit of every dependency.

## Data quality boundaries

TDX daily K-lines use the provider's scheduled 15:00 close label; that label is not proof of a last trade at 15:00 while the session is open. Forming daily and minute rows are chart-only until their scheduled close. Board data has a different source and cache age and cannot silently fill missing TDX prices. Index breadth fields count the returned index's constituents and are not advertised as the full A-share market breadth.
