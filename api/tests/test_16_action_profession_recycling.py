# -*- coding: utf8 -*-

import requests

from variables import API_URL, CREATURE_ID

ROUTE_INVENTORY = f'{API_URL}/mypc/{CREATURE_ID}/inventory/item'
ROUTE_RECYCLING = f'{API_URL}/mypc/{CREATURE_ID}/action/profession/recycling'


def test_singouins_profession_recycling(jwt_header, myitems):
    # We need the Machette à bananes (metaid:11), equipped in lefthand at creation
    weapon = [x for x in myitems['weapon'] if x['metaid'] == 11][0]
    assert myitems['equipment']['lefthand']['id'] == weapon['_id']

    # An equipped Item is refused
    response = requests.post(f"{ROUTE_RECYCLING}/{weapon['_id']}", headers=jwt_header['access'])
    assert response.status_code == 200
    assert response.json().get("success") is False
    assert 'is equipped' in response.json().get("msg")

    # Once unequipped, it is recycled
    response = requests.post(f"{ROUTE_INVENTORY}/{weapon['_id']}/unequip/weapon/lefthand", headers=jwt_header['access'])  # noqa: E501
    assert response.status_code == 200
    assert response.json().get("success") is True

    response = requests.post(f"{ROUTE_RECYCLING}/{weapon['_id']}", headers=jwt_header['access'])
    assert response.status_code == 200
    assert response.json().get("success") is True
