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

if (HERE / "app.py").exists():
    os.chdir(HERE)
    sys.path.insert(0, str(HERE))
    runpy.run_path(str(HERE / "app.py"), run_name="__main__")
else:
    try:
        import app  # the copy built into the exe (Build Installer.bat)
    except ImportError:
        print(f"app.py isn't next to {sys.executable}. Keep the exe in the same folder as the rest of the app.")
        input("Press Enter to close.")
        sys.exit(1)
    try:
        app.main()
    except Exception:
        traceback.print_exc()
        input("Shelfrip stopped because of the error above. Press Enter to close.")
        sys.exit(1)
