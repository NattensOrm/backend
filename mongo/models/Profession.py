import uuid

from mongoengine import (
    Document,
    )
from mongoengine.fields import (
    # BooleanField,
    DateTimeField,
    # EmbeddedDocumentField,
    IntField,
    # DictField,
    # ListField,
    # StringField,
    UUIDField,
)

from mongo.utils import utcnow

#
# Collection: profession
#


class ProfessionDocument(Document):
    """
    Define the document for: Profession

    Fields:
    - _id       (UUIDField)
    - gathering (IntField)
    - mixology  (IntField)
    - recycling (IntField)
    - skinning  (IntField)
    - tanning   (IntField)
    - tracking  (IntField)
    - updated   (DateTimeField)
    """
    _id = UUIDField(binary=False, primary_key=True, default=uuid.uuid4)
    gathering = IntField(required=True, default=0)
    mixology = IntField(required=True, default=0)
    recycling = IntField(required=True, default=0)
    skinning = IntField(required=True, default=0)
    tanning = IntField(required=True, default=0)
    tracking = IntField(required=True, default=0)
    updated = DateTimeField(default=utcnow)

    meta = {
        'collection': 'professions',
        'indexes': [],
        'uuid_representation': 'standard'
    }
