# -*- coding: utf8 -*-

import uuid

from flask import g, jsonify
from flask_jwt_extended import jwt_required
from loguru import logger

from mongo.models.Highscore import HighscoreDocument
from mongo.utils import utcnow

from routes._decorators import belongs, exists
from utils.pa import instance_tick
from utils.redis import r, consume_pa, get_pa

from variables import env_vars

#
# Profession.tracking specifics
#
PA_COST_RED = 0
PA_COST_BLUE = 2
DURATION = 3600
DISTANCE = 3
PROFESSION_NAME = 'tracking'


#
# Routes /mypc/<uuid:creatureuuid>/action
#
# API: POST /mypc/<uuid:creatureuuid>/action/profession/tracking
@jwt_required()
# Custom decorators
@exists.creature
@belongs.creature_in_instance
# Only checked here: the PA are consumed once the Effect is applied (see below)
@exists.pa(red=PA_COST_RED, blue=PA_COST_BLUE, consume=False)
def tracking(creatureuuid):
    """ Applies a temporary tracking Effect to a Creature. """

    try:
        rpath = f"{env_vars['API_ENV']}:{g.Creature.instance}:effects:{g.Creature.id}"
        rkey = f'{rpath}:{PROFESSION_NAME.capitalize()}'

        r.hset(
            rkey,
            mapping={
                    "bearer": str(g.Creature.id),
                    "duration_base": DURATION,
                    "id": str(uuid.uuid4()),
                    "instance": str(g.Creature.instance),
                    "extra": 'None',
                    "name": PROFESSION_NAME.capitalize(),
                    "source": str(g.Creature.id),
                    "type": 'effect',
                },
            )
        r.expire(rkey, DURATION)
    except Exception as e:
        msg = f'{g.h} Redis Query KO [{e}]'
        logger.error(msg)
        return jsonify(
            {
                "success": False,
                "msg": msg,
                "payload": None,
            }
        ), 200

    # A refusal is free, PA are spent once the action is done (Lordslair +
    # chifret 2026-10-29): here once the Effect is set, a Redis error is free
    consume_pa(
        creatureuuid=g.Creature.id,
        redpa=PA_COST_RED,
        bluepa=PA_COST_BLUE,
        tick=instance_tick(g.Creature),
        )

    # We set the HighScores
    highscores_update_query = {
        f'inc__profession__{PROFESSION_NAME}': 1,
        "set__updated": utcnow(),
        }
    HighscoreDocument.objects(_id=g.Creature.id).update_one(**highscores_update_query)

    msg = f'{g.h} Profession ({PROFESSION_NAME}) Query OK'
    logger.debug(msg)
    return jsonify(
        {
            "success": True,
            "msg": msg,
            "payload": {
                "pa": get_pa(creatureuuid=g.Creature.id, tick=instance_tick(g.Creature)),
            }
        }
    ), 200
