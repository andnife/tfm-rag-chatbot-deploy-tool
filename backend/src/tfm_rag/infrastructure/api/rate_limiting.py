"""In-process token-bucket rate limiter (Task 4 / T2).

Used to throttle the unauthenticated public widget endpoints
(`/api/public/chatbots/{public_key}/...`), which have no auth boundary
(the `public_key` in the URL IS the credential) and can trigger real LLM
calls — currently the only abuse control on that surface.

MULTI-WORKER LIMITATION: state (the token buckets) lives entirely in this
process's memory. Running multiple uvicorn/gunicorn workers, or multiple
replicas behind a load balancer, means each process enforces its own
independent bucket per key — so the *effective* global rate limit becomes
`rate_per_minute * num_processes`, not a true shared limit. This is
acceptable for a single-process deployment. If/when the app scales
horizontally, replace this with a shared store (Redis, etc.) — there was a
`Settings.rate_limit_redis_url` placeholder for this that was removed as
dead code in this same task; treat it as prior art, not a real setting.

BOUNDED CARDINALITY: the rate-limit dependency runs *before* route
resolution, so any request with an attacker-controlled (even non-existent)
`public_key` creates a bucket entry — the first request for a fresh key is
always allowed, so bucket creation itself can never be throttled. Left
unbounded, a client that rotates keys on every request would grow
`_buckets` without limit (memory-exhaustion DoS). To prevent that, this
limiter (a) evicts buckets that have refilled back to full capacity and
then sat idle past `idle_ttl_seconds`, via a cheap periodic sweep every
`sweep_interval` calls (not a per-request full scan), and (b) enforces a
hard `max_keys` cap, evicting the least-recently-touched bucket (LRU, via
`OrderedDict`) whenever a brand new key would exceed it. Because every
`try_acquire` call — allowed or denied — refreshes the bucket's position,
a key that keeps getting real traffic is never the LRU pick, so eviction
of unrelated (attacker-rotated) keys can't hand out a free refill to a key
that's still under active rate-limit pressure.
"""
from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class _Bucket:
    tokens: float
    updated_at: float


class TokenBucketRateLimiter:
    """A per-key token bucket, refilled continuously over time.

    `try_acquire(key)` attempts to consume one token for `key`:
      * Returns `None` if a token was available (request allowed).
      * Returns the number of seconds to wait before retrying otherwise
        (suitable for a `Retry-After` response header), and does NOT
        consume a token.

    The clock is injectable for deterministic unit testing; production
    code should use the default (`time.monotonic`).

    `try_acquire` is synchronous (no `await` anywhere in it), so when
    called from the async FastAPI dependency it runs to completion
    without yielding to the event loop — i.e. it's atomic under asyncio's
    single-threaded cooperative scheduling. A lock would only be needed
    if this were ever called concurrently from multiple OS threads.
    """

    def __init__(
        self,
        *,
        rate_per_minute: int,
        burst: int,
        clock: Callable[[], float] = time.monotonic,
        max_keys: int = 10_000,
        idle_ttl_seconds: float = 3600.0,
        sweep_interval: int = 256,
    ) -> None:
        if rate_per_minute <= 0:
            raise ValueError("rate_per_minute must be positive")
        if burst <= 0:
            raise ValueError("burst must be positive")
        if max_keys <= 0:
            raise ValueError("max_keys must be positive")
        if sweep_interval <= 0:
            raise ValueError("sweep_interval must be positive")
        self._refill_per_second = rate_per_minute / 60.0
        self._capacity = float(burst)
        self._clock = clock
        self._max_keys = max_keys
        self._idle_ttl_seconds = idle_ttl_seconds
        self._sweep_interval = sweep_interval
        self._calls_since_sweep = 0
        # Order = recency of access (LRU): every touched key is moved to
        # the end, so the front is always the least-recently-touched entry.
        self._buckets: OrderedDict[str, _Bucket] = OrderedDict()

    def try_acquire(self, key: str) -> float | None:
        now = self._clock()

        self._calls_since_sweep += 1
        if self._calls_since_sweep >= self._sweep_interval:
            self._calls_since_sweep = 0
            self._evict_stale_idle_buckets(now)

        bucket = self._buckets.get(key)
        if bucket is None:
            self._evict_for_new_key()
            bucket = _Bucket(tokens=self._capacity, updated_at=now)
            self._buckets[key] = bucket
        else:
            elapsed = max(0.0, now - bucket.updated_at)
            bucket.tokens = min(
                self._capacity, bucket.tokens + elapsed * self._refill_per_second
            )
            bucket.updated_at = now
        self._buckets.move_to_end(key)

        if bucket.tokens >= 1.0:
            bucket.tokens -= 1.0
            return None

        missing = 1.0 - bucket.tokens
        return missing / self._refill_per_second

    def _evict_for_new_key(self) -> None:
        """Enforce the hard cardinality cap before inserting a brand new
        key. Evicts the least-recently-touched bucket(s) — never the key
        currently being inserted, since it isn't in the dict yet."""
        while len(self._buckets) >= self._max_keys:
            self._buckets.popitem(last=False)

    def _evict_stale_idle_buckets(self, now: float) -> None:
        """Opportunistic sweep: drop buckets that are back at full
        capacity (no rate-limit pressure) and haven't been touched for
        `idle_ttl_seconds`. Scans from the LRU end only, and stops at the
        first entry that doesn't qualify — since entries are ordered by
        recency, later ones were touched more recently and are even less
        likely to qualify, so this is cheap in the common case rather
        than a full-dict scan on every request."""
        while self._buckets:
            key, bucket = next(iter(self._buckets.items()))
            idle_for = now - bucket.updated_at
            if idle_for < self._idle_ttl_seconds:
                break
            refilled = min(
                self._capacity, bucket.tokens + idle_for * self._refill_per_second
            )
            if refilled < self._capacity:
                break
            del self._buckets[key]
