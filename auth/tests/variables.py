# -*- coding: utf8 -*-

import os
import redis
import uuid

GUNICORN_PORT   = os.environ.get("GUNICORN_PORT", 5000)
API_ENV         = os.environ.get("API_ENV", 5000)
API_URL         = f'http://127.0.0.1:{GUNICORN_PORT}'

r = redis.StrictRedis(
    host=os.environ.get("REDIS_HOST", '127.0.0.1'),
    port=os.environ.get("REDIS_PORT", 6379),
    db=os.environ.get("REDIS_BASE", 0),
    encoding='utf-8',
    )

USER_NAME       = 'user@example.net'
USER_ID         = str(uuid.uuid3(uuid.NAMESPACE_DNS, USER_NAME))

AUTH_PAYLOAD    = {'username': USER_NAME, 'password': 'plop'}

# Fake SMTP server catching auth's mails (Mailpit, see the CI workflows).
# Unset = no Mailpit available: the mail tests are skipped
MAILPIT_URL     = os.environ.get("MAILPIT_URL")
