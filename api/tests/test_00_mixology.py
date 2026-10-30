# -*- coding: utf8 -*-

import copy
import functools
import importlib.util
import json
import os
import re
import sys
import types
import uuid

import flask_jwt_extended
import mongoengine
import mongomock
import pytest
from flask import Flask, g, jsonify

# Needed for local imports and simulate production paths (api/ on sys.path,
# resolved from this file so it works whatever the cwd pytest runs from)
LOCAL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)
sys.path.append(LOCAL_PATH)

# Lordslair 2026-10-29 (Discord #engine-ai): crafting the heals is the
# mixology profession. In town without PA, in an Instance for 0 red / 4 blue
# PA spent once the resources are. The recipe is read from the metas, one
# yield of 1 to 5 by score and shard (formula B), profession points and
# highscore like the other professions. Meta 2 goes to
# Satchel.consumable.health.fast, meta 3 to .long; meta 1 (standard heal) is
# never crafted (design ruling Q78).
# Lordslair 2026-10-30 (Discord #engine-api msgs 1565771540983718041,
# 1565773539817295984): the client posts its choices as a JSON body
# {recipe, product, shard}, never a quantity; anything else is a 400.
# Unit test: Satchel/Profession/Highscore are real documents on an in-memory
# mongomock, so the conditional update and the $inc run for real. The PA are
# a dict standing for the Redis pools, with the exists.pa / consume_pa rules.
REPO_PATH = os.path.join(LOCAL_PATH, os.pardir)
MONGO_UTILS = os.path.join(REPO_PATH, 'mongo', 'utils.py')
MONGO_CONSTANTS = os.path.join(REPO_PATH, 'mongo', 'constants.py')
MODELS = os.path.join(REPO_PATH, 'mongo', 'models')
RECIPES = os.path.join(REPO_PATH, 'mongo', 'data', 'metas', 'recipes.json')
TOOLS = os.path.join(LOCAL_PATH, 'routes', 'mypc', 'action', 'profession', '_tools.py')
ROUTE = os.path.join(LOCAL_PATH, 'routes', 'mypc', 'action', 'profession', 'mixology.py')
MOCK_ALIAS = 'test-mixology'

CREATURE_ID = uuid.uuid4()
SINGOUIN_RACE = 2
TICK = 3600
# mongo.constants.RARITY: the shard rarities, rank = index
RARITIES = ['Broken', 'Common', 'Uncommon', 'Rare', 'Epic', 'Legendary']
SHARDS = [rarity.lower() for rarity in RARITIES]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _recipes():
    """ The recipe metas as the api holds them (variables.metaIndexed['recipe']). """
    with open(RECIPES) as file:
        recipes = json.load(file)
    for recipe in recipes:
        recipe['_id'] = recipe.pop('id')
    return {recipe['_id']: recipe for recipe in recipes}


def _instance_tick(creature):
    """ utils.pa.instance_tick: no tick, so no PA, outside an Instance. """
    return None if creature.instance is None else TICK


def _pa_check(pools):
    """
    Stands for exists.pa(consume=False): nothing checked outside an Instance;
    inside, red PA cover a blue shortfall (Q104) or the action is refused.
    """
    def pa(red=0, blue=0, consume=False):
        assert consume is False

        def decorator(view):
            @functools.wraps(view)
            def wrapper(*args, **kwargs):
                if _instance_tick(g.Creature) is not None:
                    shortfall = max(blue - pools['blue'], 0)
                    if pools['red'] < red + shortfall:
                        refusal = {"success": False, "msg": "No PA", "payload": dict(pools)}
                        return jsonify(refusal), 200
                return view(*args, **kwargs)
            return wrapper
        return decorator
    return pa


@pytest.fixture
def mongo():
    """
    In-memory Mongo on its own alias, dropped after the test: in CI the
    default alias may already point at the real Mongo, registered by another
    test importing the mongo package.
    """
    mongoengine.connect(
        'pytest', alias=MOCK_ALIAS, mongo_client_class=mongomock.MongoClient,
        uuidRepresentation='standard',
        )
    yield
    # mongomock keeps its data while any client lives: drop it explicitly
    mongoengine.connection.get_connection(MOCK_ALIAS).drop_database('pytest')
    mongoengine.disconnect(alias=MOCK_ALIAS)


