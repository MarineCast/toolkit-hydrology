"""Deterministic HTTP cooldown checks: no real requests, clocks or sleeps."""

from datetime import datetime, timezone
from email.utils import format_datetime
from types import SimpleNamespace

import pytest
import requests

from hydrology import pipeline
from hydrology.core import Config
from hydrology.pipelines import acquisition
from hydrology.utils import http


class Clock:
    def __init__(self):
        self.now = datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp()
        self.monotonic = 1000.0
        self.sleeps = []

    def sleep(self, seconds):
        assert seconds >= 0
        self.sleeps.append(seconds)
        self.advance(seconds)

    def advance(self, seconds):
        self.now += seconds
        self.monotonic += seconds


class Response:
    def __init__(self, status=200, retry_after=None, body=None):
        self.status_code = status
        self.headers = {} if retry_after is None else {"Retry-After": retry_after}
        self.body = {"features": []} if body is None else body
        self.closed = False

    def close(self):
        self.closed = True

    def json(self):
        return self.body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


class Session:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(url)
        result = next(self.responses)
        if isinstance(result, BaseException):
            raise result
        return result


@pytest.fixture
def clock(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(
        http,
        "time",
        SimpleNamespace(
            time=lambda: clock.now, monotonic=lambda: clock.monotonic, sleep=clock.sleep
        ),
    )
    return clock


def config(tmp_path, **overrides):
    return Config(cache=str(tmp_path), rate_seconds=0, retries=1, **overrides)


def test_long_numeric_cooldown_is_not_shortened(clock, tmp_path):
    response = Response(429, "90")
    session = Session(response, Response())
    client = http.Client(config(tmp_path, retry_wait_budget_seconds=100), session)
    client.get("https://example.test/page")
    assert len(session.calls) == 2
    assert clock.sleeps == [90]
    assert client.wait_remaining == 10
    assert response.closed


def test_long_cooldown_defers_all_host_requests_and_survives_restart(clock, tmp_path):
    session = Session(Response(429, "1641"), Response())
    cfg = config(tmp_path)
    client = http.Client(cfg, session)
    deadline = clock.now + 1641
    with pytest.raises(http.RequestDeferred) as deferred:
        client.get("https://example.test/page")
    assert deferred.value.retry_at == deadline
    assert deferred.value.url == "https://example.test/page"
    assert "resume with the same cache" in str(deferred.value)
    assert clock.sleeps == []
    with pytest.raises(http.RequestDeferred):
        client.get("https://example.test/other-station")
    assert len(session.calls) == 1
    restarted = http.Client(cfg, session)
    with pytest.raises(http.RequestDeferred):
        restarted.get("https://example.test/other-station")
    assert len(session.calls) == 1
    clock.advance(1642)
    http.Client(cfg, session).get("https://example.test/other-station")
    assert len(session.calls) == 2


@pytest.mark.parametrize(
    "header", [None, "", "nonsense", "-1", "NaN", "inf", "Wed, 99 Xxx 2026"]
)
def test_invalid_or_missing_retry_after_uses_backoff(clock, tmp_path, header):
    session = Session(Response(503, header), Response())
    http.Client(config(tmp_path), session).get("https://example.test/page")
    assert clock.sleeps == [1]
    assert len(session.calls) == 2


@pytest.mark.parametrize("offset,expected", [(90, 90), (-30, 0)])
def test_http_date_and_past_date(clock, tmp_path, offset, expected):
    header = format_datetime(
        datetime.fromtimestamp(clock.now + offset, timezone.utc), usegmt=True
    )
    session = Session(Response(503, header), Response())
    http.Client(config(tmp_path, retry_wait_budget_seconds=100), session).get(
        "https://example.test/page"
    )
    assert sum(clock.sleeps) == expected
    assert len(session.calls) == 2


def test_http_date_over_budget_is_deferred(clock, tmp_path):
    header = format_datetime(
        datetime.fromtimestamp(clock.now + 1800, timezone.utc), usegmt=True
    )
    session = Session(Response(503, header))
    with pytest.raises(http.RequestDeferred):
        http.Client(config(tmp_path), session).get("https://example.test/page")
    assert len(session.calls) == 1 and not clock.sleeps


def test_retry_exhaustion_does_not_sleep_or_dispatch_again(clock, tmp_path):
    session = Session(Response(429, "2"), Response(429, "2"))
    client = http.Client(config(tmp_path), session)
    with pytest.raises(http.RequestDeferred, match="retries exhausted"):
        client.get("https://example.test/page")
    assert len(session.calls) == 2 and clock.sleeps == [2]
    clock.advance(10)
    with pytest.raises(http.RequestDeferred):
        client.get("https://example.test/different-metric")
    assert len(session.calls) == 2


def test_server_failure_without_header_exhausts_retries(clock, tmp_path):
    session = Session(Response(500), Response(500))
    with pytest.raises(http.ProviderError, match="retries exhausted") as exc:
        http.Client(config(tmp_path), session).get("https://example.test/page")
    assert not isinstance(exc.value, http.RequestDeferred)
    assert len(session.calls) == 2 and clock.sleeps == [1]


def test_wait_budget_is_shared_across_requests(clock, tmp_path):
    session = Session(Response(503, "40"), Response(), Response(503, "30"))
    client = http.Client(config(tmp_path), session)
    client.get("https://example.test/first")
    with pytest.raises(http.RequestDeferred, match="budget"):
        client.get("https://example.test/second")
    assert len(session.calls) == 3 and clock.sleeps == [40]
    assert client.wait_remaining == 20


def test_network_retry_uses_same_wait_budget(clock, tmp_path):
    session = Session(requests.Timeout("synthetic timeout"))
    with pytest.raises(http.RequestDeferred):
        http.Client(config(tmp_path, retry_wait_budget_seconds=0), session).get(
            "https://example.test/page"
        )
    assert len(session.calls) == 1 and not clock.sleeps


def test_interrupted_sleep_keeps_cooldown_and_completed_pages(
    clock, tmp_path, monkeypatch
):
    first = {
        "features": [{"id": "a"}],
        "links": [{"rel": "next", "href": "https://example.test/next"}],
    }
    session = Session(Response(body=first), Response(429, "90"), Response())
    cfg = config(tmp_path, retry_wait_budget_seconds=100)

    def interrupted(seconds):
        clock.advance(10)
        raise KeyboardInterrupt

    monkeypatch.setattr(http.time, "sleep", interrupted)
    with pytest.raises(KeyboardInterrupt):
        list(http.Client(cfg, session).pages("https://example.test/first"))
    assert len(session.calls) == 2
    clock.advance(81)
    monkeypatch.setattr(http.time, "sleep", clock.sleep)
    resumed = http.Client(cfg, session)
    pages = list(resumed.pages("https://example.test/first"))
    assert len(pages) == 2 and resumed.hits == 1
    assert len(session.calls) == 3


def test_quota_does_not_block_cached_pages_or_other_provider(clock, tmp_path):
    session = Session(Response(), Response(429, "1641"), Response())
    client = http.Client(config(tmp_path), session)
    client.get("https://us.test/cached")
    with pytest.raises(http.RequestDeferred):
        client.get("https://us.test/quota")
    assert client.get("https://us.test/cached")["body"] == {"features": []}
    client.get("https://ca.test/page")
    assert len(session.calls) == 3 and client.hits == 1


@pytest.mark.parametrize("metadata_deferred", [False, True])
def test_acquisition_reports_deferred_not_empty(
    clock, tmp_path, monkeypatch, metadata_deferred
):
    session = Session(Response(429, "1641"))
    cfg = config(
        tmp_path, rivers=("skagit",), start_date="2023-01-01", end_date="2023-01-01"
    )
    client = http.Client(cfg, session)

    class Adapter:
        def __init__(self, client):
            self.client = client

        def discover(self, station):
            if metadata_deferred:
                self.client.get("https://example.test/metadata")
            return {}

        def observations(self, *args):
            return self.client.get("https://example.test/data")

    monkeypatch.setattr(acquisition, "Client", lambda config: client)
    monkeypatch.setattr(acquisition, "USGS", Adapter)
    observations, _, outcomes, _ = pipeline.acquire(cfg)
    assert observations.empty
    assert set(outcomes["skagit"]) == {
        "discharge_mean",
        "temperature_mean",
        "temperature_max",
    }
    assert all(value.startswith("deferred:") for value in outcomes["skagit"].values())
    assert len(session.calls) == 1


@pytest.mark.parametrize("budget", [-1, float("inf"), float("nan")])
def test_invalid_wait_budget_rejected(budget):
    with pytest.raises(ValueError, match="retry_wait_budget_seconds"):
        Config(retry_wait_budget_seconds=budget)


def test_forward_wall_clock_jump_does_not_shorten_cooldown(
    clock, tmp_path, monkeypatch
):
    session = Session(Response(429, "90"), Response())
    client = http.Client(config(tmp_path, retry_wait_budget_seconds=100), session)
    schedule = client._schedule

    def jump_after_schedule(*args):
        schedule(*args)
        clock.now += 3600

    monkeypatch.setattr(client, "_schedule", jump_after_schedule)
    client.get("https://example.test/page")
    assert clock.sleeps == [90]
    assert len(session.calls) == 2


def test_early_sleep_return_never_dispatches_before_deadline(
    clock, tmp_path, monkeypatch
):
    session = Session(Response(429, "90"))
    client = http.Client(config(tmp_path, retry_wait_budget_seconds=100), session)
    monkeypatch.setattr(
        http.time, "sleep", lambda seconds: clock.sleeps.append(seconds)
    )
    with pytest.raises(http.RequestDeferred):
        client.get("https://example.test/page")
    assert clock.sleeps == [90]
    assert len(session.calls) == 1
