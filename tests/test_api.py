import pytest
from pathlib import Path
from app import config, db


def test_everything_needs_a_signed_in_device(api):
    from fastapi.testclient import TestClient
    from app.main import app
    anon = TestClient(app)
    for path in ("/api/state", "/api/batches", "/api/profiles", "/api/keepers", "/img/x.jpg"):
        assert anon.get(path).status_code == 401, path


def test_static_shell_is_public_but_api_is_not():
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app)
    assert c.get("/").status_code == 200 and c.get("/manifest.webmanifest").status_code == 200


def test_invite_redeem_creates_account_and_session(api):
    from fastapi.testclient import TestClient
    from app.main import app
    code = api.post("/api/admin/invites", json={}).json()["code"]
    fresh = TestClient(app)
    r = fresh.post("/api/auth/redeem", json={"code": code, "name": "Pat"})
    assert r.status_code == 200
    me = fresh.get("/api/me").json()
    assert me["name"] == "Pat" and me["role"] == "user"
    assert fresh.post("/api/auth/redeem", json={"code": code, "name": "Eve"}).status_code in (400, 409, 403)


def test_standard_user_cannot_use_admin_endpoints(friend_api):
    assert friend_api.get("/api/admin/users").status_code == 403
    assert friend_api.post("/api/admin/invites", json={}).status_code == 403


def test_swipe_rank_undo_roundtrip(api, ready_batch):
    lid = ready_batch["listings"][0]["id"]
    assert api.post("/api/swipe", json={"listing_id": lid, "verdict": "like"}).json()["rank"] == 0.75
    assert api.post("/api/swipe", json={"listing_id": lid, "verdict": "dislike"}).json()["rank"] == 0.25
    r = api.post("/api/rank", json={"listing_id": lid, "rank": 1.7}).json()
    assert r["rank"] == 1.0 and r["manual"] == 1 and r["verdict"] == "like"
    assert api.delete(f"/api/swipe/{lid}").json() == {"ok": True}
    assert db.q1("SELECT * FROM swipes WHERE listing_id=?", (lid,)) is None
    assert api.post("/api/swipe", json={"listing_id": lid, "verdict": "maybe"}).status_code == 400


def test_people_cannot_see_each_others_listings(api, friend_api, ready_batch):
    lid = ready_batch["listings"][0]["id"]
    assert friend_api.get(f"/api/listing/{lid}").status_code == 404
    assert friend_api.post("/api/swipe", json={"listing_id": lid, "verdict": "like"}).status_code == 404
    assert friend_api.get(f"/api/batches/{ready_batch['id']}").status_code == 404


def test_finishing_a_batch_is_idempotent(api, ready_batch):
    assert api.post(f"/api/batches/{ready_batch['id']}/finish").json() == {"ok": True}
    assert api.post(f"/api/batches/{ready_batch['id']}/finish").json() == {"ok": True}


def test_budget_exhausted_locks_new_batches_but_not_swiping(friend_api, monkeypatch):
    monkeypatch.setattr(config, "brain_mode", lambda: "claude")
    db.ex("INSERT INTO usage (user_id, model, input_tokens, output_tokens, cost, at) VALUES (?,?,?,?,?,?)",
          (friend_api.user["id"], "claude-sonnet-5-5", 1, 1, 3.5, db.now()))
    r = friend_api.post("/api/batches", json={"size": 5})
    assert r.status_code == 409 and "Claude" in r.json()["detail"]
    assert friend_api.get("/api/state").status_code == 200


