#!/usr/bin/env python3
# -*- coding: utf8 -*-
"""
List or delete the application commands registered on Discord.

Without --delete, the matching commands are only listed (dry run).

Examples:
  ./delete.py                                 # list everything
  ./delete.py --name infra                    # list /infra, wherever it is
  ./delete.py --name infra --delete           # delete /infra, wherever it is
  ./delete.py --global-only --all --delete    # delete every global command
  ./delete.py --guild 1234 --name foo --name bar --delete
"""
import argparse
import asyncio
import discord
import os
import sys

# Discord variables
DISCORD_TOKEN = os.environ.get("SEP_DISCORD_TOKEN")


def parse_args():
    parser = argparse.ArgumentParser(
        description='List or delete Discord application commands',
        )
    parser.add_argument(
        '--name', action='append', default=[],
        help='Command name to match (repeatable)',
        )
    parser.add_argument(
        '--all', action='store_true',
        help='Match every command (needed for --delete without --name)',
        )
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument(
        '--global-only', action='store_true',
        help='Only look at global commands',
        )
    scope.add_argument(
        '--guild', type=int, action='append', default=[],
        help='Only look at this guild ID (repeatable)',
        )
    parser.add_argument(
        '--delete', action='store_true',
        help='Actually delete the matching commands (default: dry run)',
        )
    args = parser.parse_args()

    if args.delete and not args.name and not args.all:
        parser.error('--delete needs --name or --all')
    return args


def matches(command, args):
    return args.all or not args.name or command['name'] in args.name


async def process(label, commands, delete_one, args):
    selected = [c for c in commands if matches(c, args)]
    print(f'[{label}] {len(selected)}/{len(commands)} command(s) matched')
    for command in selected:
        action = 'Deleting' if args.delete else 'Found'
        print(f'  {action} /{command["name"]} (id:{command["id"]})')
        if args.delete:
            await delete_one(command['id'])


async def main(args):
    # HTTP only: no gateway connection, so no command sync is triggered
    bot = discord.Bot()
    try:
        await bot.login(DISCORD_TOKEN)
        app_id = (await bot.application_info()).id

        if not args.guild:
            commands = await bot.http.get_global_commands(app_id)
            await process(
                'global', commands,
                lambda cid: bot.http.delete_global_command(app_id, cid),
                args,
                )
        if args.global_only:
            return

        guild_ids = args.guild or [g.id async for g in bot.fetch_guilds()]
        for guild_id in guild_ids:
            commands = await bot.http.get_guild_commands(app_id, guild_id)
            await process(
                f'guild:{guild_id}', commands,
                lambda cid, gid=guild_id: bot.http.delete_guild_command(
                    app_id, gid, cid,
                    ),
                args,
                )
    finally:
        await bot.close()


if __name__ == '__main__':
    if not DISCORD_TOKEN:
        sys.exit('SEP_DISCORD_TOKEN is not set')
    asyncio.run(main(parse_args()))
