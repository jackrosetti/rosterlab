# RosterLab model contract

RosterLab keeps forecasting, joint-outcome generation, league simulation, and decision objectives separate. That separation is the core contract of the MVP.

## 1. Marginal player distributions

Each player-week forecast contains a mean, standard deviation, team, opponent, and persistent-role loading.

- RB, WR, and TE outcomes use shifted lognormal marginals to represent right-skew and spike weeks.
- QB, K, and D/ST outcomes currently use bounded normal marginals.
- A zero mean produces a deterministic zero, which handles explicit bye-week forecasts.

The system does not claim these marginals are calibrated yet. Their source and any fallback status remain visible in the report.

## 2. Dependence structure

A Gaussian copula joins the marginals. A standardized player outcome is driven by:

```text
game factor
+ team offense factor
+ team passing or rushing factor
+ opponent offense factor where applicable
+ persistent player-role factor
+ idiosyncratic weekly noise
```

Passing and rushing factors are negatively related. The persistent role factor is sampled once per player and simulation world, then reused across weeks. It represents season-level uncertainty such as a committee takeover, fragile depth-chart role, or true breakout.

The same simulated world is reused for the baseline and every candidate move. This common-random-number design substantially reduces the noise of small counterfactual deltas.

## 3. Lineups and league seasons

The lineup solver exactly respects ESPN slot eligibility using dynamic programming over lineup-slot bitmasks.

- Future lineups maximize expected points.
- For the current matchup, the strongest legal lineup candidates are simulated directly against the actual opponent. The lineup with the highest matchup win probability is selected.
- Every remaining regular-season matchup is resolved.
- Standings use wins and then points-for.
- The configured number of playoff teams is seeded and the bracket is simulated through the title.

Each move therefore produces distributions for weekly scores, current matchup margin, next-three-week points, rest-of-season points, remaining wins, regular-season finish, playoff qualification, and championship outcome.

## 4. Objective functions

RosterLab intentionally has no blended “overall value.” It calculates independent objectives:

| Key | Quantity maximized |
| --- | --- |
| `title` | Change in championship probability |
| `playoffs` | Change in playoff probability |
| `this_week` | Change in current matchup win probability |
| `expected_wins` | Change in expected remaining standings wins |
| `next_3_points` | Paired expected optimal-lineup point change over three weeks |
| `playoff_window` | Paired expected point change during fantasy playoff weeks |
| `rest_points` | Paired expected point change across all remaining weeks |
| `floor` | 10th percentile of the paired rest-of-season point change |
| `upside` | 90th percentile of the paired rest-of-season point change |
| `reliability` | `P(point change > 0) - P(point change < 0)` |
| `comparative_advantage` | Your deterministic lineup gain minus the median rival gain from the same player |

Changing the primary objective only changes ordering. It does not alter the simulation or other calculations.

## 5. Comparative advantage and opportunity cost

For every candidate player, the model temporarily adds that player to each rival roster and measures the marginal optimal-lineup gain. This is deliberately described as a roster-slot-free upper bound; it is not a prediction of whom the rival would drop.

The report shows:

- your exact lineup gain for the specified add/drop pair;
- the median and maximum rival marginal gain;
- comparative advantage over the median rival;
- positional scarcity versus the next available free agent at that position;
- the maximum rival value created by making your dropped player available;
- objective regret: the value surrendered relative to the best evaluated move under each objective.

FAAB bands are not part of the simulation-derived value. They remain a visibly low-confidence heuristic until pooled auction data exists.

## 6. Risk and distributions

Risk is reported, not chosen through a vague risk-tolerance slider.

- p10 and lower-tail CVaR describe downside.
- p90 and upper-tail CVaR describe upside.
- standard deviation describes dispersion.
- `P(helps)` and `P(hurts)` describe the sign of the paired counterfactual.
- Weekly p10–p90 bands show when a move changes the roster rather than only its season aggregate.

The Pareto frontier contains moves not dominated simultaneously on title odds, playoff odds, current-week win probability, downside protection, and comparative advantage.

## 7. What remains uncalibrated

Before treating outputs as decision-grade, fit and validate:

1. Position-specific marginal families and tail behavior.
2. Game, offense, pass, rush, and opponent factor loadings.
3. Cross-week role persistence by player archetype.
4. Injury and inactive probabilities.
5. Projection-source bias and dispersion.
6. ESPN-specific playoff tiebreakers and unusual scoring formats.

Validation should use proper scoring rules, interval coverage, empirical correlation matrices, and prospective timestamped snapshots. A fantasy title is far too noisy to serve as the primary model metric.
