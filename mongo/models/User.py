import uuid

from mongoengine import (
    Document,
    EmbeddedDocument,
    )
from mongoengine.fields import (
    BooleanField,
    DateTimeField,
    EmbeddedDocumentField,
    # IntField,
    # DictField,
    # ListField,
    StringField,
    UUIDField,
)

from mongo.utils import utcnow

#
# Collection: user
#


class UserDiscord(EmbeddedDocument):
    """
    Define the embedded document for: User.discord

    Fields:
    - id    (StringField) Discord user id (snowflake): the identity, never
                          changes. A str: 64 bits don't fit a JS Number
    - name  (StringField) Discord username: display only, refreshed by the
                          bot - users can rename, never look a User up by it

    Unlinked: both None (stored as an empty discord: {}).
    """
    id = StringField(default=None)
    name = StringField(default=None)


class UserDocument(Document):
    """
    Define the document for: User

    Fields:
    - _id       (UUIDField)
    - active    (BooleanField)
    - created   (DateTimeField)
    - discord   (EmbeddedDocumentField)
    - hash      (StringField)
    - name      (StringField)
    - updated   (DateTimeField)
    """
    _id = UUIDField(binary=False, primary_key=True, default=uuid.uuid4)
    active = BooleanField(required=True, default=False)
    created = DateTimeField(default=utcnow)
    discord = EmbeddedDocumentField(UserDiscord, required=True)
    hash = StringField(required=True)
    name = StringField(required=True)
    updated = DateTimeField(default=utcnow)

    meta = {
        'collection': 'users',
        'indexes': [
            # One Discord user <-> one User, enforced by Mongo. Partial:
            # unlinked Users have no discord.id and don't count
            {
                'fields': ['discord.id'],
                'unique': True,
                'partialFilterExpression': {'discord.id': {'$type': 'string'}},
            },
        ],
        'uuid_representation': 'standard'
        }
