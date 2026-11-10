"""Branding consistency test for Home Assistant and HACS metadata."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "metz_remote"


def test_integration_branding_names():
    manifest = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))
    hacs = json.loads((ROOT / "hacs.json").read_text(encoding="utf-8"))
    assert manifest["domain"] == "metz_remote"
    assert manifest["name"] == "Metz Remote"
    assert manifest["version"] == "0.3.11"
    assert hacs["name"] == "Metz Remote"
    for path in (COMPONENT / "strings.json", COMPONENT / "translations" / "de.json", COMPONENT / "translations" / "en.json"):
        labels = json.loads(path.read_text(encoding="utf-8"))
        assert labels["title"] == "Metz Remote"
        assert "Metz Remote" in labels["config"]["step"]["user"]["title"]
        assert "Metz Remote" in labels["config"]["step"]["confirm"]["title"]


def test_no_old_integration_name_in_package_text():
    for path in ROOT.rglob("*"):
        if path.is_file() and path.suffix in (".py", ".md", ".json"):
            assert "Metz Classic" + " TV" not in path.read_text(encoding="utf-8"), path
