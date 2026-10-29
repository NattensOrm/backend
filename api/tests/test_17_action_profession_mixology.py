# -*- coding: utf8 -*-

import pytest
import requests

from variables import API_URL, CREATURE_ID


@pytest.mark.parametrize('metaid', [1, 4])
def test_singouins_mixology_not_craftable(jwt_header, metaid):
    # Meta 1 is plain currency (never crafted), meta 4 does not exist
    response = requests.post(f"{API_URL}/mypc/{CREATURE_ID}/action/profession/mixology/{metaid}", headers=jwt_header['access'])  # noqa: E501
    assert response.status_code == 400
    assert response.json().get("success") is False


def test_singouins_mixology_not_enough(jwt_header):
    # The test Creature (a singouin) starts without any banana: the recipe cannot be paid
    response = requests.post(f"{API_URL}/mypc/{CREATURE_ID}/action/profession/mixology/2", headers=jwt_header['access'])  # noqa: E501
    assert response.status_code == 200
    assert response.json().get("success") is False
    assert response.json().get("payload")['satchel']['currency']['banana'] < 25
