"""Pre-registration: parameters are frozen and hashed before any control runs.

In research, freezing parameters guards against p-hacking. In surveillance it
guards against something worse: tuning thresholds until the alerts tell the
story you wanted. A surveillance program whose parameters move after seeing
outcomes is not a control.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import yaml


class ParamsDriftError(RuntimeError):
    """Raised when live parameters do not match any registered hash."""


def load_params(path: str) -> dict:
    with open(path) as fh:
        return yaml.safe_load(fh)


def _canonical(params: dict) -> str:
    # sort_keys makes the hash independent of YAML ordering
    return json.dumps(params, sort_keys=True, separators=(",", ":"))


def params_hash(params: dict) -> str:
    return hashlib.sha256(_canonical(params).encode()).hexdigest()


def register(conn, params: dict) -> str:
    """Explicitly register one immutable parameter set for a new version.

    This is intentionally separate from ordinary control execution.  A version
    can identify exactly one canonical parameter hash, so changing a threshold
    requires a version bump before the new set can be registered.
    """
    h = params_hash(params)
    version = str(params.get("version", "unversioned"))
    existing = conn.execute(
        "SELECT version FROM params WHERE params_hash = ?", (h,)
    ).fetchone()
    if existing is not None and existing[0] != version:
        raise ParamsDriftError(
            "parameter hash is already registered as version {}; use that "
            "version or make an intentional, versioned change".format(existing[0]))
    prior = conn.execute(
        "SELECT params_hash FROM params WHERE version = ? AND params_hash != ?",
        (version, h)).fetchone()
    if prior is not None:
        raise ParamsDriftError(
            "version {} is already registered with a different parameter hash; "
            "bump `version` before registering changed parameters".format(version))
    if existing is None:
        conn.execute(
            "INSERT INTO params (params_hash, registered_at, version, content)"
            " VALUES (?, ?, ?, ?)",
            (h, datetime.now(timezone.utc).isoformat(), version, _canonical(params)),
        )
        conn.commit()
    return h


def verify(conn, params: dict) -> None:
    h = params_hash(params)
    row = conn.execute(
        "SELECT 1 FROM params WHERE params_hash = ?", (h,)
    ).fetchone()
    if row is None:
        raise ParamsDriftError(
            "Live parameters (hash {}) are not registered. Bump `version` in "
            "config/params.yaml and re-register before running controls."
            .format(h[:12])
        )
