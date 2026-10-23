"""Persist only user preferences, never pairing credentials or input text."""

import json
import os
from pathlib import Path
import re
import tempfile

DEFAULT_PORT = 39945


def parse_port(value):
    if isinstance(value, str):
        value = value.strip()
        if not re.fullmatch(r"[0-9]{1,5}", value):
            raise ValueError("連接埠須為 1–65535 的整數")
        value = int(value)
    if type(value) is not int or not 1 <= value <= 65535:
        raise ValueError("連接埠須為 1–65535 的整數")
    return value


class PortSettings:
    def __init__(self, path=None):
        config_home = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
        self.path = Path(path) if path is not None else Path(config_home) / "phone-pad/settings.json"
        self.warning = ""

    def load(self):
        self.warning = ""
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return parse_port(data["port"])
        except FileNotFoundError:
            return DEFAULT_PORT
        except (OSError, ValueError, KeyError, TypeError):
            self.warning = "無法讀取連接埠設定，先使用 39945；可重新設定並儲存"
            return DEFAULT_PORT

    def save(self, port):
        port = parse_port(port)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                             prefix=".settings-", delete=False) as file:
                temporary = Path(file.name)
                json.dump({"port": port}, file)
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
