"""Safe serialization helpers for data embedded in rendered HTML."""
import json


def json_for_script(value):
    """Serialize JSON into a script block without permitting an HTML tag breakout."""
    return (json.dumps(value, ensure_ascii=False)
            .replace("&", "\\u0026")
            .replace("<", "\\u003c")
            .replace(">", "\\u003e")
            .replace("\u2028", "\\u2028")
            .replace("\u2029", "\\u2029"))
