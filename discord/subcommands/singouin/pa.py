# -*- coding: utf8 -*-

import discord

from discord.commands import option
from discord.ext import commands
from loguru import logger

from mongo.models.Creature import CreatureDocument
from mongo.models.Instance import InstanceDocument

from subcommands.singouin._autocomplete import get_mysingouins_list
from subcommands.singouin._tools import creature_sprite

from utils.redis import get_pa


def pa(group_singouin):
    @group_singouin.command(
        description=(
            '[@Singouins role] '
            'Display your Singouin Action Points (PA)'
            ),
        default_permission=False,
        name='pa',
        )
    @commands.has_any_role('Singouins')
    @option(
        "singouinuuid",
        description="Singouin ID",
        autocomplete=get_mysingouins_list
        )
    async def pa(
        ctx,
        singouinuuid: str,
    ):
        h = f'[#{ctx.channel.name}][{ctx.author.name}]'
        logger.info(f'{h} /{group_singouin} pa {singouinuuid}')

        file = None

        try:
            Creature = CreatureDocument.objects(_id=singouinuuid).get()

            embed = discord.Embed(
                title=Creature.name,
                colour=discord.Colour.blue()
            )

            # Designer ruling: outside an Instance there are no PA at all (no Redis read).
            # PA regenerate at the pace of the Instance tick: red 1 PA per tick, blue per 2.
            tick = None
            if Creature.instance:
                try:
                    tick = InstanceDocument.objects(_id=Creature.instance).get().tick
                except InstanceDocument.DoesNotExist:
                    logger.warning(f'{h} ├──> InstanceDocument Query KO (404): no PA')

            if tick is None:
                embed.description = 'Not in an Instance: no PA'
                logger.info(f'{h} ├──> Singouin-PA: not in an Instance')
            else:
                PA = get_pa(creatureuuid=singouinuuid, tick=tick)

                redbar    = PA['red']['pa'] * ':red_square:'
                redbar   += (16 - PA['red']['pa']) * ':white_large_square:'
                bluebar   = PA['blue']['pa'] * ':blue_square:'
                bluebar  += (8 - PA['blue']['pa']) * ':white_large_square:'

                embed.add_field(
                    name='PA Count:',
                    value=(
                        f"> {redbar} ({PA['red']['pa']}/16)\n"
                        f"> :clock1: : {PA['red']['ttnpa']}s \n"
                        f"▬▬\n"
                        f"> {bluebar} ({PA['blue']['pa']}/8)\n"
                        f"> :clock1: : {PA['blue']['ttnpa']}s"
                        ),
                    inline=False,
                    )

                # We check if we have a sprite to add as thumbnail
                if creature_sprite(Creature):
                    file = discord.File(f'/tmp/{Creature.id}.png', filename=f'{Creature.id}.png')
                    embed.set_thumbnail(url=f'attachment://{Creature.id}.png')
                logger.info(f'{h} ├──> Singouin-PA Query OK')
        except Exception as e:
            description = f'Singouin-PA Query KO [{e}]'
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
                await ctx.respond(embed=embed, ephemeral=True, file=file)
            except Exception as e:
                logger.error(f'{h} └──> Answer send KO [{e}]')
