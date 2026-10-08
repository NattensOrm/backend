# -*- coding: utf8 -*-

import json
import os
import redis

from loguru import logger

from variables import env_vars

# Left unconfigured, redis-py defaults to a 100-connection pool that raises
# MaxConnectionsError as soon as it's exhausted - fine at low concurrency,
# but a service popping hundreds/thousands of concurrent workers can blow
# past that fast. A blocking pool makes callers wait briefly for a free
# connection instead of failing outright, and the size is tunable per-
# deployment via env var.
REDIS_MAX_CONNECTIONS = int(os.environ.get('REDIS_MAX_CONNECTIONS', 500))
REDIS_POOL_TIMEOUT = int(os.environ.get('REDIS_POOL_TIMEOUT', 5))

try:
    pool = redis.BlockingConnectionPool(
        host=env_vars['REDIS_HOST'],
        port=env_vars['REDIS_PORT'],
        db=env_vars['REDIS_BASE'],
        max_connections=REDIS_MAX_CONNECTIONS,
        timeout=REDIS_POOL_TIMEOUT,
        )
    r = redis.StrictRedis(connection_pool=pool)
except Exception as e:
    logger.error(f'Redis Connection KO (r) [{e}]')
else:
    logger.debug(f'Redis Connection OK (r) [max_connections:{REDIS_MAX_CONNECTIONS}]')

# This used to be a symlink to a connector shared with api/auth
# (_redis/redis.py) - now a real, trimmed-down file with only what discord
# actually calls: get_pa (read-only PA checks) and cput (pub/sub). No
# consume_pa, qput, or str2typed here - discord doesn't consume PA, and it
# consumes queues via yarqueue directly (see subtasks/yqueue.py) rather
# than through this module's producer-side qput helper.
# discord/variables.py already has its own str2bool, unrelated to this
# file. See api/docs/ARCHITECTURE.md's "Redis usage" for why the symlink
# got dropped.


def _pa_from_ttl(ttl: int, pa_max: int, duration: int) -> dict:
    """
    Converts the Redis TTL of a PA pool into the PA available right now.
    Same semantics as api/utils/pa.py's pa_from_ttl(), kept local on purpose.

    :param ttl: The raw TTL returned by Redis (negative when the key is absent).
    :param pa_max: The pool size.
    :param duration: Seconds needed to regenerate one PA.

    :return: {'pa': available PA, 'ttnpa': seconds to the next PA, 'ttl': the raw TTL}
    """
    # A negative TTL (-2 key absent, -1 no expiry) counts as nothing to wait for
    remaining = max(ttl, 0)

    return {
        "pa": int(round((pa_max * duration - remaining) / duration)),
        "ttnpa": remaining % duration,
        "ttl": ttl,
    }


def get_pa(creatureuuid: str, *, tick: int) -> dict:
    """
    Retrieves the blue and red PA and their TTL for a Creature.

    :param creatureuuid: The UUID of the creature.
    :param tick: The tick (seconds) of the Creature's Instance (InstanceDocument.tick,
                 3600 when the Creature is in none). Red regenerates 1 PA per tick,
                 blue 1 PA per 2 ticks - same rule as api/utils/pa.py.

    :return: A dictionary with PA and TTL information for both blue and red.
    """
    # Constants
    RED_PA_MAX = 16
    BLUE_PA_MAX = 8
    RED_PA_DURATION = tick
    BLUE_PA_DURATION = 2 * tick

    ttls = {
        "blue": r.ttl(f"{env_vars['API_ENV']}:pas:{creatureuuid}:blue"),
        "red": r.ttl(f"{env_vars['API_ENV']}:pas:{creatureuuid}:red"),
    }

    return {
        "blue": _pa_from_ttl(ttls['blue'], BLUE_PA_MAX, BLUE_PA_DURATION),
        "red": _pa_from_ttl(ttls['red'], RED_PA_MAX, RED_PA_DURATION),
    }


def cput(channel: str, msg: dict) -> None:
    """
    Publishes a message (dict) to a specified Redis PubSub channel.

    :param channel: Name of the Redis channel to publish to.
    :param msg: The message dictionary to be published.
    """
    try:
        logger.trace(f'Pubsub PUBLISH >> (channel:{channel})')
        r.publish(channel, json.dumps(msg))
    except Exception as e:
        msg = (f'Pubsub PUBLISH KO (channel:{channel}) [{e}]')
        logger.error(msg)
    else:
        logger.trace(f'Pubsub PUBLISH OK (channel:{channel})')
