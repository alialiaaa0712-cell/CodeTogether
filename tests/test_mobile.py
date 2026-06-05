from pathlib import Path


def test_root_still_returns_healthcheck(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "service": "CodeTogether"}


def test_mobile_index_is_served(client):
    resp = client.get("/mobile/index.html")
    assert resp.status_code == 200
    assert "CodeTogether Mobile" in resp.text


def test_mobile_assets_are_served(client):
    css = client.get("/mobile/style.css")
    js = client.get("/mobile/app.js")
    assert css.status_code == 200
    assert js.status_code == 200
    assert ".topbar" in css.text
    assert 'console.log("CodeTogether mobile ready")' in js.text
