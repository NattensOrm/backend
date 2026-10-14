# -*- coding: utf8 -*-

import discord

from loguru import logger
from discord.ext import commands

from mongo.models.Creature import CreatureDocument
from mongo.models.User import UserDocument

# Squad/Korp ranks that make a Creature an actual member.
# 'Pending' (invited, not accepted yet) is deliberately left out.
MEMBER_RANKS = ('Leader', 'Member')


def grant(group_user, bot):
    @group_user.command(
        description='[@everyone] Update your Discord roles (Squad/Korp)',
        name='grant',
        )
    @commands.guild_only()  # Hides the command from the menu in DMs
    async def grant(
        ctx,
    ):
        h = f'[#{ctx.channel.name}][{ctx.author.name}]'
        logger.info(f'{h} /{group_user} grant')

        # Mongo queries + Discord role calls can outlast the 3s
        # interaction deadline: acknowledge first, answer afterwards
        await ctx.defer(ephemeral=True)

        # Get the User
        try:
            User = UserDocument.objects(discord__name=ctx.author.name).get()
        except UserDocument.DoesNotExist:
            logger.warning("UserDocument Query KO (404)")
            await ctx.respond(
                embed=discord.Embed(
                    description=f'Unknown Discord Name:`{ctx.author.name}` in DB',
                    colour=discord.Colour.orange(),
                    ),
                ephemeral=True,
                )
            return
        except UserDocument.MultipleObjectsReturned:
            logger.error(f'{h} ├──> Discord Name linked to several Users')
            await ctx.respond(
                embed=discord.Embed(
                    description=f'Discord Name:`{ctx.author.name}` linked to several Users in DB',
                    colour=discord.Colour.red(),
                    ),
                ephemeral=True,
                )
            return
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

        guild = ctx.guild

        # Get the Singouin role
        singouinrole = discord.utils.get(guild.roles, name='Singouins')
        if singouinrole is None:
            logger.error(f'{h} ├──> Role Singouins not found')
            await ctx.respond(
                embed=discord.Embed(
                    description='Discord get-role:Singouins KO (Role not found)',
                    colour=discord.Colour.red(),
                    ),
                ephemeral=True,
                )
            return
        # Add the Singouin role to the user
        try:
            if singouinrole not in ctx.author.roles:
                await ctx.author.add_roles(singouinrole)
        except Exception as e:
            await ctx.respond(
                embed=discord.Embed(
                    description=f'Discord add-role:Singouins KO\n[{e}]',
                    colour=discord.Colour.red(),
                    ),
                ephemeral=True,
                )
            return

        # Get the Singouin(s)
        # The QuerySet is lazy: list() runs the query inside the try
        try:
            Creatures = list(CreatureDocument.objects(account=User.id))
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

        if not Creatures:
            msg = f'No Singouins found in DB for `{ctx.author.name}`'
            logger.warning(msg)
            await ctx.respond(
                embed=discord.Embed(
                    description=msg,
                    colour=discord.Colour.orange(),
                    ),
                ephemeral=True,
                )
            return

        # Squad/Korp roles to add, by name (deduplicated across Creatures)
        roles = {}
        # Squad/Korp roles not found in the guild, reported in the final answer
        missing_roles = []
        for Creature in Creatures:
            for kind, membership in (('Korp', Creature.korp), ('Squad', Creature.squad)):
                # A Pending invitee is not a member yet: no role until it accepts
                if not membership.id or membership.rank not in MEMBER_RANKS:
                    continue
                name = f'{kind}-{membership.id}'
                if name in roles or name in missing_roles:
                    continue
                role = discord.utils.get(guild.roles, name=name)
                if role is None:
                    # Role not created yet (subtasks/channels.py): skip it
                    missing_roles.append(name)
                    logger.warning(f'{h} ├──> Role {name} not found')
                elif role not in ctx.author.roles:
                    roles[name] = role

        # Add the Squad/Korp roles to the user, in one API call
        if roles:
            try:
                await ctx.author.add_roles(*roles.values())
            except Exception as e:
                await ctx.respond(
                    embed=discord.Embed(
                        description=f"Discord add-role:{', '.join(roles)} KO\n[{e}]",
                        colour=discord.Colour.red(),
                        ),
                    ephemeral=True,
                    )
                return

        logger.info(f'{h} ├──> Query OK')
        if missing_roles:
            missing = ', '.join(f'`{name}`' for name in missing_roles)
            await ctx.respond(
                embed=discord.Embed(
                    description=(
                        "Discord & Squad/Korp grant :ok:\n"
                        f"Role(s) not found yet, try again later: {missing}"
                        ),
                    colour=discord.Colour.orange()
                    )
                )
        else:
            await ctx.respond(
                embed=discord.Embed(
                    description="Discord & Squad/Korp grant :ok:",
                    colour=discord.Colour.green()
                    )
                )
        logger.info(f'{h} └──> Answer sent')
