# -*- coding: utf8 -*-

import secrets

from utils.redis import r
from variables import env_vars

CONFIRMATION_TOKEN_DURATION = 3600  # 1 hour, in seconds
RESET_TOKEN_DURATION = 3600  # 1 hour, in seconds


def _confirmation_token_key(token):
    return f"{env_vars['API_ENV']}:auth:confirm_token:{token}"


def _current_confirmation_token_key(email):
    return f"{env_vars['API_ENV']}:auth:current_confirm_token:{email}"


def generate_confirmation_token(email):
    """ Generate a Redis-backed confirmation token for `email`, valid for
    CONFIRMATION_TOKEN_DURATION seconds. Also stored under a per-email
    lookup key, so a caller who only knows the email (tests, support
    tooling) can find the current pending token without needing the
    emailed link itself. """
    token = secrets.token_urlsafe(32)
    r.set(_confirmation_token_key(token), email, ex=CONFIRMATION_TOKEN_DURATION)
    r.set(_current_confirmation_token_key(email), token, ex=CONFIRMATION_TOKEN_DURATION)
    return token


def confirm_token(token):
    """ Resolve a confirmation token to the email it was issued for, or
    None if it's invalid/unknown/expired (Redis expiring the key IS the
    expiration check - no separate max-age logic needed). """
    email = r.get(_confirmation_token_key(token))
    if email is None:
        return None
    return email.decode()


def _reset_token_key(token):
    return f"{env_vars['API_ENV']}:auth:reset_token:{token}"


def _current_reset_token_key(email):
    return f"{env_vars['API_ENV']}:auth:current_reset_token:{email}"


def generate_reset_token(email):
    """ Generate a Redis-backed password-reset token for `email`, valid for
    RESET_TOKEN_DURATION seconds. Also stored under a per-email lookup key
    (see generate_confirmation_token). """
    token = secrets.token_urlsafe(32)
    r.set(_reset_token_key(token), email, ex=RESET_TOKEN_DURATION)
    r.set(_current_reset_token_key(email), token, ex=RESET_TOKEN_DURATION)
    return token


def resolve_reset_token(token):
    """ Resolve a password-reset token to the email it was issued for, and
    consume it - unlike a confirmation token, a reset token must not be
    replayable, so a second attempt with the same token must fail even
    within its TTL. Returns None if invalid/unknown/expired/already used. """
    key = _reset_token_key(token)
    email = r.get(key)
    if email is None:
        return None
    r.delete(key)
    return email.decode()


# Discord link codes: issued here (POST /discord/link) to a logged-in User,
# consumed by the discord bot (/user link code:...). Same key names in
# discord/utils/redis.py's link_code_consume() - keep the two in sync.
DISCORD_LINK_CODE_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'  # No 0/O, 1/I
DISCORD_LINK_CODE_LENGTH = 8
DISCORD_LINK_CODE_DURATION = 600  # 10 minutes, in seconds


def _discord_link_code_key(code):
    return f"{env_vars['API_ENV']}:discord:link_code:{code}"


def _current_discord_link_code_key(useruuid):
    return f"{env_vars['API_ENV']}:discord:current_link_code:{useruuid}"


def generate_discord_link_code(useruuid):
    """ Generate a Redis-backed Discord link code for the User `useruuid`,
    valid for DISCORD_LINK_CODE_DURATION seconds. Short (typed by hand in
    Discord), so the bot limits the attempts. Single-use: the bot deletes
    it on read. A new code revokes the User's previous one, found through
    the per-User lookup key (see generate_confirmation_token). """
    useruuid = str(useruuid)
    while True:
        code = ''.join(
            secrets.choice(DISCORD_LINK_CODE_ALPHABET)
            for _ in range(DISCORD_LINK_CODE_LENGTH)
            )
        # NX: never take over a live code of another User (2^40 codes, so
        # this only loops on an astronomically unlikely collision)
        if r.set(_discord_link_code_key(code), useruuid, ex=DISCORD_LINK_CODE_DURATION, nx=True):
            break

    # SET ... GET (Redis >= 6.2): swap in the new code, get the old one back
    previous = r.set(
        _current_discord_link_code_key(useruuid), code, ex=DISCORD_LINK_CODE_DURATION, get=True,
        )
    if previous is not None:
        r.delete(_discord_link_code_key(previous.decode()))
    return code


def revoke_discord_link_code(useruuid):
    """ Revoke the User's pending Discord link code, if any. """
    # GETDEL (Redis >= 6.2): one shot, a concurrent generate can't slip in
    code = r.getdel(_current_discord_link_code_key(str(useruuid)))
    if code is not None:
        r.delete(_discord_link_code_key(code.decode()))
