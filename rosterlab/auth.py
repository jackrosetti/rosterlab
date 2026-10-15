from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional, Tuple


KEYCHAIN_SERVICE = "com.rosterlab.espn"
SECURITY_COMMAND = Path("/usr/bin/security")
OSASCRIPT_COMMAND = Path("/usr/bin/osascript")
SWIFT_COMMAND = Path("/usr/bin/swift")
KEYCHAIN_STORE_SCRIPT = Path(__file__).with_name("keychain_store.swift")


class CredentialError(RuntimeError):
    pass


@dataclass(frozen=True)
class ESPNCredentials:
    espn_s2: str
    swid: str

    def __post_init__(self) -> None:
        if not self.espn_s2.strip():
            raise ValueError("ESPN espn_s2 cookie is empty")
        if not self.swid.strip():
            raise ValueError("ESPN SWID cookie is empty")


def normalize_swid(value: str) -> str:
    cleaned = value.strip().strip('"').strip("'")
    if cleaned and not cleaned.startswith("{"):
        cleaned = "{" + cleaned
    if cleaned and not cleaned.endswith("}"):
        cleaned = cleaned + "}"
    return cleaned


def credentials_from_environment(
    environ: Optional[Mapping[str, str]] = None,
) -> Optional[ESPNCredentials]:
    environ = environ or os.environ
    espn_s2 = environ.get("ESPN_S2", "").strip()
    swid = normalize_swid(environ.get("ESPN_SWID", ""))
    if not espn_s2 and not swid:
        return None
    if not espn_s2 or not swid:
        raise CredentialError("ESPN_S2 and ESPN_SWID must be provided together.")
    return ESPNCredentials(espn_s2=espn_s2, swid=swid)


def keychain_supported() -> bool:
    return (
        sys.platform == "darwin"
        and SECURITY_COMMAND.exists()
        and SWIFT_COMMAND.exists()
        and KEYCHAIN_STORE_SCRIPT.exists()
    )


def native_prompt_supported() -> bool:
    return sys.platform == "darwin" and OSASCRIPT_COMMAND.exists()


def _native_hidden_prompt(message: str) -> str:
    if not native_prompt_supported():
        raise CredentialError("Native secure credential entry requires macOS.")
    script = (
        'display dialog "' + message.replace('"', '\\\"') + '" '
        'default answer "" with hidden answer '
        'buttons {"Cancel", "Continue"} default button "Continue" '
        'cancel button "Cancel" with title "RosterLab ESPN Login"\n'
        'return text returned of result'
    )
    completed = subprocess.run(
        [str(OSASCRIPT_COMMAND), "-e", script],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise CredentialError("ESPN credential entry was cancelled.")
    return completed.stdout.rstrip("\r\n")


def prompt_credentials_native() -> ESPNCredentials:
    """Collect ESPN cookies without exposing them in a terminal or process arguments."""
    espn_s2 = _native_hidden_prompt(
        "Paste the ESPN espn_s2 cookie. It will be stored only in macOS Keychain."
    ).strip()
    swid = normalize_swid(
        _native_hidden_prompt(
            "Paste the ESPN SWID cookie, including braces if shown."
        )
    )
    return ESPNCredentials(espn_s2=espn_s2, swid=swid)


def keychain_account(league_id: int, season: int) -> str:
    return f"league:{int(league_id)}:season:{int(season)}"


def _store_keychain_payload(*, account: str, payload: str) -> None:
    """Store arbitrary-length data through Security.framework, never through argv."""
    completed = subprocess.run(
        [str(SWIFT_COMMAND), str(KEYCHAIN_STORE_SCRIPT), account, KEYCHAIN_SERVICE],
        input=payload,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise CredentialError("macOS Keychain rejected the credential update")


def save_credentials(credentials: ESPNCredentials, *, league_id: int, season: int) -> None:
    if not keychain_supported():
        raise CredentialError(
            "Secure credential storage requires macOS Keychain. On this platform, use "
            "ESPN_S2 and ESPN_SWID environment variables instead."
        )
    payload = json.dumps(
        {"espn_s2": credentials.espn_s2, "swid": normalize_swid(credentials.swid)},
        separators=(",", ":"),
    )
    _store_keychain_payload(
        account=keychain_account(league_id, season),
        payload=payload,
    )


def load_keychain_credentials(*, league_id: int, season: int) -> Optional[ESPNCredentials]:
    if not keychain_supported():
        return None
    completed = subprocess.run(
        [
            str(SECURITY_COMMAND),
            "find-generic-password",
            "-a",
            keychain_account(league_id, season),
            "-s",
            KEYCHAIN_SERVICE,
            "-w",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return None
    try:
        payload = json.loads(completed.stdout.strip())
        return ESPNCredentials(
            espn_s2=str(payload["espn_s2"]),
            swid=normalize_swid(str(payload["swid"])),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise CredentialError(
            "Stored ESPN credentials are malformed; run `rosterlab login` again."
        ) from exc


def resolve_credentials(*, league_id: int, season: int) -> Tuple[Optional[ESPNCredentials], str]:
    environment = credentials_from_environment()
    if environment is not None:
        return environment, "environment"
    keychain = load_keychain_credentials(league_id=league_id, season=season)
    if keychain is not None:
        return keychain, "macOS Keychain"
    return None, "none"


def delete_credentials(*, league_id: int, season: int) -> bool:
    if not keychain_supported():
        return False
    completed = subprocess.run(
        [
            str(SECURITY_COMMAND),
            "delete-generic-password",
            "-a",
            keychain_account(league_id, season),
            "-s",
            KEYCHAIN_SERVICE,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.returncode == 0
