"""Connectivity check, not the candidate's reconciliation implementation."""

import argparse
import json
import os
import sys

import httpx

parser = argparse.ArgumentParser()
parser.add_argument("--real", action="store_true")
args = parser.parse_args()
base = (
    os.getenv("ONEC_BASE_URL", "")
    if args.real
    else "http://localhost:" + os.getenv("SOURCE_PORT", "8093")
)
if not base:
    print(
        json.dumps(
            {
                "status": "BLOCKED",
                "reason": "Organizer must provide ONEC_BASE_URL and access",
            }
        )
    )
    sys.exit(2)
auth = (os.getenv("ONEC_USER", ""), os.getenv("ONEC_PASSWORD", "")) if args.real else None
try:
    with httpx.Client(auth=auth, timeout=15) as client:
        counts = {}
        for name in ("accounts", "charges", "payments"):
            path = os.getenv("ONEC_" + name.upper() + "_PATH", name) if args.real else name
            response = client.get(
                base.rstrip("/") + "/" + path.lstrip("/"), params={"$format": "json"}
            )
            response.raise_for_status()
            rows = response.json()["value"]
            if not isinstance(rows, list) or not rows:
                raise ValueError("Missing seeded collection")
            counts[name] = len(rows)
    print(
        json.dumps(
            {
                "status": "PASS",
                "mode": "real" if args.real else "mock",
                "counts": counts,
            }
        )
    )
except (httpx.HTTPError, ValueError, KeyError) as error:
    print(json.dumps({"status": "BLOCKED", "reason": type(error).__name__}))
    sys.exit(2)
