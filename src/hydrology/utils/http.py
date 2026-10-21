"""Rate-limited HTTP, content-addressed snapshots and resumable page caching."""

import json
import math
import os
import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

from .io import atomic_json
from .provenance import digest


class ProviderError(RuntimeError):
    pass


class AuthenticationError(ProviderError):
    pass


class UnsupportedVariable(ProviderError):
    pass


def retry_after_deadline(value, now):
    """Return the server's UTC deadline; malformed headers use bounded backoff."""
    if value is None:
        return None
    try:
        delay = float(value)
    except (TypeError, ValueError):
        try:
            stamp = parsedate_to_datetime(value)
            if stamp.tzinfo is None:
                return None
            return max(now, stamp.timestamp())
        except (TypeError, ValueError, OverflowError):
            return None
    if not math.isfinite(delay) or delay < 0:
        return None
    deadline = now + delay
    return deadline if math.isfinite(deadline) else None


class RequestDeferred(ProviderError):
    """No further network request is permitted for this host in this invocation."""

    def __init__(self, host, url, retry_at, reason):
        self.host = host
        self.url = url
        self.retry_at = retry_at
        self.reason = reason
        try:
            self.retry_at_utc = datetime.fromtimestamp(
                retry_at, timezone.utc
            ).isoformat()
        except (ValueError, OverflowError, OSError):
            self.retry_at_utc = f"Unix timestamp {retry_at}"
        super().__init__(
            f"{host}: deferred until {self.retry_at_utc}; {reason}; "
            "completed cached pages retained; resume with the same cache"
        )


