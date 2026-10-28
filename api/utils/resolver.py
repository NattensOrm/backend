# -*- coding: utf8 -*-

# Calls from the API to the fight resolver /internal/* routes.
#
# Design ruling (2026-10-28, option A): after a successful equip, unequip or
# offset, the API tells the resolver that the creature gear changed, so it
# recomputes the gear-derived state before the client gets its answer.
#
# The call is synchronous on purpose, bounded by RESOLVER_TIMEOUT. It never
# raises: the gear change is already saved, a resolver failure is only logged
# (no retry). variables is imported lazily, so this module stays importable
# without a Mongo connection for the unit tests (see tests/test_00_gear_changed.py).

import datetime
import uuid

import requests
from loguru import logger

# (connect, read) seconds
RESOLVER_TIMEOUT = (1, 2)


def notify_gear_changed(creature, reason: str) -> None:
    """
    Tells the resolver that the Creature gear changed. Never raises.

    Skipped (no call) when the Creature is not in an Instance, or when
    RESOLVER_INTERNAL_TOKEN is unset (already warned once at import).

    :param creature: The CreatureDocument, already saved.
    :param reason: 'equip', 'unequip' or 'offset'.
    """
    if not creature.instance:
        logger.trace(f'[Creature.id:{creature.id}] not in an Instance: no gear-changed notify')
        return

    try:
        from variables import RESOLVER_INTERNAL_TOKEN, RESOLVER_URL
    except Exception as e:
        logger.warning(f'[Creature.id:{creature.id}] gear-changed ({reason}) settings KO [{e}]')
        return
    if not RESOLVER_INTERNAL_TOKEN:
        logger.trace(f'[Creature.id:{creature.id}] no resolver token: no gear-changed notify')
        return

    url = (f'{RESOLVER_URL}/internal/instance/{str(creature.instance)}'
           f'/creature/{str(creature.id)}/gear-changed')
    body = {
        "reason": reason,
        "by": str(creature.id),
        "at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "requestId": str(uuid.uuid4()),
    }
    h = f'[Creature.id:{creature.id}] gear-changed ({reason})'

    try:
        response = requests.post(
            url,
            json=body,
            headers={"Authorization": f"Bearer {RESOLVER_INTERNAL_TOKEN}"},
            timeout=RESOLVER_TIMEOUT,
            )
    except Exception as e:
        logger.warning(f'{h} resolver call KO [{type(e).__name__}: {e}]')
        return

    if response.status_code == 200:
        logger.debug(f'{h} resolver call OK')
    else:
        logger.warning(f'{h} resolver call KO (status:{response.status_code})')
