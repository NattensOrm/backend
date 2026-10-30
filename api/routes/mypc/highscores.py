# -*- coding: utf8 -*-

from flask import g, jsonify
from flask_jwt_extended import jwt_required
from loguru import logger

from mongo.models.Highscore import HighscoreDocument

from utils.decorators import (
    check_creature_exists,
    )

# Highscore.internal holds the server-side counters (Lordslair 2026-10-30,
# #engine-api msg 1565832626781290527): never sent to the player
PRIVATE_FIELDS = ['internal']


#
# Routes /mypc/<uuid:creatureuuid>/highscores
#
# API: GET /mypc/<uuid:creatureuuid>/highscores
@jwt_required()
# Custom decorators
@check_creature_exists
def highscores_get(creatureuuid):
    try:
        # The private fields are never loaded: a player read does not depend on their shape
        Highscores = HighscoreDocument.objects(_id=creatureuuid).exclude(*PRIVATE_FIELDS).first()
        if Highscores is None:
            msg = f'{g.h} HighscoreDocument Query KO - DoesNotExist'
            logger.warning(msg)
            return jsonify(
                {
                    "success": False,
                    "msg": msg,
                    "payload": None,
                }
            ), 200
    except Exception as e:
        # The exception is logged only: its text never reaches the client
        logger.error(f'{g.h} HighscoreDocument Query KO [{e}]')
        return jsonify(
            {
                "success": False,
                "msg": f'{g.h} HighscoreDocument Query KO',
                "payload": None,
            }
        ), 200
    else:
        msg = f'{g.h} HighscoreDocument Query OK'
        logger.debug(msg)
        return jsonify(
            {
                "success": True,
                "msg": msg,
                "payload": Highscores.to_mongo(),
            }
        ), 200
