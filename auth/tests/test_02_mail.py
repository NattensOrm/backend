# -*- coding: utf8 -*-

import os
import re

import pytest
import requests

from variables import API_ENV, API_URL, MAILPIT_URL, r

# These tests go through the real SMTP path (utils/mail.py) against Mailpit,
# a fake SMTP server that catches mails instead of delivering them, and read
# tokens from the mails themselves - unlike test_01_auth.py, which reads them
# straight from Redis and so never looks at what a user actually receives.
pytestmark = pytest.mark.skipif(not MAILPIT_URL, reason='needs a Mailpit server (MAILPIT_URL)')  # noqa: E501

# secrets.token_urlsafe() alphabet
CONFIRM_LINK_RE = re.compile(r'href="([^"]*/confirm/([A-Za-z0-9_-]+))"')
RESET_CODE_RE = re.compile(r'<strong>([A-Za-z0-9_-]{20,})</strong>')


def _delete_user(mail, password):
    response = requests.post(f'{API_URL}/login', json={'username': mail, 'password': password})  # noqa: E501
    access_header = {"Authorization": f"Bearer {response.json().get('access_token')}"}
    requests.delete(f'{API_URL}/delete', headers=access_header)


def test_singouins_auth_mail_register_sends_a_working_confirmation_link(mails_to):
    mail = 'mail-register@example.net'
    response = requests.post(f'{API_URL}/register', json={'password': 'plop', 'mail': mail})  # noqa: E501
    # 201 = "mail OK": with a reachable SMTP server, the send must succeed
    assert response.status_code == 201

    [message] = mails_to(mail)
    assert 'Bienvenue' in message['Subject']
    if os.environ.get('SEP_SMTP_FROM'):
        assert message['From']['Address'] == os.environ['SEP_SMTP_FROM']

    link, token = CONFIRM_LINK_RE.search(message['HTML']).groups()
    assert token == r.get(f"{API_ENV}:auth:current_confirm_token:{mail}").decode()

    # Follow the link exactly as it is in the mail
    response = requests.get(link)
    assert response.status_code == 200
    assert 'User confirmation OK' in response.json().get("msg")

    _delete_user(mail, 'plop')


def test_singouins_auth_mail_resend_sends_a_new_working_link(mails_to):
    mail = 'mail-resend@example.net'
    response = requests.post(f'{API_URL}/register', json={'password': 'plop', 'mail': mail})  # noqa: E501
    assert response.status_code == 201

    response = requests.post(f'{API_URL}/resend', json={'mail': mail})
    assert response.status_code == 200

    # One mail from register, one from resend - newest first
    newest, oldest = mails_to(mail)
    new_link, new_token = CONFIRM_LINK_RE.search(newest['HTML']).groups()
    _, old_token = CONFIRM_LINK_RE.search(oldest['HTML']).groups()
    assert new_token != old_token

    response = requests.get(new_link)
    assert response.status_code == 200
    assert 'User confirmation OK' in response.json().get("msg")

    _delete_user(mail, 'plop')


def test_singouins_auth_mail_resend_already_confirmed_sends_nothing(mails_to):
    mail = 'mail-resend-active@example.net'
    response = requests.post(f'{API_URL}/register', json={'password': 'plop', 'mail': mail})  # noqa: E501
    assert response.status_code == 201

    [message] = mails_to(mail)
    link, _ = CONFIRM_LINK_RE.search(message['HTML']).groups()
    requests.get(link)

    response = requests.post(f'{API_URL}/resend', json={'mail': mail})
    assert response.status_code == 200
    # Still only the registration mail
    assert len(mails_to(mail)) == 1

    _delete_user(mail, 'plop')


def test_singouins_auth_mail_forgot_password_sends_a_working_reset_code(mails_to):
    mail = 'mail-forgot@example.net'
    response = requests.post(f'{API_URL}/register', json={'password': 'old-password', 'mail': mail})  # noqa: E501
    assert response.status_code == 201

    response = requests.post(f'{API_URL}/forgot-password', json={'mail': mail})
    assert response.status_code == 200

    reset_mail = mails_to(mail)[0]
    assert 'initialisation' in reset_mail['Subject']
    code = RESET_CODE_RE.search(reset_mail['HTML']).group(1)
    assert code == r.get(f"{API_ENV}:auth:current_reset_token:{mail}").decode()

    response = requests.post(f'{API_URL}/reset-password', json={'token': code, 'password': 'new-password'})  # noqa: E501
    assert response.status_code == 200
    assert 'Reset password OK' in response.json().get("msg")

    _delete_user(mail, 'new-password')


def test_singouins_auth_mail_unknown_email_gets_nothing(mails_to):
    # Enumeration safety, side-effect half: test_01_auth.py checks the
    # responses are identical, this checks no mail goes out either
    mail = 'mail-nobody@example.net'
    response = requests.post(f'{API_URL}/resend', json={'mail': mail})
    assert response.status_code == 200
    response = requests.post(f'{API_URL}/forgot-password', json={'mail': mail})
    assert response.status_code == 200

    assert mails_to(mail) == []
