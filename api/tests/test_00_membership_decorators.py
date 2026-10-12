# -*- coding: utf8 -*-

import os
import sys
import types
import uuid

import pytest
from flask import Flask, g

# Needed for local imports and simulate production paths (api/ on sys.path,
# resolved from this file so it works whatever the cwd pytest runs from)
LOCAL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)
sys.path.append(LOCAL_PATH)

# The Korp/Squad membership decorators (utils.decorators check_creature_in_*,
# routes._decorators.belongs creature_in_*). CreatureKorp/CreatureSquad are
# required embedded documents whose id defaults to None, so "no membership"
# is an embedded document with id None (or, on old documents, no embedded
# document at all). It must answer "Creature not in a Korp/Squad".
#
# Regression: the former guard `hasattr(g.Creature.korp, 'id') is False` was
# always True when the embedded document exists with id None, so
# test_no_membership_id_none_is_not_in_a failed: the creature fell through to
# "Creature not in this Korp/Squad". Pure unit test: no Mongo, no Redis.

CREATURE_ID = uuid.uuid4()
GROUP_ID = uuid.uuid4()
OTHER_ID = uuid.uuid4()

# utils.decorators imports the Mongo models. Importing the real mongo package
# connects to Mongo and loads the metas (mongo/__init__.py), so these leaves
# are stubbed in sys.modules: once a dotted name is there, Python never
# imports its parents.
MODEL_STUBS = {
    'mongo.models.Creature': ['CreatureDocument'],
    'mongo.models.Instance': ['InstanceDocument'],
    'mongo.models.Item': ['ItemDocument'],
    'mongo.models.Korp': ['KorpDocument'],
    'mongo.models.Squad': ['SquadDocument'],
    'mongo.models.User': ['UserDocument'],
    }
# Modules bound to the stubs at import: imported fresh here, then dropped
# (and any previous copy put back) so that no other test sees them
ISOLATED = [
    'utils.decorators',
    'routes._decorators.belongs',
    ]
# Marks a parent package attribute that did not exist before the import
_ABSENT = object()


@pytest.fixture
def modules(monkeypatch):
    """
    Imports utils.decorators and routes._decorators.belongs against stubbed
    models. Inside api/tests, `variables` resolves to tests/variables.py
    (loaded by conftest), not api/variables.py (which connects to Mongo at
    import), so the keys utils.redis needs from it are provided here.
    Returns {'utils': module, 'belongs': module}.
    """
    variables = sys.modules['variables']
    # Same keys as api/variables.py: utils.redis builds its (lazy) pool from them at import
    monkeypatch.setattr(variables, 'env_vars', {
        'API_ENV': 'pytest',
        'REDIS_HOST': '127.0.0.1',
        'REDIS_PORT': 6379,
        'REDIS_BASE': 0,
        }, raising=False)

    for name, attributes in MODEL_STUBS.items():
        stub = types.ModuleType(name)
        for attribute in attributes:
            setattr(stub, attribute, None)
        monkeypatch.setitem(sys.modules, name, stub)

    # An import also binds the module on its parent package, and
    # `from <parent> import <child>` reads that attribute: saved and put back too
    saved = {}
    for name in ISOLATED:
        parent, _, child = name.rpartition('.')
        parent_module = sys.modules.get(parent)
        attribute = _ABSENT if parent_module is None else getattr(parent_module, child, _ABSENT)
        saved[name] = (sys.modules.pop(name, None), attribute)
    try:
        import utils.decorators as decorators
        import routes._decorators.belongs as belongs
        yield {'utils': decorators, 'belongs': belongs}
    finally:
        for name, (previous, _) in saved.items():
            sys.modules.pop(name, None)
            if previous is not None:
                sys.modules[name] = previous
        for name, (_, attribute) in saved.items():
            parent, _, child = name.rpartition('.')
            parent_module = sys.modules.get(parent)
            if parent_module is None:
                continue
            if attribute is _ABSENT:
                if hasattr(parent_module, child):
                    delattr(parent_module, child)
            else:
                setattr(parent_module, child, attribute)


# (module key, decorator name, Creature field, g attribute, label in messages)
CASES = [
    ('utils', 'check_creature_in_korp', 'korp', 'Korp', 'Korp'),
    ('utils', 'check_creature_in_squad', 'squad', 'Squad', 'Squad'),
    ('belongs', 'creature_in_korp', 'korp', 'Korp', 'Korp'),
    ('belongs', 'creature_in_squad', 'squad', 'Squad', 'Squad'),
    ]
IDS = [f'{case[0]}.{case[1]}' for case in CASES]


@pytest.fixture(params=CASES, ids=IDS)
def run(request, modules):
    """
    Wraps a recording view with the decorator under test and calls it in a
    minimal Flask app context, with g.Creature and g.Korp/g.Squad as fakes.
    Returns call(membership) -> (result, calls, label), where membership is
    the Creature's embedded document (SimpleNamespace or None).
    """
    module_key, decorator_name, field, g_name, label = request.param
    decorator = getattr(modules[module_key], decorator_name)
    app = Flask(__name__)

    def call(membership):
        calls = []

        @decorator
        def view():
            calls.append(True)
            return 'called'

        with app.app_context():
            g.Creature = types.SimpleNamespace(id=CREATURE_ID, **{field: membership})
            setattr(g, g_name, types.SimpleNamespace(id=GROUP_ID))
            result = view()
            if isinstance(result, tuple):
                response, status = result
                result = (response.get_json(), status)
        return result, calls, label

    return call


def _refusal(label, text):
    return ({
        "success": False,
        "msg": f'[Creature.id:{CREATURE_ID}] Creature {text} {label}',
        "payload": None,
        }, 200)


def test_no_membership_id_none_is_not_in_a(run):
    # Embedded document present, id None: the usual "no Korp/Squad" shape
    result, calls, label = run(types.SimpleNamespace(id=None, rank=None))
    assert result == _refusal(label, 'not in a')
    assert calls == []


def test_no_embedded_document_is_not_in_a(run):
    # Old documents: no embedded document at all
    result, calls, label = run(None)
    assert result == _refusal(label, 'not in a')
    assert calls == []


def test_other_group_is_not_in_this(run):
    result, calls, label = run(types.SimpleNamespace(id=OTHER_ID, rank='Member'))
    assert result == _refusal(label, 'not in this')
    assert calls == []


def test_same_group_calls_the_view(run):
    result, calls, _ = run(types.SimpleNamespace(id=GROUP_ID, rank='Member'))
    assert result == 'called'
    assert calls == [True]


#
# Isolation: runs last in this file, after every use of the modules fixture
#
def test_isolation_leaves_no_stub_bound_module():
    for name in ISOLATED:
        parent, _, child = name.rpartition('.')
        current = sys.modules.get(name)
        assert getattr(current, 'CreatureDocument', 'real') is not None
        assert getattr(current, 'InstanceDocument', 'real') is not None
        parent_module = sys.modules.get(parent)
        if parent_module is not None and hasattr(parent_module, child):
            # `from <parent> import <child>` must give what sys.modules holds
            assert getattr(parent_module, child) is current
