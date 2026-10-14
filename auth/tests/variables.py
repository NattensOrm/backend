# -*- coding: utf8 -*-

import os
import pymongo
import redis
import urllib.parse
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

# Direct access to the users collection, to set up/check states no route
# exposes (e.g. a Discord link, written by the discord bot)
MONGO_URI = 'mongodb://%s:%s@%s/%s?authSource=admin' % (
    urllib.parse.quote_plus(os.environ.get("MONGO_USER", 'singouins')),
    urllib.parse.quote_plus(os.environ.get("MONGO_PASS") or ''),
    os.environ.get("MONGO_HOST", '127.0.0.1'),
    os.environ.get("MONGO_BASE", 'singouins'),
    )
users = pymongo.MongoClient(MONGO_URI)[os.environ.get("MONGO_BASE", 'singouins')]['users']
