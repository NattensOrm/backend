# -*- coding: utf8 -*-

import json
import os

ARMORS_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    '..', 'data', 'metas', 'armors.json',
)


def _load_armors():
    with open(ARMORS_FILE, 'r', encoding='utf-8') as file:
        return json.load(file)


def test_meta_armors_ids_are_unique():
    """
    Every armor meta has its own id (ids are the Mongo primary keys)
    """
    ids = [armor['id'] for armor in _load_armors()]

    assert len(ids) == len(set(ids))


def test_meta_armors_heavy_is_a_marker_count():
    """
    heavy (Lourd ! markers) is a positive integer when present
    """
    invalid = {
        armor['id']: armor['heavy']
        for armor in _load_armors()
        if 'heavy' in armor
        and (type(armor['heavy']) is not int or armor['heavy'] < 1)
    }

    assert invalid == {}


def test_meta_armors_bulldozer_is_a_heavy_body_armor():
    """
    bulldozer is true when present, only on a heavy armor piece (not a shield)
    """
    invalid = {
        armor['id']: (armor['bulldozer'], armor['slot'], armor.get('heavy'))
        for armor in _load_armors()
        if 'bulldozer' in armor
        and (armor['bulldozer'] is not True
             or armor['slot'] == 'Shield'
             or 'heavy' not in armor)
    }

    assert invalid == {}


def test_meta_armors_set_is_a_name():
    """
    set (armor suit the piece belongs to) is a non-empty string when present
    """
    invalid = {
        armor['id']: armor['set']
        for armor in _load_armors()
        if 'set' in armor
        and (type(armor['set']) is not str or armor['set'] == '')
    }

    assert invalid == {}
