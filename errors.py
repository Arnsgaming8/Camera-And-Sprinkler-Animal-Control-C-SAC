import json
import os
import traceback
from datetime import datetime, timezone

ERROR_FILE = os.path.join(os.path.dirname(__file__), "errors.json")
MAX_ERRORS = 200
_USE_MEMORY = os.environ.get("ERRORS_MEMORY", "0") == "1"
_memory_store = []


def log_error(source, message, exc_info=None):
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "message": str(message),
        "traceback": traceback.format_exc() if exc_info else None,
    }
    if _USE_MEMORY:
        _memory_store.append(entry)
        if len(_memory_store) > MAX_ERRORS:
            _memory_store[:] = _memory_store[-MAX_ERRORS:]
    else:
        errors = _load_errors()
        errors.append(entry)
        if len(errors) > MAX_ERRORS:
            errors = errors[-MAX_ERRORS:]
        _save_errors(errors)


def get_errors(limit=50):
    if _USE_MEMORY:
        return _memory_store[-limit:][::-1]
    errors = _load_errors()
    return errors[-limit:][::-1]


def clear_errors():
    if _USE_MEMORY:
        _memory_store.clear()
    else:
        _save_errors([])


def _load_errors():
    try:
        with open(ERROR_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_errors(errors):
    with open(ERROR_FILE, "w") as f:
        json.dump(errors, f, indent=2)
