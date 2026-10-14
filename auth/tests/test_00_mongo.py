# -*- coding: utf8 -*-

import os
import urllib.parse

from mongoengine import connect
from mongoengine.connection import get_db

# MongoDB variables
MONGO_BASE = os.environ.get("MONGO_BASE", 'singouins')
MONGO_HOST = os.environ.get("MONGO_HOST", '127.0.0.1')
MONGO_PASS = os.environ.get("MONGO_PASS")
MONGO_USER = os.environ.get("MONGO_USER", 'singouins')

username = urllib.parse.quote_plus(MONGO_USER)
password = urllib.parse.quote_plus(MONGO_PASS)

# Single-node MongoDB container (prod & CI): no SRV, no replicaSet, no TLS
MONGO_URI = 'mongodb://%s:%s@%s/%s?authSource=admin' % (
    username,
    password,
    MONGO_HOST,
    MONGO_BASE,
    )


def test_singouins_mongo_connection():
    connect(host=MONGO_URI, uuidRepresentation='standard')
    db = get_db('default')

    assert db.command("ping")