@pytest.fixture
def modules(mongo, monkeypatch):
    """
    Loads the real models, profession tools and route from their files under a
    stub mongo package (mongo/__init__.py and its connect() never run). The
    decorators are stubbed: there is no exists.pa, the route spends no PA.
    """
    package = types.ModuleType('mongo')
    package.__path__ = []
    monkeypatch.setitem(sys.modules, 'mongo', package)
    monkeypatch.setitem(sys.modules, 'mongo.utils', _load('mongo.utils', MONGO_UTILS))
    monkeypatch.setitem(sys.modules, 'mongo.constants', _load('mongo.constants', MONGO_CONSTANTS))

    models = {}
    for name, document in [
        ('Satchel', 'SatchelDocument'),
        ('Profession', 'ProfessionDocument'),
        ('Highscore', 'HighscoreDocument'),
    ]:
        model = _load(f'test_mixology_{name}', os.path.join(MODELS, f'{name}.py'))
        getattr(model, document)._meta['db_alias'] = MOCK_ALIAS
        monkeypatch.setitem(sys.modules, f'mongo.models.{name}', model)
        models[name] = model

    tools = _load('test_mixology_tools', TOOLS)
    monkeypatch.setitem(sys.modules, 'routes.mypc.action.profession._tools', tools)

    decorators = types.ModuleType('routes._decorators')
    pools = {'red': 0, 'blue': 0}
    decorators.exists = types.SimpleNamespace(creature=lambda view: view, pa=_pa_check(pools))
    monkeypatch.setitem(sys.modules, 'routes._decorators', decorators)

    def consume_pa(creatureuuid, redpa=0, bluepa=0, *, tick):
        """ Does nothing without a tick; red pays the blue shortfall (Q104). """
        if tick is None:
            return
        shortfall = max(bluepa - pools['blue'], 0)
        pools['blue'] -= bluepa - shortfall
        pools['red'] -= redpa + shortfall
        pools['spent'] = pools.get('spent', 0) + 1

    redis = types.ModuleType('utils.redis')
    redis.consume_pa = consume_pa
    redis.get_pa = lambda creatureuuid, *, tick: None if tick is None else dict(pools)
    monkeypatch.setitem(sys.modules, 'utils.redis', redis)
    pa = types.ModuleType('utils.pa')
    pa.instance_tick = _instance_tick
    monkeypatch.setitem(sys.modules, 'utils.pa', pa)

    variables = types.ModuleType('variables')
    variables.metaIndexed = {'recipe': _recipes()}
    monkeypatch.setitem(sys.modules, 'variables', variables)

    monkeypatch.setattr(flask_jwt_extended, 'jwt_required', lambda: lambda view: view)

    route = _load('test_mixology_route', ROUTE)
    return types.SimpleNamespace(route=route, models=models, variables=variables, pools=pools)


@pytest.fixture
def world(modules):
    app = Flask(__name__)
    satchel_model = modules.models['Satchel']
    creature = types.SimpleNamespace(id=CREATURE_ID, instance=None, race=SINGOUIN_RACE)

    def collection(name, document):
        return getattr(modules.models[name], document)._get_collection()

    satchels = collection('Satchel', 'SatchelDocument')
    professions = collection('Profession', 'ProfessionDocument')
    highscores = collection('Highscore', 'HighscoreDocument')

    def setup(banana=0, broken=0, mixology=0, consumable=True, **shards):
        """
        The Creature documents; consumable=False stands for a pre-Q78 Satchel.
        The shards of the other rarities are given by name (rare=3).
        """
        document = satchel_model.SatchelDocument(
            _id=CREATURE_ID,
            ammo=satchel_model.SatchelAmmo(),
            currency=satchel_model.SatchelCurrency(banana=banana, sausage=500),
            resource=satchel_model.SatchelResource(),
            shard=satchel_model.SatchelShard(broken=broken, **shards),
            )
        if consumable:
            document.consumable = satchel_model.SatchelConsumable(
                health=satchel_model.SatchelConsumableHealth(),
                )
        document.save()
        modules.models['Profession'].ProfessionDocument(_id=CREATURE_ID, mixology=mixology).save()
        # Only the part the route touches: Highscore embeds are all required
        highscores.insert_one({'_id': str(CREATURE_ID), 'profession': {'tanning': 3}})

    def stored():
        """ The three documents as Mongo holds them (string _id, binary=False). """
        return {
            'satchel': satchels.find_one({'_id': str(CREATURE_ID)}),
            'profession': professions.find_one({'_id': str(CREATURE_ID)}),
            'highscore': highscores.find_one({'_id': str(CREATURE_ID)}),
            }

    def post(**request):
        """ Calls the route with that request (json=..., or data=... and content_type=...). """
        with app.test_request_context(method='POST', **request):
            g.h = f'[Creature.id:{CREATURE_ID}]'
            g.Creature = creature
            response, code = modules.route.mixology(creatureuuid=CREATURE_ID)
            return code, response.get_json()

    def craft(metaid, rarity='broken', recipe=1):
        return post(json={'recipe': recipe, 'product': metaid, 'shard': rarity})

    return types.SimpleNamespace(
        post=post, craft=craft, setup=setup, stored=stored, creature=creature,
        professions=professions, modules=modules, pools=modules.pools,
        )


