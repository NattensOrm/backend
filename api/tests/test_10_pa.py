# -*- coding: utf8 -*-

import requests

from variables import (
    API_ENV,
    API_URL,
    CREATURE_ID,
    r,
    )


def test_singouins_pa(jwt_header):
    # PJTest is not in an Instance at this point of the suite (Instances only
    # appear in test_11): designer ruling, no Instance means no PA at all.
    # The in-Instance read is covered by test_12_pa_instance.py.
    response  = requests.get(f'{API_URL}/mypc/{CREATURE_ID}/pa', headers=jwt_header['access'])
    assert response.status_code == 200
    assert response.json().get("success") is True
    assert response.json().get("payload") is None


def test_singouins_pa_reset():
    r.delete(f"{API_ENV}:pas:{CREATURE_ID}:blue")
    r.delete(f"{API_ENV}:pas:{CREATURE_ID}:red")
