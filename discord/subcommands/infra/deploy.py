# -*- coding: utf8 -*-

import asyncio
import discord

from kubernetes import client
from loguru import logger
from discord.commands import option
from discord.ext import commands
from kubernetes import config

from subcommands.infra._tools import log_pretty

#
# Globals used to build the ENV VAR for the batch
#
CUST_OUTPUT_PATH = '/var/www/websites'
CUST_DOMAIN = 'singouins.com'
CUST_SUBDOMAIN = 'games'

#
# Timeouts (seconds)
#
# K8s fails the Job after this, retries and Pending time included
JOB_DEADLINE = 600
# K8s deletes the finished Job after this, if the bot did not
JOB_TTL = 300
# Bot stops waiting after this (must stay < 900: Discord token lifetime)
BOT_TIMEOUT = JOB_DEADLINE + 60


def api_error(e):
    # str(ApiException) also dumps HTTP headers and body: too verbose
    if isinstance(e, client.ApiException):
        return f'K8s API error {e.status} {e.reason}'
    return str(e)[:200]


def deploy(group_admin):
    @group_admin.command(
        description='[@Team role] Deploy latest Front build',
        default_permission=False,
        name='deploy',
        )
    @commands.guild_only()  # Hides the command from the menu in DMs
    @commands.has_any_role('Team')
    @option(
        "env",
        description="Target environment",
        choices=['DEV', 'PROD'],
        )
    async def deploy(
        ctx,
        env: str,
    ):
        h = f'[#{ctx.channel.name}][{ctx.author.name}]'
        logger.info(f'{h} /{group_admin} deploy {env}')

        await ctx.defer()  # To defer answer (default: 15min)

        env = env.lower()
        namespace = 'singouins-networking'

        if env == 'dev':
            output_folder = f'{CUST_SUBDOMAIN}.dev.{CUST_DOMAIN}'
        else:
            output_folder = f'{CUST_SUBDOMAIN}.{CUST_DOMAIN}'

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

        try:
            logger.info(f'{h} ├──> K8s Query Starting')

            app_name = 'front-deployer'
            pod_name = app_name
            # One Job per env: DEV and PROD deploys can run side by side
            job_name = f'{app_name}-{env}-job'
            pod_template = client.V1PodTemplateSpec(
                spec=client.V1PodSpec(
                    restart_policy="Never",
                    containers=[
                        client.V1Container(
                            image="alpine/git:2.36.2",
                            name=pod_name,
                            image_pull_policy="IfNotPresent",
                            # Same uid as the files already on the PVC
                            # (no fsGroup: it would chown the whole volume)
                            security_context=client.V1SecurityContext(
                                run_as_user=1000,
                                run_as_group=1000,
                                run_as_non_root=True,
                                allow_privilege_escalation=False,
                                ),
                            volume_mounts=[
                                client.V1VolumeMount(name="websites", mount_path=CUST_OUTPUT_PATH),
                                client.V1VolumeMount(name="deployer-sh", mount_path='/code'),
                                ],
                            command=["/code/job-front-deployer.sh"],
                            env=[
                                # uid 1000 has no home in the image
                                client.V1EnvVar(name='HOME', value='/tmp'),
                                client.V1EnvVar(name='CUST_GIT_BRANCH', value=f'build-{env}'),
                                client.V1EnvVar(name='CUST_OUTPUT_PATH', value=CUST_OUTPUT_PATH),
                                client.V1EnvVar(name='CUST_OUTPUT_FOLDER', value=output_folder),
                                client.V1EnvVar(
                                    name='CUST_GIT_QUIET',
                                    value_from=client.V1EnvVarSource(
                                        secret_key_ref=client.V1SecretKeySelector(  # noqa: E501
                                            name='git-secret',
                                            key='git-angular-quiet',
                                            )
                                        )
                                    ),
                                client.V1EnvVar(
                                    name='CUST_GIT_REPO',
                                    value_from=client.V1EnvVarSource(
                                        secret_key_ref=client.V1SecretKeySelector(  # noqa: E501
                                            name='git-secret',
                                            key='git-angular-repo',
                                            )
                                        )
                                    ),
                                client.V1EnvVar(
                                    name='CUST_GIT_USER',
                                    value_from=client.V1EnvVarSource(
                                        secret_key_ref=client.V1SecretKeySelector(  # noqa: E501
                                            name='git-secret',
                                            key='git-angular-user',
                                            )
                                        )
                                    ),
                                client.V1EnvVar(
                                    name='CUST_GIT_TOKEN',
                                    value_from=client.V1EnvVarSource(
                                        secret_key_ref=client.V1SecretKeySelector(  # noqa: E501
                                            name='git-secret',
                                            key='git-angular-token',
                                            )
                                        )
                                    ),
                                ],
                            )
                        ],
                    volumes=[
                        client.V1Volume(
                            name='websites',
                            persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(  # noqa: E501
                                claim_name='nginx-www-pvc',
                                ),
                            ),
                        client.V1Volume(
                            name='deployer-sh',
                            config_map=client.V1ConfigMapVolumeSource(
                                items=[
                                    client.V1KeyToPath(
                                        key='deployer-sh',
                                        path='job-front-deployer.sh',
                                        mode=493,  # == 0755 permission
                                        )
                                    ],
                                name='deployer-configmap',
                                ),
                            ),
                        ],
                    ),
                metadata=client.V1ObjectMeta(
                    namespace=namespace,
                    name=pod_name,
                    labels={
                        "name": app_name,
                        "env": env,
                        },
                    ),
                )

            job = client.V1Job(
                api_version="batch/v1",
                kind="Job",
                metadata=client.V1ObjectMeta(
                    namespace=namespace,
                    name=job_name,
                    ),
                spec=client.V1JobSpec(
                    backoff_limit=4,
                    active_deadline_seconds=JOB_DEADLINE,
                    ttl_seconds_after_finished=JOB_TTL,
                    parallelism=1,
                    completions=1,
                    template=pod_template,
                    ),
                )

            api_response = client.BatchV1Api().create_namespaced_job(
                body=job,
                namespace=namespace,
                )
            logger.debug(f'{h} ├──> K8s Query Ended')
        except client.ApiException as e:
            if e.status != 409:
                logger.error(f'{h} └──> K8s Query KO [{e}]')
                description = f'Command aborted: {api_error(e)}'
            else:
                # The Job of this env still exists: running, or finished
                # but not deleted yet (JOB_TTL cleans it up)
                logger.warning(f'{h} └──> K8s Query KO - Job already exists')
                description = (
                    f'Command aborted: a deploy is already running for {env} '
                    f'(or its Job awaits cleanup, up to {JOB_TTL}s)'
                    )
            embed = discord.Embed(
                description=description,
                colour=discord.Colour.red()
            )
            await ctx.respond(embed=embed)
            return
        except Exception as e:
            logger.error(f'{h} └──> K8s Query KO [{e}]')
            embed = discord.Embed(
                description='Command aborted: K8s Query KO',
                colour=discord.Colour.red()
            )
            await ctx.respond(embed=embed)
            return
        else:
            # Job started
            description = '>> Job starting'
            await ctx.interaction.edit_original_response(
                embed=discord.Embed(
                    title=f'K8s deploy [{env}]',
                    description=description,
                    colour=discord.Colour.blue()
                    )
                )
            logger.info(f'{h} └──> K8s Query OK - Job created')

            deadline = asyncio.get_running_loop().time() + BOT_TIMEOUT
            job_completed = False
            while not job_completed:
                description = description + '.'
                await ctx.interaction.edit_original_response(
                    embed=discord.Embed(
                        title=f'K8s deploy [{env}]',
                        description=description,
                        colour=discord.Colour.blue()
                        )
                    )

                finished = {}
                try:
                    api_response = client.BatchV1Api().read_namespaced_job_status(
                        name=job_name,
                        namespace=namespace,
                        )
                except Exception as e:
                    if getattr(e, 'status', None) == 404:
                        # Deleted outside of the bot: nothing left to watch
                        logger.error(f'{h} └──> K8s Query KO - Job not found')
                        description += '\n>> Job not found (deleted outside the bot?)'
                        await ctx.interaction.edit_original_response(
                            embed=discord.Embed(
                                title=f'K8s deploy [{env}]',
                                description=description,
                                colour=discord.Colour.red()
                                )
                            )
                        break
                    # Transient: we retry on next tick, BOT_TIMEOUT still applies
                    logger.warning(f'{h} ├──> K8s Query KO [{api_error(e)}]')
                else:
                    # status.failed is set as soon as one pod fails, even while
                    # the Job is still retrying: only these conditions are final
                    finished = {
                        c.type: c
                        for c in api_response.status.conditions or []
                        if c.type in ('Complete', 'Failed') and c.status == 'True'
                        }
                # Safety net if K8s never reports a final state
                timed_out = asyncio.get_running_loop().time() > deadline

                if finished or timed_out:
                    job_completed = True

                    if not finished:
                        logger.warning('K8s Query OK - Job timed out')
                        description += (
                            f'\n>> Job timed out (no result after {BOT_TIMEOUT}s)'
                            )
                        colour = discord.Colour.red()
                    elif 'Failed' in finished:
                        reason = finished['Failed'].reason
                        logger.warning(f'K8s Query OK - Job failed [{reason}]')
                        description += f'\n>> Job failed ({reason})'
                        colour = discord.Colour.red()
                    else:
                        logger.trace('K8s Query OK - Job completed')
                        description += '\n>> Job completed'
                        colour = discord.Colour.green()

                    await ctx.interaction.edit_original_response(
                        embed=discord.Embed(
                            title=f'K8s deploy [{env}]',
                            description=description,
                            colour=colour
                            )
                        )

                    log = None
                    log_error = None
                    try:
                        pod = client.CoreV1Api().list_namespaced_pod(
                            namespace,
                            # Set by K8s on the pods of this Job only
                            label_selector=f"job-name={job_name}",
                            )
                        if pod.items:
                            # With retries there is one pod per attempt
                            latest = max(
                                pod.items,
                                key=lambda p: p.metadata.creation_timestamp,
                                )
                            log = client.CoreV1Api().read_namespaced_pod_log(
                                name=latest.metadata.name,
                                since_seconds=1728000,
                                namespace=namespace,
                                )
                            logger.trace(log)
                        else:
                            log_error = 'no pod found'
                            logger.warning('K8s Query OK - Logs NotFound')
                    except Exception as e:
                        log_error = api_error(e)
                        logger.error(f'K8s Query KO [{e}]')

                    if log is None:
                        description += f'\n>> Job logs: unavailable ({log_error})'
                    elif not log.strip():
                        logger.trace('K8s Query OK - Logs empty')
                        description += '\n>> Job logs: none (no output)'
                    else:
                        logger.trace('K8s Query OK - Logs fetched')
                        description += '\n>> Job logs:\n```'

                        for line in log_pretty(log):
                            description += line
                            await ctx.interaction.edit_original_response(
                                embed=discord.Embed(
                                    title=f'K8s deploy [{env}]',
                                    description=f'{description}```',
                                    colour=colour
                                    )
                                )
                        description += '```'

                    # Now we delete the Job
                    try:
                        client.BatchV1Api().delete_namespaced_job(
                            name=job_name,
                            namespace=namespace,
                            body=client.V1DeleteOptions(
                                propagation_policy='Foreground',
                                grace_period_seconds=0,
                                ),
                            )
                    except Exception as e:
                        if getattr(e, 'status', None) == 404:
                            # Already gone (TTL, or deleted by hand)
                            description += '\n>> Job already deleted'
                        else:
                            logger.error(f'K8s Query KO [{e}]')
                            description += (
                                f'\n>> Job deletion failed ({api_error(e)}), '
                                'K8s will clean it up'
                                )
                    else:
                        description += '\n>> Job deleting'
                    await ctx.interaction.edit_original_response(
                        embed=discord.Embed(
                            title=f'K8s deploy [{env}]',
                            description=description,
                            colour=colour
                            )
                        )
                await asyncio.sleep(1)
            logger.trace('K8s Pods Query OK')

        logger.info(f'{h} └──> K8s Query OK')
        return
