"""Task 4 (T2): in-process token-bucket rate limiter for the public widget
chat endpoint. The clock is injected so tests are deterministic and fast
(no real `time.sleep`).
"""
from tfm_rag.infrastructure.api.rate_limiting import TokenBucketRateLimiter


class _FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_allows_up_to_burst_requests_immediately() -> None:
    clock = _FakeClock()
    limiter = TokenBucketRateLimiter(rate_per_minute=60, burst=3, clock=clock)

    assert limiter.try_acquire("k") is None
    assert limiter.try_acquire("k") is None
    assert limiter.try_acquire("k") is None


def test_denies_the_request_beyond_burst() -> None:
    clock = _FakeClock()
    limiter = TokenBucketRateLimiter(rate_per_minute=60, burst=3, clock=clock)
    for _ in range(3):
        limiter.try_acquire("k")

    retry_after = limiter.try_acquire("k")

    assert retry_after is not None
    assert retry_after > 0


def test_retry_after_reflects_refill_rate() -> None:
    # 60/min = 1 token/sec. Burst=1: after consuming the only token, the
    # next one is available in ~1s.
    clock = _FakeClock()
    limiter = TokenBucketRateLimiter(rate_per_minute=60, burst=1, clock=clock)
    limiter.try_acquire("k")

    retry_after = limiter.try_acquire("k")

    assert retry_after is not None
    assert 0.9 < retry_after <= 1.0


def test_allows_again_after_enough_time_has_passed() -> None:
    clock = _FakeClock()
    limiter = TokenBucketRateLimiter(rate_per_minute=60, burst=1, clock=clock)
    limiter.try_acquire("k")
    assert limiter.try_acquire("k") is not None  # denied, bucket empty

    clock.advance(1.1)  # a bit over 1s → one token refilled

    assert limiter.try_acquire("k") is None


def test_bucket_never_exceeds_capacity_even_after_a_long_idle_period() -> None:
    clock = _FakeClock()
    limiter = TokenBucketRateLimiter(rate_per_minute=60, burst=3, clock=clock)
    limiter.try_acquire("k")  # 2 tokens left

    clock.advance(3600)  # an hour of idle time — must NOT accumulate unboundedly

    # Only 3 (capacity) should be acquirable back-to-back, not more.
    assert limiter.try_acquire("k") is None
    assert limiter.try_acquire("k") is None
    assert limiter.try_acquire("k") is None
    assert limiter.try_acquire("k") is not None


def test_different_keys_have_independent_buckets() -> None:
    clock = _FakeClock()
    limiter = TokenBucketRateLimiter(rate_per_minute=60, burst=1, clock=clock)

    assert limiter.try_acquire("chatbot-a:1.2.3.4") is None
    assert limiter.try_acquire("chatbot-b:1.2.3.4") is None  # different key, own bucket
    assert limiter.try_acquire("chatbot-a:1.2.3.4") is not None  # a's bucket is empty


# --- unbounded-growth / eviction (security fix: bound `_buckets` cardinality) --


def test_rotating_distinct_keys_does_not_grow_buckets_beyond_cap() -> None:
    """An attacker hammering the endpoint with a fresh (even non-existent)
    `public_key` on every request must not be able to grow `_buckets`
    without bound — that's a memory-exhaustion DoS."""
    clock = _FakeClock()
    limiter = TokenBucketRateLimiter(
        rate_per_minute=60, burst=3, clock=clock, max_keys=10
    )

    for i in range(1000):
        limiter.try_acquire(f"attacker-key-{i}")

    assert len(limiter._buckets) <= 10


def test_cap_eviction_does_not_reset_an_active_keys_budget() -> None:
    """A key that keeps getting touched (i.e. is genuinely "active") must
    never be picked as the eviction victim just because many other,
    one-shot keys were inserted around it — otherwise an attacker could
    use key-rotation to give a *different*, currently-throttled key a
    free refill."""
    clock = _FakeClock()
    limiter = TokenBucketRateLimiter(
        rate_per_minute=60, burst=1, clock=clock, max_keys=5
    )

    # Exhaust the victim's only token: it is now under rate-limit pressure.
    assert limiter.try_acquire("victim") is None
    assert limiter.try_acquire("victim") is not None

    # Attacker rotates far more distinct keys than the cap allows, but the
    # victim keeps getting touched (denied) in between each rotation, so it
    # stays "active" and must never be the eviction victim.
    for i in range(50):
        limiter.try_acquire(f"attacker-key-{i}")
        retry_after = limiter.try_acquire("victim")
        assert retry_after is not None, (
            "victim's bucket was evicted and silently refilled — "
            "budget was reset by eviction of unrelated keys"
        )

    assert len(limiter._buckets) <= 5


def test_stale_idle_buckets_are_evicted_by_periodic_sweep() -> None:
    """Buckets that have refilled back to full capacity and have then sat
    untouched for the idle window should eventually be swept away, even
    without ever hitting the hard cap."""
    clock = _FakeClock()
    limiter = TokenBucketRateLimiter(
        rate_per_minute=60,
        burst=3,
        clock=clock,
        max_keys=10_000,
        idle_ttl_seconds=60.0,
        sweep_interval=4,
    )

    limiter.try_acquire("idle-key")  # bucket created, 2/3 tokens left
    clock.advance(120.0)  # refills to full capacity AND goes stale

    # Drive enough calls (on other keys) to trigger the periodic sweep.
    for i in range(8):
        limiter.try_acquire(f"other-{i}")

    assert "idle-key" not in limiter._buckets


def test_periodic_sweep_never_evicts_a_bucket_still_under_pressure() -> None:
    """A bucket that hasn't refilled back to capacity (i.e. still reflects
    real rate-limit pressure) must survive the idle sweep even after a
    long time, as long as it isn't literally "full"."""
    clock = _FakeClock()
    limiter = TokenBucketRateLimiter(
        rate_per_minute=1,  # very slow refill: 1 token per 60s
        burst=3,
        clock=clock,
        max_keys=10_000,
        idle_ttl_seconds=60.0,
        sweep_interval=4,
    )

    limiter.try_acquire("busy-key")
    limiter.try_acquire("busy-key")
    limiter.try_acquire("busy-key")  # bucket now empty (3/3 consumed)
    clock.advance(90.0)  # idle beyond ttl, but only ~1.5 tokens refilled (< capacity)

    for i in range(8):
        limiter.try_acquire(f"other-{i}")

    assert "busy-key" in limiter._buckets
