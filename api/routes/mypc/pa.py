# -*- coding: utf8 -*-

from flask                      import g, jsonify
from flask_jwt_extended         import jwt_required
from loguru                     import logger

from utils.decorators import check_creature_exists
from utils.pa import instance_tick
from utils.redis import get_pa


#
# Routes /mypc/<uuid:creatureuuid>/pa/*
#
# API: GET /mypc/<uuid:creatureuuid>/pa
@jwt_required()
# Custom decorators
@check_creature_exists
def pa_get(creatureuuid):
    try:
        tick = instance_tick(g.Creature)
        if tick is None:
            # Designer ruling: outside an Instance there are no PA pools at all
            msg = f'{g.h} Creature not in an Instance: no PA'
            logger.debug(msg)
            return jsonify(
                {
                    "success": True,
                    "msg": msg,
                    "payload": None,
                }
            ), 200

        msg = f'{g.h} PA Query OK'
        logger.debug(msg)
        return jsonify(
            {
                "success": True,
                "msg": msg,
                "payload": get_pa(creatureuuid=g.Creature.id, tick=tick),
            }
        ), 200
    except Exception as e:
        msg = f'{g.h} PA Query KO [{e}]'
        logger.error(msg)
        return jsonify(
            {
                "success": False,
                "msg": msg,
                "payload": None,
            }
        ), 200
