"""Optional: write a note per finished batch into a folder in the Obsidian vault."""
import time
from pathlib import Path

from . import config


def export_batch(profile, batch, rows):
    if not config.OBSIDIAN_DIR:
        return
    root = Path(config.OBSIDIAN_DIR).expanduser()
    if not root.is_dir():
        return
    folder = root / "Batches" / _safe(profile["name"])
    folder.mkdir(parents=True, exist_ok=True)
    date = time.strftime("%Y-%m-%d", time.localtime(batch["finished_at"] or time.time()))
    likes = [r for r in rows if r["verdict"] == "like"]
    passes = [r for r in rows if r["verdict"] != "like"]
    lines = [
        "---",
        f"profile: {profile['name']}",
        f"batch: {batch['number']}",
        f"date: {date}",
        f"liked: {len(likes)}",
        f"passed: {len(passes)}",
        f"queries: [{', '.join(batch['queries'] or [])}]",
        "---",
        f"# {profile['name']} batch {batch['number']}",
        "",
    ]
    if profile.get("taste_summary"):
        lines += ["## Taste so far", profile["taste_summary"], ""]
    lines.append("## Liked (best first)")
    for r in likes:
        lines.append(f"- [{r['title']}]({r['url']}) {r['price_text'] or ''} · {r['location_text'] or ''}")
        if r.get("take"):
            lines.append(f"    - {r['take']}")
    lines += ["", "## Passed"]
    for r in passes:
        lines.append(f"- [{r['title']}]({r['url']}) {r['price_text'] or ''}")
    (folder / f"{date} batch {batch['number']}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _safe(s):
    return "".join(ch for ch in s if ch.isalnum() or ch in " -_").strip() or "Profile"
