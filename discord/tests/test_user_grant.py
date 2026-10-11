# -*- coding: utf8 -*-

import uuid
from unittest.mock import MagicMock

import pytest

from mongo.models.Creature import CreatureKorp, CreatureSquad
from subcommands.user.grant import grant as grant_command


async def test_grant_responds_once_regardless_of_creature_count(bot, make_ctx, get_callback, make_user, make_creature):  # noqa: E501
    # Regression test: the success response used to live inside the
    # `for Creature in Creatures` loop, so a user with 2+ creatures would
    # trigger a second ctx.respond() and blow up on an already-acknowledged
    # interaction. It must fire exactly once, after the loop.
    user = make_user(discord={'name': 'tester', 'ack': False})
    make_creature(account=user.id)
    make_creature(account=user.id)

    group = bot.create_group(name='user', description='test')
    grant_command(group, bot)
    callback = get_callback(group, 'grant')

    ctx = make_ctx(author_name='tester')
    await callback(ctx)

    assert ctx.respond.call_count == 1


async def test_grant_unknown_discord_user_responds_once(bot, make_ctx, get_callback):
    group = bot.create_group(name='user', description='test')
    grant_command(group, bot)
    callback = get_callback(group, 'grant')

    ctx = make_ctx(author_name='not-in-db')
    await callback(ctx)

    assert ctx.respond.call_count == 1


def _make_role(name):
    role = MagicMock()
    role.name = name
    return role


def _granted_role_names(ctx):
    return [call.args[0].name for call in ctx.author.add_roles.await_args_list]


@pytest.mark.parametrize('rank', ['Leader', 'Member'])
async def test_grant_gives_squad_role_to_squad_members(bot, make_ctx, get_callback, make_user, make_creature, rank):  # noqa: E501
    user = make_user(discord={'name': 'tester', 'ack': False})
    squad_id = uuid.uuid4()
    make_creature(account=user.id, squad=CreatureSquad(id=squad_id, rank=rank))

    group = bot.create_group(name='user', description='test')
    grant_command(group, bot)
    callback = get_callback(group, 'grant')

    roles = [_make_role('Singouins'), _make_role(f'Squad-{squad_id}')]
    ctx = make_ctx(author_name='tester', guild_roles=roles)
    await callback(ctx)

    assert _granted_role_names(ctx) == ['Singouins', f'Squad-{squad_id}']
    assert ctx.respond.call_count == 1


async def test_grant_skips_squad_role_for_pending_invitee(bot, make_ctx, get_callback, make_user, make_creature):  # noqa: E501
    # Ruling: a Pending invitee (invited, not accepted yet) is not a member,
    # so it must not get the Squad role (and channel) before it accepts.
    user = make_user(discord={'name': 'tester', 'ack': False})
    squad_id = uuid.uuid4()
    make_creature(account=user.id, squad=CreatureSquad(id=squad_id, rank='Pending'))

    group = bot.create_group(name='user', description='test')
    grant_command(group, bot)
    callback = get_callback(group, 'grant')

    roles = [_make_role('Singouins'), _make_role(f'Squad-{squad_id}')]
    ctx = make_ctx(author_name='tester', guild_roles=roles)
    await callback(ctx)

    assert _granted_role_names(ctx) == ['Singouins']
    assert ctx.respond.call_count == 1


async def test_grant_skips_korp_role_for_pending_invitee(bot, make_ctx, get_callback, make_user, make_creature):  # noqa: E501
    user = make_user(discord={'name': 'tester', 'ack': False})
    make_creature(account=user.id, korp=CreatureKorp(id=uuid.uuid4(), rank='Pending'))

    group = bot.create_group(name='user', description='test')
    grant_command(group, bot)
    callback = get_callback(group, 'grant')

    ctx = make_ctx(author_name='tester', guild_roles=[_make_role('Singouins')])
    await callback(ctx)

    assert _granted_role_names(ctx) == ['Singouins']
    assert ctx.respond.call_count == 1
