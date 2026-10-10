# -*- coding: utf8 -*-

import uuid

from mongo.models.Satchel import SatchelDocument
from subcommands.bazaar.ammo import ammo as ammo_command


async def test_sell_updates_balance_and_ammo_count(bot, make_ctx, get_callback, make_satchel):
    singouin_id = uuid.uuid4()
    satchel = make_satchel(_id=singouin_id, ammo={'cal22': 20}, currency={'banana': 0})

    group = bot.create_group(name='bazaar', description='test')
    ammo_command(group, bot)
    callback = get_callback(group, 'ammo')

    ctx = make_ctx()
    await callback(ctx, str(singouin_id), 'Sell', 'cal22')

    assert ctx.respond.call_count == 1
    satchel.reload()
    # price 0.1/unit * 10 units == 1
    assert satchel.currency.banana == 1
    assert satchel.ammo.cal22 == 10


async def test_buy_updates_balance_and_ammo_count(bot, make_ctx, get_callback, make_satchel):
    singouin_id = uuid.uuid4()
    satchel = make_satchel(_id=singouin_id, ammo={'cal22': 0}, currency={'banana': 100})

    group = bot.create_group(name='bazaar', description='test')
    ammo_command(group, bot)
    callback = get_callback(group, 'ammo')

    ctx = make_ctx()
    await callback(ctx, str(singouin_id), 'Buy', 'cal22')

    assert ctx.respond.call_count == 1
    satchel.reload()
    assert satchel.currency.banana == 99
    assert satchel.ammo.cal22 == 10


async def test_satchel_not_found_responds_once(bot, make_ctx, get_callback):
    group = bot.create_group(name='bazaar', description='test')
    ammo_command(group, bot)
    callback = get_callback(group, 'ammo')

    ctx = make_ctx()
    await callback(ctx, str(uuid.uuid4()), 'Sell', 'cal22')

    assert ctx.respond.call_count == 1


async def test_buy_with_insufficient_balance_is_rejected(bot, make_ctx, get_callback, make_satchel):  # noqa: E501
    singouin_id = uuid.uuid4()
    satchel = make_satchel(_id=singouin_id, ammo={'cal22': 0}, currency={'banana': 0})

    group = bot.create_group(name='bazaar', description='test')
    ammo_command(group, bot)
    callback = get_callback(group, 'ammo')

    ctx = make_ctx()
    await callback(ctx, str(singouin_id), 'Buy', 'cal22')

    assert ctx.respond.call_count == 1
    satchel.reload()
    assert satchel.currency.banana == 0
    assert satchel.ammo.cal22 == 0


async def test_sell_more_than_owned_is_rejected(bot, make_ctx, get_callback, make_satchel):
    singouin_id = uuid.uuid4()
    satchel = make_satchel(_id=singouin_id, ammo={'cal22': 0}, currency={'banana': 0})

    group = bot.create_group(name='bazaar', description='test')
    ammo_command(group, bot)
    callback = get_callback(group, 'ammo')

    ctx = make_ctx()
    await callback(ctx, str(singouin_id), 'Sell', 'cal22')

    assert ctx.respond.call_count == 1
    satchel.reload()
    assert satchel.ammo.cal22 == 0
    assert satchel.currency.banana == 0


async def test_sell_with_under_ten_in_stock_is_rejected(bot, make_ctx, get_callback, make_satchel):  # noqa: E501
    singouin_id = uuid.uuid4()
    satchel = make_satchel(_id=singouin_id, ammo={'cal22': 9}, currency={'banana': 3})

    group = bot.create_group(name='bazaar', description='test')
    ammo_command(group, bot)
    callback = get_callback(group, 'ammo')

    ctx = make_ctx()
    await callback(ctx, str(singouin_id), 'Sell', 'cal22')

    assert ctx.respond.call_count == 1
    embed = ctx.respond.call_args.kwargs['embed']
    assert embed.description == 'Not enough Cal22 in stock (have 9, need 10)'
    satchel.reload()
    assert satchel.ammo.cal22 == 9
    assert satchel.currency.banana == 3


