# -*- coding: utf8 -*-

import pytest
import requests

from variables import API_URL, CREATURE_ID

MIXOLOGY_URL = f"{API_URL}/mypc/{CREATURE_ID}/action/profession/mixology"


@pytest.mark.parametrize('metaid', [1, 4])
def test_singouins_mixology_not_craftable(jwt_header, metaid):
    # Meta 1 is plain currency (never crafted), meta 4 does not exist
    body = {"recipe": 1, "product": metaid, "shard": "broken"}
    response = requests.post(MIXOLOGY_URL, json=body, headers=jwt_header['access'])
    assert response.status_code == 400
    assert response.json().get("success") is False


def test_singouins_mixology_unknown_recipe(jwt_header):
    body = {"recipe": 999, "product": 2, "shard": "broken"}
    response = requests.post(MIXOLOGY_URL, json=body, headers=jwt_header['access'])
    assert response.status_code == 400
    assert response.json().get("success") is False


@pytest.mark.parametrize('rarity', ['Broken', 'mythic'])
def test_singouins_mixology_unknown_shard_rarity(jwt_header, rarity):
    body = {"recipe": 1, "product": 2, "shard": rarity}
    response = requests.post(MIXOLOGY_URL, json=body, headers=jwt_header['access'])
    assert response.status_code == 400
    assert response.json().get("success") is False


@pytest.mark.parametrize('body', [
    {"recipe": 1, "product": 2},
    {"recipe": 1, "product": 2, "shard": "broken", "count": 5},
    {"recipe": "1", "product": 2, "shard": "broken"},
    ])
def test_singouins_mixology_invalid_body(jwt_header, body):
    response = requests.post(MIXOLOGY_URL, json=body, headers=jwt_header['access'])
    assert response.status_code == 400
    assert response.json().get("success") is False


def test_singouins_mixology_without_body(jwt_header):
    response = requests.post(MIXOLOGY_URL, headers=jwt_header['access'])
    assert response.status_code == 400
    assert response.json().get("success") is False


def test_singouins_mixology_not_enough(jwt_header):
    # The test Creature (a singouin) starts without any banana: the recipe cannot be paid
    body = {"recipe": 1, "product": 2, "shard": "broken"}
    response = requests.post(MIXOLOGY_URL, json=body, headers=jwt_header['access'])
    assert response.status_code == 200
    assert response.json().get("success") is False
    assert response.json().get("payload")['satchel']['currency']['banana'] < 25
