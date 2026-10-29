# -*- coding: utf8 -*-

import re

import requests

from variables import API_ENV, API_URL, USER_ID, r, users

# Same keys as auth/utils/token.py (and discord/utils/redis.py, the consumer)
CODE_KEY = f'{API_ENV}:discord:link_code:{{}}'
CURRENT_KEY = f'{API_ENV}:discord:current_link_code:{USER_ID}'
# A link, as written by the discord bot: id (a str, see UserDiscord) + name
DISCORD = {'id': '123456789012345678', 'name': 'tester'}


def _new_code(jwt_header):
    response = requests.post(f'{API_URL}/discord/link', headers=jwt_header['access'])
    assert response.status_code == 200
    return response.json()


def test_singouins_auth_discord_link_code(jwt_header):
    payload = _new_code(jwt_header)

    assert re.fullmatch(r'[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}', payload['code'])
    assert payload['ttl'] == 600
    # The code is a secret: not echoed in the message
    assert payload['code'] not in payload['msg']

    # Stored without the dash, pointing to the logged-in User, expiring
    code = payload['code'].replace('-', '')
    assert r.get(CODE_KEY.format(code)).decode() == USER_ID
    assert 0 < r.ttl(CODE_KEY.format(code)) <= 600
    assert r.get(CURRENT_KEY).decode() == code


def test_singouins_auth_discord_link_code_revokes_previous(jwt_header):
    first = _new_code(jwt_header)['code'].replace('-', '')
    second = _new_code(jwt_header)['code'].replace('-', '')

    assert first != second
    assert r.get(CODE_KEY.format(first)) is None
    assert r.get(CODE_KEY.format(second)).decode() == USER_ID
    assert r.get(CURRENT_KEY).decode() == second


def test_singouins_auth_discord_link_code_needs_login():
    response = requests.post(f'{API_URL}/discord/link')
    assert response.status_code == 401


def test_singouins_auth_discord_unlink(jwt_header):
    # Linked (written by the discord bot) with a pending code
    users.update_one({'_id': USER_ID}, {'$set': {'discord': DISCORD}})
    code = _new_code(jwt_header)['code'].replace('-', '')

    response = requests.delete(f'{API_URL}/discord/link', headers=jwt_header['access'])
    assert response.status_code == 200
    assert 'unlink OK' in response.json()['msg']
    assert 'was not linked' not in response.json()['msg']

    assert users.find_one({'_id': USER_ID})['discord'] == {}
    # The pending code can't relink the account behind the user's back
    assert r.get(CODE_KEY.format(code)) is None
    assert r.get(CURRENT_KEY) is None


def test_singouins_auth_discord_unlink_is_idempotent(jwt_header):
    response = requests.delete(f'{API_URL}/discord/link', headers=jwt_header['access'])
    assert response.status_code == 200
    assert 'was not linked' in response.json()['msg']
    assert users.find_one({'_id': USER_ID})['discord'] == {}


def test_singouins_auth_discord_unlink_needs_login():
    response = requests.delete(f'{API_URL}/discord/link')
    assert response.status_code == 401


def test_singouins_auth_infos_shows_discord_link(jwt_header):
    users.update_one({'_id': USER_ID}, {'$set': {'discord': DISCORD}})
    response = requests.get(f'{API_URL}/infos', headers=jwt_header['access'])
    assert response.status_code == 200
    assert response.json()['user']['discord'] == DISCORD

    requests.delete(f'{API_URL}/discord/link', headers=jwt_header['access'])
    response = requests.get(f'{API_URL}/infos', headers=jwt_header['access'])
    assert response.json()['user']['discord'] == {}
