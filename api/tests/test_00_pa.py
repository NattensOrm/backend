# -*- coding: utf8 -*-

import os
import sys

from unittest.mock import MagicMock

import fakeredis
import pytest

# Needed for local imports and simulate production paths (api/ on sys.path,
# resolved from this file so it works whatever the cwd pytest runs from)
LOCAL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)
sys.path.append(LOCAL_PATH)

from utils.pa import (  # noqa: E402
    BLUE_PA_MAX,
    RED_PA_MAX,
    pa_durations,
    pa_from_ttl,
    ttl_after_spend,
    )

CREATURE_ID = '00000000-0000-0000-0000-00000000c0fe'


#
# Pure arithmetic (no service needed)
#
def test_pa_constants():
    assert RED_PA_MAX == 16
    assert BLUE_PA_MAX == 8


def test_pa_durations_normal_tick():
    """ Red regenerates 1 PA per tick, blue 1 PA per 2 ticks. """
    assert pa_durations(3600) == {'red': 3600, 'blue': 7200}


def test_pa_durations_fast_tick():
    assert pa_durations(60) == {'red': 60, 'blue': 120}


@pytest.mark.parametrize('ttl', [-2, -1])
def test_pa_from_ttl_pool_full(ttl):
    """ A missing key (ttl -2) or a key without expiry (ttl -1) is a full pool. """
    assert pa_from_ttl(ttl, RED_PA_MAX, 3600) == {'pa': 16, 'ttnpa': 0, 'ttl': ttl}
    assert pa_from_ttl(ttl, BLUE_PA_MAX, 7200) == {'pa': 8, 'ttnpa': 0, 'ttl': ttl}


def test_pa_from_ttl_blue_two_spent_normal_tick():
    """
    PO example: blue pool, 2 PA just spent in a normal instance (TTL 14400).
    With the blue duration of 2 ticks that is 6 PA left, not 4.
    """
    assert pa_from_ttl(14400, BLUE_PA_MAX, 7200) == {'pa': 6, 'ttnpa': 0, 'ttl': 14400}


def test_pa_from_ttl_red_partially_regenerated():
    """ 5000s left on a red pool: 1 PA still missing, 1400s before the next one. """
    assert pa_from_ttl(5000, RED_PA_MAX, 3600) == {'pa': 15, 'ttnpa': 1400, 'ttl': 5000}


def test_pa_from_ttl_fast_instance():
    """ Fast instance (tick 60): 3 red PA spent 10s ago. """
    assert pa_from_ttl(170, RED_PA_MAX, 60) == {'pa': 13, 'ttnpa': 50, 'ttl': 170}
    # Same instance, 1 blue PA spent 30s ago (blue duration 120s)
    assert pa_from_ttl(90, BLUE_PA_MAX, 120) == {'pa': 7, 'ttnpa': 90, 'ttl': 90}


def test_ttl_after_spend_from_absent_key():
    """ Spending on a full pool starts the TTL from zero, not from Redis' -2. """
    assert ttl_after_spend(-2, 2, 7200) == 14400
    assert ttl_after_spend(-1, 1, 3600) == 3600


def test_ttl_after_spend_from_existing_ttl():
    assert ttl_after_spend(5000, 1, 3600) == 8600
    assert ttl_after_spend(170, 2, 60) == 290


#
# get_pa() / consume_pa() against fakeredis
#
@pytest.fixture
def pa_redis(monkeypatch):
    """
    utils.redis imports `variables` for env_vars. Inside api/tests that name
    resolves to tests/variables.py (loaded by conftest), not api/variables.py
    (which connects to Mongo at import), so env_vars is provided here, then
    the Redis client is swapped for an in-memory fakeredis.
    """
    # Same keys as api/variables.py: utils.redis builds its (lazy) pool from them at import
    env_vars = {
        'API_ENV': 'pytest',
        'REDIS_HOST': '127.0.0.1',
        'REDIS_PORT': 6379,
        'REDIS_BASE': 0,
        }
    monkeypatch.setattr(sys.modules['variables'], 'env_vars', env_vars, raising=False)

    import utils.redis as utils_redis

    monkeypatch.setattr(utils_redis, 'r', fakeredis.FakeStrictRedis(server=fakeredis.FakeServer()))
    return utils_redis


