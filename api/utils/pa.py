# -*- coding: utf8 -*-

# Pure Action Points (PA) arithmetic, shared by utils/redis.py (read/consume)
# and the decorators. Deliberately stdlib-only at module level so it can be
# unit-tested without a Mongo/Redis connection (see tests/test_00_pa.py).
#
# PA pools live in Redis as `{API_ENV}:pas:{creatureuuid}:red|blue` whose TTL
# is the time left until the pool is full again. A missing key (TTL -2, or -1
# with no expiry) means the pool is full.
#
# Designer ruling: outside an Instance there are no PA at all (no Redis read,
# no Redis write). instance_tick() returns None in that case and the callers
# skip the pools entirely.

from typing import Optional

RED_PA_MAX = 16
BLUE_PA_MAX = 8


def pa_durations(tick: int) -> dict:
    """
    Seconds needed to regenerate one PA of each colour for a given Instance tick.

    Designer ruling: red regenerates 1 PA per Instance tick, blue 1 PA per
    2 Instance ticks. The combat resolver reads the pools with the same rule.

    :param tick: The Instance tick, in seconds.

    :return: {'red': tick, 'blue': 2 * tick}
    """
    return {
        'red': tick,
        'blue': 2 * tick,
    }


def pa_from_ttl(ttl: int, pa_max: int, duration: int) -> dict:
    """
    Converts the Redis TTL of a PA pool into the PA available right now.

    :param ttl: The raw TTL returned by Redis (negative when the key is absent).
    :param pa_max: The pool size (RED_PA_MAX or BLUE_PA_MAX).
    :param duration: Seconds needed to regenerate one PA (see pa_durations()).

    :return: {'pa': available PA, 'ttnpa': seconds to the next PA, 'ttl': the raw TTL}
    """
    # A negative TTL (-2 key absent, -1 no expiry) counts as nothing to wait for
    remaining = max(ttl, 0)

    return {
        'pa': int(round((pa_max * duration - remaining) / duration)),
        'ttnpa': remaining % duration,
        'ttl': ttl,
    }


def ttl_after_spend(ttl: int, spent: int, duration: int) -> int:
    """
    New TTL of a PA pool after spending some PA.

    :param ttl: The raw TTL returned by Redis (negative when the key is absent).
    :param spent: The number of PA spent.
    :param duration: Seconds needed to regenerate one PA (see pa_durations()).

    :return: The TTL to apply on the pool key, in seconds.
    """
    return max(ttl, 0) + spent * duration


def instance_tick(creature) -> Optional[int]:
    """
    Tick of the Instance the Creature is in, or None when it is in none
    (or the Instance no longer exists): not in an Instance means no PA.

    Reuses flask's g.Instance when a decorator already loaded it for this
    request, to avoid a second Mongo query.

    :param creature: The CreatureDocument.

    :return: The tick in seconds, or None (not in an Instance: no PA).
    """
    # Lazy imports keep this module importable without a Mongo connection for the unit tests
    from flask import g
    from loguru import logger
    from mongo.models.Instance import InstanceDocument

    if not creature.instance:
        return None

    Instance = getattr(g, 'Instance', None)
    if Instance is not None and Instance.id == creature.instance:
        return Instance.tick

    try:
        return InstanceDocument.objects(_id=creature.instance).get().tick
    except InstanceDocument.DoesNotExist:
        logger.warning(
            f'[Creature.id:{creature.id}] InstanceDocument({creature.instance}) NOTFOUND: no PA'
            )
        return None
