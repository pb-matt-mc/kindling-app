"""Runtime configuration, read from environment (.env supported)."""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("KINDLING_DATA_DIR", ROOT / "data"))
IMG_DIR = DATA_DIR / "images"
DB_PATH = DATA_DIR / "kindling.db"
STATIC_DIR = ROOT / "static"

# "apify" or "scrapecreators" for real listings, "mock" for fake ones (nothing spent)
SOURCE = os.getenv("KINDLING_SOURCE", "mock").strip().lower()
SCRAPECREATORS_API_KEY = os.getenv("SCRAPECREATORS_API_KEY", "").strip()
APIFY_TOKEN = os.getenv("APIFY_TOKEN", "").strip()
APIFY_ACTOR = os.getenv("APIFY_ACTOR", "apify/facebook-marketplace-scraper").strip()
# Apify bills per listing returned, so cap each search
APIFY_RESULTS_PER_QUERY = int(os.getenv("APIFY_RESULTS_PER_QUERY", "20"))

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
# Cheap model screens thumbnails; stronger model does the per-listing deep look
MODEL_SCREEN = os.getenv("KINDLING_MODEL_SCREEN", "claude-haiku-5-5")
MODEL_SCORE = os.getenv("KINDLING_MODEL_SCORE", "claude-sonnet-5-5")

# Optional: folder in the Obsidian vault to write batch notes into
OBSIDIAN_DIR = os.getenv("KINDLING_OBSIDIAN_DIR", "").strip()

# How many photos per listing to download and show Claude
PHOTOS_PER_LISTING = int(os.getenv("KINDLING_PHOTOS_PER_LISTING", "3"))
# Share of each batch reserved for "exploration" picks (keeps the model from tunnel vision)
EXPLORE_SHARE = float(os.getenv("KINDLING_EXPLORE_SHARE", "0.2"))

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
