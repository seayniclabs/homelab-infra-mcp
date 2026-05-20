"""Response formatting helpers."""

import json
from typing import Any


def json_response(payload: Any) -> str:
    return json.dumps(payload, default=str)
