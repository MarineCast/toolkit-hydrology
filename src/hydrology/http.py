"""Rate-limited HTTP, content-addressed snapshots and resumable page caching."""

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

from .core import atomic_json, digest


class ProviderError(RuntimeError):
    pass


class AuthenticationError(ProviderError):
    pass


class UnsupportedVariable(ProviderError):
    pass


class Client:
    def __init__(self, config, session=None):
        self.config = config
        self.session = session or requests.Session()
        self.lock = threading.Lock()
        self.last = {}
        self.hits = 0
        self.requests = 0

    def get(self, url, params=None):
        url = requests.Request("GET", url, params=params).prepare().url
        key = digest(url)
        root = Path(self.config.cache)
        pointer = root / "requests" / f"{key}.json"
        if pointer.exists() and not self.config.refresh:
            self.hits += 1
            return json.loads(pointer.read_text())
        host = urlparse(url).netloc
        headers = {}
        if host == "api.waterdata.usgs.gov" and os.getenv("USGS_API_KEY"):
            headers["X-Api-Key"] = os.environ["USGS_API_KEY"]
        for attempt in range(self.config.retries + 1):
            with self.lock:
                time.sleep(
                    max(
                        0,
                        self.config.rate_seconds
                        - (time.monotonic() - self.last.get(host, 0)),
                    )
                )
                self.last[host] = time.monotonic()
            try:
                self.requests += 1
                response = self.session.get(
                    url, headers=headers, timeout=self.config.timeout
                )
                if response.status_code in (401, 403):
                    raise AuthenticationError(f"{host}: HTTP {response.status_code}")
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt == self.config.retries:
                        raise ProviderError(
                            f"{host}: HTTP {response.status_code}; retries exhausted"
                        )
                    time.sleep(
                        min(60, float(response.headers.get("Retry-After", 2**attempt)))
                    )
                    continue
                response.raise_for_status()
                body = response.json()
                if "features" not in body:
                    raise ProviderError(f"{host}: expected GeoJSON FeatureCollection")
                envelope = {
                    "url": url,
                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                    "source_release": digest(body),
                    "body": body,
                }
                atomic_json(
                    root / "snapshots" / f"{envelope['source_release']}.json", envelope
                )
                atomic_json(pointer, envelope)
                return envelope
            except (requests.Timeout, requests.ConnectionError) as exc:
                if attempt == self.config.retries:
                    raise ProviderError(f"{host}: {type(exc).__name__}") from exc
                time.sleep(2**attempt)
            except (requests.HTTPError, ValueError) as exc:
                raise ProviderError(f"{host}: invalid response: {exc}") from exc

    def pages(self, url, params=None):
        seen = set()
        initial_host = urlparse(url).netloc
        while url:
            envelope = self.get(url, params)
            if envelope["url"] in seen:
                raise ProviderError("Pagination cycle")
            seen.add(envelope["url"])
            yield envelope
            links = envelope["body"].get("links", [])
            next_urls = [x["href"] for x in links if x.get("rel") == "next"]
            url = urljoin(url, next_urls[0]) if next_urls else None
            if url and urlparse(url).netloc != initial_host:
                raise ProviderError("Cross-host pagination rejected")
            params = None