def test_a_full_web_no_longer_locks_new_batches(api, admin):
    """Kindling locked batches at 50 swiped listings until you crystallized. Orbit has no such lock."""
    from app import learn
    p = db.active_profile(admin["id"])
    bid = db.ex("INSERT INTO batches (profile_id, number, status, size, created_at) VALUES (?,?,?,?,?)",
                (p["id"], 1, "done", 5, db.now()))
    for i in range(learn.WEB_LIMIT + 5):
        lid = db.ex("INSERT INTO listings (profile_id, batch_id, fb_id, created_at) VALUES (?,?,?,?)", (p["id"], bid, f"f{i}", db.now()))
        db.ex("INSERT INTO swipes (listing_id, verdict, rank, swiped_at) VALUES (?,?,?,?)", (lid, "like", .75, db.now()))
    assert api.post("/api/batches", json={"size": 5}).status_code == 200


def test_interrupted_batches_are_failed_on_startup(admin):
    from fastapi.testclient import TestClient
    from app.main import app
    p = db.active_profile(admin["id"])
    bid = db.ex("INSERT INTO batches (profile_id, number, status, size, created_at) VALUES (?,?,?,?,?)",
                (p["id"], 1, "scoring", 5, db.now()))
    with TestClient(app):
        pass
    assert db.q1("SELECT status FROM batches WHERE id=?", (bid,))["status"] == "error"


def test_must_have_is_saved_as_a_subset_of_the_checklist(api, admin):
    pid = db.active_profile(admin["id"])["id"]
    r = api.put(f"/api/profiles/{pid}", json={"criteria": ["Rolled arms", "Under 84 in"], "must_have": ["rolled arms", "Not listed"]})
    assert r.status_code == 200
    assert r.json()["criteria"] == ["Rolled arms", "Under 84 in"] and r.json()["must_have"] == ["Rolled arms"]
    # removing the item from the checklist removes its must-have
    r = api.put(f"/api/profiles/{pid}", json={"criteria": ["Under 84 in"]})
    assert r.json()["must_have"] == []
    # editing other fields leaves must-haves alone
    api.put(f"/api/profiles/{pid}", json={"criteria": ["A", "B"], "must_have": ["B"]})
    assert api.put(f"/api/profiles/{pid}", json={"hunt": "new"}).json()["must_have"] == ["B"]
    assert api.put(f"/api/profiles/{pid}", json={"must_have": []}).json()["must_have"] == []


def test_existing_checklists_start_with_no_must_haves(api, admin):
    assert db.active_profile(admin["id"])["must_have"] == []


def test_old_kindling_cookie_still_signs_you_in_and_moves_to_the_new_name(admin):
    from fastapi.testclient import TestClient
    from app import auth
    from app.main import app
    tok = auth.new_session(admin["id"], "legacy")
    c = TestClient(app)
    c.cookies.set(auth.LEGACY_COOKIE, tok)
    r = c.get("/api/me")
    assert r.status_code == 200 and r.json()["name"] == admin["name"]
    assert auth.COOKIE in r.headers.get("set-cookie", "") and tok in r.headers["set-cookie"]


def test_old_env_names_still_configure_the_app():
    from app import config
    assert config.env("DEFINITELY_UNSET", "dflt") == "dflt"
    import os
    os.environ["KINDLING_TESTONLY"] = "old"
    try:
        assert config.env("TESTONLY") == "old"
        os.environ["ORBIT_TESTONLY"] = "new"
        assert config.env("TESTONLY") == "new"           # the new name wins
    finally:
        os.environ.pop("KINDLING_TESTONLY", None)
        os.environ.pop("ORBIT_TESTONLY", None)


def test_an_existing_kindling_db_is_kept_and_new_installs_use_orbit_db(tmp_path):
    import subprocess, sys, os
    code = "from app import config; print(config.DB_PATH.name)"
    env = {**os.environ, "KINDLING_DATA_DIR": str(tmp_path), "ORBIT_DATA_DIR": ""}
    run = lambda: subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, cwd=Path(__file__).resolve().parents[1]).stdout.strip()
    assert run() == "orbit.db"
    (tmp_path / "kindling.db").write_bytes(b"x")
    assert run() == "kindling.db"
    (tmp_path / "orbit.db").write_bytes(b"x")
    assert run() == "orbit.db"
