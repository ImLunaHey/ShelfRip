# Helping with Shelfrip

Thanks for wanting to help. You don't need to write code to make Shelfrip better.

## Without writing code

- **File discs with sharing on.** Every disc you file teaches the shared disc database what's on it,
  so the next person's rip of the same disc is named right first time. It's in Settings, and you
  were asked during setup.
- **Report wrong names.** If Shelfrip picked the wrong movie, put episodes in the wrong order or
  named an extra wrong, [tell us which disc](https://github.com/Shelfrip/ShelfRip/issues/new?template=1-wrong-name.yml).
  These are the most useful reports there are.
- **Send feedback.** The **Feedback** button at the top of the Shelfrip window needs no account.
- **Add your discs to [TheDiscDB](https://thediscdb.com/).** Shelfrip uses it to name extras, so
  every disc added there helps every Shelfrip user too.
- **Tell someone.** A post in your Plex, Jellyfin or disc-collecting community helps more than you'd think.

## Writing code

Shelfrip is plain Python 3.10+ with only the standard library, and a single-page interface in
`review.html`.

```
python app.py              # run it
python tests\run_all.py    # run the tests
```

`tests/record.py` starts Shelfrip in a throwaway folder, which is handy for trying changes without
touching your own settings and shelf.

A quick map of the code:

| File | What it does |
|---|---|
| `app.py` | The local web server behind the window, and the API the page calls |
| `rip_all.py` | Finds drives and runs MakeMKV |
| `identify.py` | Works out what's on a disc: movie or TV, which titles are episodes or extras |
| `extras.py`, `discdb.py`, `crosscheck.py` | Naming extras, recognising known discs, and second opinions from other databases |
| `review.py` | Filing reviewed names into your library |
| `community.py`, `server/` | The shared disc database: the client and the Cloudflare Worker |
| `naming.py`, `paths.py` | File names for each media server, and where Shelfrip keeps its own files |
| `plex.py` | Asking Plex to scan new files and checking it matched them |
| `split.py` | Splitting TV discs by chapter with MKVToolNix |
| `music.py` | Music CDs with cyanrip and MusicBrainz |
| `catalog.py`, `progress.py` | Your disc history, and XP, ranks, streaks, goals and badges |
| `health.py`, `tidy.py` | Spotting problems early, and keeping the rip folder clean |
| `desktop.py`, `launcher.py` | The window, the tray icon and the Windows bits |
| `review.html` | The whole interface |

Before a pull request:

1. Open an issue first for anything bigger than a small fix, so we can agree on the approach.
2. Keep to the standard library. Shelfrip ships as a small installer with nothing to install.
3. Run `python tests\run_all.py`. The same tests run on Windows and Linux for every pull request.
4. If you change how something is named, say which discs you tried it on.

By contributing, you agree your work is released under the [MIT License](LICENSE.txt).
