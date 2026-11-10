# Custom mod distribution

## One-time setup (you)

1. Create a **public** GitHub repo and clone it.
2. Copy `publish.py`, `updater.py`, and `manifest.json` into the repo root.
3. Make a `mods/` folder and put your mod folders in it:
   ```
   mods/Excuze-ModName/
   mods/LethalPosters/
   ```
4. Install and log in to the GitHub CLI: `gh auth login`
5. Edit `MANIFEST_URL` at the top of `updater.py` (and `GAME_FOLDER` if it isn't Lethal Company):
   `https://raw.githubusercontent.com/<you>/<repo>/main/manifest.json`
   (change `main` if your default branch differs)
6. Build the exe for friends:
   ```
   pip install pyinstaller
   pyinstaller --onefile --name ModUpdater updater.py
   ```
   Send them `dist/ModUpdater.exe` once. Since you said no self-update, you'll re-send only if the tool itself changes.

Optional `.gitignore`: add `build/` (and `mods/` if you don't want the source in git;
publishing only needs the releases and `manifest.json`).

## Releasing (you)

```
python publish.py                 # publishes every mod whose files changed
python publish.py LethalPosters   # just one
python publish.py --bump minor
python publish.py --dry-run
```

It zips each changed mod (mod folder as the zip's only top-level entry), creates a GitHub Release
per mod/version, records the SHA-256 in `manifest.json`, then commits and pushes the manifest.
The manifest is only updated after the upload succeeds, so friends never see a link to a missing file.

## Updating (friends)

Close the game and r2modman, then run `ModUpdater.exe`. First run asks which r2modman profile
to use and remembers it; after that it just shows what changed and asks to confirm.

Flags: `--yes` (no prompts), `--profile NAME`, `--reset` (pick profile again), `--force` (reinstall all).

## Notes

- Mods are replaced as whole folders inside `BepInEx/plugins`. Configs in `BepInEx/config` are untouched.
- The manifest is fetched from `raw.githubusercontent.com` (not the API), so no API rate limits. It can be
  cached for a few minutes after you push.
- Dependencies from Thunderstore (e.g. LethalLib) still need to be installed in the profile by friends.
