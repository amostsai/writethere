import json

import pytest

from phone_pad.settings import PortSettings, parse_port


def test_first_run_defaults_to_39945_without_writing(tmp_path):
    settings = PortSettings(tmp_path / "settings.json")
    assert settings.load() == 39945
    assert not settings.path.exists()


def test_saved_port_is_loaded_by_the_next_instance(tmp_path):
    path = tmp_path / "phone-pad" / "settings.json"
    PortSettings(path).save(45678)
    assert PortSettings(path).load() == 45678
    assert json.loads(path.read_text()) == {"port": 45678}
    assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("value", [0, 65536, -1, True, None, "abc", "3.5", "３９９４５"])
def test_invalid_ports_rejected(value):
    with pytest.raises(ValueError):
        parse_port(value)


def test_accepts_port_boundaries_and_trimmed_input():
    assert parse_port(" 39945 ") == 39945
    assert parse_port(1) == 1
    assert parse_port(65535) == 65535


@pytest.mark.parametrize("contents", ['broken', '[]', '{}', '{"port":0}', '{"port":true}'])
def test_bad_config_uses_default_and_explains_without_overwriting(tmp_path, contents):
    path = tmp_path / "settings.json"
    path.write_text(contents)
    settings = PortSettings(path)
    assert settings.load() == 39945
    assert settings.warning
    assert path.read_text() == contents


def test_failed_save_preserves_existing_setting(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    settings = PortSettings(path)
    settings.save(39945)

    def fail(*args):
        raise OSError("disk full")

    monkeypatch.setattr("phone_pad.settings.os.replace", fail)
    with pytest.raises(OSError):
        settings.save(45678)
    assert PortSettings(path).load() == 39945
    assert list(tmp_path.iterdir()) == [path]


def test_respects_xdg_config_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert PortSettings().path == tmp_path / "phone-pad" / "settings.json"
