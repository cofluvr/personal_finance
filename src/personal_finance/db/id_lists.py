"""Lists of IDs as one SQL parameter. See decisions.md D-057, recommendation 1.

SQLite allows at most 32,766 parameters in one statement, so a list of any length is passed as one
JSON array and read in SQL as `IN (SELECT value FROM json_each(?))`.
"""

import json


def ids_as_json_array(ids) -> str:
    """The IDs as one JSON array of strings, for a single `json_each(?)` parameter."""
    ids = list(ids)
    if not all(isinstance(identifier, str) for identifier in ids):
        raise TypeError("IDs passed as a JSON array must all be strings")
    return json.dumps(ids)
