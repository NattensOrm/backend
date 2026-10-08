# -*- coding: utf8 -*-

import requests

from variables import (
    API_ENV,
    API_URL,
    CREATURE_ID,
    CREATURE_NAME,
    r,
    )

# Designer rulings (2026-10-08): entering an instance gives a Singouin back
# all its PA, there are no PA outside an instance, and a Singouin may not
# re-enter an instance it has already left.
#
# Start state (after test_11): PJTest is out of any instance, and the PC
# named 'PJTestInstanceJoin' sits alone in its own instance. End state must
# be the same so that test_99 can clean up.

BLUE_KEY = f"{API_ENV}:pas:{CREATURE_ID}:blue"
RED_KEY = f"{API_ENV}:pas:{CREATURE_ID}:red"
BODY = {"mapid": 1, "hardcore": True, "fast": False, "public": True}


def test_singouins_mypc_instance_create_resets_pa(jwt_header, mypc):
    assert 'instance' not in mypc['indexed'][CREATURE_ID]

    # Simulate spent PA
    r.set(BLUE_KEY, 'None', ex=9000)
    r.set(RED_KEY, 'None', ex=5000)

    response  = requests.put(f'{API_URL}/mypc/{CREATURE_ID}/instance', headers=jwt_header['access'], json=BODY)  # noqa: E501
    assert response.status_code == 201
    assert response.json().get("success") is True

    # Entering an instance = full PA pools = no keys
    assert r.exists(BLUE_KEY) == 0
    assert r.exists(RED_KEY) == 0

    response  = requests.get(f'{API_URL}/mypc/{CREATURE_ID}/pa', headers=jwt_header['access'])
    assert response.status_code == 200
    assert response.json().get("success") is True
    assert response.json().get("payload")['blue']['pa'] == 8
    assert response.json().get("payload")['red']['pa'] == 16


def test_singouins_mypc_instance_double_entry_refused(jwt_header, mypc):
    assert 'instance' in mypc['indexed'][CREATURE_ID]

    # Creating a second instance while already in one
    response  = requests.put(f'{API_URL}/mypc/{CREATURE_ID}/instance', headers=jwt_header['access'], json=BODY)  # noqa: E501
    assert response.status_code == 200
    assert response.json().get("success") is False
    assert 'already in Instance' in response.json().get("msg")

    # Joining another instance while already in one
    pcjoin = [x for x in mypc['raw'] if x['name'] == 'PJTestInstanceJoin'][0]
    response = requests.post(f"{API_URL}/mypc/{CREATURE_ID}/instance/{pcjoin['instance']}/join", headers=jwt_header['access'])  # noqa: E501
    assert response.status_code == 200
    assert response.json().get("success") is False
    assert 'already in Instance' in response.json().get("msg")


def test_singouins_mypc_instance_leave_resets_pa(jwt_header, mypc):
    instance_id = mypc['indexed'][CREATURE_ID]['instance']

    # Simulate spent PA
    r.set(BLUE_KEY, 'None', ex=9000)

    # PJTest is alone in its instance: leaving deletes it
    response = requests.post(f"{API_URL}/mypc/{CREATURE_ID}/instance/{instance_id}/leave", headers=jwt_header['access'])  # noqa: E501
    assert response.status_code == 200
    assert response.json().get("success") is True

    # Outside an instance there are no PA
    assert r.exists(BLUE_KEY) == 0
    assert r.exists(RED_KEY) == 0

    response = requests.get(f'{API_URL}/mypc', headers=jwt_header['access'])
    assert response.status_code == 200
    assert response.json().get("success") is True
    pc = [x for x in response.json().get("payload") if x['name'] == CREATURE_NAME][0]
    assert 'instance' not in pc


def test_singouins_mypc_instance_no_reentry(jwt_header, mypc):
    assert 'instance' not in mypc['indexed'][CREATURE_ID]
    pcjoin = [x for x in mypc['raw'] if x['name'] == 'PJTestInstanceJoin'][0]

    # PJTest already left the current PJTestInstanceJoin instance in test_11,
    # so PJTestInstanceJoin closes it (last player) and opens a fresh one
    response = requests.post(f"{API_URL}/mypc/{pcjoin['_id']}/instance/{pcjoin['instance']}/leave", headers=jwt_header['access'])  # noqa: E501
    assert response.status_code == 200
    assert response.json().get("success") is True

    response  = requests.put(f"{API_URL}/mypc/{pcjoin['_id']}/instance", headers=jwt_header['access'], json=BODY)  # noqa: E501
    assert response.status_code == 201
    assert response.json().get("success") is True
    instance_id = response.json().get("payload")['_id']

    # PJTest joins the fresh instance
    response = requests.post(f"{API_URL}/mypc/{CREATURE_ID}/instance/{instance_id}/join", headers=jwt_header['access'])  # noqa: E501
    assert response.status_code == 200
    assert response.json().get("success") is True

    # Simulate spent PA
    r.set(BLUE_KEY, 'None', ex=9000)

    # PJTest leaves (PJTestInstanceJoin stays, so the instance survives)
    response = requests.post(f"{API_URL}/mypc/{CREATURE_ID}/instance/{instance_id}/leave", headers=jwt_header['access'])  # noqa: E501
    assert response.status_code == 200
    assert response.json().get("success") is True
    assert r.exists(BLUE_KEY) == 0
    assert r.exists(RED_KEY) == 0

    # PJTest may not re-enter an instance it left
    response = requests.post(f"{API_URL}/mypc/{CREATURE_ID}/instance/{instance_id}/join", headers=jwt_header['access'])  # noqa: E501
    assert response.status_code == 200
    assert response.json().get("success") is False
    assert 'no re-entry' in response.json().get("msg")

    # End state: PJTest out, PJTestInstanceJoin still in its instance
    response = requests.get(f'{API_URL}/mypc', headers=jwt_header['access'])
    assert response.status_code == 200
    assert response.json().get("success") is True
    pcs = response.json().get("payload")
    pc = [x for x in pcs if x['name'] == CREATURE_NAME][0]
    pcjoin = [x for x in pcs if x['name'] == 'PJTestInstanceJoin'][0]
    assert 'instance' not in pc
    assert pcjoin['instance'] == instance_id

    r.delete(BLUE_KEY)
    r.delete(RED_KEY)