@pytest.fixture
def no_gain(world, monkeypatch):
    """ profession_gain rolls above 25 points: neutral when the test is about the yield. """
    monkeypatch.setattr(world.modules.route, 'profession_gain', lambda *args: None)
    return world


#
# PA: none in town, 0 red / 4 blue in an Instance
#
def test_mixology_in_town_touches_no_pa(no_gain):
    no_gain.setup(banana=25, broken=1)
    no_gain.pools.update(red=0, blue=0)

    code, body = no_gain.craft(2)

    assert code == 200
    assert body['success'] is True
    assert body['payload']['pa'] is None
    assert no_gain.pools == {'red': 0, 'blue': 0}


@pytest.mark.parametrize('red, blue, after', [
    (10, 4, {'red': 10, 'blue': 0}),
    (10, 10, {'red': 10, 'blue': 6}),
    # Red covers the blue shortfall (Q104)
    (10, 1, {'red': 7, 'blue': 0}),
])
def test_mixology_in_an_instance_spends_4_blue_once(no_gain, red, blue, after):
    no_gain.setup(banana=25, broken=1)
    no_gain.creature.instance = uuid.uuid4()
    no_gain.pools.update(red=red, blue=blue)

    code, body = no_gain.craft(2)

    assert code == 200
    assert body['success'] is True
    assert no_gain.stored()['satchel']['consumable']['health']['fast'] == 1
    assert no_gain.pools == dict(after, spent=1)
    assert body['payload']['pa'] == dict(after, spent=1)


@pytest.mark.parametrize('red, blue', [(0, 3), (2, 1), (0, 0)])
def test_mixology_in_an_instance_short_of_pa_is_a_free_refusal(world, red, blue):
    world.setup(banana=100, broken=5)
    world.creature.instance = uuid.uuid4()
    world.pools.update(red=red, blue=blue)
    before = world.stored()

    code, body = world.craft(2)

    assert code == 200
    assert body['success'] is False
    assert world.stored() == before
    assert world.pools == {'red': red, 'blue': blue}


def test_mixology_in_an_instance_without_the_resources_spends_no_pa(world):
    world.setup(banana=24, broken=1)
    world.creature.instance = uuid.uuid4()
    world.pools.update(red=10, blue=10)
    before = world.stored()

    code, body = world.craft(2)

    assert code == 200
    assert body['success'] is False
    assert world.stored() == before
    assert world.pools == {'red': 10, 'blue': 10}


#
# Body: {"recipe", "product", "shard"}, strictly validated before any write
#
VALID_BODY = {'recipe': 1, 'product': 2, 'shard': 'broken'}


@pytest.mark.parametrize('body', [
    # A missing field
    {'product': 2, 'shard': 'broken'},
    {'recipe': 1, 'shard': 'broken'},
    {'recipe': 1, 'product': 2},
    {},
    # Another field: the client never sends a quantity
    {**VALID_BODY, 'count': 5},
    {**VALID_BODY, 'currency': 0},
    # A wrong type: no coercion
    {**VALID_BODY, 'recipe': '1'},
    {**VALID_BODY, 'recipe': True},
    {**VALID_BODY, 'recipe': 1.0},
    {**VALID_BODY, 'recipe': None},
    {**VALID_BODY, 'recipe': float('nan')},
    {**VALID_BODY, 'product': float('inf')},
    {**VALID_BODY, 'product': '2'},
    {**VALID_BODY, 'product': [2]},
    {**VALID_BODY, 'shard': 0},
    {**VALID_BODY, 'shard': None},
    {**VALID_BODY, 'shard': ['broken']},
    # Not an object
    [VALID_BODY],
    'broken',
    None,
    ])
