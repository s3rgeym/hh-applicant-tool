from __future__ import annotations

from hh_applicant_tool.ui import TEMPLATES_DIR


def test_multi_account_controls_are_wired_to_js_api():
    html = (TEMPLATES_DIR / "index.html").read_text(encoding="utf-8")
    js = (TEMPLATES_DIR / "js" / "app.js").read_text(encoding="utf-8")

    assert 'id="profile-select"' in html
    assert "switchProfile(this.value)" in html
    assert "createProfile()" in html
    assert "deleteCurrentProfile()" in html
    assert "Переавторизоваться" in html

    assert "pywebview.api.get_profiles()" in js
    assert "pywebview.api.switch_profile(profileId)" in js
    assert "pywebview.api.create_profile(profileId)" in js
    assert "pywebview.api.delete_profile(profileId)" in js
