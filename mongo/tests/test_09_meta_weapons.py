# -*- coding: utf8 -*-

import json
import os
import sys

# Needed for local imports and simulate production paths
LOCAL_PATH = os.path.dirname(os.path.abspath('mongo'))
sys.path.append(LOCAL_PATH)

from mongo.models.Satchel import SatchelAmmo  # noqa: E402

WEAPONS_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    '..', 'data', 'metas', 'weapons.json',
)
ALLOWED_SIZES = {'1x2', '2x2', '2x3', '2x4', '3x4'}


def _load_weapons():
    with open(WEAPONS_FILE, 'r', encoding='utf-8') as file:
        return json.load(file)


def test_meta_weapons_ids_are_unique():
    """
    Every weapon meta has its own id (ids are the Mongo primary keys)
    """
    ids = [weapon['id'] for weapon in _load_weapons()]

    assert len(ids) == len(set(ids))


def test_meta_weapons_calibers_are_satchel_ammo_fields():
    """
    Every ranged weapon caliber matches a SatchelAmmo field,
    otherwise reload/unload cannot find the ammo in the Satchel
    """
    ammo_fields = set(SatchelAmmo._fields)
    unknown = {
        weapon['id']: weapon['caliber']
        for weapon in _load_weapons()
        if weapon['ranged'] and weapon['caliber'] is not None
        and weapon['caliber'] not in ammo_fields
    }

    assert unknown == {}


def test_meta_weapons_have_stock_and_cadence():
    """
    Every weapon meta carries the stock and cadence keys (null allowed)
    """
    missing = [
        weapon['id']
        for weapon in _load_weapons()
        if 'stock' not in weapon or 'cadence' not in weapon
    ]

    assert missing == []


def test_meta_weapons_burst_only_needs_a_cadence():
    """
    burst_only (automatic fire) is true when present, and only on weapons
    with a cadence above 1, otherwise the resolver ignores it
    """
    invalid = {
        weapon['id']: (weapon['burst_only'], weapon['cadence'])
        for weapon in _load_weapons()
        if 'burst_only' in weapon
        and (weapon['burst_only'] is not True
             or weapon['cadence'] is None or weapon['cadence'] <= 1)
    }

    assert invalid == {}


def test_meta_weapons_sizes_are_known():
    """
    Every weapon meta size is one of the inventory sizes of the design sheet
    """
    unknown = {
        weapon['id']: weapon['size']
        for weapon in _load_weapons()
        if weapon['size'] not in ALLOWED_SIZES
    }

    assert unknown == {}