def test_mixology_of_an_invalid_body_is_400_and_writes_nothing(world, body):
    world.setup(banana=100, broken=5)
    world.creature.instance = uuid.uuid4()
    world.pools.update(red=10, blue=10)
    before = world.stored()

    code, response = world.post(json=body)

    assert code == 400
    assert response['success'] is False
    assert isinstance(response['payload'], list)
    # The errors never echo the client's input
    assert all('input' not in error for error in response['payload'])
    assert world.stored() == before
    assert world.pools == {'red': 10, 'blue': 10}


@pytest.mark.parametrize('request_args', [
    {},
    {
        'data': 'recipe=1&product=2&shard=broken',
        'content_type': 'application/x-www-form-urlencoded',
        },
    {'data': '{"recipe": 1,', 'content_type': 'application/json'},
    ])
def test_mixology_without_a_json_body_is_400_and_writes_nothing(world, request_args):
    world.setup(banana=100, broken=5)
    before = world.stored()

    code, response = world.post(**request_args)

    assert code == 400
    assert response['success'] is False
    assert world.stored() == before


def test_mixology_of_a_valid_body_succeeds(no_gain):
    no_gain.setup(banana=25, broken=1)

    code, response = no_gain.post(json=VALID_BODY)

    assert code == 200
    assert response['success'] is True


@pytest.mark.parametrize('recipe', [0, 2, 999, -1])
def test_mixology_of_an_unknown_recipe_is_400_and_writes_nothing(world, recipe):
    world.setup(banana=100, broken=5)
    before = world.stored()

    code, body = world.craft(2, recipe=recipe)

    assert code == 400
    assert body['success'] is False
    assert body['payload'] is None
    assert f'recipe:{recipe} unknown' in body['msg']
    assert world.stored() == before


@pytest.mark.parametrize('metaid', [1, 0, 4, 999])
def test_mixology_of_a_product_not_in_the_recipe_is_400_and_writes_nothing(world, metaid):
    # Meta 1 is plain currency, never crafted; the others do not exist
    world.setup(banana=100, broken=5)
    before = world.stored()

    code, body = world.craft(metaid)

    assert code == 400
    assert body['success'] is False
    assert body['payload'] is None
    assert 'not a product of recipe:1' in body['msg']
    assert world.stored() == before


def test_mixology_of_a_recipe_listing_a_product_without_satchel_field_is_400(world):
    # A recipe meta listing meta 1 still never crafts it: no Satchel field
    recipes = world.modules.variables.metaIndexed['recipe']
    recipes[1] = copy.deepcopy(recipes[1])
    recipes[1]['product'] = {'consumable': [1, 2, 3]}
    world.setup(banana=100, broken=5)
    before = world.stored()

    code, body = world.craft(1)

    assert code == 400
    assert body['success'] is False
    assert 'never crafted' in body['msg']
    assert world.stored() == before


def test_mixology_of_a_recipe_without_product_is_400(world):
    recipes = world.modules.variables.metaIndexed['recipe']
    recipes[1] = copy.deepcopy(recipes[1])
    del recipes[1]['product']
    world.setup(banana=100, broken=5)
    before = world.stored()

    code, body = world.craft(2)

    assert code == 400
    assert body['success'] is False
    assert world.stored() == before


