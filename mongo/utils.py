# -*- coding: utf8 -*-

import datetime

from bson import json_util

# Explicit json_options for Document.to_json(): without them mongoengine warns
# (DeprecationWarning) and falls back to these very options, and plans to
# change that default. Legacy on purpose: other services and the frontend
# read this JSON (e.g. dates as {"$date": <epoch ms>}), it must not change.
JSON_OPTIONS = json_util.LEGACY_JSON_OPTIONS


def utcnow() -> datetime.datetime:
    """
    Current UTC time as a naive datetime, like the deprecated
    datetime.datetime.utcnow() (Python >= 3.12) it replaces.

    Naive on purpose: the Mongo connection is not tz_aware (mongo/__init__.py),
    so the dates read back from the DB are naive UTC, and Python refuses to
    compare or subtract naive and aware datetimes. Every date written by the
    services and every model default goes through here to stay consistent.
    """
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
