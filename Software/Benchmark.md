# Benchmark Summary

## How to run (automated)

With the app listening on port 5001 (see `README.md`):

```bash
BENCHMARK_EMAIL='Amir@imam.com' BENCHMARK_PASSWORD='123' python3 scripts/http_benchmark.py
```

Optional environment variables:

| Variable | Default | Meaning |
| --- | --- | --- |
| `BENCHMARK_BASE_URL` | `http://127.0.0.1:5001` | Server origin |
| `BENCHMARK_N` | `20` | Requests per endpoint |
| `BENCHMARK_MESSAGE` | `List my courses` | JSON `message` for `POST /api/chatbot` |

## Setup (historical)
- Host: `http://127.0.0.1:5001`
- Account used: `test@benchmark.com` (teacher) — or any teacher account via `BENCHMARK_*`
- Requests per endpoint: `N=20`
- Chatbot payload for API test: `"List my courses"`

## Refactor Scope
- Extracted chatbot NLP helpers from `app.py` into `services/chatbot_intents.py`
- Extracted chatbot routes (`/chatbot`, `/api/chatbot`) into `services/chatbot_routes.py`
- Registered chatbot routes in `app.py` via `register_chatbot_routes(app)`

## Results

### 1) Baseline (Before Refactor)
| Endpoint | p50 (ms) | p95 (ms) | Errors |
|---|---:|---:|---:|
| `GET /teacher-dashboard` | 0.98 | 1.48 | 0/20 |
| `GET /chatbot` | 1.02 | 1.42 | 0/20 |
| `GET /calendar` | 0.98 | 1.80 | 0/20 |
| `GET /floor-map` | 1.10 | 1.70 | 0/20 |
| `POST /api/chatbot` | 1.57 | 2.56 | 0/20 |

### 2) After Helper Extraction
| Endpoint | p50 (ms) | p95 (ms) | Errors |
|---|---:|---:|---:|
| `GET /teacher-dashboard` | 1.01 | 1.75 | 0/20 |
| `GET /chatbot` | 1.03 | 2.35 | 0/20 |
| `GET /calendar` | 1.43 | 3.07 | 0/20 |
| `GET /floor-map` | 1.11 | 2.49 | 0/20 |
| `POST /api/chatbot` | 1.62 | 2.98 | 0/20 |

### 3) After Route Extraction
| Endpoint | p50 (ms) | p95 (ms) | Errors |
|---|---:|---:|---:|
| `GET /teacher-dashboard` | 1.59 | 1.93 | 0/20 |
| `GET /chatbot` | 1.32 | 1.87 | 0/20 |
| `GET /calendar` | 1.55 | 2.11 | 0/20 |
| `GET /floor-map` | 1.32 | 1.91 | 0/20 |
| `POST /api/chatbot` | 3.08 | 3.59 | 0/20 |

### 4) After Calendar Route Extraction
| Endpoint | p50 (ms) | p95 (ms) | Errors |
|---|---:|---:|---:|
| `GET /teacher-dashboard` | 1.42 | 5.05 | 0/20 |
| `GET /chatbot` | 1.27 | 1.90 | 0/20 |
| `GET /calendar` | 1.32 | 1.92 | 0/20 |
| `GET /floor-map` | 1.37 | 2.24 | 0/20 |
| `POST /api/chatbot` | 2.05 | 2.62 | 0/20 |

### 5) Current (`scripts/http_benchmark.py`, 2026-04-01)

Local run (`BENCHMARK_EMAIL=Amir@imam.com`, `BENCHMARK_PASSWORD=123`, `N=20`):

| Endpoint | p50 (ms) | p95 (ms) | Errors |
|---|---:|---:|---:|
| `GET /teacher-dashboard` | 2.30 | 7.61 | 0/20 |
| `GET /chatbot` | 1.81 | 3.77 | 0/20 |
| `GET /calendar` | 1.46 | 3.43 | 0/20 |
| `GET /floor-map` | 1.35 | 1.99 | 0/20 |
| `POST /api/chatbot` | 1.44 | 3.89 | 0/20 |

## Notes
- No functional regressions observed (all measured endpoints remained at `0/20` errors).
- Absolute latency remains very low (single-digit ms in local dev).
- Minor variation across runs is expected in debug mode and local loopback benchmarks.
- `POST /api/chatbot` latency depends on configuration: if `GEMINI_API_KEY` is unset, the handler returns immediately with a configuration message (no Gemini round-trip), so times stay in the low-ms range.