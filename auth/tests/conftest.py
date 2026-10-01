# -*- coding: utf8 -*-

import pytest
import requests

from variables import AUTH_PAYLOAD, API_URL, MAILPIT_URL


@pytest.fixture(scope="session")
def jwt_header():
    header = {}
    # Perform the login call and get the token
    response = requests.post(f'{API_URL}/login', json=AUTH_PAYLOAD)
    assert response.status_code == 200

    access_token = response.json().get("access_token")
    assert access_token is not None  # Ensure the token is present

    refresh_token = response.json().get("refresh_token")
    assert refresh_token is not None  # Ensure the token is present

    header = {
        "access": {"Authorization": f"Bearer {access_token}"},
        "refresh": {"Authorization": f"Bearer {refresh_token}"}
    }
    # Return the token so it can be used in other tests
    return header


@pytest.fixture
def mails_to():
    """ Return the mails Mailpit caught for an address, newest first, each
    with its HTML body fetched (Mailpit's search only returns summaries). """
    def _mails_to(address):
        response = requests.get(f'{MAILPIT_URL}/api/v1/search', params={'query': f'to:"{address}"'})  # noqa: E501
        assert response.status_code == 200
        mails = []
        for summary in response.json()['messages']:
            message = requests.get(f"{MAILPIT_URL}/api/v1/message/{summary['ID']}")
            assert message.status_code == 200
            mails.append(message.json())
        return mails
    return _mails_to
