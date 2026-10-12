# -*- coding: utf8 -*-

import os
import sys
import uuid

# Needed for local imports and simulate production paths
LOCAL_PATH = os.path.dirname(os.path.abspath('mongo'))
sys.path.append(LOCAL_PATH)

from mongo.models.Instance import InstanceDocument  # noqa: E402

CREATURE_NAME = 'PyTest Creature'
CREATURE_ID = str(uuid.uuid3(uuid.NAMESPACE_DNS, CREATURE_NAME))
LEAVER_NAME = 'PyTest Leaver'
LEAVER_ID = str(uuid.uuid3(uuid.NAMESPACE_DNS, LEAVER_NAME))
MAP_ID = 1


def test_mongodb_instance_new():
    """
    Creating a new InstanceDocument
    """

    newInstance = InstanceDocument(
        creator=CREATURE_ID,
        map=MAP_ID,
        )
    newInstance.save()

    assert str(newInstance.creator) == CREATURE_ID
    assert newInstance.map == MAP_ID
    # Nobody left a freshly created instance
    assert newInstance.leavers == []


def test_mongodb_instance_search():
    """
    Searching a InstanceDocument
    """
    assert InstanceDocument.objects(creator=CREATURE_ID).count() == 1

    Instance = InstanceDocument.objects(creator=CREATURE_ID).get()
    assert str(Instance.creator) == CREATURE_ID
    assert Instance.leavers == []


def test_mongodb_instance_leavers():
    """
    Recording a leaver on an InstanceDocument (atomic add_to_set)
    """
    Instance = InstanceDocument.objects(creator=CREATURE_ID).get()

    InstanceDocument.objects(_id=Instance.id).update_one(add_to_set__leavers=LEAVER_ID)
    # Adding the same leaver twice must not duplicate it
    InstanceDocument.objects(_id=Instance.id).update_one(add_to_set__leavers=LEAVER_ID)
    Instance.reload()

    assert [str(leaver) for leaver in Instance.leavers] == [LEAVER_ID]


def test_mongodb_instance_del():
    """
    Removing a InstanceDocument
    """

    Instances = InstanceDocument.objects(creator=CREATURE_ID)
    if Instances.count() > 0:
        for Instance in Instances:
            Instance.delete()

    assert InstanceDocument.objects(creator=CREATURE_ID).count() == 0