#
# Recipe
#
@pytest.mark.parametrize('metaid, kind, other', [(2, 'fast', 'long'), (3, 'long', 'fast')])
def test_mixology_pays_the_recipe_and_fills_its_satchel_entry(no_gain, metaid, kind, other):
    no_gain.setup(banana=30, broken=2)

    code, body = no_gain.craft(metaid)

    assert code == 200
    assert body['success'] is True
    satchel = no_gain.stored()['satchel']
    assert satchel['consumable']['health'][kind] == 1
    assert satchel['consumable']['health'][other] == 0
    # Nothing produces the base heal yet
    assert satchel['consumable']['health']['base'] == 0
    # Recipe 1 craft_potion: 25 banana (a singouin) + 1 shard of the chosen rarity (broken)
    assert satchel['currency']['banana'] == 5
    assert satchel['currency']['sausage'] == 500
    assert satchel['shard']['broken'] == 1
    assert body['payload']['consumable'] == {'count': 1, 'metaid': metaid}
    assert body['payload']['satchel']['consumable']['health'][kind] == 1


def test_mixology_reads_the_recipe_cost_from_the_metas(no_gain):
    recipe = no_gain.modules.variables.metaIndexed['recipe'][1]
    recipe['component']['wallet'] = {'currency': 7, 'shard': 3}
    no_gain.setup(banana=10, broken=5)

    code, body = no_gain.craft(2)

    assert code == 200
    assert body['success'] is True
    satchel = no_gain.stored()['satchel']
    assert satchel['currency']['banana'] == 3
    assert satchel['shard']['broken'] == 2


def test_mixology_reads_the_recipe_products_from_the_metas(world):
    # The recipe -> consumables link is in the metas too
    recipes = world.modules.variables.metaIndexed['recipe']
    recipes[1] = copy.deepcopy(recipes[1])
    recipes[1]['product'] = {'consumable': [3]}
    world.setup(banana=100, broken=5)
    before = world.stored()

    code, body = world.craft(2)

    assert code == 400
    assert body['success'] is False
    assert world.stored() == before


@pytest.mark.parametrize('banana, broken', [(24, 1), (25, 0), (0, 0)])
def test_mixology_without_the_resources_is_a_free_refusal(world, banana, broken):
    # Nothing written: no currency or shard spent, no consumable, no profession
    # point, no highscore
    world.setup(banana=banana, broken=broken)
    before = world.stored()

    code, body = world.craft(2)

    assert code == 200
    assert body['success'] is False
    assert 'Not enough' in body['msg']
    assert body['payload']['satchel']['currency']['banana'] == banana
    assert world.stored() == before


def test_mixology_by_a_race_without_currency_is_a_free_refusal(world):
    # No faction currency known for the race: nothing guessed, nothing written
    world.setup(banana=100, broken=5)
    world.creature.race = 11
    before = world.stored()

    code, body = world.craft(2)

    assert code == 200
    assert body['success'] is False
    assert world.stored() == before


#
# Yield
#
# Lordslair 2026-10-30 (msg 1565666550147457115): value = 1 + 2*score/100 +
# 2*rank/5, the yield is floor(value) plus 1 with the fraction as chance.
HISTOGRAM_ROW = re.compile(
    r'#\s+(\d+)\s+\| \[[█.]{20}\] (\d)\.(\d) -> (\d)(?: or (\d) \((\d+)% / (\d+)%\))?$'
    )
HISTOGRAM_RANK = re.compile(r'# Shard \w+ \(rank (\d)\)')


def _histogram():
    """ The route comment rows: (rank, score, value in hundredths, low, high, % low, % high). """
    rows, rank = [], None
    with open(ROUTE, encoding='utf8') as file:
        for line in file:
            line = line.strip()
            if HISTOGRAM_RANK.match(line):
                rank = int(HISTOGRAM_RANK.match(line).group(1))
            elif HISTOGRAM_ROW.match(line):
                score, units, tenths, low, high, p_low, p_high = HISTOGRAM_ROW.match(line).groups()
                rows.append((
                    rank, int(score), int(units) * 100 + int(tenths) * 10, int(low),
                    None if high is None else int(high),
                    None if p_low is None else int(p_low),
                    None if p_high is None else int(p_high),
                    ))
    return rows


def test_mixology_histogram_matches_the_formula(modules):
    rows = _histogram()
    assert len(rows) == 30
    # Each rank and score once
    assert {(rank, score) for rank, score, *_ in rows} == {
        (rank, score) for rank in range(6) for score in (0, 25, 50, 75, 100)
        }
    for rank, score, value, low, high, p_low, p_high in rows:
        assert modules.route.mixology_value(score, rank) == value
        assert low == value // 100
        if high is None:
            assert value % 100 == 0
        else:
            assert high == low + 1
            assert (p_low, p_high) == (100 - value % 100, value % 100)


