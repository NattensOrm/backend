import uuid

from mongoengine import (
    Document,
    # EmbeddedDocument,
    )
from mongoengine.fields import (
    DateTimeField,
    # EmbeddedDocumentField,
    # IntField,
    # DictField,
    # ListField,
    # StringField,
    UUIDField,
)

from mongo.utils import utcnow

#
# Collection: squad
#


class SquadDocument(Document):
    """
    Define the document for: Squad

    Fields:
    - _id       (UUIDField)
    - created   (DateTimeField)
    - leader    (UUIDField)
    - updated   (DateTimeField)
    """
    _id = UUIDField(binary=False, primary_key=True, default=uuid.uuid4)
    created = DateTimeField(default=utcnow)
    leader = UUIDField(binary=False, required=True)
    updated = DateTimeField(default=utcnow)

    meta = {
        'collection': 'squads',
        'indexes': [],
        'uuid_representation': 'standard'
    }
