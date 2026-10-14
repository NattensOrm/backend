# -*- coding: utf8 -*-

from unittest.mock import MagicMock, patch

import discord
import pytest
from loguru import logger
from mongoengine.queryset import QuerySet

from mongo.models.User import UserDocument
from subcommands.user.link import link as link_command
from utils.redis import LINK_ATTEMPTS_MAX, LINK_ATTEMPTS_WINDOW, link_attempts_incr
from variables import env_vars

CODE = 'K7Q4MZ2X'
CODE_KEY = f"{env_vars['API_ENV']}:discord:link_code:{{}}"
ATTEMPTS_KEY = f"{env_vars['API_ENV']}:discord:link_attempts:{{}}"


class FakeRedis:
    """ In-memory stand-in for the few Redis commands the link code helpers
    use (this suite runs without a live Redis, see scripts/test-local.sh).
    Pipelines run their queued commands in order on execute(). """
    def __init__(self):
        self.data = {}
        self.ttls = {}

    def get(self, key):
        value = self.data.get(key)
        return value.encode() if value is not None else None

    def set(self, key, value, ex=None):
        self.data[key] = str(value)
        self.ttls[key] = ex if ex is not None else -1

    def delete(self, key):
        self.ttls.pop(key, None)
        return int(self.data.pop(key, None) is not None)

    def incr(self, key):
        self.data[key] = str(int(self.data.get(key, 0)) + 1)
        self.ttls.setdefault(key, -1)
        return int(self.data[key])

    def ttl(self, key):
        return self.ttls.get(key, -2)

    def expire(self, key, seconds):
        self.ttls[key] = seconds

    def pipeline(self, transaction=True):
        fake = self

        class _Pipeline:
            def __init__(self):
                self.calls = []

            def __getattr__(self, name):
                return lambda *args, **kwargs: self.calls.append((name, args, kwargs))

            def execute(self):
                return [getattr(fake, name)(*args, **kwargs) for name, args, kwargs in self.calls]
        return _Pipeline()


@pytest.fixture
def fake_redis():
    fake = FakeRedis()
    with patch('utils.redis.r', fake):
        yield fake


@pytest.fixture
def issue_code(fake_redis):
    # What auth's POST /discord/link stores (auth/utils/token.py)
    def _issue_code(user, code=CODE):
        fake_redis.set(CODE_KEY.format(code), str(user.id), ex=600)
        return code
    return _issue_code


@pytest.fixture
def link_callback(bot, get_callback):
    group = bot.create_group(name='user', description='test')
    link_command(group, bot)
    return get_callback(group, 'link')


@pytest.fixture
def log_messages():
    messages = []
    sink_id = logger.add(messages.append, level='TRACE')
    yield messages
    logger.remove(sink_id)


def _ctx(make_ctx, *, author_name='tester', author_id=1234, channel_type=discord.ChannelType.private):  # noqa: E501
    ctx = make_ctx(author_name=author_name, channel_type=channel_type)
    ctx.author.id = author_id
    return ctx


def _description(ctx):
    # The command also runs in guild channels: every single answer must
    # stay private to the caller
    assert ctx.respond.await_args_list
    assert all(call.kwargs.get('ephemeral') is True for call in ctx.respond.await_args_list)
    return ctx.respond.await_args.kwargs['embed'].description


@pytest.mark.parametrize('channel_type', [discord.ChannelType.text, discord.ChannelType.private])
async def test_link_success_in_guild_channel_and_dm(link_callback, make_ctx, make_user, issue_code, fake_redis, channel_type):  # noqa: E501
    user = make_user(name='fresh@example.com', discord={'name': None, 'ack': False})
    code = issue_code(user)

    ctx = _ctx(make_ctx, author_name='new_discord_user', channel_type=channel_type)
    ctx.defer.side_effect = lambda **kwargs: ctx.respond.assert_not_called()
    await link_callback(ctx, 'k7q4-mz2x')

    ctx.defer.assert_awaited_once_with(ephemeral=True)
    assert ctx.respond.call_count == 1
    assert 'link :ok:' in _description(ctx)
    user.reload()
    assert user.discord.name == 'new_discord_user'
    assert user.discord.ack is True
    # Single use: consumed
    assert fake_redis.get(CODE_KEY.format(code)) is None


@pytest.mark.parametrize('typed', ['K7Q4MZ2X', 'k7q4mz2x', ' K7Q4-MZ2X ', 'K7Q4 MZ2X'])
async def test_link_code_case_dash_and_spaces_dont_matter(link_callback, make_ctx, make_user, issue_code, typed):  # noqa: E501
    user = make_user(discord={'name': None, 'ack': False})
    issue_code(user)

    ctx = _ctx(make_ctx)
    await link_callback(ctx, typed)

    assert 'link :ok:' in _description(ctx)
    user.reload()
    assert user.discord.name == 'tester'


async def test_link_code_is_single_use(link_callback, make_ctx, make_user, issue_code):
    user = make_user(discord={'name': None, 'ack': False})
    issue_code(user)
    await link_callback(_ctx(make_ctx, author_name='first'), CODE)

    ctx = _ctx(make_ctx, author_name='second', author_id=5678)
    await link_callback(ctx, CODE)

    assert 'already used' in _description(ctx)
    user.reload()
    assert user.discord.name == 'first'


async def test_link_unknown_code_leaves_db_untouched(link_callback, make_ctx, make_user, fake_redis):  # noqa: E501
    user = make_user(discord={'name': None, 'ack': False})

    ctx = _ctx(make_ctx)
    await link_callback(ctx, CODE)

    assert ctx.respond.call_count == 1
    assert 'Unknown, expired or already used' in _description(ctx)
    user.reload()
    assert user.discord.name is None


