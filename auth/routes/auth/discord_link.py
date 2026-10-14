# -*- coding: utf8 -*-

import datetime

from flask import jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from loguru import logger

from mongo.models.User import UserDiscord, UserDocument
from routes.auth import auth_bp
from routes.auth.schemas import DiscordLinkCodeResponse, MessageResponse
from utils.token import (
    DISCORD_LINK_CODE_DURATION,
    generate_discord_link_code,
    revoke_discord_link_code,
    )


@auth_bp.post(
    '/discord/link',
    summary="Get a single-use code to link the logged-in user's Discord account",
    description=(
        "The code is typed in Discord with `/user link code:<code>` (dash and "
        "case don't matter). Valid `ttl` seconds, single use; a new code "
        "revokes the previous one. Linking replaces any previous Discord link "
        "of the account."
        ),
    security=[{"access_token": []}],
    responses={200: DiscordLinkCodeResponse, 404: MessageResponse, 500: MessageResponse},
    )
@jwt_required()
def discord_link():
    # Being logged in here is what proves the account ownership: the code
    # carries that proof over to Discord. Always the caller's own account.
    username = get_jwt_identity()

    User = UserDocument.objects(name=username).first()
    if User is None:
        msg = 'UserDocument Query KO (404)'
        logger.warning(msg)
        return jsonify({"msg": msg}), 404

    try:
        code = generate_discord_link_code(User.id)
    except Exception as e:
        msg = f'Discord link code KO (username:{username}) [{e}]'
        logger.error(msg)
        return jsonify({"msg": msg}), 500

    # The code is a secret: never logged
    msg = f'Discord link code OK (username:{username})'
    logger.debug(msg)
    return jsonify(
        {
            "msg": msg,
            # Dashed for readability, Discord accepts it with or without
            "code": f'{code[:4]}-{code[4:]}',
            "ttl": DISCORD_LINK_CODE_DURATION,
        }
    ), 200


@auth_bp.delete(
    '/discord/link',
    summary="Unlink the logged-in user's Discord account",
    description=(
        "Also revokes a pending link code. Idempotent: unlinking an account "
        "that is not linked is a success too. Squad/Korp Discord roles "
        "already granted are not removed."
        ),
    security=[{"access_token": []}],
    responses={200: MessageResponse, 404: MessageResponse, 500: MessageResponse},
    )
@jwt_required()
def discord_unlink():
    # Always the caller's own account, never taken from the request
    username = get_jwt_identity()

    User = UserDocument.objects(name=username).first()
    if User is None:
        msg = 'UserDocument Query KO (404)'
        logger.warning(msg)
        return jsonify({"msg": msg}), 404

    try:
        # Code first: a code issued before the unlink must not relink it
        revoke_discord_link_code(User.id)
        UserDocument.objects(pk=User.pk).update_one(
            set__discord=UserDiscord(),
            set__updated=datetime.datetime.utcnow(),
            )
    except Exception as e:
        msg = f'Discord unlink KO (username:{username}) [{e}]'
        logger.error(msg)
        return jsonify({"msg": msg}), 500

    if User.discord.name:
        msg = f'Discord unlink OK (username:{username})'
    else:
        msg = f'Discord unlink OK (username:{username}) [was not linked]'
    logger.debug(msg)
    return jsonify({"msg": msg}), 200