async def test_buy_short_by_one_is_rejected_with_balance_message(bot, make_ctx, get_callback, make_satchel):  # noqa: E501
    singouin_id = uuid.uuid4()
    # cal50: price 1/unit * 10 units == 10
    satchel = make_satchel(_id=singouin_id, ammo={'cal50': 0}, currency={'banana': 9})

    group = bot.create_group(name='bazaar', description='test')
    ammo_command(group, bot)
    callback = get_callback(group, 'ammo')

    ctx = make_ctx()
    await callback(ctx, str(singouin_id), 'Buy', 'cal50')

    assert ctx.respond.call_count == 1
    embed = ctx.respond.call_args.kwargs['embed']
    assert embed.description == 'Not enough bananas (have 9, need 10)'
    satchel.reload()
    assert satchel.currency.banana == 9
    assert satchel.ammo.cal50 == 0


async def test_buy_debits_and_adds_ammo_on_a_non_default_caliber(bot, make_ctx, get_callback, make_satchel):  # noqa: E501
    # Exercises the dynamic field path (inc__ammo__<caliber>) on another
    # caliber than cal22, and checks the footer shows the persisted balance.
    singouin_id = uuid.uuid4()
    satchel = make_satchel(_id=singouin_id, ammo={'arrow': 5}, currency={'banana': 25})

    group = bot.create_group(name='bazaar', description='test')
    ammo_command(group, bot)
    callback = get_callback(group, 'ammo')

    ctx = make_ctx()
    await callback(ctx, str(singouin_id), 'Buy', 'arrow')

    satchel.reload()
    # arrow: price 1/unit * 10 units == 10
    assert satchel.currency.banana == 15
    assert satchel.ammo.arrow == 15
    embed = ctx.respond.call_args.kwargs['embed']
    assert embed.footer.text == 'New Account balance: 15 🍌'


async def test_sell_keeps_a_concurrent_resolver_decrement(bot, make_ctx, get_callback, make_satchel, resolver_eats, hook_query):  # noqa: E501
    # Lost-update shape: the resolver's $inc -1 lands after the bot read the
    # satchel (1st SatchelDocument.objects call) and before its write (2nd).
    singouin_id = uuid.uuid4()
    satchel = make_satchel(_id=singouin_id, ammo={'cal50': 20}, currency={'banana': 5})

    group = bot.create_group(name='bazaar', description='test')
    ammo_command(group, bot)
    callback = get_callback(group, 'ammo')

    ctx = make_ctx()
    with hook_query(SatchelDocument, lambda: resolver_eats(singouin_id), before_call=2):
        await callback(ctx, str(singouin_id), 'Sell', 'cal50')

    satchel.reload()
    # cal50: price 1/unit * 10 units == 10
    assert satchel.currency.banana == 5 - 1 + 10
    assert satchel.ammo.cal50 == 10


async def test_buy_guard_refuses_when_balance_drops_after_the_read(bot, make_ctx, get_callback, make_satchel, resolver_eats, hook_query):  # noqa: E501
    # The bot reads exactly enough bananas, the resolver eats one before the
    # write: the guarded update must refuse, and nothing must change.
    singouin_id = uuid.uuid4()
    satchel = make_satchel(_id=singouin_id, ammo={'cal50': 0}, currency={'banana': 10})

    group = bot.create_group(name='bazaar', description='test')
    ammo_command(group, bot)
    callback = get_callback(group, 'ammo')

    ctx = make_ctx()
    with hook_query(SatchelDocument, lambda: resolver_eats(singouin_id), before_call=2):
        await callback(ctx, str(singouin_id), 'Buy', 'cal50')

    assert ctx.respond.call_count == 1
    embed = ctx.respond.call_args.kwargs['embed']
    assert embed.description == 'Not enough bananas (have 9, need 10)'
    satchel.reload()
    assert satchel.currency.banana == 9
    assert satchel.ammo.cal50 == 0
