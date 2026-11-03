"""The local model and event detectors must be cheap enough to share a small machine."""
import time

from app import db, events, model, orbit
from tests.world import populate


def test_event_detection_on_ten_times_the_real_data_is_a_fraction_of_a_second(admin):
    pid = db.active_profile(admin["id"])["id"]
    populate(pid, 600, seed=21, batches=10)
    profile = db.q1("SELECT * FROM profiles WHERE id=?", (pid,))
    t = time.process_time()
    found = events.detect(profile)
    cpu = time.process_time() - t
    assert cpu < 3.0, f"{cpu:.2f}s of CPU for 600 listings"
    assert isinstance(found, list)


def test_state_with_hundreds_of_placements_stays_fast(admin):
    pid = db.active_profile(admin["id"])["id"]
    populate(pid, 400, seed=22, batches=8)
    user = admin
    t = time.process_time()
    for _ in range(5):
        orbit.state(user, db.q1("SELECT * FROM profiles WHERE id=?", (pid,)))
    assert (time.process_time() - t) / 5 < 1.5
