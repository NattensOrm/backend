# -*- coding: utf8 -*-

from flask import jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from loguru import logger

from mongo.models.User import UserDocument
from routes.auth import auth_bp
from routes.auth.schemas import LoggedInAsResponse, public_user


@auth_bp.get(
    '/infos',
    summary="Get the logged-in user's identity and account (password hash excluded)",
    security=[{"access_token": []}],
    responses={200: LoggedInAsResponse},
    )
@jwt_required()
def infos():
    username = get_jwt_identity()

    # Includes the Discord link (user.discord), written by the discord bot
    User = UserDocument.objects(name=username).first()
    if User is None:
        logger.warning('UserDocument Query KO (404)')

    msg = "User Query OK"
    logger.trace(msg)
    # Access the identity of the current user with get_jwt_identity
    return jsonify(
        logged_in_as=username,
        user=public_user(User) if User is not None else None,
    ), 200