@pytest.mark.parametrize('typed', ['K7Q4', 'K7Q4MZ2XX', 'K0Q4MZ2X', 'someone@example.com'])
async def test_link_malformed_code_is_refused_without_lookup(link_callback, make_ctx, fake_redis, typed):  # noqa: E501
    ctx = _ctx(make_ctx)
    with patch('subcommands.user.link.link_code_consume') as consume:
        await link_callback(ctx, typed)

    consume.assert_not_called()
    assert ctx.respond.call_count == 1
    assert 'Code NotValid' in _description(ctx)


async def test_link_attempts_are_limited_per_discord_user(link_callback, make_ctx, make_user, issue_code, fake_redis):  # noqa: E501
    # Brute-force guard: past the limit, even a valid code is not looked up
    user = make_user(discord={'name': None, 'ack': False})
    for _ in range(LINK_ATTEMPTS_MAX):
        await link_callback(_ctx(make_ctx), 'AAAAAAAA')
    code = issue_code(user)

    ctx = _ctx(make_ctx)
    await link_callback(ctx, code)

    assert 'Too many attempts' in _description(ctx)
    user.reload()
    assert user.discord.name is None
    assert fake_redis.get(CODE_KEY.format(code)) is not None
    # The window expires: the counter always has a TTL
    assert fake_redis.ttl(ATTEMPTS_KEY.format(1234)) == LINK_ATTEMPTS_WINDOW

    # Another Discord user is not affected
    other = _ctx(make_ctx, author_name='other', author_id=5678)
    await link_callback(other, code)
    assert 'link :ok:' in _description(other)


def test_link_attempts_counter_gets_its_ttl_back(fake_redis):
    # A lost EXPIRE (crash between INCR and EXPIRE) must not lock out forever
    key = ATTEMPTS_KEY.format(1234)
    fake_redis.data[key] = '2'
    fake_redis.ttls[key] = -1

    assert link_attempts_incr(1234) == 3
    assert fake_redis.ttl(key) == LINK_ATTEMPTS_WINDOW


async def test_link_already_linked_to_caller_is_idempotent(link_callback, make_ctx, make_user, issue_code):  # noqa: E501
    user = make_user(discord={'name': 'tester', 'ack': True})
    issue_code(user)

    ctx = _ctx(make_ctx, author_name='tester')
    await link_callback(ctx, CODE)

    assert 'already done' in _description(ctx)
    user.reload()
    assert user.discord.name == 'tester'


async def test_link_replaces_link_to_another_discord_user(link_callback, make_ctx, make_user, issue_code):  # noqa: E501
    # The code proves the ownership: a hijacked (or stale) link is replaced,
    # that's how a player takes their account back
    user = make_user(discord={'name': 'hijacker', 'ack': True})
    issue_code(user)

    ctx = _ctx(make_ctx, author_name='owner')
    await link_callback(ctx, CODE)

    assert 'link :ok:' in _description(ctx)
    user.reload()
    assert user.discord.name == 'owner'


async def test_link_caller_already_linked_to_another_user_is_refused(link_callback, make_ctx, make_user, issue_code):  # noqa: E501
    # A 2nd link would make the Discord name match 2 Users, which breaks
    # every discord__name lookup (/user grant, /singouin ...)
    make_user(name='first@example.com', discord={'name': 'tester', 'ack': True})
    second = make_user(name='second@example.com', discord={'name': None, 'ack': False})
    issue_code(second)

    ctx = _ctx(make_ctx, author_name='tester')
    await link_callback(ctx, CODE)

    assert 'another Singouin account' in _description(ctx)
    second.reload()
    assert second.discord.name is None


async def test_link_code_of_deleted_user(link_callback, make_ctx, make_user, issue_code):
    user = make_user(discord={'name': None, 'ack': False})
    issue_code(user)
    user.delete()

    ctx = _ctx(make_ctx)
    await link_callback(ctx, CODE)

    assert ctx.respond.call_count == 1
    assert 'No User found' in _description(ctx)


async def test_link_redis_failure_responds_once(link_callback, make_ctx):
    broken = MagicMock()
    broken.pipeline.side_effect = RuntimeError('boom')

    ctx = _ctx(make_ctx)
    with patch('utils.redis.r', broken):
        await link_callback(ctx, CODE)

    assert ctx.respond.call_count == 1
    assert 'boom' in _description(ctx)


async def test_link_query_failure_responds_once(link_callback, make_ctx, make_user, issue_code):
    issue_code(make_user())

    ctx = _ctx(make_ctx)
    with patch.object(UserDocument, 'objects', MagicMock(side_effect=RuntimeError('boom'))):
        await link_callback(ctx, CODE)

    assert ctx.respond.call_count == 1
    assert 'boom' in _description(ctx)


async def test_link_update_failure_responds_once(link_callback, make_ctx, make_user, issue_code):
    user = make_user(discord={'name': None, 'ack': False})
    issue_code(user)

    ctx = _ctx(make_ctx)
    with patch.object(QuerySet, 'update_one', side_effect=RuntimeError('boom')):
        await link_callback(ctx, CODE)

    assert ctx.respond.call_count == 1
    assert 'link KO' in _description(ctx)
    user.reload()
    assert user.discord.name is None


async def test_link_never_logs_the_code(link_callback, make_ctx, make_user, issue_code, log_messages):  # noqa: E501
    issue_code(make_user(discord={'name': None, 'ack': False}))

    await link_callback(_ctx(make_ctx), 'K7Q4-MZ2X')
    await link_callback(_ctx(make_ctx), 'AAAA-AAAA')

    assert log_messages
    assert not [m for m in log_messages if 'K7Q4' in m or 'AAAA' in m]
