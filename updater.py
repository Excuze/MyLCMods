#!/usr/bin/env python3
"""
Mod updater for friends. Installs/updates custom mods into an r2modman profile.

Usage:
    updater.py                  interactive (pick profile once, then it's remembered)
    updater.py --yes            no prompts, use remembered profile (good for shortcuts)
    updater.py --profile NAME   use a specific r2modman profile by name
    updater.py --reset          forget the remembered profile and pick again
    updater.py --force          reinstall everything even if versions match

Build to a single exe:
    pip install pyinstaller
    pyinstaller --onefile --name ModUpdater updater.py
"""
import argparse
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

# ---- EDIT THESE -------------------------------------------------------------
MANIFEST_URL = "https://raw.githubusercontent.com/YOUR_USER/YOUR_REPO/main/manifest.json"
GAME_FOLDER = "LethalCompany"  # folder name under r2modmanPlus-local
# -----------------------------------------------------------------------------

APP_DIR = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
CONFIG_FILE = APP_DIR / "updater_config.json"
STATE_NAME = "custom_mods_state.json"  # stored in the profile root, per profile


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "mod-updater/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def profiles_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", ""))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path.home() / ".config"
    return base / "r2modmanPlus-local" / GAME_FOLDER / "profiles"


def choose_profile(args, config) -> Path:
    pdir = profiles_dir()

    if args.profile:
        p = pdir / args.profile
        if not p.is_dir():
            sys.exit(f"Profile '{args.profile}' not found in {pdir}")
        return p

    saved = config.get("profile")
    if saved and not args.reset and Path(saved).is_dir():
        return Path(saved)

    if args.yes:
        sys.exit("No remembered profile. Run once without --yes (or pass --profile NAME).")

    if not pdir.is_dir():
        print(f"Couldn't find r2modman profiles at:\n  {pdir}")
        while True:
            raw = input("Paste the full path to your profile folder: ").strip().strip('"')
            if Path(raw).is_dir():
                return Path(raw)
            print("That folder doesn't exist.")

    profiles = sorted(p for p in pdir.iterdir() if p.is_dir())
    if not profiles:
        sys.exit(f"No profiles found in {pdir}")
    print("Profiles:")
    for i, p in enumerate(profiles, 1):
        print(f"  {i}. {p.name}")
    while True:
        raw = input("Pick a profile number: ").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(profiles):
            return profiles[int(raw) - 1]


def install_mod(name: str, info: dict, plugins: Path) -> None:
    data = fetch(info["url"])
    if hashlib.sha256(data).hexdigest() != info["sha256"].lower():
        raise RuntimeError("download hash mismatch")

    # Work in a temp dir next to plugins (same filesystem, outside the folder BepInEx scans).
    tmp = Path(tempfile.mkdtemp(dir=plugins.parent, prefix=".updater_"))
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = [n for n in z.namelist() if n.strip("/")]
            if {n.replace("\\", "/").split("/")[0] for n in names} != {name}:
                raise RuntimeError(f"zip must contain only the '{name}' folder at top level")
            root = tmp.resolve()
            for n in names:  # zip-slip guard
                dest = (tmp / n).resolve()
                if dest != root and root not in dest.parents:
                    raise RuntimeError("unsafe path in zip")
            z.extractall(tmp)

        new_dir = tmp / name
        target = plugins / name
        old_dir = tmp / "_old"
        had_old = target.exists()
        try:
            if had_old:
                shutil.move(str(target), str(old_dir))
            shutil.move(str(new_dir), str(target))
        except PermissionError:
            # roll back if we'd already moved the old copy away
            if had_old and old_dir.exists() and not target.exists():
                shutil.move(str(old_dir), str(target))
            raise RuntimeError("files are locked - close the game and r2modman, then try again")
        except Exception:
            if had_old and old_dir.exists() and not target.exists():
                shutil.move(str(old_dir), str(target))
            raise
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def pause(args):
    if not args.yes:
        try:
            input("\nPress Enter to exit...")
        except EOFError:
            pass


def main():
    ap = argparse.ArgumentParser(description="Install/update custom mods into an r2modman profile.")
    ap.add_argument("--yes", "-y", action="store_true", help="no prompts; use remembered profile")
    ap.add_argument("--profile", help="r2modman profile name to use")
    ap.add_argument("--reset", action="store_true", help="forget the remembered profile")
    ap.add_argument("--force", action="store_true", help="reinstall all mods")
    args = ap.parse_args()

    config = load_json(CONFIG_FILE, {})
    profile = choose_profile(args, config)
    config["profile"] = str(profile)
    try:
        CONFIG_FILE.write_text(json.dumps(config, indent=2), encoding="utf-8")
    except OSError:
        pass  # not fatal; we'll just ask again next time

    plugins = profile / "BepInEx" / "plugins"
    plugins.mkdir(parents=True, exist_ok=True)
    state_file = profile / STATE_NAME
    state = load_json(state_file, {})

    print(f"Profile: {profile.name}")
    try:
        manifest = json.loads(fetch(MANIFEST_URL).decode("utf-8"))
        mods = manifest["mods"]
    except Exception as e:
        print(f"Couldn't fetch the mod list: {e}")
        pause(args)
        sys.exit(1)

    todo = []
    for name, info in mods.items():
        installed = state.get(name)
        if args.force or installed != info["version"] or not (plugins / name).is_dir():
            todo.append(name)
            print(f"  {name}: {installed or 'not installed'} -> {info['version']}")
        else:
            print(f"  {name}: up to date ({installed})")

    if not todo:
        print("\nEverything is up to date.")
        pause(args)
        return

    if not args.yes and input(f"\nInstall/update {len(todo)} mod(s)? [Y/n] ").strip().lower() not in ("", "y", "yes"):
        return

    failures = 0
    for name in todo:
        info = mods[name]
        print(f"Installing {name} {info['version']}...", end=" ", flush=True)
        try:
            install_mod(name, info, plugins)
            state[name] = info["version"]
            state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")
            print("done")
        except Exception as e:
            failures += 1
            print(f"FAILED ({e})")

    print(f"\nFinished. {len(todo) - failures} updated, {failures} failed.")
    pause(args)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