def test_get_pa_full_pools(pa_redis):
    pa = pa_redis.get_pa(creatureuuid=CREATURE_ID, tick=3600)
    assert pa['red'] == {'pa': 16, 'ttnpa': 0, 'ttl': -2}
    assert pa['blue'] == {'pa': 8, 'ttnpa': 0, 'ttl': -2}


def test_consume_pa_normal_tick(pa_redis):
    """ Blue costs 2 ticks of TTL per PA, red 1 tick; reading back honours the same rule. """
    pa_redis.consume_pa(creatureuuid=CREATURE_ID, redpa=1, bluepa=2, tick=3600)

    assert pa_redis.r.ttl(f'pytest:pas:{CREATURE_ID}:red') == 3600
    assert pa_redis.r.ttl(f'pytest:pas:{CREATURE_ID}:blue') == 14400

    pa = pa_redis.get_pa(creatureuuid=CREATURE_ID, tick=3600)
    assert pa['red']['pa'] == 15
    assert pa['blue']['pa'] == 6


def test_consume_pa_accumulates_on_existing_key(pa_redis):
    pa_redis.consume_pa(creatureuuid=CREATURE_ID, bluepa=1, tick=3600)
    pa_redis.consume_pa(creatureuuid=CREATURE_ID, bluepa=1, tick=3600)

    assert pa_redis.r.ttl(f'pytest:pas:{CREATURE_ID}:blue') == 14400
    assert pa_redis.get_pa(creatureuuid=CREATURE_ID, tick=3600)['blue']['pa'] == 6


def test_consume_pa_fast_tick(pa_redis):
    pa_redis.consume_pa(creatureuuid=CREATURE_ID, redpa=3, bluepa=1, tick=60)

    assert pa_redis.r.ttl(f'pytest:pas:{CREATURE_ID}:red') == 180
    assert pa_redis.r.ttl(f'pytest:pas:{CREATURE_ID}:blue') == 120

    pa = pa_redis.get_pa(creatureuuid=CREATURE_ID, tick=60)
    assert pa['red']['pa'] == 13
    assert pa['blue']['pa'] == 7


def test_consume_pa_zero_is_noop(pa_redis):
    pa_redis.consume_pa(creatureuuid=CREATURE_ID, tick=3600)

    assert not pa_redis.r.exists(f'pytest:pas:{CREATURE_ID}:red')
    assert not pa_redis.r.exists(f'pytest:pas:{CREATURE_ID}:blue')


def test_tick_is_keyword_only_and_mandatory(pa_redis):
    """
    The silent 3600 default was the bug: tick is keyword-only and has no default,
    None must be passed explicitly to mean "not in an Instance".
    """
    with pytest.raises(TypeError):
        pa_redis.get_pa(CREATURE_ID, 3600)
    with pytest.raises(TypeError):
        pa_redis.consume_pa(CREATURE_ID, 0, 1, 3600)
    with pytest.raises(TypeError):
        pa_redis.get_pa(creatureuuid=CREATURE_ID)
    with pytest.raises(TypeError):
        pa_redis.consume_pa(creatureuuid=CREATURE_ID, bluepa=1)


@pytest.fixture
def redis_spy(pa_redis, monkeypatch):
    """ Wraps the fakeredis client so the tests can assert Redis was never called. """
    spy = MagicMock(wraps=pa_redis.r)
    monkeypatch.setattr(pa_redis, 'r', spy)
    return spy


def test_get_pa_outside_instance_is_none(pa_redis, redis_spy):
    """ Designer ruling: outside an Instance (tick None) there are no PA, Redis is not read. """
    assert pa_redis.get_pa(creatureuuid=CREATURE_ID, tick=None) is None
    assert redis_spy.method_calls == []


def test_consume_pa_outside_instance_is_noop(pa_redis, redis_spy):
    """ Designer ruling: outside an Instance (tick None) nothing is consumed nor written. """
    pa_redis.consume_pa(creatureuuid=CREATURE_ID, redpa=2, bluepa=1, tick=None)

    assert redis_spy.method_calls == []
    assert not pa_redis.r.exists(f'pytest:pas:{CREATURE_ID}:red')
    assert not pa_redis.r.exists(f'pytest:pas:{CREATURE_ID}:blue')
