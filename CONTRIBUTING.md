# Contributing to BConn

Thanks for taking a look. BConn is a small Python + GTK 3 project; the most
useful contributions are bug reports with a clear reproduction, reliability
improvements, and documentation fixes.

## Before you start

- Read [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) for the architecture, module
  map, and debugging notes.
- For installation and troubleshooting, see [`docs/INSTALL.md`](docs/INSTALL.md).
- Keep the core (`bconn/bluez.py`, `transaction.py`, `audio.py`, `daemon.py`,
  `config.py`) free of GTK imports. Only `bconn/ui/*` may use GTK.
- No new runtime daemon, no root requirement, and no continuous scanning.

## Development loop

```bash
git clone https://github.com/d43m0n1z3r/bconn.git
cd bconn

# One command installs the system packages, the app, the shortcut, and the
# user service. Developers can keep using ./bin/* instead.
sudo ./install.sh

python3 -m unittest discover -s tests -v

./bin/bconn doctor
./bin/bconn --verbose list
./bin/bconn-gui --window
```

The integration tests start their own private `dbus-daemon` and a fake BlueZ
service, so they do not touch your real Bluetooth stack.

## Pull requests

- Keep changes focused; one behavior change per PR.
- Add or update tests for behavior changes. `tests/test_integration_fake.py` is
  the place for end-to-end CLI/daemon coverage.
- Update the docs when user-visible behavior, commands, config keys, or
  installation steps change.
- Match the existing style: type hints, stdlib `unittest`, small pure helpers in
  `bconn/ui/model.py`.
- Run the full suite and the doctor before opening the PR.
- Describe what you tested and on which distro/desktop/Bluetooth device.

## Reporting bugs

Include:

1. `bconn doctor` output (read-only).
2. Distro, desktop, session type (X11/Wayland), BlueZ version.
3. The exact command and the full error (`bconn --verbose …`).
4. Whether the device is paired, trusted, connected, and opted in to
   auto-connect.
5. For daemon issues: `journalctl --user-unit bconn-daemon -n 100`.

Do not paste Bluetooth pairing keys or any secrets. MAC addresses are usually
fine to share, but you can redact the last two octets if you prefer.

## License

BConn is released under the MIT License (see [`LICENSE`](LICENSE)). By
submitting a contribution, you agree that it may be distributed under the same
license.
