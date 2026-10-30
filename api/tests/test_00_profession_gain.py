# -*- coding: utf8 -*-

import importlib.util
import os
import sys
import types
import uuid

import pytest

# Needed for local imports and simulate production paths (api/ on sys.path,
# resolved from this file so it works whatever the cwd pytest runs from)
LOCAL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)
sys.path.append(LOCAL_PATH)

# profession_gain gives 0 or 1 point per action, rolled with the odds of the
# score's own band only (see the table in _tools.py). The lower bands used to
# roll too, so an action could give up to 4 points and scores passed 100.
# Unit test: no Mongo, the Profession updates and the rolls are recorded.
TOOLS = os.path.join(LOCAL_PATH, 'routes', 'mypc', 'action', 'profession', '_tools.py')

CREATURE_ID = uuid.uuid4()


@pytest.fixture
def tools(monkeypatch):
    """
    Loads _tools.py from its file with ProfessionDocument and mongo.utils
    stubbed. `updates` holds each Profession update, `rolls` the weights of
    each roll; `forced` is what every roll returns.
    """
    state = types.SimpleNamespace(updates=[], rolls=[], forced=1, score=0)

    class _QuerySet:
        def __init__(self, **query):
            self.query = query

        def update(self, **update):
            state.updates.append(update)

        def get(self):
            return types.SimpleNamespace(tanning=state.score)

    profession = types.ModuleType('mongo.models.Profession')
    profession.ProfessionDocument = types.SimpleNamespace(objects=_QuerySet)
    monkeypatch.setitem(sys.modules, 'mongo.models.Profession', profession)
    utils = types.ModuleType('mongo.utils')
    utils.utcnow = lambda: 'now'
    monkeypatch.setitem(sys.modules, 'mongo.utils', utils)

    spec = importlib.util.spec_from_file_location('test_profession_gain_tools', TOOLS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def choices(population, weights):
        state.rolls.append(tuple(weights))
        return [state.forced]

    monkeypatch.setattr(module, 'choices', choices)
    state.gain = module.profession_gain
    return state


def _points(tools):
    """ Points added to the Profession by the recorded updates. """
    return sum(update['inc__tanning'] for update in tools.updates)


@pytest.mark.parametrize('score', [0, 1, 24])
def test_below_25_an_action_gives_exactly_one_point(tools, score):
    tools.gain(CREATURE_ID, 'tanning', score)

    assert tools.rolls == []
    assert _points(tools) == 1


@pytest.mark.parametrize('score, weights', [
    (25, (50, 50)), (49, (50, 50)),
    (50, (60, 40)), (74, (60, 40)),
    (75, (70, 30)), (99, (70, 30)),
])
@pytest.mark.parametrize('forced', [0, 1])
def test_a_band_rolls_once_with_its_own_odds(tools, score, weights, forced):
    tools.forced = forced

    tools.gain(CREATURE_ID, 'tanning', score)

    assert tools.rolls == [weights]
    assert _points(tools) == forced


@pytest.mark.parametrize('score', [100, 101, 250])
def test_from_100_an_action_gives_no_point(tools, score):
    tools.gain(CREATURE_ID, 'tanning', score)

    assert tools.rolls == []
    assert tools.updates == []


def test_without_a_score_it_reads_the_profession(tools):
    tools.score = 60

    tools.gain(CREATURE_ID, 'tanning')

    assert tools.rolls == [(60, 40)]
    assert _points(tools) == 1
