# -*- coding: utf8 -*-

import uuid
from unittest.mock import MagicMock, patch

import pytest

from mongo.models.Creature import CreatureDocument, CreatureKorp, CreatureSquad
from mongo.models.User import UserDocument
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
    # Flattened across calls: Singouins is added on its own, the
    # Squad/Korp roles together in a single add_roles(*roles) call
    return [role.name for call in ctx.author.add_roles.await_args_list for role in call.args]


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


async def test_grant_gives_korp_then_squad_role_to_korp_member(bot, make_ctx, get_callback, make_user, make_creature):  # noqa: E501
    # Regression test: the Korp role used to be looked up as
    # `Korp-{Creature.korp}` (the embedded document, not its id), so it was
    # never found and the Squad role was never granted either.
    user = make_user(discord={'name': 'tester', 'ack': False})
    korp_id = uuid.uuid4()
    squad_id = uuid.uuid4()
    make_creature(
        account=user.id,
        korp=CreatureKorp(id=korp_id, rank='Member'),
        squad=CreatureSquad(id=squad_id, rank='Member'),
        )

    group = bot.create_group(name='user', description='test')
    grant_command(group, bot)
    callback = get_callback(group, 'grant')

    roles = [
        _make_role('Singouins'),
        _make_role(f'Korp-{korp_id}'),
        _make_role(f'Squad-{squad_id}'),
        ]
    ctx = make_ctx(author_name='tester', guild_roles=roles)
    await callback(ctx)

    assert _granted_role_names(ctx) == ['Singouins', f'Korp-{korp_id}', f'Squad-{squad_id}']  # noqa: E501
    assert ctx.respond.call_count == 1


async def test_grant_skips_role_missing_from_guild(bot, make_ctx, get_callback, make_user, make_creature):  # noqa: E501
    # A Squad/Korp role not created yet in the guild must not be passed to
    # add_roles(None): it is skipped, reported, and the command completes.
    user = make_user(discord={'name': 'tester', 'ack': False})
    korp_id = uuid.uuid4()
    squad_id = uuid.uuid4()
    make_creature(
        account=user.id,
        korp=CreatureKorp(id=korp_id, rank='Member'),
        squad=CreatureSquad(id=squad_id, rank='Leader'),
        )

    group = bot.create_group(name='user', description='test')
    grant_command(group, bot)
    callback = get_callback(group, 'grant')

    # Korp role missing, Squad role present
    roles = [_make_role('Singouins'), _make_role(f'Squad-{squad_id}')]
    ctx = make_ctx(author_name='tester', guild_roles=roles)
    await callback(ctx)

    assert None not in [role for call in ctx.author.add_roles.await_args_list for role in call.args]  # noqa: E501
    assert _granted_role_names(ctx) == ['Singouins', f'Squad-{squad_id}']
    assert ctx.respond.call_count == 1
    embed = ctx.respond.await_args.kwargs['embed']
    assert f'Korp-{korp_id}' in embed.description


def _setup(bot):
    group = bot.create_group(name='user', description='test')
    grant_command(group, bot)
    return group


async def test_grant_defers_before_answering(bot, make_ctx, get_callback, make_user, make_creature):  # noqa: E501
    # The Mongo queries + role calls can outlast Discord's 3s deadline:
    # the interaction must be acknowledged before any work is done.
    user = make_user(discord={'name': 'tester', 'ack': False})
    make_creature(account=user.id)
    callback = get_callback(_setup(bot), 'grant')

    ctx = make_ctx(author_name='tester', guild_roles=[_make_role('Singouins')])
    ctx.defer.side_effect = lambda **kwargs: ctx.respond.assert_not_called()
    await callback(ctx)

    ctx.defer.assert_awaited_once_with(ephemeral=True)
    assert ctx.respond.call_count == 1


async def test_grant_discord_name_linked_to_several_users_responds_once(bot, make_ctx, get_callback, make_user):  # noqa: E501
    # Regression test: MultipleObjectsReturned used to fall through the
    # generic except, leaving `User` unbound -> NameError, no answer.
    make_user(discord={'name': 'tester', 'ack': True})
    make_user(discord={'name': 'tester', 'ack': True})
    callback = get_callback(_setup(bot), 'grant')

    ctx = make_ctx(author_name='tester', guild_roles=[_make_role('Singouins')])
    await callback(ctx)

    assert ctx.respond.call_count == 1
    assert 'several Users' in ctx.respond.await_args.kwargs['embed'].description
    ctx.author.add_roles.assert_not_awaited()


