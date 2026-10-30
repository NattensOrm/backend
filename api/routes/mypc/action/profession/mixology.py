# -*- coding: utf8 -*-


from flask import g, jsonify
from flask_jwt_extended import jwt_required
from loguru import logger
from random import randrange

from mongo.models.Highscore import HighscoreDocument
from mongo.models.Profession import ProfessionDocument
from mongo.models.Satchel import SatchelDocument
from mongo.utils import utcnow

from routes._decorators import exists
from routes.mypc.action.profession._tools import profession_gain
from utils.pa import instance_tick
from utils.redis import consume_pa, get_pa
from variables import metaIndexed, rarity_array

#
# Profession.mixology specifics
#
# Lordslair 2026-10-29: allowed in town and in an Instance. Outside an
# Instance there are no PA (exists.pa and consume_pa do nothing then)
PA_COST_RED = 0
PA_COST_BLUE = 4
PROFESSION_NAME = 'mixology'
# Satchel.consumable.health field of each crafted consumables meta. fight-resolver
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
# Yield, Lordslair 2026-10-30 (Discord #engine-ai msg 1565666550147457115).
# Computed in hundredths: an exact integer value never draws a +1
YIELD_SCORE_MAX = 100
YIELD_RANK_MAX = 5


def recipe_for(metaid):
    """Return the recipe meta producing the consumables meta, or None."""
    for recipe in metaIndexed['recipe'].values():
        if metaid in recipe.get('product', {}).get('consumable', []):
            return recipe
    return None


def mixology_trinket_rank(rarity):
    """
    Return the rank of the shard the crafter burns, or None for an unknown
    rarity: its rarity_array['item'] index (Broken 0 .. Legendary 5).
    Lordslair 2026-10-30 (msgs 1565667043003334668, 1565667218056945665): the
    trinket is the shard the recipe burns, its rarity chosen by the crafter.
    """
    rarities = [level.lower() for level in rarity_array['item']]
    return rarities.index(rarity) if rarity in rarities else None


def mixology_value(profession_score, trinket_rank):
    """Return the yield value in hundredths: 1 + 2*score/100 + 2*rank/5."""
    score = min(max(profession_score, 0), YIELD_SCORE_MAX)
    return 100 + 200 * score // YIELD_SCORE_MAX + 200 * trinket_rank // YIELD_RANK_MAX


