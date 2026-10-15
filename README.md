# RosterLab

RosterLab is a local, read-only decision engine for the **Insight Fantasy Football** league. Its MVP is model-first: it evaluates the same add/drop move under multiple explicit objectives rather than hiding tradeoffs inside one hand-tuned score.

The current version is a working vertical slice:

- connects to a private ESPN league through ESPN's unofficial v3 read endpoint;
- stores ESPN session cookies in macOS Keychain and never handles the ESPN password;
- syncs actual rosters, roster slots, scoring rules, waiver rules, standings, and matchups;
- saves immutable, timestamped raw snapshots in SQLite;
- records future weekly ESPN projections and historical waiver results;
- builds legal lineups from the league's actual ESPN roster slots;
- generates correlated player outcomes with a Gaussian copula, skewed skill-position marginals, and persistent role uncertainty;
- simulates the remaining schedule and playoff bracket;
- compares add/drop moves with paired Monte Carlo worlds;
- chooses the current-week lineup by simulated matchup win probability;
- calculates title, playoff, short-run, long-run, risk, comparative-advantage, scarcity, and opportunity-cost views;
- finds the Pareto frontier instead of forcing unlike objectives into one score;
- emits a local HTML model lab with weekly score bands and paired-delta histograms;
- labels FAAB bands as the low-confidence heuristic they currently are.

No ESPN cookie is written to the project, snapshot database, or reports by RosterLab. On macOS, interactive login stores the session in Login Keychain.

## Try the complete demo

No installation or third-party Python packages are required. Python 3.9+ is enough.

```bash
python3 -m rosterlab demo --scenario bubble --objective title --iterations 2000
```

The command writes `reports/demo-waiver-board.html`.

Change the decision lens without changing or rerunning the underlying model semantics:

```bash
python3 -m rosterlab demo --objective this_week
python3 -m rosterlab demo --objective floor
python3 -m rosterlab demo --objective playoff_window
python3 -m rosterlab demo --scenario underdog --objective title
python3 -m rosterlab objectives
python3 -m rosterlab lab --iterations 1000
```

`lab` runs contender, bubble, and underdog standings scenarios and writes one complete report per scenario under `reports/model-lab/`.

The current objectives are:

- championship probability;
- playoff probability;
- current matchup win probability;
- expected remaining regular-season wins;
- next-three-week points;
- fantasy-playoff-window points;
- rest-of-season points;
- downside protection, defined as the paired point-change p10;
- upside capture, defined as the paired point-change p90;
- reliability, defined as `P(move helps) - P(move hurts)`;
- comparative advantage versus the median rival roster.

See [docs/MODEL.md](docs/MODEL.md) for exact semantics and assumptions.

## Connect Insight Fantasy Football

ESPN does not offer a documented public fantasy API or OAuth flow. RosterLab opens ESPN for normal sign-in and then accepts the two session cookies used by its read-only fantasy endpoints. It never asks for your ESPN password. The verified cookies are saved in macOS Keychain; the project profile contains no secrets.

```bash
python3 -m rosterlab login --league-id YOUR_LEAGUE_ID --season 2026 --native-dialog
python3 -m rosterlab status --verify
```

On macOS, `--native-dialog` uses two hidden system dialogs that support ordinary
clipboard paste. The cookies are passed to the native Keychain API over standard
input and are never placed in process arguments.

Take the first snapshot:

```bash
python3 -m rosterlab sync
```

Audit the imported rules and rosters:

```bash
python3 -m rosterlab league --show-scoring
python3 -m rosterlab teams
```

The owner team is inferred from the authenticated ESPN member ID, so the usual recommendation command no longer needs `--team-id`:

```bash
python3 -m rosterlab recommend --iterations 5000 --objective title
```

Environment-variable authentication and public leagues are also supported. See [docs/ESPN_SYNC.md](docs/ESPN_SYNC.md) for the complete login, Keychain, sync, inspection, refresh, and logout workflow.

For more stable small deltas, use 5,000 or more iterations after validating that the imported league looks correct.

## Time-safe snapshots

Every sync appends raw inputs with an `observed_at` timestamp and content hash. Nothing is overwritten. To reconstruct a recommendation using only information available at an earlier timestamp:

```bash
python3 -m rosterlab recommend \
  --team-id 1 \
  --as-of '2026-09-22T02:00:00+00:00'
```

Run `sync` whenever information changes materially—at minimum before waivers, after waivers, after final practice reports, and before the Sunday games. Historical truth cannot reconstruct an old information set that was never captured.

## Important limitations of v0.2

- ESPN weekly projections are the current marginal forecast baseline. Prop ingestion is not implemented yet.
- Future projections that ESPN does not publish are visibly labeled as historical, positional, or carry-forward fallbacks.
- The correlation coefficients and persistent-role priors are structurally plausible but have not yet been fitted to historical play-by-play data.
- Current-week lineups optimize win probability among the strongest 32 expected-point lineups. Future weeks use the maximum-mean legal lineup.
- Playoff seeding currently uses wins followed by points-for. Unusual ESPN tiebreakers are not yet modeled.
- FAAB bid bands are heuristic. Conditional player value is simulated; auction clearing prices are not.
- Recommendations are read-only and conditional on the claim succeeding.

These boundaries are intentional. The next valuable work is timestamped prop/consensus ingestion, historical calibration of the joint outcome model, and pooled waiver-market data—not automated ESPN transactions.

## Tests

```bash
python3 -m unittest discover -s tests -v
```
