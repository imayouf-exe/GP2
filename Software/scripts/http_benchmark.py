#!/usr/bin/env python3
"""
HTTP micro-benchmark for local dev (matches Benchmark.md methodology).

Requires the Flask app running (default http://127.0.0.1:5001).

Environment:
  BENCHMARK_BASE_URL   default http://127.0.0.1:5001
  BENCHMARK_EMAIL      teacher account email
  BENCHMARK_PASSWORD   password
  BENCHMARK_N          requests per endpoint (default 20)
  BENCHMARK_MESSAGE    JSON body message for POST /api/chatbot (default "List my courses")

Example:
  BENCHMARK_EMAIL=Amir@imam.com BENCHMARK_PASSWORD=123 python3 scripts/http_benchmark.py
"""

from __future__ import annotations

import json
import os
import re
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar


def _meta_csrf(html: str) -> str | None:
    m = re.search(
        r'<meta\s+name=["\']csrf-token["\']\s+content=["\']([^"\']+)["\']',
        html,
        re.I,
    )
    return m.group(1) if m else None


def _pctl(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    n = len(sorted_vals)
    if n == 1:
        return sorted_vals[0]
    idx = (n - 1) * p
    lo = int(idx)
    hi = min(lo + 1, n - 1)
    frac = idx - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def main() -> int:
    base = os.environ.get("BENCHMARK_BASE_URL", "http://127.0.0.1:5001").rstrip("/")
    email = os.environ.get("BENCHMARK_EMAIL", "").strip()
    password = os.environ.get("BENCHMARK_PASSWORD", "")
    n = int(os.environ.get("BENCHMARK_N", "20"))
    chat_msg = os.environ.get("BENCHMARK_MESSAGE", "List my courses").strip() or "List my courses"

    if not email or not password:
        print(
            "Set BENCHMARK_EMAIL and BENCHMARK_PASSWORD (teacher account).\n"
            "Example: BENCHMARK_EMAIL=Amir@imam.com BENCHMARK_PASSWORD=123 python3 scripts/http_benchmark.py",
            file=sys.stderr,
        )
        return 1

    jar = CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    def get(path: str) -> tuple[int, str]:
        url = base + path
        try:
            with opener.open(url, timeout=30) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                return resp.status, body
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace") if e.fp else ""
            return e.code, body
        except OSError as e:
            print(f"Connection failed ({url}): {e}", file=sys.stderr)
            sys.exit(2)

    # Login page → CSRF
    code, html = get("/login")
    if code != 200:
        print(f"GET /login failed: HTTP {code}", file=sys.stderr)
        return 1
    csrf = _meta_csrf(html)
    if not csrf:
        print("Could not find csrf-token meta on /login", file=sys.stderr)
        return 1

    data = urllib.parse.urlencode(
        {
            "email": email,
            "password": password,
            "csrf_token": csrf,
        }
    ).encode()
    req = urllib.request.Request(
        base + "/login",
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": base,
            "Referer": base + "/login",
        },
    )
    try:
        with opener.open(req, timeout=30) as resp:
            _ = resp.read()
            login_status = resp.status
    except urllib.error.HTTPError as e:
        login_status = e.code
        _ = e.read()
    if login_status not in (200, 302, 303):
        print(f"POST /login failed: HTTP {login_status}", file=sys.stderr)
        return 1

    # Fresh CSRF after session established
    code, html = get("/teacher-dashboard")
    if code != 200:
        print(f"GET /teacher-dashboard after login: HTTP {code}", file=sys.stderr)
        return 1
    csrf = _meta_csrf(html) or csrf

    get_paths = (
        "/teacher-dashboard",
        "/chatbot",
        "/calendar",
        "/floor-map",
    )

    def bench_get(path: str) -> tuple[list[float], int]:
        times: list[float] = []
        errors = 0
        for _ in range(n):
            url = base + path
            t0 = time.perf_counter()
            try:
                with opener.open(url, timeout=30) as resp:
                    _ = resp.read()
                    elapsed_ms = (time.perf_counter() - t0) * 1000
                    times.append(elapsed_ms)
                    if resp.status != 200:
                        errors += 1
            except urllib.error.HTTPError:
                errors += 1
            except OSError:
                errors += 1
        return times, errors

    def bench_post_api(path: str, payload: dict) -> tuple[list[float], int]:
        times: list[float] = []
        errors = 0
        body = json.dumps(payload).encode("utf-8")
        for _ in range(n):
            req = urllib.request.Request(
                base + path,
                data=body,
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "X-CSRF-Token": csrf,
                    "Origin": base,
                },
            )
            t0 = time.perf_counter()
            try:
                with opener.open(req, timeout=60) as resp:
                    _ = resp.read()
                    elapsed_ms = (time.perf_counter() - t0) * 1000
                    times.append(elapsed_ms)
                    if resp.status != 200:
                        errors += 1
            except urllib.error.HTTPError:
                errors += 1
            except OSError:
                errors += 1
        return times, errors

    rows: list[tuple[str, float, float, str]] = []

    for path in get_paths:
        times, err = bench_get(path)
        times.sort()
        p50 = statistics.median(times) if times else 0.0
        p95 = _pctl(times, 0.95) if times else 0.0
        rows.append((f"GET {path}", p50, p95, f"{err}/{n}"))

    times, err = bench_post_api("/api/chatbot", {"message": chat_msg})
    times.sort()
    p50 = statistics.median(times) if times else 0.0
    p95 = _pctl(times, 0.95) if times else 0.0
    rows.append((f"POST /api/chatbot", p50, p95, f"{err}/{n}"))

    print(f"Host: {base}")
    print(f"Account: {email} (teacher)")
    print(f"Requests per endpoint: N={n}")
    print(f"Chatbot payload: {json.dumps(chat_msg)}")
    print()
    print("| Endpoint | p50 (ms) | p95 (ms) | Errors |")
    print("|---|---:|---:|---:|")
    for label, p50, p95, errs in rows:
        print(f"| `{label}` | {p50:.2f} | {p95:.2f} | {errs} |")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
