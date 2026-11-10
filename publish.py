#!/usr/bin/env python3
"""
Publish changed mods: zip -> GitHub Release -> update manifest.json -> commit & push.

Requires: git, and the GitHub CLI (`gh`) logged in (`gh auth login`).

Layout (run from the repo root):
    mods/
        Excuze-ModName/     <- your mod folders, exactly as they go in BepInEx/plugins
        LethalPosters/
    manifest.json

Usage:
    python publish.py                      publish every mod whose contents changed (patch bump)
    python publish.py LethalPosters        only that mod
    python publish.py --bump minor         bump minor instead of patch
    python publish.py --force LethalPosters   republish even if unchanged
    python publish.py --dry-run            show what would happen
    python publish.py --no-push            update manifest locally, don't commit/push
"""
import argparse
import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MODS_DIR = ROOT / "mods"
BUILD_DIR = ROOT / "build"
MANIFEST = ROOT / "manifest.json"
IGNORED = {".git", ".DS_Store", "Thumbs.db", "__pycache__"}


def run(*cmd, capture=False):
    return subprocess.run(cmd, cwd=ROOT, check=True, text=True, capture_output=capture)


def files_in(folder: Path):
    return sorted(
        p for p in folder.rglob("*")
        if p.is_file() and not any(part in IGNORED for part in p.relative_to(folder).parts)
    )


def folder_hash(folder: Path) -> str:
    """Hash of file paths + contents, so we only republish when something really changed."""
    h = hashlib.sha256()
    for f in files_in(folder):
        h.update(f.relative_to(folder).as_posix().encode())
        h.update(b"\0")
        h.update(f.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def zip_mod(folder: Path, out: Path) -> None:
    """Zip with the mod folder as the single top-level entry."""
    out.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files_in(folder):
            z.write(f, (Path(folder.name) / f.relative_to(folder)).as_posix())


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bump(version: str, part: str) -> str:
    major, minor, patch = (int(x) for x in version.split("."))
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mods", nargs="*", help="mod folder names (default: all in mods/)")
    ap.add_argument("--bump", choices=["patch", "minor", "major"], default="patch")
    ap.add_argument("--force", action="store_true", help="publish even if unchanged")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-push", action="store_true")
    args = ap.parse_args()

    if not MODS_DIR.is_dir():
        sys.exit(f"Missing {MODS_DIR}. Put your mod folders in a 'mods' directory.")

    manifest = json.loads(MANIFEST.read_text("utf-8")) if MANIFEST.exists() else {"mods": {}}
    manifest.setdefault("mods", {})

    available = sorted(d.name for d in MODS_DIR.iterdir() if d.is_dir() and d.name not in IGNORED)
    selected = args.mods or available
    unknown = [m for m in selected if m not in available]
    if unknown:
        sys.exit(f"Not found in mods/: {', '.join(unknown)}")

    slug = None
    published = []

    for name in selected:
        folder = MODS_DIR / name
        content = folder_hash(folder)
        entry = manifest["mods"].get(name)

        if entry and entry.get("content") == content and not args.force:
            print(f"{name}: unchanged ({entry['version']})")
            continue

        version = bump(entry["version"], args.bump) if entry else "1.0.0"
        print(f"{name}: {entry['version'] if entry else 'new'} -> {version}")
        if args.dry_run:
            continue

        if slug is None:
            slug = run("gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner",
                       capture=True).stdout.strip()

        zip_path = BUILD_DIR / f"{name}.zip"
        zip_mod(folder, zip_path)
        tag = f"{name}-v{version}"

        # Upload first; only point the manifest at it once the asset exists.
        run("gh", "release", "create", tag, str(zip_path),
            "--title", f"{name} {version}", "--notes", f"{name} {version}")

        manifest["mods"][name] = {
            "version": version,
            "url": f"https://github.com/{slug}/releases/download/{tag}/{name}.zip",
            "sha256": sha256_file(zip_path),
            "content": content,
        }
        MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", "utf-8")  # save after each success
        published.append(f"{name} {version}")

    if args.dry_run:
        return
    if not published:
        print("Nothing to publish.")
        return

    if args.no_push:
        print("Manifest updated locally (not pushed).")
        return

    run("git", "add", "manifest.json")
    run("git", "commit", "-m", "Publish: " + ", ".join(published))
    run("git", "push")
    print("\nPublished: " + ", ".join(published))


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        sys.exit(f"\nCommand failed: {' '.join(map(str, e.cmd))}")