class Client:
    def __init__(self, config, session=None):
        self.config = config
        self.session = session or requests.Session()
        self.lock = threading.Lock()
        self.host_locks = {}
        self.last = {}
        self.deferred_hosts = {}
        self.cooldown_monotonic = {}
        self.wait_remaining = config.retry_wait_budget_seconds
        self.hits = 0
        self.requests = 0
        self.sources = {}
        self.scoped_sources = {}
        self.scope = threading.local()

    def _host_lock(self, host):
        with self.lock:
            return self.host_locks.setdefault(host, threading.Lock())

    def _cooldown_path(self, host):
        return Path(self.config.cache) / "cooldowns" / f"{digest(host)}.json"

    def _schedule(self, host, retry_at, reason):
        self.cooldown_monotonic[host] = time.monotonic() + max(
            0, retry_at - time.time()
        )
        atomic_json(
            self._cooldown_path(host),
            {"host": host, "retry_at": retry_at, "reason": reason},
        )

    def _defer(self, host, url, retry_at, reason):
        self.deferred_hosts[host] = (retry_at, reason)
        raise RequestDeferred(host, url, retry_at, reason)

    def _wait_for_cooldown(self, host, url):
        if host in self.deferred_hosts:
            retry_at, reason = self.deferred_hosts[host]
            self._defer(host, url, retry_at, reason)
        path = self._cooldown_path(host)
        if not path.exists():
            return
        state = json.loads(path.read_text())
        retry_at = float(state["retry_at"])
        if state["host"] != host or not math.isfinite(retry_at):
            raise ProviderError("Invalid persisted provider cooldown")
        monotonic_deadline = self.cooldown_monotonic.setdefault(
            host, time.monotonic() + max(0, retry_at - time.time())
        )
        while (
            delay := max(retry_at - time.time(), monotonic_deadline - time.monotonic())
        ) > 0:
            # Reserve the shared invocation budget before sleeping. An interrupted
            # sleep leaves the absolute cooldown on disk for a subsequent run.
            with self.lock:
                if delay > self.wait_remaining:
                    self._defer(
                        host,
                        url,
                        retry_at,
                        f"{state['reason']}; remaining retry-wait budget "
                        f"{self.wait_remaining:g}s is below required {delay:g}s",
                    )
                self.wait_remaining -= delay
            time.sleep(delay)

    def _verify(self, envelope, url=None):
        try:
            body = envelope["body"]
            if not isinstance(envelope["url"], str) or urlparse(
                envelope["url"]
            ).scheme not in ("http", "https"):
                raise ValueError("invalid source URL")
            if not isinstance(body, dict) or not isinstance(body["features"], list):
                raise ValueError("expected GeoJSON features list")
            json.dumps(body, allow_nan=False)
            if digest(body) != envelope["source_release"]:
                raise ValueError("content hash mismatch")
            stamp = datetime.fromisoformat(
                envelope["retrieved_at"].replace("Z", "+00:00")
            )
            if stamp.tzinfo is None:
                raise ValueError("retrieval timestamp requires timezone")
            if url is not None and envelope["url"] != url:
                raise ValueError("request URL mismatch")
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise ProviderError(f"Invalid cached/provider envelope: {exc}") from exc
        return envelope

    def _remember(self, envelope):
        with self.lock:
            self.sources[envelope["url"]] = {
                k: envelope[k] for k in ("url", "retrieved_at", "source_release")
            }
            scope = getattr(self.scope, "river_id", None)
            if scope is not None:
                self.scoped_sources.setdefault(scope, {})[envelope["url"]] = (
                    self.sources[envelope["url"]]
                )
        return envelope

    def get(self, url, params=None):
        url = requests.Request("GET", url, params=params).prepare().url
        key = digest(url)
        root = Path(self.config.cache)
        pointer = root / "requests" / f"{key}.json"
        if pointer.exists() and not self.config.refresh:
            try:
                envelope = self._verify(json.loads(pointer.read_text()), url)
                snapshot = root / "snapshots" / f"{envelope['source_release']}.json"
                self._verify(json.loads(snapshot.read_text()))
            except (OSError, ValueError) as exc:
                raise ProviderError(f"Unreadable cache {pointer}: {exc}") from exc
            with self.lock:
                self.hits += 1
            return self._remember(envelope)
        if self.config.offline:
            raise ProviderError(f"Offline mode: no verified cached response for {url}")
        host = urlparse(url).netloc
        headers = {}
        if host == "api.waterdata.usgs.gov" and os.getenv("USGS_API_KEY"):
            headers["X-Api-Key"] = os.environ["USGS_API_KEY"]
        # Serialize dispatch to the same host so other workers cannot issue new
        # requests after its cooldown is learned. Other providers remain independent.
        with self._host_lock(host):
            for attempt in range(self.config.retries + 1):
                self._wait_for_cooldown(host, url)
                delay = max(
                    0,
                    self.config.rate_seconds
                    - (time.monotonic() - self.last.get(host, 0)),
                )
                if delay:
                    time.sleep(delay)
                self.last[host] = time.monotonic()
                try:
                    self.requests += 1
                    response = self.session.get(
                        url, headers=headers, timeout=self.config.timeout
                    )
                    if response.status_code in (401, 403):
                        raise AuthenticationError(
                            f"{host}: HTTP {response.status_code}"
                        )
                    if response.status_code == 429 or response.status_code >= 500:
                        now = time.time()
                        server_deadline = retry_after_deadline(
                            response.headers.get("Retry-After"), now
                        )
                        retry_at = (
                            server_deadline
                            if server_deadline is not None
                            else now + 2**attempt
                        )
                        reason = f"HTTP {response.status_code}"
                        self._schedule(host, retry_at, reason)
                        getattr(response, "close", lambda: None)()
                        if attempt == self.config.retries:
                            if (
                                response.status_code == 429
                                or server_deadline is not None
                            ):
                                self._defer(
                                    host, url, retry_at, reason + "; retries exhausted"
                                )
                            raise ProviderError(f"{host}: {reason}; retries exhausted")
                        continue
                    response.raise_for_status()
                    body = response.json()
                    if "features" not in body:
                        raise ProviderError(
                            f"{host}: expected GeoJSON FeatureCollection"
                        )
                    envelope = {
                        "url": url,
                        "retrieved_at": datetime.fromtimestamp(
                            time.time(), timezone.utc
                        ).isoformat(),
                        "source_release": digest(body),
                        "body": body,
                    }
                    self._verify(envelope, url)
                    atomic_json(
                        root / "snapshots" / f"{envelope['source_release']}.json",
                        envelope,
                    )
                    atomic_json(pointer, envelope)
                    return self._remember(envelope)
                except (requests.Timeout, requests.ConnectionError) as exc:
                    if attempt == self.config.retries:
                        raise ProviderError(f"{host}: {type(exc).__name__}") from exc
                    self._schedule(host, time.time() + 2**attempt, type(exc).__name__)
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
