r"""
launcher.py - what Shelfrip.exe runs.

Two kinds of exe are built from it:

  * "Build Exe.bat" (your own PC): the exe holds Python but runs the .py files sitting next to
    it, so updated scripts are picked up without rebuilding.
  * "Build Installer.bat" (the version you give to other people): the whole app is inside the
    exe's folder and there are no .py files next to it.

Whichever it is: if app.py is next to the exe, that copy runs; otherwise the built-in one does.
"""

# Everything the scripts use from Python's standard library, so it's packed into the exe.
import __future__  # noqa: F401
import argparse, collections, csv, datetime, gzip, hashlib, html, http.server, http.client  # noqa: E401,F401
import json, os, pathlib, re, runpy, shutil, socket, sqlite3, ssl, statistics, struct  # noqa: E401,F401
import subprocess, sys, tempfile, threading, time, traceback, webbrowser, zlib  # noqa: E401,F401
import urllib.error, urllib.parse, urllib.request  # noqa: E401,F401
import email, email.message, encodings.idna  # noqa: E401,F401
import base64, ctypes, ctypes.wintypes  # noqa: E401,F401

HERE = pathlib.Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) \
    else pathlib.Path(__file__).resolve().parent

def fail(text: str) -> None:
    """Show an error: in the console if there is one, else in a message box."""
    if sys.stdout is not None and sys.stdin is not None:
        print(text)
        input("Press Enter to close.")
    else:
        try:
            import desktop
            desktop.message_box("Shelfrip", text)
        except Exception:
            pass
    sys.exit(1)


if (HERE / "app.py").exists():
    os.chdir(HERE)
    sys.path.insert(0, str(HERE))
    try:
        runpy.run_path(str(HERE / "app.py"), run_name="__main__")
    except SystemExit:
        raise
    except Exception:
        fail("Shelfrip stopped because of an error:\n\n" + traceback.format_exc()[-1500:])
else:
    try:
        import app  # the copy built into the exe (Build Installer.bat)
    except ImportError:
        fail(f"app.py isn't next to {sys.executable}. Keep the exe in the same folder as the rest of the app.")
    try:
        app.main()
    except SystemExit:
        raise
    except Exception:
        fail("Shelfrip stopped because of an error:\n\n" + traceback.format_exc()[-1500:])
