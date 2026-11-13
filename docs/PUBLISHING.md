# Publishing BConn

A short maintainer checklist for putting BConn on GitHub. Nothing here is
required to run BConn locally.

---

## 1. Before the first push

### Check the repository URLs

All clone URLs already point at `d43m0n1z3r/bconn`. Verify:

```bash
grep -rn "d43m0n1z3r/bconn" README.md CONTRIBUTING.md install.sh docs/
```

If you rename the repository or move it to an organisation, update the URLs
and the installer's default clone address:

```bash
grep -rl "d43m0n1z3r/bconn" README.md CONTRIBUTING.md install.sh docs/ | \
  xargs sed -i 's#d43m0n1z3r/bconn#NEW-OWNER/NEW-REPO#g'
```

### License

BConn is released under the **MIT License**. The repository already contains:

- [`LICENSE`](../LICENSE) with the full MIT text;
- a `License` section in `README.md`;
- `license = "MIT"` and `license-files = ["LICENSE"]` in `pyproject.toml`.

If you ever switch licenses, update all three together.

### Check the version

`bconn/__init__.py` is the single source of truth. `pyproject.toml` declares
`dynamic = ["version"]` and reads the value with:

```toml
[tool.setuptools.dynamic]
version = { attr = "bconn.__version__" }
```

Verify the value and that packaging sees it:

```bash
grep -n "__version__" bconn/__init__.py
python3 -c "import bconn; print(bconn.__version__)"
python3 -m build --sdist --wheel
ls dist/
```

### Run the checks

```bash
python3 -m unittest discover -s tests -v
./bin/bconn doctor
./bin/bconn shortcut status
./bin/bconn daemon status     # if you use the daemon locally
```

All tests must pass. The doctor may report warnings on a machine without a
tray host or notification daemon; blocking failures must be fixed.

---

## 2. Create and push the repository

```bash
cd /path/to/bconn
git init
git add .
git status                    # review what will be committed
git commit -m "BConn 0.1.0: tray-first Bluetooth companion"

git branch -M main
git remote add origin git@github.com:d43m0n1z3r/bconn.git
git push -u origin main
```

Do **not** commit:

- `__pycache__/`, `*.pyc`, build artifacts (already in `.gitignore`);
- local logs or `state.json` (already ignored);
- `~/.config/bconn/` or `~/.local/state/bconn/` (they live outside the repo);
- pairing keys, D-Bus dumps with secrets, or screenshots of personal devices.

---

## 3. Repository settings

Suggested description:

> Tray-first Bluetooth companion for Linux: one-click connect, PipeWire audio
> routing, opt-in auto-reconnect, and actionable diagnostics.

Suggested topics (GitHub tags):

```text
bluetooth  bluez  linux  kali-linux  xfce  gtk3  pygobject  pipewire  tray-app  cli
```

Enable Issues. A `CONTRIBUTING.md` is already included and GitHub will link it
when someone opens a PR.

---

## 4. Verify from a fresh clone

Use a temporary directory so the test does not depend on your local checkout:

```bash
rm -rf /tmp/bconn-check
git clone https://github.com/d43m0n1z3r/bconn.git /tmp/bconn-check
cd /tmp/bconn-check

python3 -m unittest discover -s tests -v
./bin/bconn --version
./bin/bconn doctor
test -x install.sh && echo "installer is executable"
```

Then, if you want to test the full desktop install:

```bash
sudo ./install.sh
bconn --version
bconn doctor
sudo ./install.sh --uninstall
```

---

## 5. Release versioning

BConn uses [Semantic Versioning](https://semver.org/) and tags releases as
`vMAJOR.MINOR.PATCH`. The version lives only in `bconn/__init__.py`; the tag
must match it exactly, or the release workflow fails.

The workflows in `.github/workflows/` are:

- `ci.yml` — runs the test suite on pushes to `main`, pull requests, and when
  called by the release workflow.
- `release.yml` — runs on tags matching `v*`, checks that the tag matches
  `bconn.__version__`, builds the sdist and wheel, and publishes a GitHub
  Release with generated notes and the built files attached.

Both use standard GitHub-hosted runners. For a public repository, Actions
minutes, Releases, and release assets are free.

### Cut a release

1. Pick the next version and update the single source:

   ```bash
   cd /home/daemonizer/Documents/Project/v1/bconn
   # edit bconn/__init__.py, for example: __version__ = "0.2.0"
   ```

2. Add the matching section to `CHANGELOG.md` and move anything from
   `[Unreleased]` into it. Update the comparison links at the bottom.

3. Run the checks from
   [`docs/DEVELOPMENT.md`](DEVELOPMENT.md#8-release-checklist) and commit:

   ```bash
   python3 -m unittest discover -s tests -v
   python3 -m pytest -q
   git add -A
   git commit -m "release: BConn 0.2.0"
   git push origin main
   ```

4. Tag and push the tag. This is what starts the release workflow:

   ```bash
   git tag -a v0.2.0 -m "BConn 0.2.0"
   git push origin v0.2.0
   ```

5. Watch the **Actions** tab. When the workflow finishes, the release is on the
   **Releases** page with generated notes and `bconn-0.2.0.tar.gz` /
   `bconn-0.2.0-py3-none-any.whl` attached.

To publish without Actions (or to fix a failed run), open
**GitHub → Releases → Draft a new release**, select the existing tag, and
publish. Never move or reuse a published tag; bump the version instead.

---

## 6. After publishing

- Add screenshots or a short GIF of the tray menu and scan window to the README
  if you can; a visual is the fastest way to explain the app.
- Keep the "Status" and test-count lines in `README.md` current.
- When behavior changes, update `README.md`, `docs/INSTALL.md`, and
  `docs/DEVELOPMENT.md` in the same PR.
- Re-run the release checklist in
  [`docs/DEVELOPMENT.md`](DEVELOPMENT.md#8-release-checklist).
