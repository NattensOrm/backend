# -*- coding: utf8 -*-

import functools
import importlib.util
import os
import sys
import types
import uuid

import flask_jwt_extended
import pytest
from flask import Flask, g, jsonify

# Needed for local imports and simulate production paths (api/ on sys.path,
# resolved from this file so it works whatever the cwd pytest runs from)
LOCAL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)
sys.path.append(LOCAL_PATH)

# Rulings 2026-10-29 (Lordslair: "un refus doit être gratuit [...] Les PA ne
# devraient être consommés que si l'action est réalisée"; chifret: "Être
# refusé est différent de rater. Rater, c'est validé."): out of combat, a
# refusal (not found, not owned, missing resources) costs no PA, a validated
# action costs its PA exactly once, whatever its roll yields.
# Unit test: no Mongo, no Redis, the routes are loaded from their files.
PROFESSION_ROUTES = os.path.join(LOCAL_PATH, 'routes', 'mypc', 'action', 'profession')
RARITIES = ['Broken', 'Common', 'Uncommon', 'Rare', 'Epic', 'Legendary']
TICK = 3600


def _identity(func):
    return func


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _module(name, monkeypatch, **attributes):
    module = types.ModuleType(name)
    for key, value in attributes.items():
        setattr(module, key, value)
    monkeypatch.setitem(sys.modules, name, module)
    return module


def _refusal(msg):
    return jsonify({"success": False, "msg": msg, "payload": None}), 200


class _QuerySet(list):
    """ A Mongo queryset: truthy when it holds a document, get() returns it. """
    def get(self):
        return self[0]


@pytest.fixture
def world(monkeypatch):
    """
    Loads gathering / recycling / tanning / tracking straight from their files
    (the routes.mypc package pulls every route at import). Models, tools and
    Redis are stubbed, every side effect appends to `events`.

    exists.pa is stubbed as the real one behaves: it records its arguments in
    `pa_checks` and, with consume=True only, consumes before the view runs.
    exists.item / belongs.item_to_creature refuse when named in `refuse`.
    """
    events = []
    pa_checks = {}
    refuse = set()
    state = types.SimpleNamespace(resource=None, skin=10, redis_error=False)

    def pa(red=0, blue=0, consume=False):
        def decorator(func):
            pa_checks[func.__name__] = {'red': red, 'blue': blue, 'consume': consume}

            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                if consume is True:
                    events.append(('pa', g.Creature.id, red, blue, TICK))
                return func(*args, **kwargs)
            return wrapper
        return decorator

    def refusing(name):
        def decorator(func):
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                if name in refuse:
                    return _refusal(f'{name} refused')
                return func(*args, **kwargs)
            return wrapper
        return decorator

    _module(
        'routes._decorators', monkeypatch,
        exists=types.SimpleNamespace(creature=_identity, pa=pa, item=refusing('item')),
        belongs=types.SimpleNamespace(
            creature_in_instance=_identity,
            creature_out_of_instance=_identity,
            item_to_creature=refusing('item_to_creature'),
            ),
        )

    satchel = types.SimpleNamespace(
        update=lambda **kwargs: events.append(('satchel',)),
        reload=lambda: None,
        to_mongo=lambda: {},
        )

    def satchel_get():
        satchel.resource = types.SimpleNamespace(skin=state.skin)
        return satchel

    _module(
        'mongo.models.Highscore', monkeypatch,
        HighscoreDocument=types.SimpleNamespace(
            objects=lambda _id=None: types.SimpleNamespace(
                update=lambda **kwargs: events.append(('highscore',)),
                update_one=lambda **kwargs: events.append(('highscore',)),
                ),
            ),
        )
    _module(
        'mongo.models.Profession', monkeypatch,
        ProfessionDocument=types.SimpleNamespace(
            objects=lambda _id=None: types.SimpleNamespace(
                get=lambda: types.SimpleNamespace(gathering=0, recycling=0, skinning=0),
                ),
            ),
        )
    _module(
        'mongo.models.Resource', monkeypatch,
        ResourceDocument=types.SimpleNamespace(
            objects=lambda _id=None: _QuerySet([state.resource] if state.resource else []),
            ),
        )
    _module(
        'mongo.models.Satchel', monkeypatch,
        SatchelDocument=types.SimpleNamespace(
            objects=lambda _id=None: types.SimpleNamespace(
                get=satchel_get,
                update_one=lambda **kwargs: events.append(('satchel',)),
                ),
            ),
        )
    _module(
        'routes.mypc.action.profession._tools', monkeypatch,
        probabilistic_binary=lambda stat: 0,
        profession_gain=lambda *args: events.append(('profession',)),
        profession_scaled=lambda score: 0,
        )
    _module('utils.pa', monkeypatch, instance_tick=lambda creature: TICK)

    def hset(key, mapping):
        if state.redis_error:
            raise ConnectionError('Redis down')
        events.append(('effect', mapping['name']))

    _module(
        'utils.redis', monkeypatch,
        r=types.SimpleNamespace(hset=hset, expire=lambda key, ttl: None),
        consume_pa=lambda creatureuuid, redpa=0, bluepa=0, *, tick: events.append(
            ('pa', creatureuuid, redpa, bluepa, tick)),
        get_pa=lambda **kwargs: {'pa': 'stub'},
        )
    _module(
        'variables', monkeypatch,
        env_vars={'API_ENV': 'TEST'},
        rarity_array={'item': RARITIES},
        )
    monkeypatch.setattr(flask_jwt_extended, 'jwt_required', lambda: _identity)

    routes = {
        name: _load(f'test_pa_on_success_{name}', os.path.join(PROFESSION_ROUTES, f'{name}.py'))
        for name in ('gathering', 'recycling', 'tanning', 'tracking')
        }
    app = Flask(__name__)
    creature = types.SimpleNamespace(
        id=uuid.uuid4(),
        instance=uuid.uuid4(),
        stats=types.SimpleNamespace(total=types.SimpleNamespace(m=50, b=50)),
        )

    def call(name, item=None, **kwargs):
        with app.test_request_context():
            g.h = f'[Creature.id:{creature.id}]'
            g.Creature = creature
            g.Item = item
            view = getattr(routes[name], name)
            response, code = view(creatureuuid=creature.id, **kwargs)
            return code, response.get_json()

    return types.SimpleNamespace(
        call=call, creature=creature, events=events, pa_checks=pa_checks,
        refuse=refuse, state=state,
        )


