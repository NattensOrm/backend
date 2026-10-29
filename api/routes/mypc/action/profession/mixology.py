# -*- coding: utf8 -*-


from flask import g, jsonify
from flask_jwt_extended import jwt_required
from loguru import logger

from mongo.models.Highscore import HighscoreDocument
from mongo.models.Profession import ProfessionDocument
from mongo.models.Satchel import SatchelDocument
from mongo.utils import utcnow

from routes._decorators import exists
from routes.mypc.action.profession._tools import profession_gain
from utils.pa import instance_tick
from utils.redis import consume_pa, get_pa
from variables import metaIndexed

#
# Profession.mixology specifics
#
# Lordslair 2026-10-29: allowed in town and in an Instance. Outside an
# Instance there are no PA (exists.pa and consume_pa do nothing then)
PA_COST_RED = 0
PA_COST_BLUE = 4
PROFESSION_NAME = 'mixology'
# Satchel.consumable field of each crafted consumables meta. fight-resolver
# reads and spends these paths: do not rename them. Meta 1 (standard heal)
# is plain currency, never crafted (design ruling Q78).
CONSUMABLE_FIELDS = {
    2: 'fast',
    3: 'long',
    }
# The recipe 'currency' is the crafter's faction currency, by race. Banana
# for the singouins; no pourchon (sausage) race exists in the backend yet.
RACE_CURRENCY = {
    1: 'banana',
    2: 'banana',
    3: 'banana',
    4: 'banana',
    }
# One consumable per craft, two at mastery (the top profession_scaled step)
PROFESSION_MASTERY = 100


def recipe_for(metaid):
    """Return the recipe meta producing the consumables meta, or None."""
    for recipe in metaIndexed['recipe'].values():
        if metaid in recipe.get('product', {}).get('consumable', []):
            return recipe
    return None


def mixology_yield(profession_score):
    """Return the consumables made by one craft (1, 2 at mastery)."""
    return 2 if profession_score >= PROFESSION_MASTERY else 1


def refused(msg, code, payload=None):
    logger.warning(msg)
    return jsonify(
        {
            "success": False,
            "msg": msg,
            "payload": payload,
        }
    ), code


#
# Routes /mypc/<uuid:creatureuuid>/action
#
# API: POST /mypc/<uuid:creatureuuid>/action/profession/mixology/<int:metaid>
@jwt_required()
# Custom decorators
@exists.creature
# Only checked here: the PA are consumed once the resources are spent (see below)
@exists.pa(red=PA_COST_RED, blue=PA_COST_BLUE, consume=False)
def mixology(creatureuuid, metaid):
    # Path parameter checks: before any write
    kind = CONSUMABLE_FIELDS.get(metaid)
    if kind is None:
        return refused(f'{g.h} Mixology KO (consumable:{metaid} is never crafted)', 400)

    recipe = recipe_for(metaid)
    if recipe is None:
        return refused(f'{g.h} Mixology KO (consumable:{metaid} has no recipe)', 400)

    currency = RACE_CURRENCY.get(g.Creature.race)
    if currency is None:
        return refused(f'{g.h} Mixology KO (race:{g.Creature.race} has no currency)', 200)

    wallet = recipe['component']['wallet']
    cost_currency = wallet['currency']
    cost_broken = wallet['broken']

    Profession = ProfessionDocument.objects(_id=g.Creature.id).get()
    profession_score = Profession.mixology
    count = mixology_yield(profession_score)

    # One conditional update: the cost is checked and paid atomically, so two
    # concurrent crafts cannot both spend the same resources. A refusal writes
    # nothing. $inc creates consumable.<kind> on satchels that predate it.
    updated = SatchelDocument.objects(
        _id=g.Creature.id,
        **{
            f'currency__{currency}__gte': cost_currency,
            'shard__broken__gte': cost_broken,
        },
    ).update_one(
        **{
            f'inc__currency__{currency}': -cost_currency,
            'inc__shard__broken': -cost_broken,
            f'inc__consumable__{kind}': count,
            'set__updated': utcnow(),
        }
    )
    Satchel = SatchelDocument.objects(_id=g.Creature.id).first()

    if Satchel is None:
        return refused(f'{g.h} Mixology KO (Satchel NOTFOUND)', 404)

    if updated == 0:
        return refused(
            f'{g.h} Not enough currency.{currency} ({cost_currency})'
            f' or shard.broken ({cost_broken}) for {recipe["hs"]}.',
            200,
            {"satchel": Satchel.to_mongo()},
            )

    # A refusal is free, PA are spent once the action is validated
    consume_pa(
        creatureuuid=g.Creature.id,
        redpa=PA_COST_RED,
        bluepa=PA_COST_BLUE,
        tick=instance_tick(g.Creature),
        )

    # We set the HighScores
    HighscoreDocument.objects(_id=g.Creature.id).update(
        **{
            f'inc__profession__{PROFESSION_NAME}': 1,
            'set__updated': utcnow(),
        }
    )

    # We update the Profession score
    profession_gain(g.Creature.id, PROFESSION_NAME, profession_score)

    # We're done
    msg = f'{g.h} Profession ({PROFESSION_NAME}) Query OK'
    logger.debug(msg)
    return jsonify(
        {
            "success": True,
            "msg": msg,
            "payload": {
                "pa": get_pa(creatureuuid=g.Creature.id, tick=instance_tick(g.Creature)),
                "consumable": {
                    "count": count,
                    "metaid": metaid,
                    },
                "satchel": Satchel.to_mongo(),
            }
        }
    ), 200
