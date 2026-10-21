"""Local run settings: explicit configuration > process environment > CWD .env."""

import os
import shlex
import sys
from datetime import date, datetime, timezone
from pathlib import Path

KEYS = {
    "DATA_DIR": "product_output",
    "START_DATE": "start_date",
    "END_DATE": "end_date",
    "VERBOSITY": "verbosity",
}


def resolve(explicit, env_file=None):
    """Read four whitelisted settings, without environment mutation or writes.

    File-backed runs require all four effective keys. With no file, existing API
    defaults remain supported. File-relative DATA_DIR preserves its final symlink.
    """
    path = (
        Path(env_file).expanduser().absolute()
        if env_file is not None
        else Path.cwd() / ".env"
    )
    values, errors = {}, []
    exists = path.exists()
    if env_file is not None and not exists:
        errors.append("Explicit env_file does not exist.")
    if exists:
        try:
            if not path.is_file():
                raise OSError
            seen = set()
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), 1
            ):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("export "):
                    line = line[7:].lstrip()
                key, separator, raw = line.partition("=")
                key = key.strip()
                if key not in KEYS:
                    continue
                if key in seen:
                    errors.append(f"{key} is repeated on .env line {number}.")
                seen.add(key)
                try:
                    tokens = shlex.split(raw, comments=True)
                    if not separator or len(tokens) != 1:
                        raise ValueError
                    values[key] = tokens[0]
                except ValueError:
                    errors.append(f"{key} has invalid syntax on .env line {number}.")
        except (OSError, UnicodeError):
            errors.append("env_file must be a readable UTF-8 file.")
    file_output = (
        "DATA_DIR" in values
        and "DATA_DIR" not in os.environ
        and explicit.get("product_output") is None
    )
    values.update({key: os.environ[key] for key in KEYS if key in os.environ})
    values.update(
        {
            key: explicit[field]
            for key, field in KEYS.items()
            if explicit.get(field) is not None
        }
    )
    if exists or env_file is not None:
        errors.extend(
            f"{key} must be set."
            for key in KEYS
            if key not in values
            or values[key] is None
            or str(values[key]).strip() == ""
        )
    for key in ("START_DATE", "END_DATE"):
        if key in values:
            try:
                parsed = date.fromisoformat(str(values[key]))
                if parsed.isoformat() != str(values[key]):
                    raise ValueError
            except (TypeError, ValueError):
                errors.append(f"{key} must be a valid YYYY-MM-DD date.")
    if (
        "START_DATE" in values
        and "END_DATE" in values
        and str(values["START_DATE"]) > str(values["END_DATE"])
    ):
        errors.append("START_DATE must be on or before END_DATE.")
    if "VERBOSITY" in values:
        value = values["VERBOSITY"]
        if isinstance(value, str) and value.lower() in {"true", "false"}:
            value = value.lower() == "true"
        if type(value) is not bool:
            errors.append("VERBOSITY must be True or False.")
        values["VERBOSITY"] = value
    if "DATA_DIR" in values:
        try:
            raw = os.fspath(values["DATA_DIR"])
            if not isinstance(raw, str) or not raw.strip() or "\x00" in raw:
                raise ValueError
            target = Path(raw).expanduser()
            if file_output and not target.is_absolute():
                target = path.parent / target
            # Canonical publication needs the named symlink, not its snapshot.
            target = target.absolute()
            target = target.parent.resolve() / target.name
            ancestor = target
            while not ancestor.exists():
                ancestor = ancestor.parent
            if not ancestor.is_dir() or not os.access(ancestor, os.W_OK | os.X_OK):
                errors.append(
                    "DATA_DIR or its existing ancestor must be a writable directory."
                )
            values["DATA_DIR"] = str(target)
        except (TypeError, ValueError, OSError, RuntimeError):
            errors.append("DATA_DIR must be a usable directory path.")
    if errors:
        raise ValueError("Hydrology preflight failed:\n- " + "\n- ".join(errors))
    return {KEYS[key]: value for key, value in values.items()}


def log(verbosity, message):
    """Callers provide whitelisted operational messages, never provider bodies/keys."""
    if verbosity:
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        print(f"[hydrology {stamp}] {message}", file=sys.stderr, flush=True)
