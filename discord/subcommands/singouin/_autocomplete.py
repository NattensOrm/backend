# -*- coding: utf8 -*-

import discord

from loguru import logger

from mongo.models.Creature import CreatureDocument
from utils.users import linked_user


async def get_mysingouins_list(ctx: discord.AutocompleteContext):
    db_list = []
    try:
        # By Discord id (see utils/users.py)
        User = linked_user(ctx.interaction.user)
        if User is None:
            logger.warning("UserDocument Query KO (404)")
            return db_list
        Creatures = CreatureDocument.objects(account=User.id)
        for Creature in Creatures:
            db_list.append(
                discord.OptionChoice(Creature.name, value=str(Creature.id))
                )
    except Exception as e:
        logger.error(f'MongoDB Query KO [{e}]')
    return db_list
