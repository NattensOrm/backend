# -*- coding: utf8 -*-

import requests
import uuid

from variables import (
    API_ENV,
    API_URL,
    CREATURE_ID,
    CREATURE_NAME,
    r,
    )

# Designer rulings (2026-10-08): outside an instance nothing of a Singouin
# exists in Redis (leaving purges PA pools, actives and ammo), so entering an
# instance starts from nothing by construction (full PA, no actives), and a
# Singouin may not re-enter an instance it has already left.
#
# Start state (after test_11): PJTest is out of any instance, and the PC
# named 'PJTestInstanceJoin' sits alone in its own instance. End state must
# be the same so that test_99 can clean up.

BLUE_KEY = f"{API_ENV}:pas:{CREATURE_ID}:blue"
RED_KEY = f"{API_ENV}:pas:{CREATURE_ID}:red"
BODY = {"mapid": 1, "hardcore": True, "fast": False, "public": True}
ACTIVE = {
    "bearer": CREATURE_ID,
    "duration_base": 60,
    "name": 'PyTest',
    "type": 'effect',
    }


def test_singouins_mypc_instance_create_starts_full(jwt_header, mypc):
    assert 'instance' not in mypc['indexed'][CREATURE_ID]

    response  = requests.put(f'{API_URL}/mypc/{CREATURE_ID}/instance', headers=jwt_header['access'], json=BODY)  # noqa: E501
    assert response.status_code == 201
    assert response.json().get("success") is True

    # No reset on entry: nothing wrote the PA keys since the last leave
    # (test_10 deletes them), so the pools are full by construction
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


def test_singouins_mypc_instance_leave_purges_everything(jwt_header, mypc):
    instance_id = mypc['indexed'][CREATURE_ID]['instance']
    other_id = str(uuid.uuid4())
    other_key = f"{API_ENV}:{instance_id}:effects:{other_id}:PyTest"

    # Simulate spent PA, actives, and the resolver's ammo key
    r.set(BLUE_KEY, 'None', ex=9000)
    for actives_type in ('effects', 'statuses', 'cds'):
        key = f"{API_ENV}:{instance_id}:{actives_type}:{CREATURE_ID}:PyTest"
        r.hset(key, mapping=ACTIVE)
        r.expire(key, 9000)
    r.set(f"{instance_id}:ammo:{CREATURE_ID}", 10)
    # Another bearer's active in the same instance (a mob, say): the instance
    # closes below, so it must go with it
    r.hset(other_key, mapping=ACTIVE)
    r.expire(other_key, 9000)

    # PJTest is alone in its instance: leaving deletes it
    response = requests.post(f"{API_URL}/mypc/{CREATURE_ID}/instance/{instance_id}/leave", headers=jwt_header['access'])  # noqa: E501
    assert response.status_code == 200
    assert response.json().get("success") is True

    # Outside an instance nothing of the creature exists in Redis
    assert r.keys(f"{API_ENV}:pas:{CREATURE_ID}:*") == []
    assert r.keys(f"{API_ENV}:{instance_id}:*:{CREATURE_ID}:*") == []
    assert r.keys(f"{instance_id}:ammo:{CREATURE_ID}") == []
    # A closed instance takes every key scoped by it, whoever the bearer
    assert r.exists(other_key) == 0
    assert r.keys(f"{API_ENV}:{instance_id}:*") == []
    assert r.keys(f"{instance_id}:*") == []

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

    # Simulate spent PA, and an active of the player who stays
    r.set(BLUE_KEY, 'None', ex=9000)
    stayer_key = f"{API_ENV}:{instance_id}:effects:{pcjoin['_id']}:PyTest"
    r.hset(stayer_key, mapping=ACTIVE)
    r.expire(stayer_key, 9000)

    # PJTest leaves (PJTestInstanceJoin stays, so the instance survives)
    response = requests.post(f"{API_URL}/mypc/{CREATURE_ID}/instance/{instance_id}/leave", headers=jwt_header['access'])  # noqa: E501
    assert response.status_code == 200
    assert response.json().get("success") is True
    assert r.exists(BLUE_KEY) == 0
    assert r.exists(RED_KEY) == 0
    # Only the leaver's keys went: the instance survives, so does the stayer's active
    assert r.exists(stayer_key) == 1
    r.delete(stayer_key)

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
