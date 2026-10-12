# -*- coding: utf8 -*-

import datetime
import uuid

from mongoengine import (
    Document,
    EmbeddedDocument,
    )
from mongoengine.fields import (
    # BooleanField,
    DateTimeField,
    EmbeddedDocumentField,
    IntField,
    # DictField,
    ListField,
    StringField,
    UUIDField,
)

#
# Collection: skills
#


class SkillEntry(EmbeddedDocument):
    """
    Define the embedded document for: Skill.skills[]

    Fields:
    - name      (StringField)
    - level     (IntField)

    `name` is the FightClass code name (e.g. "BloodRush").
    The `skills` list must not contain two entries with the same name.
    This is not enforced by the ODM; it is enforced by the learn route.
    """
    name = StringField(required=True)
    level = IntField(required=True, min_value=1)


class SkillDocument(Document):
    """
    Define the document for: Skill
    One document per Creature, sharing the same _id.

    Fields:
    - _id       (UUIDField)
    - skills    (ListField of EmbeddedDocumentField)
    - loadout   (ListField of StringField)
    - updated   (DateTimeField)

    `loadout` holds the names of the learnt skills equipped for fights.
    An empty loadout means all learnt skills are available.
    """
    _id = UUIDField(binary=False, primary_key=True, default=uuid.uuid4)
    skills = ListField(EmbeddedDocumentField(SkillEntry), default=list)
    loadout = ListField(StringField(), default=list)
    updated = DateTimeField(default=datetime.datetime.utcnow)

    meta = {
        'collection': 'skills',
        'indexes': [],
        'uuid_representation': 'standard'
    }
