# Linux support

Linux support is experimental and runs from source. The shared naming, review,
filing and subtitle-processing code remains the same as on Windows.

## Running

Install Python 3.10 or later and the native Linux version of MakeMKV, including
`makemkvcon`. Configure MakeMKV's licence separately. Put `makemkvcon` on PATH or
select its full executable path under Settings > Programs.

From the checkout:

```sh
python3 app.py
```

The interface opens in Chromium/Chrome app mode when available, otherwise in your
default browser. You can also open `http://127.0.0.1:8765` yourself. Keep the terminal
running. `python3 app.py --background` starts the server without opening a browser;
it does not daemonize the process. Use the page's Quit button to exit.

Set Linux paths for the rip and library folders, for example `/home/you/Ripped`
and `/home/you/Media`. Settings live in `$XDG_CONFIG_HOME/shelfrip`, or
`~/.config/shelfrip`. `SHELFRIP_DATA` overrides this location. Newly saved settings
have mode 0600 because API keys and the OpenSubtitles password are stored there.
The OpenSubtitles password is **not encrypted** on Linux.

System tools used by the Linux integration:

- `udevadm`: cached optical-drive/media discovery, without launching a new MakeMKV
  scan every poll. Usually supplied by the system's udev/systemd package.
- `eject`: opens a drive's tray. Failures are reported rather than treated as success.
- `xdg-open` (xdg-utils): opens files, video players and report folders.
- `zenity` or `kdialog`: native file/folder dialogs. KDE prefers kdialog when
  available. If neither is installed, type paths into settings.
- `notify-send` (libnotify): optional desktop notifications.
- `cyanrip`: audio-CD ripping. CD drive offsets accept `/dev/sr0=6, /dev/sr1=667`.
- MKVToolNix (`mkvmerge`, `mkvextract`, `mkvpropedit`): media inspection and splitting.
- `tesseract`: optional subtitle OCR.

Desktop tools need a graphical login session. They are optional for using the
local web interface on a headless machine. Drive access is still required for ripping.

## Distribution compatibility

The application uses standard Linux interfaces and discovers external tools on
PATH. It does not require a specific distribution, package manager or init system.
Install the tools above using your distribution's packages or the tool's own Linux
installation instructions; package names and availability vary. No Python packages
from pip are required.

Optical-drive discovery uses sysfs and udev's cached properties. This needs a running
udev-compatible device manager and `udevadm`, but does not require systemd as PID 1.
Containers and restricted environments must expose the optical devices and the
necessary system interfaces to use hardware features.

Headless systems can use the local web interface without desktop helper programs.
For desktop features, install the appropriate helpers listed above and run Shelfrip
in your graphical login session. Missing optional helpers do not prevent ripping.

## Drives and permissions

Devices are identified by their Linux path (such as `/dev/sr0`), not by assuming
sysfs order matches MakeMKV's drive indices. `/dev/cdrom` aliases are accepted for
ejection and offset configuration. Ejection validates that the resolved path is
an optical block device before invoking `eject`.

If a drive is visible but cannot be read, inspect its permissions and the matching
SCSI generic device's permissions. Configure access through your distribution's
udev rules, session ACLs or optical-drive group, then sign in again if group
membership changed. Do not run Shelfrip as root. A USB DVD drive can test DVDs and
audio CDs; Blu-ray/4K testing requires a compatible drive.

If udev discovery is unavailable, video drive discovery falls back to MakeMKV.
That fallback may scan other drives, and does not provide Linux audio-CD detection.

## Tests and real hardware validation

```sh
python3 tests/test_linux.py
python3 tests/run_all.py
```

The Linux tests cover fake sysfs/udev discovery, empty and loaded drives, audio CDs,
Unicode labels, stable device selection, busy-drive handling, TOC parsing (including
enhanced CDs), read failures, eject failures, desktop helpers, process ownership,
settings permissions and starting the real application with an isolated data folder.
The application smoke test requests the HTML, settings, version and drive-status APIs,
then stops its child process. No tests eject a physical drive or start a real rip.

Before calling Linux support hardware-validated, test with a separate rip/library
folder and auto-rip/auto-file disabled:

1. Connect an empty drive; confirm it appears. Insert a DVD; confirm the label and
   loaded state change. Remove/reinsert it and unplug/reconnect the USB drive.
2. Rip a DVD, review its files, play a title, then file it into the test library.
   Confirm the expected files and automatic ejection. Test manual ejection too.
3. Cancel a rip; confirm its MakeMKV process stops. Retry the disc and check recovery.
4. Insert an audio CD; confirm detection and a stable MusicBrainz disc ID, then rip
   with cyanrip and check track count, durations, FLAC tags and filing.
5. With two drives, rip concurrently and confirm polling does not interrupt either.
6. Test folder selection, playback, notifications and app-window behaviour in actual
   GNOME/KDE sessions, including Wayland. Headless API tests do not establish this.

## Remaining Windows parity work

- Native Linux tray/background lifecycle and restart controls.
- Linux installer/packages and an appropriate update mechanism. The Windows
  installer/update flow is not a Linux updater.
- Reading CD-Text from audio discs on Linux. MusicBrainz lookup works independently.
- Mounted-disc fingerprinting and TheDiscDB scanner integration, which still use
  Windows drive-root assumptions in the application.
- Desktop keyring storage for passwords, instead of permission-restricted settings.
- Full physical-drive and graphical-session testing as listed above.

Linux support does not yet provide complete Windows feature parity.
