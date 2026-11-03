"""Runtime configuration, read from environment (.env supported)."""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

def env(name, default=""):
    """ORBIT_<NAME>, falling back to the old KINDLING_<NAME> so existing .env files and services keep working."""
    return os.getenv("ORBIT_" + name) or os.getenv("KINDLING_" + name) or default


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(env("DATA_DIR", ROOT / "data"))
IMG_DIR = DATA_DIR / "images"
# New installs use orbit.db. An existing kindling.db is kept in place (renaming it is a manual migration step, done
# with the service stopped), so upgrading never strands anyone's data.
_NEW_DB, _OLD_DB = DATA_DIR / "orbit.db", DATA_DIR / "kindling.db"
DB_PATH = _OLD_DB if (_OLD_DB.exists() and not _NEW_DB.exists()) else _NEW_DB
STATIC_DIR = ROOT / "static"

# "apify" or "scrapecreators" for real listings, "mock" for fake ones (nothing spent)
SOURCE = env("SOURCE", "mock").strip().lower()
SCRAPECREATORS_API_KEY = os.getenv("SCRAPECREATORS_API_KEY", "").strip()
APIFY_TOKEN = os.getenv("APIFY_TOKEN", "").strip()
APIFY_ACTOR = os.getenv("APIFY_ACTOR", "apify/facebook-marketplace-scraper").strip()
# Apify bills per listing returned, so cap each search
APIFY_RESULTS_PER_QUERY = int(os.getenv("APIFY_RESULTS_PER_QUERY", "20"))

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
# Cheap model screens thumbnails; stronger model does the per-listing deep look
MODEL_SCREEN = env("MODEL_SCREEN", "claude-haiku-5-5")
MODEL_SCORE = env("MODEL_SCORE", "claude-sonnet-5-5")

# Optional: folder in the Obsidian vault to write batch notes into
OBSIDIAN_DIR = env("OBSIDIAN_DIR", "").strip()

# How many photos per listing to download and show Claude
PHOTOS_PER_LISTING = int(env("PHOTOS_PER_LISTING", "3"))
# Share of each batch reserved for "exploration" picks (keeps the model from tunnel vision)
EXPLORE_SHARE = float(env("EXPLORE_SHARE", "0.2"))

DATA_DIR.mkdir(parents=True, exist_ok=True)
IMG_DIR.mkdir(parents=True, exist_ok=True)


def brain_mode() -> str:
    return "claude" if ANTHROPIC_API_KEY else "mock"


def source_mode() -> str:
    if SOURCE == "scrapecreators" and SCRAPECREATORS_API_KEY:
        return "scrapecreators"
    if SOURCE == "apify" and APIFY_TOKEN:
        return "apify"
    return "mock"
