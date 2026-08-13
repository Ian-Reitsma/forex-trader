from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin

import httpx

from forex_trader.config import AppConfig
from forex_trader.domain.macro_factor_risk import SUPPORTED_EIGHT_CURRENCY_PAIRS


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Capture a read-only authenticated forex-trader runtime diagnostic.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--timeout", type=float, default=30.0)
    return parser


def _get(client: httpx.Client, base_url: str, path: str) -> dict[str, object]:
    started = time.perf_counter()
    try:
        response = client.get(urljoin(base_url.rstrip("/") + "/", path.lstrip("/")))
        elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
        content_type = response.headers.get("content-type", "")
        try:
            body: object = response.json() if "json" in content_type else response.text
        except ValueError:
            body = response.text
        return {
            "path": path,
            "status_code": response.status_code,
            "elapsed_ms": elapsed_ms,
            "content_type": content_type,
            "body": body,
        }
    except httpx.HTTPError as exc:
        return {
            "path": path,
            "status_code": None,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            "error": f"{type(exc).__name__}: {exc}",
        }


def main() -> int:
    args = _parser().parse_args()
    if args.timeout <= 0:
        raise SystemExit("--timeout must be positive")

    config = AppConfig.from_env()
    headers = {"Accept": "application/json"}
    if config.api_token:
        headers["Authorization"] = f"Bearer {config.api_token}"

    generated_at = datetime.now(UTC)
    output = args.output or Path("diagnostics") / f"runtime-diagnostic-{generated_at.strftime('%Y%m%d-%H%M%S')}.json"
    output.parent.mkdir(parents=True, exist_ok=True)

    common = (
        "/health",
        "/health/live",
        "/health/ready?instrument=EUR_USD",
        "/v1/status",
        "/v1/runtime",
        "/v1/account",
        "/v1/positions",
        "/v1/providers",
        "/v1/risk/breaker",
        "/v1/promotion",
        "/v1/operations/summary?hours=24",
        "/v1/operations/events?hours=24&limit=200",
        "/v1/fundamentals/snapshots",
        "/v1/fundamentals/history",
        "/v1/events/scheduled",
    )
    requests: list[dict[str, object]] = []
    with httpx.Client(headers=headers, timeout=args.timeout, follow_redirects=True) as client:
        requests.extend(_get(client, args.base_url, path) for path in common)
        requests.extend(
            _get(client, args.base_url, f"/v1/readiness/{instrument}")
            for instrument in SUPPORTED_EIGHT_CURRENCY_PAIRS
        )

    failed_auth = [row["path"] for row in requests if row.get("status_code") in {401, 403}]
    server_failures = [row["path"] for row in requests if isinstance(row.get("status_code"), int) and int(row["status_code"]) >= 500]
    transport_failures = [row["path"] for row in requests if row.get("status_code") is None]
    report = {
        "schema": "runtime-diagnostic-v2",
        "generated_at": generated_at.isoformat(),
        "base_url": args.base_url,
        "read_only": True,
        "authorization_header_supplied": bool(config.api_token),
        "summary": {
            "requests": len(requests),
            "authentication_failures": failed_auth,
            "server_failures": server_failures,
            "transport_failures": transport_failures,
        },
        "requests": requests,
    }
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output.resolve()), **report["summary"]}, indent=2, sort_keys=True))
    return 1 if failed_auth or server_failures or transport_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
