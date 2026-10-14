# -*- coding: utf8 -*-

import discord

from loguru import logger
from discord.commands import option

from mongo.models.User import UserDocument, UserDiscord
from mongo.utils import utcnow
from utils.redis import (
    LINK_ATTEMPTS_MAX,
    LINK_ATTEMPTS_WINDOW,
    LINK_CODE_ALPHABET,
    LINK_CODE_LENGTH,
    link_attempts_incr,
    link_code_consume,
    )


def _normalize(code: str) -> str | None:
    """ 'k7q4-mz2x ' -> 'K7Q4MZ2X', or None if it can't be a link code. """
    code = code.strip().upper().replace('-', '').replace(' ', '')
    if len(code) != LINK_CODE_LENGTH or not set(code) <= set(LINK_CODE_ALPHABET):
        return None
    return code


def link(group_user, bot):
    @group_user.command(
        description='[@everyone] Link your Singouin with Discord',
        name='link',
        )
    @option(
        "code",
        description="Link code (Generated in the game, valid 10 minutes)",
        )
    async def link(
        ctx,
        code: str,
    ):
        # The code is a secret: it is never written to the logs.
        # Every answer is ephemeral, so the command is fine in a guild channel.
        if ctx.channel.type is discord.ChannelType.private:
            h = f'[#{ctx.channel.type}][{ctx.author.name}]'
        else:
            h = f'[#{ctx.channel.name}][{ctx.author.name}]'
        logger.info(f'{h} /{group_user} link')

        # Redis + Mongo queries: acknowledge first, answer afterwards
        await ctx.defer(ephemeral=True)

        # Being logged in the game is the ownership proof, the code carries
        # it over here: it must not be guessable, hence the attempts limit
        try:
            attempts = link_attempts_incr(ctx.author.id)
        except Exception as e:
            logger.error(f'{h} └──> Redis Query KO [{e}]')
            await ctx.respond(
                embed=discord.Embed(
                    description=f'Redis Query KO\n[{e}]',
                    colour=discord.Colour.red(),
                    ),
                ephemeral=True,
                )
            return

        if attempts > LINK_ATTEMPTS_MAX:
            logger.warning(f'{h} └──> Too many attempts ({attempts})')
            await ctx.respond(
                embed=discord.Embed(
                    description=(
                        f'Too many attempts, '
                        f'retry in {LINK_ATTEMPTS_WINDOW // 60} minutes'
                        ),
                    colour=discord.Colour.orange(),
                    ),
                ephemeral=True,
                )
            return

        normalized = _normalize(code)
        if normalized is None:
            logger.debug(f'{h} └──> Code malformed')
            await ctx.respond(
                embed=discord.Embed(
                    description=(
                        'Registration KO: Code NotValid\n'
                        f'Expected {LINK_CODE_LENGTH} characters, like `K7Q4-MZ2X`'
                        ),
                    colour=discord.Colour.red(),
                    ),
                ephemeral=True,
                )
            return

        try:
            useruuid = link_code_consume(normalized)
        except Exception as e:
            logger.error(f'{h} └──> Redis Query KO [{e}]')
            await ctx.respond(
                embed=discord.Embed(
                    description=f'Redis Query KO\n[{e}]',
                    colour=discord.Colour.red(),
                    ),
                ephemeral=True,
                )
            return

        if useruuid is None:
            logger.debug(f'{h} └──> Code NotFound')
            await ctx.respond(
                embed=discord.Embed(
                    description=(
                        'Unknown, expired or already used code\n'
                        'Generate a new one in the game'
                        ),
                    colour=discord.Colour.orange(),
                    ),
                ephemeral=True,
                )
            return

        try:
            User = UserDocument.objects(pk=useruuid).first()
            Linked = UserDocument.objects(
                discord__name=ctx.author.name,
                pk__ne=useruuid,
                ).first()
        except Exception as e:
            logger.error(f'{h} └──> MongoDB Query KO [{e}]')
            await ctx.respond(
                embed=discord.Embed(
                    description=f'MongoDB Query KO\n[{e}]',
                    colour=discord.Colour.red(),
                    ),
                ephemeral=True,
                )
            return

        if User is None:
            # Account deleted after the code was issued
            logger.warning(f'{h} └──> User NotFound')
            await ctx.respond(
                embed=discord.Embed(
                    description='No User found in DB for this code',
                    colour=discord.Colour.red(),
                    ),
                ephemeral=True,
                )
            return

        if User.discord.name == ctx.author.name:
            logger.debug(f'{h} └──> Link already done')
            await ctx.respond(
                embed=discord.Embed(
                    description='Discord & Singouin link already done',
                    colour=discord.Colour.green(),
                    ),
                ephemeral=True,
                )
            return

        # One Discord user <-> one User: every discord__name lookup relies on it
        if Linked is not None:
            logger.warning(f'{h} └──> Discord user already linked to another User')
            await ctx.respond(
                embed=discord.Embed(
                    description='Your Discord user is already linked to another Singouin account',
                    colour=discord.Colour.red(),
                    ),
                ephemeral=True,
                )
            return

        # The code proves the account ownership: a previous link to another
        # Discord user (stale, or hijacked) is replaced
        if User.discord.name:
            logger.info(f'{h} ├──> Replacing a previous Discord link')

        try:
            UserDocument.objects(pk=User.pk).update_one(
                set__discord=UserDiscord(name=ctx.author.name, ack=True),
                set__updated=utcnow(),
                )
        except Exception as e:
            logger.error(f'{h} └──> MongoDB Update KO [{e}]')
            await ctx.respond(
                embed=discord.Embed(
                    description=f'Discord & Singouin link KO [{e}]',
                    colour=discord.Colour.red(),
                    ),
                ephemeral=True,
                )
            return

        logger.info(f'{h} ├──> Query OK')
        await ctx.respond(
            embed=discord.Embed(
                description="Discord & Singouin link :ok: ",
                colour=discord.Colour.green(),
                ),
            ephemeral=True,
            )
        logger.info(f'{h} └──> Answer sent')