def mixology_yield(profession_score, trinket_rank):
    """Return the consumables made by one craft (1 to 5)."""
    # Value = 1 + 2*score/100 + 2*rank/5 ; floor + chance of +1 = fraction
    # Trinket Broken (rank 0) / no trinket
    #    0  | [████................] 1.0 -> 1
    #   25  | [██████..............] 1.5 -> 1 or 2 (50% / 50%)
    #   50  | [████████............] 2.0 -> 2
    #   75  | [██████████..........] 2.5 -> 2 or 3 (50% / 50%)
    #  100  | [████████████........] 3.0 -> 3
    # Trinket Common (rank 1)
    #    0  | [██████..............] 1.4 -> 1 or 2 (60% / 40%)
    #   25  | [████████............] 1.9 -> 1 or 2 (10% / 90%)
    #   50  | [██████████..........] 2.4 -> 2 or 3 (60% / 40%)
    #   75  | [████████████........] 2.9 -> 2 or 3 (10% / 90%)
    #  100  | [██████████████......] 3.4 -> 3 or 4 (60% / 40%)
    # Trinket Uncommon (rank 2)
    #    0  | [███████.............] 1.8 -> 1 or 2 (20% / 80%)
    #   25  | [█████████...........] 2.3 -> 2 or 3 (70% / 30%)
    #   50  | [███████████.........] 2.8 -> 2 or 3 (20% / 80%)
    #   75  | [█████████████.......] 3.3 -> 3 or 4 (70% / 30%)
    #  100  | [███████████████.....] 3.8 -> 3 or 4 (20% / 80%)
    # Trinket Rare (rank 3)
    #    0  | [█████████...........] 2.2 -> 2 or 3 (80% / 20%)
    #   25  | [███████████.........] 2.7 -> 2 or 3 (30% / 70%)
    #   50  | [█████████████.......] 3.2 -> 3 or 4 (80% / 20%)
    #   75  | [███████████████.....] 3.7 -> 3 or 4 (30% / 70%)
    #  100  | [█████████████████...] 4.2 -> 4 or 5 (80% / 20%)
    # Trinket Epic (rank 4)
    #    0  | [██████████..........] 2.6 -> 2 or 3 (40% / 60%)
    #   25  | [████████████........] 3.1 -> 3 or 4 (90% / 10%)
    #   50  | [██████████████......] 3.6 -> 3 or 4 (40% / 60%)
    #   75  | [████████████████....] 4.1 -> 4 or 5 (90% / 10%)
    #  100  | [██████████████████..] 4.6 -> 4 or 5 (40% / 60%)
    # Trinket Legendary (rank 5)
    #    0  | [████████████........] 3.0 -> 3
    #   25  | [██████████████......] 3.5 -> 3 or 4 (50% / 50%)
    #   50  | [████████████████....] 4.0 -> 4
    #   75  | [██████████████████..] 4.5 -> 4 or 5 (50% / 50%)
    #  100  | [████████████████████] 5.0 -> 5
    value = mixology_value(profession_score, trinket_rank)
    count, fraction = divmod(value, 100)
    # randrange(100) is 0..99: a fraction of 0 never adds 1, 40 adds it 40% of the time
    return count + (1 if randrange(100) < fraction else 0)


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
# API: POST /mypc/<uuid:creatureuuid>/action/profession/mixology/<int:metaid>/<string:rarity>
@jwt_required()
# Custom decorators
@exists.creature
# Only checked here: the PA are consumed once the resources are spent (see below)
@exists.pa(red=PA_COST_RED, blue=PA_COST_BLUE, consume=False)
def mixology(creatureuuid, metaid, rarity):
    # Path parameter checks: before any write
    kind = CONSUMABLE_FIELDS.get(metaid)
    if kind is None:
        return refused(f'{g.h} Mixology KO (consumable:{metaid} is never crafted)', 400)

    # The shard burned, Satchel.shard.<rarity>: no default rarity
    trinket_rank = mixology_trinket_rank(rarity)
    if trinket_rank is None:
        return refused(f'{g.h} Mixology KO (shard rarity:{rarity} unknown)', 400)

    recipe = recipe_for(metaid)
    if recipe is None:
        return refused(f'{g.h} Mixology KO (consumable:{metaid} has no recipe)', 400)

    currency = RACE_CURRENCY.get(g.Creature.race)
    if currency is None:
        return refused(f'{g.h} Mixology KO (race:{g.Creature.race} has no currency)', 200)

    wallet = recipe['component']['wallet']
    cost_currency = wallet['currency']
    # 'shard': that many shards of the rarity the crafter chose
    cost_shard = wallet['shard']

    Profession = ProfessionDocument.objects(_id=g.Creature.id).get()
    profession_score = Profession.mixology
    count = mixology_yield(profession_score, trinket_rank)

    # One conditional update: the cost is checked and paid atomically, so two
    # concurrent crafts cannot both spend the same resources. A refusal writes
    # nothing. $inc creates consumable.health.<kind> on satchels that predate it.
    updated = SatchelDocument.objects(
        _id=g.Creature.id,
        **{
            f'currency__{currency}__gte': cost_currency,
            f'shard__{rarity}__gte': cost_shard,
        },
    ).update_one(
        **{
            f'inc__currency__{currency}': -cost_currency,
            f'inc__shard__{rarity}': -cost_shard,
            f'inc__consumable__health__{kind}': count,
            'set__updated': utcnow(),
        }
    )
    Satchel = SatchelDocument.objects(_id=g.Creature.id).first()

    if Satchel is None:
        return refused(f'{g.h} Mixology KO (Satchel NOTFOUND)', 404)

    if updated == 0:
        return refused(
            f'{g.h} Not enough currency.{currency} ({cost_currency})'
            f' or shard.{rarity} ({cost_shard}) for {recipe["hs"]}.',
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
