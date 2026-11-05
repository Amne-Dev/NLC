import os
import sys
from pathlib import Path
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src" / "backend"))

from agent import detect_skin_model, handle_skin_set_custom, get_config_manager


def test_detect_skin_model_steve():
    p = Path("skins/default_steve.png")
    assert p.exists()
    assert detect_skin_model(p) == "classic"


def test_detect_skin_model_alex():
    p = Path("skins/ev_s.png")
    assert p.exists()
    assert detect_skin_model(p) == "slim"


def test_detect_skin_model_rilox():
    p = Path("skins/rilox11.png")
    assert p.exists()
    assert detect_skin_model(p) == "classic"


def test_detect_skin_model_legacy_64x32(tmp_path):
    legacy = tmp_path / "legacy.png"
    img = Image.new("RGBA", (64, 32), (255, 0, 0, 255))
    img.save(legacy)
    assert detect_skin_model(legacy) == "classic"


def test_handle_skin_set_custom_auto_detect(tmp_path):
    p = Path("skins/ev_s.png")
    res = handle_skin_set_custom({"skin_path": str(p), "model": "auto"})
    assert res.get("status") == "success"
    assert res.get("model") == "slim"

