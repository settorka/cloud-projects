"""Load a selected V2 dotenv file; process environment takes precedence."""

import os
from pathlib import Path
from dotenv import load_dotenv


def load_configuration():
    explicit = os.getenv("V2_ENV_FILE")
    if explicit:
        path = Path(explicit)
        if not path.is_file():
            raise RuntimeError("V2_ENV_FILE does not exist")
        load_dotenv(path, override=False)
        return
    origin = Path(__file__).resolve()
    candidates = [Path.cwd() / "v2.env", origin.parent.parent / "v2.env"]
    if len(origin.parents) > 3:
        candidates.append(origin.parents[3] / "v2.env")
    for path in candidates:
        if path.is_file():
            load_dotenv(path, override=False)
            return
    # Containers receive the file through Compose env_file; no embedded fallback.


def integer(name, minimum=1, maximum=2**31 - 1):
    value = int(os.environ[name])
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be {minimum}..{maximum}")
    return value
