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
# releasing it.
ITEM_LOCK_TTL = datetime.timedelta(seconds=30)


def lock_item(itemuuid) -> bool:
    """ Locks the Item; False when it is gone or already locked. """
    now = utcnow()
    free = Q(locked=None) | Q(locked__lt=now - ITEM_LOCK_TTL)
    return ItemDocument.objects(Q(_id=itemuuid) & free).update_one(set__locked=now) == 1


def unlock_item(itemuuid) -> None:
    """ Releases the Item lock. A deleted Item has nothing to release. """
    ItemDocument.objects(_id=itemuuid).update_one(unset__locked=True)
