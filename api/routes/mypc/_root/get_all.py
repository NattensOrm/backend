# -*- coding: utf8 -*-

from flask import g, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from loguru import logger

from mongo.models.Creature import CreatureDocument
from mongo.models.Skill import SkillDocument

from utils.decorators import check_user_exists


# API: GET /mypc
@jwt_required()
# Custom decorators
@check_user_exists
def mypc_get_all():
    g.h = f'[User.id:{g.User.id}]'
    try:
        Creatures = CreatureDocument.objects(account=g.User.id)
        # Learnt skills: one query for all the Creatures, indexed by Creature.id
        Skills = SkillDocument.objects(_id__in=[Creature.id for Creature in Creatures])
        skills_by_id = {Skill.id: Skill for Skill in Skills}

        payload = []
        for Creature in Creatures:
            entry = Creature.to_mongo()
            Skill = skills_by_id.get(Creature.id)
            # Creatures created before the skills collection existed have no document
            if Skill is None:
                entry['skills'] = []
                entry['loadout'] = []
            else:
                entry['skills'] = [
                    {"name": skill.name, "level": skill.level} for skill in Skill.skills
                ]
                entry['loadout'] = list(Skill.loadout)
            payload.append(entry)
    except Exception as e:
        msg = f'{g.h} Creatures/Skills query KO (username:{get_jwt_identity()}) [{e}]'
        logger.error(msg)
        return jsonify(
            {
                "success": False,
                "msg": msg,
                "payload": None,
            }
        ), 200
    else:
        msg = f'{g.h} Creatures Query OK'
        logger.debug(msg)
        return jsonify(
            {
                "success": True,
                "msg": msg,
                "payload": payload,
            }
        ), 200
