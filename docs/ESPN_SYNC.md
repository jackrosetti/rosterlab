# ESPN login and league sync

RosterLab uses ESPN's read-only fantasy endpoints. ESPN does not publish a supported fantasy API or OAuth flow, so a private league is authenticated with the `espn_s2` and `SWID` cookies from an ESPN browser session. RosterLab never asks for, receives, or stores an ESPN username or password.

The endpoint and cookie mechanism follow the maintained [`cwendt94/espn-api`](https://github.com/cwendt94/espn-api) implementation. Because the interface is undocumented, the ESPN transport is isolated from the simulator and every successful response is validated before it is stored.

## First connection

Run:

```bash
python3 -m rosterlab login --league-id YOUR_LEAGUE_ID --season 2026 --native-dialog
```

The league ID is the number in the ESPN league URL. The command opens the league page on ESPN. Sign in there normally; RosterLab does not handle the password.

After sign-in, open the browser's developer tools:

1. Select **Application** (Chrome/Edge) or **Storage** (Firefox/Safari).
2. Open **Cookies** for `https://www.espn.com`.
3. Copy the values named `espn_s2` and `SWID` into the two hidden macOS dialogs.

RosterLab verifies both cookies against the requested league before saving anything. On macOS, the pair is stored as one item in Login Keychain under service `com.rosterlab.espn`. The complete arbitrary-length value is sent over standard input to a small native Security-framework helper, never as a process argument. The local `data/rosterlab.json` profile contains only league ID, season, inferred team ID, league name, and last-sync time.

If you prefer a normal interactive shell, omit `--native-dialog` and the same two
values will be requested with hidden terminal prompts.

For a public league:

```bash
python3 -m rosterlab login --league-id YOUR_LEAGUE_ID --season 2026 --public
```

For a non-interactive setup, environment variables remain supported:

```bash
export ESPN_LEAGUE_ID='123456789'
export ESPN_SEASON='2026'
export ESPN_S2='your-cookie-value'
export ESPN_SWID='{YOUR-SWID}'
python3 -m rosterlab login --from-env
```

Environment variables take precedence over Keychain at runtime. They are never copied to the snapshot database. `login --from-env` verifies them and saves them to Keychain for later runs.

## Verify and sync

Verify the live connection without changing local snapshots:

```bash
python3 -m rosterlab status --verify
```

Fetch league settings, every roster, standings, matchups, the NFL schedule, player availability, weekly projections, and historical waiver results:

```bash
python3 -m rosterlab sync
```

All payloads from one successful sync share one `observed_at` timestamp and are committed to SQLite in one transaction. A failed network request does not leave a half-finished snapshot set.

Inspect what was imported:

```bash
python3 -m rosterlab league
python3 -m rosterlab league --show-scoring
python3 -m rosterlab teams
```

The league audit includes:

- roster-slot counts and legal starter positions;
- regular-season and playoff length;
- playoff field size and tiebreaker codes;
- waiver type, reset rule, FAAB budget, and minimum bid;
- scoring type, median-matchup setting, and each ESPN scoring item;
- team names and complete current rosters.

After the first sync, the inferred owner team ID becomes the default for recommendations:

```bash
python3 -m rosterlab recommend --iterations 5000 --objective title
```

## Refresh and removal

ESPN session cookies eventually expire. If `sync` reports that ESPN rejected the session, rerun `login` to replace the Keychain item.

Remove the saved session:

```bash
python3 -m rosterlab logout
```

This removes only the Keychain credentials for the configured league and season. It does not delete snapshots or alter shell environment variables.

## Security boundaries

- Never paste an ESPN password into RosterLab or into chat.
- Cookies are equivalent to an active ESPN session and should be treated as passwords.
- Cookies are not written to source files, the profile, SQLite snapshots, reports, or command output.
- Raw ESPN snapshots can contain league member metadata. Keep `data/rosterlab.sqlite3` private.
- The integration is read-only. It cannot submit lineups, claims, bids, drops, or trades.
