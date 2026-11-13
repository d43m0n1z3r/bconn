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

`bconn/__init__.py` and `pyproject.toml` should agree:

```bash
grep -n "__version__" bconn/__init__.py
grep -n "^version" pyproject.toml
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

## 5. First release

```bash
git tag -a v0.1.0 -m "BConn 0.1.0"
git push origin v0.1.0
```

Create a GitHub release from the tag. Suggested notes:

```markdown
First public release.

- CLI: list, scan, pair, connect, disconnect, forget, power, audio, auto,
  info, doctor.
- GTK 3 tray app with scan window, pairing dialogs, preferences, details,
  notifications, and PipeWire audio routing.
- Opt-in per-device auto-reconnect via a systemd --user daemon.
- Application-menu shortcut and bundled icon.
- 73 unit/integration tests against a fake BlueZ service.

Known limitations:
- Installation is one command (`sudo ./install.sh`); `.deb` packaging is not
  ready yet. `pipx install --system-site-packages` also works.
- Focused on Kali/XFCE and BlueZ 5.x; other desktops should work but are
  not verified.
- Auto-connect is opt-in and does not override a manual disconnect.
```

---

## 6. After publishing

- Add screenshots or a short GIF of the tray menu and scan window to the README
  if you can; a visual is the fastest way to explain the app.
- Keep the "Status" and test-count lines in `README.md` current.
- When behavior changes, update `README.md`, `docs/INSTALL.md`, and
  `docs/DEVELOPMENT.md` in the same PR.
- Re-run the release checklist in
  [`docs/DEVELOPMENT.md`](DEVELOPMENT.md#8-release-checklist).
