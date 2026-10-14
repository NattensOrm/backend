# -*- coding: utf8 -*-

import discord

from discord.ext import commands
from loguru import logger

from mongo.models.Creature import CreatureDocument
from utils.users import linked_user


def show(group_singouin, bot):
    @group_singouin.command(
        description=(
            '[@Singouins role] '
            'Show your Singouin(s) informations'
            ),
        name='show',
        )
    @commands.has_any_role('Singouins')
    async def show(
        ctx,
    ):
        h = f'[#{ctx.channel.name}][{ctx.author.name}]'
        logger.info(f'{h} /{group_singouin} show')

        emojiRace = [
            discord.utils.get(bot.emojis, name='raceC'),
            discord.utils.get(bot.emojis, name='raceG'),
            discord.utils.get(bot.emojis, name='raceM'),
            discord.utils.get(bot.emojis, name='raceO'),
            ]

        # Get the User, by Discord id (see utils/users.py)
        try:
            User = linked_user(ctx.author)
        except Exception as e:
            logger.error(f'MongoDB Query KO [{e}]')
            await ctx.respond(
                embed=discord.Embed(
                    description=f'MongoDB Query KO\n[{e}]',
                    colour=discord.Colour.red(),
                    ),
                ephemeral=True,
                )
            return

        if User is None:
            msg = 'Your Discord user is not linked to a Singouin account yet'
            logger.trace(msg)
            await ctx.respond(
                embed=discord.Embed(
                    description=f'{msg}\nUse `/user link` with a code generated in the game',
                    colour=discord.Colour.orange(),
                    ),
                ephemeral=True,
                )
            return

        try:
            Creatures = CreatureDocument.objects(account=User.id)

            mydesc = ''
            for Creature in Creatures:
                emojiMyRace = emojiRace[Creature.race - 1]
                mydesc += (
                    f"{emojiMyRace} "
                    f"`{Creature.name}` "
                    f"| Level:{Creature.level}\n"
                    )

            embed = discord.Embed(
                title='Your Singouins:',
                description=mydesc,
                colour=discord.Colour.blue()
            )
            logger.info(f'{h} ├──> Singouin-List Query OK')
        except Exception as e:
            description = f'Singouin-List Query KO [{e}]'
            logger.error(f'{h} └──> {description}')
            await ctx.respond(
                embed=discord.Embed(
                    description=description,
                    colour=discord.Colour.red(),
                    ),
                ephemeral=True,
                )
            return
        else:
            try:
                await ctx.respond(embed=embed, ephemeral=True)
                logger.info(f'{h} └──> Answer send OK')
            except Exception as e:
                logger.info(f'{h} └──> Answer send KO [{e}]')
