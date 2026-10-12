# -*- coding: utf8 -*-

import uuid

from mongo.models.Item import ItemDocument
from mongo.models.Satchel import SatchelDocument
from subcommands.bazaar.item import item as item_command


async def test_sell_updates_balance_and_highscore(bot, make_ctx, get_callback, make_satchel, make_highscore, make_item):  # noqa: E501
    singouin_id = uuid.uuid4()
    satchel = make_satchel(_id=singouin_id)
    highscore = make_highscore(_id=singouin_id)
    # size 2x2, tier 1, rarity Rare (index 3): 2*2 * (1+1) * 3 // 2 == 12
    itm = make_item(bearer=singouin_id, metatype='armor', metaid=1, rarity='Rare')

    group = bot.create_group(name='bazaar', description='test')
    item_command(group, bot)
    callback = get_callback(group, 'item')

    ctx = make_ctx()
    await callback(ctx, str(singouin_id), 'Sell', str(itm.id))

    assert ctx.respond.call_count == 1

    satchel.reload()
    highscore.reload()
    itm.reload()

    assert satchel.currency.banana == 12
    assert highscore.internal.item.sold == 1
    # Sold items are shelved back onto the house account
    assert str(itm.bearer) == '00000000-cafe-cafe-cafe-000000000000'


async def test_sell_unknown_item_leaves_state_untouched(bot, make_ctx, get_callback, make_satchel, make_highscore):  # noqa: E501
    singouin_id = uuid.uuid4()
    satchel = make_satchel(_id=singouin_id)
    make_highscore(_id=singouin_id)

    group = bot.create_group(name='bazaar', description='test')
    item_command(group, bot)
    callback = get_callback(group, 'item')

    ctx = make_ctx()
    await callback(ctx, str(singouin_id), 'Sell', str(uuid.uuid4()))

    assert ctx.respond.call_count == 1
    satchel.reload()
    assert satchel.currency.banana == 0


async def test_sell_keeps_a_concurrent_resolver_decrement(bot, make_ctx, get_callback, make_satchel, make_highscore, make_item, resolver_eats, hook_query):  # noqa: E501
    # Lost-update shape: the satchel is read first, then the resolver's
    # $inc -1 lands (before the Item read), then the bot credits the sale.
    # The credit must not overwrite the resolver's write.
    singouin_id = uuid.uuid4()
    satchel = make_satchel(_id=singouin_id, currency={'banana': 5})
    make_highscore(_id=singouin_id)
    # size 2x2, tier 1, rarity Rare (index 3): 2*2 * (1+1) * 3 // 2 == 12
    itm = make_item(bearer=singouin_id, metatype='armor', metaid=1, rarity='Rare')

    group = bot.create_group(name='bazaar', description='test')
    item_command(group, bot)
    callback = get_callback(group, 'item')

    ctx = make_ctx()
    with hook_query(ItemDocument, lambda: resolver_eats(singouin_id)):
        await callback(ctx, str(singouin_id), 'Sell', str(itm.id))

    assert ctx.respond.call_count == 1
    satchel.reload()
    assert satchel.currency.banana == 5 - 1 + 12
    # The footer shows the persisted balance, not a stale computed one
    embed = ctx.respond.call_args.kwargs['embed']
    assert embed.footer.text == f'Account balance: {5 - 1 + 12} 🍌'


async def test_sell_with_satchel_gone_before_credit_is_ko_and_keeps_the_item(bot, make_ctx, get_callback, make_satchel, make_highscore, make_item, hook_query):  # noqa: E501
    # The satchel exists when it is read, then disappears before the credit:
    # the atomic credit matches nothing (credited == 0), which must go to the
    # KO path before the item is shelved, not silently "succeed".
    singouin_id = uuid.uuid4()
    make_satchel(_id=singouin_id)
    highscore = make_highscore(_id=singouin_id)
    itm = make_item(bearer=singouin_id, metatype='armor', metaid=1, rarity='Rare')

    def _satchel_vanishes():
        # Raw delete, so the patched SatchelDocument manager is not involved
        SatchelDocument._get_collection().delete_one({'_id': str(singouin_id)})

    group = bot.create_group(name='bazaar', description='test')
    item_command(group, bot)
    callback = get_callback(group, 'item')

    ctx = make_ctx()
    with hook_query(ItemDocument, _satchel_vanishes):
        await callback(ctx, str(singouin_id), 'Sell', str(itm.id))

    assert ctx.respond.call_count == 1
    embed = ctx.respond.call_args.kwargs['embed']
    assert embed.description.startswith('Bazaar-Sell Query KO')
    assert SatchelDocument.objects(_id=singouin_id).count() == 0
    itm.reload()
    assert itm.bearer == singouin_id  # not shelved
    highscore.reload()
    assert highscore.internal.item.sold == 0
