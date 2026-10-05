# -*- coding: utf8 -*-

import asyncio
import discord

from loguru import logger
from discord.commands import option
from discord.ext import commands
from kubernetes import config, client
from kubernetes.stream import stream

from subcommands.infra._tools import K8S_REQUEST_TIMEOUT, log_pretty

NAMESPACE = 'singouins-databases'
# Max wait (seconds) for the exec'd script: stream() defaults to 60s and
# then silently returns a partial output. Must stay < 900 (Discord token)
EXEC_TIMEOUT = {
    'run': 600,
    'status': 60,
    }


async def pod_exec(command, timeout):
    # K8s calls run in a thread: the bot keeps running meanwhile
    pod = await asyncio.to_thread(
        client.CoreV1Api().list_namespaced_pod,
        NAMESPACE,
        label_selector="name=backup",
        _request_timeout=K8S_REQUEST_TIMEOUT,
        )

    start = asyncio.get_running_loop().time()
    exec_stdout = await asyncio.to_thread(
        stream,
        client.CoreV1Api().connect_get_namespaced_pod_exec,
        pod.items[0].metadata.name,
        NAMESPACE,
        command=command,
        stderr=True, stdin=False,
        stdout=True, tty=False,
        _request_timeout=timeout,
        )
    if asyncio.get_running_loop().time() - start >= timeout:
        exec_stdout += (
            f'\nlevel=warn | Stopped waiting after {timeout}s: '
            'output may be incomplete\n'
            )
    return exec_stdout


def backup(group_admin):
    @group_admin.command(
        description='[@Team role] Display backup information',
        default_permission=False,
        name='backup',
        )
    @commands.guild_only()  # Hides the command from the menu in DMs
    @commands.has_any_role('Team')
    @option(
        "action",
        description="Action to execute",
        choices=['status', 'run'],
        )
    async def backup(
        ctx,
        action: str,
    ):
        h = f'[#{ctx.channel.name}][{ctx.author.name}]'
        logger.info(f'{h} /{group_admin} backup {action}')

        await ctx.defer()  # To defer answer (default: 15min)

        try:
            config.load_kube_config("/etc/k8s/kubeconfig.yaml")
        except Exception as e:
            msg = f'K8s conf load KO [{e}]'
            logger.error(msg)
            embed = discord.Embed(
                description=msg,
                colour=discord.Colour.red()
                )
            await ctx.respond(embed=embed)
            return

        if action == 'run':
            try:
                logger.info(f'{h} ├──> K8s Query Starting')
                exec_stdout = await pod_exec(
                    "/etc/periodic/hourly/cron-backup-sh",
                    EXEC_TIMEOUT[action],
                    )
                logger.info(f'{h} ├──> K8s Query Ended')
            except Exception as e:
                msg = f'K8s pod_exec KO [{e}]'
                logger.error(msg)
                embed = discord.Embed(
                    description=msg,
                    colour=discord.Colour.red()
                    )
                await ctx.respond(embed=embed)
                return
            else:
                # One edit with all lines (not one per line: rate limits)
                content = ''.join(log_pretty(exec_stdout))
                await ctx.interaction.edit_original_response(
                    embed=discord.Embed(
                        title=f'K8s backup {action}',
                        description=f'```\n{content}```',
                        colour=discord.Colour.green()
                        )
                    )
        elif action == 'status':
            try:
                logger.info(f'{h} ├──> K8s Query Starting')
                exec_stdout = await pod_exec(
                    "/etc/periodic/daily/cron-status-sh",
                    EXEC_TIMEOUT[action],
                    )
                logger.info(f'{h} ├──> K8s Query Ended')
            except Exception as e:
                msg = f'K8s pod_exec KO [{e}]'
                logger.error(msg)
                embed = discord.Embed(
                    description=msg,
                    colour=discord.Colour.red()
                    )
                await ctx.respond(embed=embed)
                return
            else:
                # One edit with all lines (not one per line: rate limits)
                content = ''.join(log_pretty(exec_stdout))
                await ctx.interaction.edit_original_response(
                    embed=discord.Embed(
                        title=f'K8s backup {action}',
                        description=f'```\n{content}```',
                        colour=discord.Colour.green()
                        )
                    )

        logger.info(f'{h} └──> K8s Query OK')
        return
