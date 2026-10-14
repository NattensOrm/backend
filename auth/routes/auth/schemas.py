# -*- coding: utf8 -*-

from pydantic import BaseModel


def public_user(user):
    """ user.to_mongo().to_dict(), minus the password hash: what the routes
    return as "user". Every field but hash shows up, new ones included - a
    new secret field on UserDocument must be popped here too. """
    doc = user.to_mongo().to_dict()
    doc.pop('hash', None)
    return doc


class MessageResponse(BaseModel):
    msg: str


class UserResponse(BaseModel):
    msg: str
    user: dict


class LoggedInAsResponse(BaseModel):
    logged_in_as: str
    # public_user() of the account, None when it no longer exists (token
    # still valid)
    user: dict | None


class AccessTokenResponse(BaseModel):
    access_token: str


class TokenPairResponse(BaseModel):
    access_token: str
    refresh_token: str


class ValidationErrorResponse(BaseModel):
    success: bool
    msg: str
    payload: list


class DiscordLinkCodeResponse(BaseModel):
    msg: str
    code: str
    ttl: int
