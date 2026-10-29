# -*- coding: utf8 -*-

import datetime

from mongoengine.queryset.visitor import Q

from mongo.models.Item import ItemDocument
from mongo.utils import utcnow

#
# Item lock, shared by equip and recycling
#
# Equip writes the Creature slots, recycling deletes the Item: two documents,
# so neither route can see the other's write atomically. Both take this lock
# on the Item document first, with one conditional update, which Mongo runs
# one at a time: of an equip and a recycling of the same Item, only one gets
# it, and the other is refused.
# - equip holds it around the slot write, then releases it;
# - recycling holds it, re-reads the slots (an equip that released the lock
#   has written them by then), then deletes the Item.
# The lock expires only to free an Item whose holder crashed before
# releasing it. Its date is the holder's token: a holder that stalled past
# the expiry can neither release nor delete under the next holder's lock.
ITEM_LOCK_TTL = datetime.timedelta(seconds=30)


def lock_item(itemuuid):
    """
    Locks the Item. Returns the lock token (its date), or None when the Item
    is gone or already locked.
    """
    now = utcnow()
    # Mongo keeps dates to the millisecond: the token must match what it stores
    token = now.replace(microsecond=now.microsecond // 1000 * 1000)
    free = Q(locked=None) | Q(locked__lt=token - ITEM_LOCK_TTL)
    if ItemDocument.objects(Q(_id=itemuuid) & free).update_one(set__locked=token) == 1:
        return token
    return None


def unlock_item(itemuuid, token) -> None:
    """ Releases the Item lock, if this token still holds it. """
    ItemDocument.objects(_id=itemuuid, locked=token).update_one(unset__locked=True)


def delete_locked_item(itemuuid, token) -> bool:
    """ Deletes the Item, if this token still holds it. True when deleted. """
    return ItemDocument.objects(_id=itemuuid, locked=token).delete() == 1