@pytest.mark.parametrize('draw', [0, 99])
def test_mixology_yield_stays_between_1_and_5(modules, monkeypatch, draw):
    monkeypatch.setattr(modules.route, 'randrange', lambda stop: draw)
    for rank in range(6):
        for score in range(-10, 151):
            assert 1 <= modules.route.mixology_yield(score, rank) <= 5
    assert modules.route.mixology_yield(0, 0) == 1
    assert modules.route.mixology_yield(100, 5) == 5


@pytest.mark.parametrize('score, rank, count', [
    (0, 0, 1), (50, 0, 2), (100, 0, 3), (50, 5, 4), (100, 5, 5),
])
def test_mixology_exact_values_never_draw_a_plus_one(modules, monkeypatch, score, rank, count):
    # The lowest draw (0) would add 1 to any fraction: none here
    monkeypatch.setattr(modules.route, 'randrange', lambda stop: 0)
    assert modules.route.mixology_yield(score, rank) == count


@pytest.mark.parametrize('score, rank, draw, count', [
    # 1.5: +1 for draws 0..49
    (25, 0, 49, 2), (25, 0, 50, 1),
    # 1.4: +1 for draws 0..39
    (0, 1, 39, 2), (0, 1, 40, 1),
    # 4.6: +1 for draws 0..59
    (100, 4, 59, 5), (100, 4, 60, 4),
])
def test_mixology_draws_the_fraction(modules, monkeypatch, score, rank, draw, count):
    monkeypatch.setattr(modules.route, 'randrange', lambda stop: draw)
    assert modules.route.mixology_yield(score, rank) == count


@pytest.mark.parametrize('score, value', [(100, 300), (101, 300), (250, 300), (-5, 100)])
def test_mixology_score_counts_between_0_and_100(modules, score, value):
    assert modules.route.mixology_value(score, 0) == value


#
# Shard rank: the shard burned, its rarity chosen by the crafter
#
@pytest.mark.parametrize('rank, rarity', list(enumerate(SHARDS)))
def test_mixology_shard_rank_is_the_shard_rarity_index(modules, rank, rarity):
    assert modules.route.mixology_shard_rank(rarity) == rank


@pytest.mark.parametrize('rank, rarity', list(enumerate(SHARDS)))
def test_mixology_burns_the_chosen_shard_and_yields_by_its_rank(
        no_gain, monkeypatch, rank, rarity,
        ):
    yields = []
    route = no_gain.modules.route
    monkeypatch.setattr(route, 'mixology_yield', lambda *args: yields.append(args) or 1)
    no_gain.setup(banana=25, mixology=40, **{shard: 2 for shard in SHARDS})

    code, body = no_gain.craft(2, rarity)

    assert code == 200
    assert body['success'] is True
    assert yields == [(40, rank)]
    shards = no_gain.stored()['satchel']['shard']
    assert shards == {shard: 1 if shard == rarity else 2 for shard in SHARDS}


@pytest.mark.parametrize('rarity', ['rare', 'legendary'])
def test_mixology_without_a_shard_of_that_rarity_is_a_free_refusal(world, rarity):
    # Plenty of the other rarities: the chosen one is what is checked
    world.setup(banana=100, broken=5, common=5, uncommon=5, epic=5)
    world.creature.instance = uuid.uuid4()
    world.pools.update(red=10, blue=10)
    before = world.stored()

    code, body = world.craft(2, rarity)

    assert code == 200
    assert body['success'] is False
    assert f'shard.{rarity}' in body['msg']
    assert world.stored() == before
    assert world.pools == {'red': 10, 'blue': 10}


@pytest.mark.parametrize('rarity', ['Rare', 'mythic', 'shard', 'currency'])
def test_mixology_of_an_unknown_rarity_is_400_and_writes_nothing(world, rarity):
    world.setup(banana=100, broken=5, rare=5)
    before = world.stored()

    code, body = world.craft(2, rarity)

    assert code == 400
    assert body['success'] is False
    assert body['payload'] is None
    assert world.stored() == before


