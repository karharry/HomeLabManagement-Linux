import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("HOMELAB_DATA_DIR", str(tmp_path))
    import core
    monkeypatch.setattr(core, "SETTINGS_PATH", str(tmp_path / "settings.json"))
