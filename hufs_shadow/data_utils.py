"""Shared numeric, snapshot and atomic JSON utilities."""
import hashlib
import json
import math
import os
import re
import tempfile
from pathlib import Path


class PublicDataError(ValueError):
    """Safe user-facing error: never include request URL or credential."""


def positive(value):
    if isinstance(value, bool):
        return None
    match = re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s*(?:m)?\s*', str(value))
    number = float(match.group(1)) if match else None
    return number if number is not None and math.isfinite(number) and 0 < number <= 300 else None


def floors(value):
    number = positive(value)
    return int(number) if number is not None and number.is_integer() and number <= 100 else None


def campus_id(campus):
    return hashlib.sha256(campus.wkb).hexdigest()


def save_json(path, obj):
    """Atomic write; this function must only receive credential-free data."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False)
    fd, tmp = tempfile.mkstemp(prefix='.public-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            out.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