@pytest.mark.parametrize('score, draw, count', [(0, 0, 1), (25, 49, 2), (25, 50, 1), (100, 0, 3)])
def test_mixology_craft_yields_by_profession_score(no_gain, monkeypatch, score, draw, count):
    monkeypatch.setattr(no_gain.modules.route, 'randrange', lambda stop: draw)
    no_gain.setup(banana=25, broken=1, mixology=score)

    code, body = no_gain.craft(3)

    assert code == 200
    assert body['payload']['consumable']['count'] == count
    stored = no_gain.stored()['satchel']
    assert stored['consumable']['health']['long'] == count
    # One craft pays one recipe, whatever it yields
    assert stored['currency']['banana'] == 0
    assert stored['shard']['broken'] == 0


#
# Profession and highscore
#
def test_mixology_gains_profession_and_highscore(world):
    # Below 25 points, profession_gain always gives 1
    world.setup(banana=25, broken=1, mixology=0)

    code, body = world.craft(2)

    assert code == 200
    stored = world.stored()
    assert stored['profession']['mixology'] == 1
    assert stored['highscore']['profession']['mixology'] == 1
    assert stored['highscore']['profession']['tanning'] == 3


#
# Internal highscores (not shown to players), Lordslair 2026-10-30
# (#engine-api msgs 1565777282864259093, 1565778121179791363)
#
@pytest.mark.parametrize('metaid, kind', [(2, 'fast'), (3, 'long')])
@pytest.mark.parametrize('rarity', SHARDS)
def test_mixology_counts_shard_used_consumable_created_and_currency_spent(
        no_gain, monkeypatch, metaid, kind, rarity):
    no_gain.setup(banana=30, **{'broken': 0, rarity: 2})
    monkeypatch.setattr(no_gain.modules.route, 'mixology_yield', lambda score, rank: 4)

    code, body = no_gain.craft(metaid, rarity)

    assert code == 200
    assert body['success'] is True
    internal = no_gain.stored()['highscore']['internal']
    # Only the burned rarity, by the recipe's shard amount
    assert internal['shard'] == {rarity: {'used': 1}}
    # The yield, not 1: one craft made 4 consumables
    assert internal['consumable'] == {'health': {kind: {'created': 4}}}
    # The recipe's currency amount, not 1
    assert internal['currency'] == {'spent': 25}


def test_mixology_internal_counters_follow_the_recipe_meta(no_gain, monkeypatch):
    recipe = no_gain.modules.variables.metaIndexed['recipe'][1]
    recipe['component']['wallet'] = {'currency': 7, 'shard': 3}
    no_gain.setup(banana=20, broken=0, rare=6)
    monkeypatch.setattr(no_gain.modules.route, 'mixology_yield', lambda score, rank: 2)

    no_gain.craft(2, 'rare')
    no_gain.craft(3, 'rare')

    internal = no_gain.stored()['highscore']['internal']
    assert internal['shard'] == {'rare': {'used': 6}}
    assert internal['consumable'] == {'health': {'fast': {'created': 2}, 'long': {'created': 2}}}
    assert internal['currency'] == {'spent': 14}


@pytest.mark.parametrize('banana, broken', [(24, 1), (25, 0)])
def test_mixology_refusal_counts_nothing(world, banana, broken):
    world.setup(banana=banana, broken=broken)

    code, body = world.craft(2)

    assert body['success'] is False
    assert 'internal' not in world.stored()['highscore']


def test_highscore_internal_reads_missing_counters_as_zeros(world):
    # Highscore documents created before these counters (or after the flat
    # internal.shard is unset by the migration) read them as zeros
    world.setup(banana=25, broken=1)
    highscores = world.modules.models['Highscore'].HighscoreDocument
    highscores._get_collection().update_one(
        {'_id': str(CREATURE_ID)}, {'$set': {'internal': {}}},
        )

    internal = highscores.objects(_id=CREATURE_ID).get().internal

    for rarity in SHARDS:
        shard = getattr(internal.shard, rarity)
        assert (shard.bought, shard.obtained, shard.recycled, shard.sold, shard.used) == (0,) * 5
    health = internal.consumable.health
    assert (health.base.created, health.fast.created, health.long.created) == (0, 0, 0)
    assert internal.currency.spent == 0


