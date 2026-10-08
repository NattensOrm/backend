# -*- coding: utf8 -*-

import os
import sys
import uuid

# Needed for local imports and simulate production paths
LOCAL_PATH = os.path.dirname(os.path.abspath('mongo'))
sys.path.append(LOCAL_PATH)

from mongo.models.Skill import SkillDocument, SkillEntry  # noqa: E402

CREATURE_NAME = 'PyTest Creature'
CREATURE_ID = str(uuid.uuid3(uuid.NAMESPACE_DNS, CREATURE_NAME))


def test_mongodb_skill_new():
    """
    Creating a new SkillDocument
    """

    newSkill = SkillDocument(
        _id=CREATURE_ID,
    )
    newSkill.save()

    assert str(newSkill.id) == CREATURE_ID
    assert newSkill.skills == []
    assert newSkill.loadout == []


def test_mongodb_skill_get():
    """
    Querying a SkillDocument
    """
    pass


def test_mongodb_skill_search():
    """
    Searching a SkillDocument
    """
    assert SkillDocument.objects(_id=CREATURE_ID).count() == 1

    Skill = SkillDocument.objects(_id=CREATURE_ID).get()
    assert str(Skill.id) == CREATURE_ID


def test_mongodb_skill_update():
    """
    Updating a SkillDocument (learnt skill + loadout)
    """
    Skill = SkillDocument.objects(_id=CREATURE_ID).get()
    Skill.skills.append(SkillEntry(name='BloodRush', level=1))
    Skill.loadout = ['BloodRush']
    Skill.save()

    Skill.reload()
    assert len(Skill.skills) == 1
    assert Skill.skills[0].name == 'BloodRush'
    assert Skill.skills[0].level == 1
    assert Skill.loadout == ['BloodRush']


def test_mongodb_skill_del():
    """
    Removing a SkillDocument
    """

    Skills = SkillDocument.objects(_id=CREATURE_ID)
    if Skills.count() > 0:
        for Skill in Skills:
            Skill.delete()

    assert SkillDocument.objects(_id=CREATURE_ID).count() == 0
