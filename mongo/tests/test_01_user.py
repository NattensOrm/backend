# -*- coding: utf8 -*-

import os
import sys
import uuid

import pytest
from mongoengine.errors import NotUniqueError

# Needed for local imports and simulate production paths
LOCAL_PATH = os.path.dirname(os.path.abspath('mongo'))
sys.path.append(LOCAL_PATH)

from mongo.models.User import UserDocument, UserDiscord  # noqa: E402

USER_NAME = 'user@example.net'
USER_ID = str(uuid.uuid3(uuid.NAMESPACE_DNS, USER_NAME))
USER_HASH = 'PYTEST_HASH_PLACEHOLDER'


def test_mongodb_user_new():
    """
    Creating a new UserDocument
    """

    newUser = UserDocument(
        _id=uuid.uuid3(uuid.NAMESPACE_DNS, USER_NAME),
        discord=UserDiscord(),
        hash=USER_HASH,
        name=USER_NAME,
    )
    newUser.save()

    assert str(newUser.id) == USER_ID
    assert newUser.discord.id is None
    assert newUser.hash == USER_HASH
    assert newUser.name == USER_NAME


def test_mongodb_user_get():
    """
    Querying a UserDocument
    """
    pass


def test_mongodb_user_search():
    """
    Searching a User
    """
    assert UserDocument.objects(_id=USER_ID).count() == 1
    assert UserDocument.objects(name=USER_NAME).count() == 1

    User = UserDocument.objects(_id=USER_ID).first()
    assert str(User.id) == USER_ID


def test_mongodb_user_discord_id_is_unique():
    """
    One Discord user <-> one User: the partial unique index on discord.id
    refuses a 2nd User with the same Discord id, unlinked Users don't count
    """
    users = [
        UserDocument(_id=uuid.uuid4(), discord=UserDiscord(), hash=USER_HASH, name=f'unlinked{i}@example.net')  # noqa: E501
        for i in range(2)
        ]
    linked = UserDocument(
        _id=uuid.uuid4(),
        discord=UserDiscord(id='123456789012345678', name='tester'),
        hash=USER_HASH,
        name='linked@example.net',
        )
    duplicate = UserDocument(
        _id=uuid.uuid4(),
        discord=UserDiscord(id='123456789012345678', name='someone_else'),
        hash=USER_HASH,
        name='duplicate@example.net',
        )
    try:
        for User in users:
            User.save()
        linked.save()
        with pytest.raises(NotUniqueError):
            duplicate.save()
        assert UserDocument.objects(discord__id='123456789012345678').count() == 1
    finally:
        for User in [*users, linked]:
            User.delete()
