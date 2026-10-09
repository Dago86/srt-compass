"""Small platform integration helpers shared by the GUI and workers."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def is_macos() -> bool:
    return sys.platform == "darwin"


def is_linux() -> bool:
    return sys.platform.startswith("linux")


def data_dir() -> Path:
    """Return the persistent application data directory.

    The legacy macOS location is deliberately preserved so existing jobs and
    downloads remain visible after upgrading. Linux follows XDG conventions.
    """
    if is_macos():
        return Path.home() / "Library" / "Application Support" / "VideoSottotitoli"
    root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return root / "SRT Compass"


def config_dir() -> Path:
    if is_macos():
        return data_dir()
    root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return root / "SRT Compass"


def state_dir() -> Path:
    if is_macos():
        return Path.home() / "Library" / "Logs" / "VideoSottotitoli"
    root = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return root / "srt-compass"


def default_download_dir() -> Path:
    return Path.home() / "Downloads" / "SRT Compass"


def secret_store_label(locale: str = "it") -> str:
    if locale == "en":
        return "macOS Keychain" if is_macos() else "desktop keyring"
    return "Portachiavi macOS" if is_macos() else "portachiavi desktop"


def open_path(path: str | Path, *, reveal: bool = False) -> None:
    """Open a file or directory with the user's desktop handler."""
    target = Path(path).expanduser()
    if is_macos():
        command = ["open"]
        if reveal:
            command.append("-R")
        command.append(str(target))
    else:
        # Linux desktop environments do not have a portable "reveal" action;
        # opening the containing directory is the least surprising equivalent.
        if reveal and target.is_file():
            target = target.parent
        opener = shutil.which("xdg-open") or shutil.which("gio")
        if not opener:
            raise OSError("Nessun programma disponibile per aprire questo file.")
        command = [opener, "open", str(target)] if Path(opener).name == "gio" else [opener, str(target)]
    subprocess.Popen(command, close_fds=True, start_new_session=True)