async def test_grant_user_query_failure_responds_once(bot, make_ctx, get_callback):
    callback = get_callback(_setup(bot), 'grant')

    ctx = make_ctx(author_name='tester', guild_roles=[_make_role('Singouins')])
    with patch.object(UserDocument, 'objects', MagicMock(side_effect=RuntimeError('boom'))):
        await callback(ctx)

    assert ctx.respond.call_count == 1
    assert 'boom' in ctx.respond.await_args.kwargs['embed'].description
    ctx.author.add_roles.assert_not_awaited()


async def test_grant_creature_query_failure_responds_once(bot, make_ctx, get_callback, make_user):  # noqa: E501
    # Regression test: the QuerySet is lazy, so the failure surfaces when it
    # is evaluated, not when objects() is called - it used to escape the
    # try, leaving `Creatures` unbound -> NameError, no answer.
    make_user(discord={'name': 'tester', 'ack': False})
    callback = get_callback(_setup(bot), 'grant')

    queryset = MagicMock()
    queryset.__iter__.side_effect = RuntimeError('boom')
    ctx = make_ctx(author_name='tester', guild_roles=[_make_role('Singouins')])
    with patch.object(CreatureDocument, 'objects', MagicMock(return_value=queryset)):
        await callback(ctx)

    assert ctx.respond.call_count == 1
    assert 'boom' in ctx.respond.await_args.kwargs['embed'].description


async def test_grant_singouins_role_missing_from_guild(bot, make_ctx, get_callback, make_user, make_creature):  # noqa: E501
    # Regression test: a missing Singouins role used to reach add_roles(None).
    user = make_user(discord={'name': 'tester', 'ack': False})
    make_creature(account=user.id)
    callback = get_callback(_setup(bot), 'grant')

    ctx = make_ctx(author_name='tester', guild_roles=[])
    await callback(ctx)

    ctx.author.add_roles.assert_not_awaited()
    assert ctx.respond.call_count == 1
    assert 'Singouins' in ctx.respond.await_args.kwargs['embed'].description


async def test_grant_shared_squad_role_added_once(bot, make_ctx, get_callback, make_user, make_creature):  # noqa: E501
    # Two Creatures of the same User in the same Squad: one role, one call.
    user = make_user(discord={'name': 'tester', 'ack': False})
    squad_id = uuid.uuid4()
    make_creature(account=user.id, squad=CreatureSquad(id=squad_id, rank='Leader'))
    make_creature(account=user.id, squad=CreatureSquad(id=squad_id, rank='Member'))
    callback = get_callback(_setup(bot), 'grant')

    roles = [_make_role('Singouins'), _make_role(f'Squad-{squad_id}')]
    ctx = make_ctx(author_name='tester', guild_roles=roles)
    await callback(ctx)

    assert _granted_role_names(ctx) == ['Singouins', f'Squad-{squad_id}']
    assert ctx.author.add_roles.await_count == 2


async def test_grant_skips_role_already_held(bot, make_ctx, get_callback, make_user, make_creature):  # noqa: E501
    user = make_user(discord={'name': 'tester', 'ack': False})
    squad_id = uuid.uuid4()
    make_creature(account=user.id, squad=CreatureSquad(id=squad_id, rank='Member'))
    callback = get_callback(_setup(bot), 'grant')

    roles = [_make_role('Singouins'), _make_role(f'Squad-{squad_id}')]
    ctx = make_ctx(author_name='tester', guild_roles=roles)
    ctx.author.roles = list(roles)
    await callback(ctx)

    ctx.author.add_roles.assert_not_awaited()
    assert ctx.respond.call_count == 1


async def test_grant_add_roles_failure_responds_once(bot, make_ctx, get_callback, make_user, make_creature):  # noqa: E501
    user = make_user(discord={'name': 'tester', 'ack': False})
    squad_id = uuid.uuid4()
    make_creature(account=user.id, squad=CreatureSquad(id=squad_id, rank='Member'))
    callback = get_callback(_setup(bot), 'grant')

    roles = [_make_role('Singouins'), _make_role(f'Squad-{squad_id}')]
    ctx = make_ctx(author_name='tester', guild_roles=roles)
    # Singouins goes through, the Squad/Korp batch is refused
    ctx.author.add_roles.side_effect = [None, RuntimeError('Forbidden')]
    await callback(ctx)

    assert ctx.respond.call_count == 1
    embed = ctx.respond.await_args.kwargs['embed']
    assert f'Squad-{squad_id}' in embed.description
    assert 'Forbidden' in embed.description