# The deploy migration: drops the legacy flat keys only, so the per-rarity
# counters written between the deploy and the migration are kept
LEGACY_SHARD_KEYS = ['bought', 'obtained', 'recycled', 'sold']
MIGRATION_FILTER = {'internal.shard.bought': {'$exists': True}}
MIGRATION_UPDATE = {'$unset': {f'internal.shard.{key}': '' for key in LEGACY_SHARD_KEYS}}


def test_highscore_flat_internal_shard_needs_the_migration(world):
    # The old flat internal.shard {bought, obtained, recycled, sold} does not
    # load any more. Recycling may already have added a per-rarity counter
    # next to it before the migration runs
    world.setup(banana=25, broken=1)
    highscores = world.modules.models['Highscore'].HighscoreDocument
    collection = highscores._get_collection()
    mixed = {'bought': 0, 'obtained': 3, 'recycled': 0, 'sold': 0, 'rare': {'obtained': 2}}
    collection.update_one({'_id': str(CREATURE_ID)}, {'$set': {'internal': {'shard': mixed}}})

    with pytest.raises(mongoengine.errors.FieldDoesNotExist):
        highscores.objects(_id=CREATURE_ID).get()

    collection.update_many(MIGRATION_FILTER, MIGRATION_UPDATE)

    assert collection.find_one({'_id': str(CREATURE_ID)})['internal']['shard'] == {
        'rare': {'obtained': 2},
        }
    shard = highscores.objects(_id=CREATURE_ID).get().internal.shard
    assert shard.rare.obtained == 2
    assert shard.broken.obtained == 0
    # Run again: nothing left to match, nothing changed
    assert collection.update_many(MIGRATION_FILTER, MIGRATION_UPDATE).matched_count == 0


def test_highscore_without_the_new_counters_saves_without_writing_them(world):
    # The discord bot loads a Highscore, bumps a counter and save()s it: on a
    # document that predates the new counters, their defaults are not written
    world.setup(banana=25, broken=1)
    highscores = world.modules.models['Highscore'].HighscoreDocument
    collection = highscores._get_collection()
    generic = {'bought': 0, 'obtained': 0, 'recycled': 0, 'sold': 0}
    internal = {name: dict(generic) for name in ['fur', 'item', 'leather', 'meat', 'ore', 'skin']}
    collection.update_one(
        {'_id': str(CREATURE_ID)},
        {'$set': {'internal': internal, 'general': {'death': 0, 'kill': 0}}},
        )

    highscore = highscores.objects(_id=CREATURE_ID).get()
    highscore.internal.item.sold += 1
    highscore.save()

    stored = collection.find_one({'_id': str(CREATURE_ID)})['internal']
    assert stored['item']['sold'] == 1
    assert set(stored) == set(internal)


def test_highscore_internal_reads_the_counters_mixology_wrote(no_gain, monkeypatch):
    no_gain.setup(banana=25, broken=0, epic=1)
    monkeypatch.setattr(no_gain.modules.route, 'mixology_yield', lambda score, rank: 5)
    highscores = no_gain.modules.models['Highscore'].HighscoreDocument
    highscores._get_collection().update_one(
        {'_id': str(CREATURE_ID)}, {'$set': {'internal': {}}},
        )

    no_gain.craft(3, 'epic')

    internal = highscores.objects(_id=CREATURE_ID).get().internal
    assert internal.shard.epic.used == 1
    assert internal.shard.broken.used == 0
    assert internal.consumable.health.long.created == 5
    assert internal.consumable.health.fast.created == 0
    assert internal.currency.spent == 25


def test_mixology_on_documents_without_its_fields(world):
    # Profession, Highscore and Satchel documents that predate mixology lack
    # the field: they read as 0 and the first craft creates it
    world.setup(banana=25, broken=1, consumable=False)
    world.professions.update_one({'_id': str(CREATURE_ID)}, {'$unset': {'mixology': ''}})
    assert 'mixology' not in world.stored()['profession']
    profession = world.modules.models['Profession'].ProfessionDocument
    assert profession.objects(_id=CREATURE_ID).get().mixology == 0

    code, body = world.craft(3)

    assert code == 200
    assert body['payload']['consumable']['count'] == 1
    stored = world.stored()
    assert stored['satchel']['consumable'] == {'health': {'long': 1}}
    assert stored['profession']['mixology'] == 1
    assert stored['highscore']['profession']['mixology'] == 1
