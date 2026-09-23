from __future__ import annotations

import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
FILES = ("index.html", "styles.css", "responsive.css", "github-pages.css", "sample-groups.css", "results.css", "app.js")
DIRECTORIES = ("templates",)


def main() -> None:
    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir(parents=True)
    for relative in FILES:
        shutil.copy2(ROOT / relative, DIST / relative)
    for relative in DIRECTORIES:
        shutil.copytree(ROOT / relative, DIST / relative)
    (DIST / ".nojekyll").write_text("", encoding="utf-8")


if __name__ == "__main__":
    main()
