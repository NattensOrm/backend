# -*- coding: utf8 -*-

import os
import sys
import uuid

import fakeredis
import pytest

# Needed for local imports and simulate production paths (api/ on sys.path,
# resolved from this file so it works whatever the cwd pytest runs from)
LOCAL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)
sys.path.append(LOCAL_PATH)

# Designer ruling (2026-10-08): outside an instance nothing of the creature
# exists in Redis. Leaving purges every key the creature owns in the instance
# being left, plus its creature-wide PA pools. Keys of other creatures, and
# actives of the same creature in ANOTHER instance, are not touched.

API_ENV = 'pytest'
CREATURE = str(uuid.uuid4())
OTHER_CREATURE = str(uuid.uuid4())
INSTANCE = str(uuid.uuid4())
OTHER_INSTANCE = str(uuid.uuid4())

ACTIVE = {
    "bearer": CREATURE,
    "duration_base": 60,
    "id": str(uuid.uuid4()),
    "instance": INSTANCE,
    "name": 'PyTest',
    "type": 'effect',
    }


#
# purge_creature_keys() against fakeredis
#
@pytest.fixture
def purge_redis(monkeypatch):
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


def _seed(r):
    """ Seeds every key family of CREATURE in INSTANCE, plus bystanders. """
    purged = [
        f"{API_ENV}:pas:{CREATURE}:red",
        f"{API_ENV}:pas:{CREATURE}:blue",
        f"{API_ENV}:{INSTANCE}:effects:{CREATURE}:PyTest",
        f"{API_ENV}:{INSTANCE}:statuses:{CREATURE}:PyTest",
        f"{API_ENV}:{INSTANCE}:cds:{CREATURE}:PyTest",
        f"{INSTANCE}:ammo:{CREATURE}",
        f"{API_ENV}:{INSTANCE}:ammo:{CREATURE}",
        ]
    survivors = [
        # Another creature in the same instance
        f"{API_ENV}:pas:{OTHER_CREATURE}:red",
        f"{API_ENV}:{INSTANCE}:effects:{OTHER_CREATURE}:PyTest",
        f"{INSTANCE}:ammo:{OTHER_CREATURE}",
        # The same creature's actives in another instance
        f"{API_ENV}:{OTHER_INSTANCE}:effects:{CREATURE}:PyTest",
        f"{OTHER_INSTANCE}:ammo:{CREATURE}",
        ]

    r.set(f"{API_ENV}:pas:{CREATURE}:red", 'None', ex=9000)
    r.set(f"{API_ENV}:pas:{CREATURE}:blue", 'None', ex=9000)
    r.set(f"{API_ENV}:pas:{OTHER_CREATURE}:red", 'None', ex=9000)
    for key in (
        f"{API_ENV}:{INSTANCE}:effects:{CREATURE}:PyTest",
        f"{API_ENV}:{INSTANCE}:statuses:{CREATURE}:PyTest",
        f"{API_ENV}:{INSTANCE}:cds:{CREATURE}:PyTest",
        f"{API_ENV}:{INSTANCE}:effects:{OTHER_CREATURE}:PyTest",
        f"{API_ENV}:{OTHER_INSTANCE}:effects:{CREATURE}:PyTest",
    ):
        r.hset(key, mapping=ACTIVE)
        r.expire(key, 60)
    for key in (
        f"{INSTANCE}:ammo:{CREATURE}",
        f"{API_ENV}:{INSTANCE}:ammo:{CREATURE}",
        f"{INSTANCE}:ammo:{OTHER_CREATURE}",
        f"{OTHER_INSTANCE}:ammo:{CREATURE}",
    ):
        r.set(key, 10)

    assert sorted(k.decode() for k in r.keys('*')) == sorted(purged + survivors)
    return purged, survivors


def test_purge_creature_keys_deletes_every_key_of_the_leaver(purge_redis):
    purged, survivors = _seed(purge_redis.r)

    deleted = purge_redis.purge_creature_keys(creatureuuid=CREATURE, instanceuuid=INSTANCE)

    assert deleted == len(purged)
    assert sorted(k.decode() for k in purge_redis.r.keys('*')) == sorted(survivors)


def test_purge_creature_keys_nothing_to_delete(purge_redis):
    # Full PA pools and no actives: no key at all, nothing fails
    assert purge_redis.purge_creature_keys(creatureuuid=CREATURE, instanceuuid=INSTANCE) == 0
    assert purge_redis.r.keys('*') == []


def test_purge_creature_keys_is_idempotent(purge_redis):
    purged, survivors = _seed(purge_redis.r)

    assert purge_redis.purge_creature_keys(creatureuuid=CREATURE, instanceuuid=INSTANCE) == len(purged)  # noqa: E501
    assert purge_redis.purge_creature_keys(creatureuuid=CREATURE, instanceuuid=INSTANCE) == 0
    assert sorted(k.decode() for k in purge_redis.r.keys('*')) == sorted(survivors)


def test_purge_creature_keys_patterns_match_bearer_segment_exactly(purge_redis):
    # Every family names the bearer as a whole segment: no *{creature}* wildcard
    for pattern in purge_redis.CREATURE_KEY_PATTERNS:
        assert '*{creature}' not in pattern
        assert '{creature}*' not in pattern
