# -*- coding: utf8 -*-

import discord

from loguru import logger

from mongo.models.User import UserDocument


def linked_user(member: discord.abc.User) -> UserDocument | None:
    """
    The User linked to a Discord user, looked up by its id: the id never
    changes, the name does (and a freed name can be taken by someone else).

    The stored name is display only: refreshed here when it changed.

    :param member: The Discord user (ctx.author, interaction.user, ...).

    :return: The linked User, or None if this Discord user is not linked.
             Mongo errors on the lookup are raised to the caller.
    """
    User = UserDocument.objects(discord__id=str(member.id)).first()
    if User is not None and User.discord.name != member.name:
        try:
            UserDocument.objects(pk=User.pk).update_one(set__discord__name=member.name)
        except Exception as e:
            # Cosmetic: the link itself holds by id, the command can go on
            logger.warning(f'Discord name refresh KO [{e}]')
        else:
            User.discord.name = member.name
    return User