def _resource(world, rarity):
    world.state.resource = types.SimpleNamespace(
        rarity=rarity,
        delete=lambda: world.events.append(('resource_delete',)),
        )


def _item(world, rarity):
    return types.SimpleNamespace(
        id=uuid.uuid4(),
        rarity=rarity,
        delete=lambda: world.events.append(('item_delete',)),
        )


def _pa_events(world):
    return [event for event in world.events if event[0] == 'pa']


def _assert_refused_free(world, code, body):
    assert code == 200
    assert body['success'] is False
    # A refusal is free: no PA consumed, nothing done
    assert world.events == []


@pytest.mark.parametrize('route, red, blue', [
    ('gathering', 0, 4),
    ('recycling', 0, 2),
    ('tanning', 0, 2),
    ('tracking', 0, 2),
    ])
def test_decorator_checks_pa_without_consuming(world, route, red, blue):
    assert world.pa_checks[route] == {'red': red, 'blue': blue, 'consume': False}


#
# gathering
#
def test_gathering_resource_not_found_is_free(world):
    code, body = world.call('gathering', resourceuuid=uuid.uuid4())

    _assert_refused_free(world, code, body)
    assert 'NotFound' in body['msg']


def test_gathering_pays_once_before_any_credit(world):
    _resource(world, 'Common')

    code, body = world.call('gathering', resourceuuid=uuid.uuid4())

    assert code == 200
    assert body['success'] is True
    assert world.events == [
        ('pa', world.creature.id, 0, 4, TICK),
        ('profession',),
        ('highscore',),
        ('satchel',),
        ('resource_delete',),
        ]


def test_gathering_zero_yield_still_pays_once(world):
    # A validated gathering that yields nothing failed, it was not refused
    _resource(world, 'Legendary')

    code, body = world.call('gathering', resourceuuid=uuid.uuid4())

    assert body['payload']['resource'][0]['count'] == 0
    assert _pa_events(world) == [('pa', world.creature.id, 0, 4, TICK)]


#
# recycling
#
@pytest.mark.parametrize('refusal', ['item', 'item_to_creature'])
def test_recycling_item_refusal_is_free(world, refusal):
    world.refuse.add(refusal)

    code, body = world.call('recycling', itemuuid=uuid.uuid4())

    _assert_refused_free(world, code, body)


def test_recycling_pays_once_before_any_credit(world):
    item = _item(world, 'Common')

    code, body = world.call('recycling', item=item, itemuuid=item.id)

    assert code == 200
    assert body['success'] is True
    assert world.events == [
        ('pa', world.creature.id, 0, 2, TICK),
        ('highscore',),
        ('satchel',),
        ('profession',),
        ('item_delete',),
        ]


def test_recycling_zero_shards_still_pays_once(world):
    item = _item(world, 'Legendary')

    code, body = world.call('recycling', item=item, itemuuid=item.id)

    assert body['payload']['resource'][0]['count'] == 0
    assert _pa_events(world) == [('pa', world.creature.id, 0, 2, TICK)]


#
# tanning
#
def test_tanning_without_enough_skin_is_free(world):
    world.state.skin = 9

    code, body = world.call('tanning')

    _assert_refused_free(world, code, body)
    assert 'Not enough resource.skin' in body['msg']


def test_tanning_pays_once_before_any_credit(world):
    code, body = world.call('tanning')

    assert code == 200
    assert body['success'] is True
    assert world.events == [
        ('pa', world.creature.id, 0, 2, TICK),
        ('highscore',),
        ('satchel',),
        ('profession',),
        ]


#
# tracking
#
def test_tracking_redis_error_is_free(world):
    world.state.redis_error = True

    code, body = world.call('tracking')

    _assert_refused_free(world, code, body)
    assert 'Redis Query KO' in body['msg']


def test_tracking_pays_once_after_the_effect(world):
    code, body = world.call('tracking')

    assert code == 200
    assert body['success'] is True
    assert world.events == [
        ('effect', 'Tracking'),
        ('pa', world.creature.id, 0, 2, TICK),
        ('highscore',),
        ]
