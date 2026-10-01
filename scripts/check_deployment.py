"""Probe a configured public readiness endpoint without application credentials."""

import json
import os
import time
from urllib.parse import urlparse
from urllib.request import urlopen


def main() -> None:
    """Require HTTPS and a readiness body, retrying briefly during rollout."""
    url = os.environ.get("DEPLOYMENT_HEALTH_URL", "")
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise SystemExit(
            "Configure DEPLOYMENT_HEALTH_URL with a public HTTPS readiness endpoint. "
            "Its JSON must contain status=ok or status=ready."
        )

    for attempt in range(5):
        try:
            with urlopen(url, timeout=15) as response:
                if urlparse(response.url).scheme != "https":
                    raise ValueError("Readiness endpoint redirected away from HTTPS")
                body = json.loads(response.read(65536))
                if response.status != 200 or body.get("status") not in {"ok", "ready"}:
                    raise ValueError("Readiness endpoint is not ready")
            print("Deployment readiness check passed.")
            return
        except Exception as exc:
            # Do not log URL query parameters, response bodies, or credentials.
            print(f"Readiness attempt {attempt + 1}/5 failed: {type(exc).__name__}")
            if attempt < 4:
                time.sleep(5)
    raise SystemExit("Deployment readiness check failed after five attempts.")


if __name__ == "__main__":
    main()
