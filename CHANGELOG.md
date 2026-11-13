# Changelog

All notable changes to BConn are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-11-13

### Added

- Device classification from BlueZ `Icon`, service UUIDs, and the Bluetooth
  Class of Device major and minor classes. Recognised subtypes include
  `smartphone`, `tablet`, `laptop`, `desktop`, `watch`, `keyboard`, `mouse`,
  `printer`, `scanner`, `camera`, and `display`.
- `Other` filter in the scan window for computers, imaging devices,
  wearables, network devices, and unknown hardware.
- OBEX Object Push client over `org.bluez.obex` with transfer progress
  polling and session cleanup.
- `bconn send <device> <file...>` (alias `push`), which pairs on demand and
  reports progress for each file.
- **Send file…** row action and file chooser in the GTK app, shown only for
  devices that advertise OBEX Object Push or File Transfer.
- Friendly OBEX error hints, including how to start `obexd`
  (`systemctl --user start obex.service`).
- `bluez-obexd` to the installer's dependency list.
- CI workflow for pushes and pull requests, and a tag-driven release workflow
  that builds distributions and publishes a GitHub Release.

### Changed

- Phones that also advertise A2DP/HFP profiles are now classified as phones
  instead of audio devices, using icon, Class of Device, and PBAP/MAP UUIDs.
- Device rows show the specific subtype (for example `laptop` or `watch`)
  instead of only the broad kind.
- Scan window empty states now explain what each filter contains, and the
  footer reports `N of M device(s)`.
- `pyproject.toml` reads its version dynamically from `bconn.__version__`, so
  the version is defined in one place.
- Release documentation now covers tags, GitHub Releases, and the workflows.

### Fixed

- The auto-reconnect daemon no longer stops discovery owned by another
  client.

## [0.1.0] - 2026-11-13

### Added

- CLI: `list`, `scan`, `pair`, `connect`, `disconnect`, `forget`, `power`,
  `audio`, `auto`, `info`, and `doctor`.
- GTK 3 tray app with a scan window, pairing dialogs, preferences, device
  details, notifications, and PipeWire audio routing.
- Opt-in per-device auto-reconnect through a `systemd --user` daemon.
- Application-menu shortcut and bundled icon.
- Unit and fake-BlueZ end-to-end tests.

[Unreleased]: https://github.com/d43m0n1z3r/bconn/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/d43m0n1z3r/bconn/compare/604928d...v0.2.0
[0.1.0]: https://github.com/d43m0n1z3r/bconn/commits/604928d
