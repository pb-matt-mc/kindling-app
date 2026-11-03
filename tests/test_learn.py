from app import db, learn


def mk_listing(pid, tags, rank, verdict=None, fb="x", keeper=0):
    bid = db.q1("SELECT id FROM batches WHERE profile_id=?", (pid,)) or {"id": db.ex(
        "INSERT INTO batches (profile_id, number, status, size, created_at) VALUES (?,?,?,?,?)", (pid, 1, "done", 5, db.now()))}
    lid = db.ex("INSERT INTO listings (profile_id, batch_id, fb_id, title, tags, created_at) VALUES (?,?,?,?,?,?)",
                (pid, bid["id"], fb, "t", db.dumps(tags), db.now()))
    db.ex("INSERT INTO swipes (listing_id, verdict, rank, manual, swiped_at) VALUES (?,?,?,0,?)",
          (lid, verdict or ("like" if rank >= .5 else "dislike"), rank, db.now()))
    return lid


def pid_of(admin):
    return db.active_profile(admin["id"])["id"]


def test_no_swipes_means_neutral_prior(admin):
    w, mean = learn.weights(pid_of(admin))
    assert w == [] and mean == 0.5


def test_liked_trait_gets_positive_weight_shrunk_toward_zero(admin):
    p = pid_of(admin)
    for i in range(4):
        mk_listing(p, ["color:green"], .75, fb=f"a{i}")
        mk_listing(p, ["color:grey"], .25, fb=f"b{i}")
    w = {x["tag"]: x["weight"] for x in learn.weights(p)[0]}
    assert w["color:green"] > 0 > w["color:grey"]
    assert abs(w["color:green"]) < 0.25  # raw offset is .25; shrinkage pulls it in


def test_one_sighting_moves_less_than_many(admin):
    p = pid_of(admin)
    mk_listing(p, ["rare:one"], .75, fb="r")
    for i in range(6):
        mk_listing(p, ["common:x"], .75, fb=f"c{i}")
        mk_listing(p, ["other:y"], .25, fb=f"d{i}")
    w = {x["tag"]: x["weight"] for x in learn.weights(p)[0]}
    assert abs(w["rare:one"]) < abs(w["common:x"])


def test_model_score_clamps_to_unit_interval():
    assert learn.model_score(["a"], {"a": 5}, .5) == 1.0
    assert learn.model_score(["a"], {"a": -5}, .5) == 0.0


def test_blend_share_grows_with_swipes_and_is_capped():
    assert learn.blend(80, 0.2, 0) == 0.8                      # no swipes: Claude only
    full = learn.blend(80, 0.2, 10_000)
    assert abs(full - (0.4 * 0.8 + 0.6 * 0.2)) < 1e-9          # model never exceeds 60%
    assert learn.blend(None, 0.2, 0) == 0.5


def test_effective_swipes_counts_crystals_with_fade(admin):
    p = pid_of(admin)
    mk_listing(p, ["a:b"], .75, fb="z")
    for n, k in enumerate((10, 10)):
        db.ex("INSERT INTO crystals (profile_id, number, n_listings, mean, created_at) VALUES (?,?,?,?,?)",
              (p, n + 1, k, .5, db.now()))
    assert learn.effective_swipes(p) == 1 + 10 * 1 + 10 * 0.5
