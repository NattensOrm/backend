# -*- coding: utf8 -*-

from types import SimpleNamespace

from subcommands.godmode._autocomplete import get_singouins_list


async def test_singouins_list_offers_exactly_playable_races(make_creature):
    # Playable races are 1..4; 5..10 are reserved, 11..16 are mob races.
    # Races 1 and 4 used to be dropped by an exclusive (gt/lt) filter.
    created = {race: make_creature(race=race) for race in range(1, 17)}

    choices = await get_singouins_list(SimpleNamespace(options={}, value=''))

    offered = {choice.value for choice in choices}
    assert offered == {str(created[race].id) for race in range(1, 5)}
