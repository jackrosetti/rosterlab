from __future__ import annotations

import html
from collections import Counter
from pathlib import Path
from typing import Iterable, Mapping, Optional, Sequence

from .models import DistributionSummary, LeagueState, MoveEvaluation
from .objectives import OBJECTIVE_BY_KEY, ObjectiveDefinition
from .optimizer import RecommendationSet


def write_html_report(
    path: Path,
    state: LeagueState,
    team_id: int,
    recommendations: RecommendationSet,
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    team = state.teams[team_id]
    baseline = recommendations.baseline
    primary = OBJECTIVE_BY_KEY[recommendations.primary_objective]
    top_move = recommendations.moves[0] if recommendations.moves else None
    sources = Counter(forecast.source for forecast in state.forecasts.values())
    source_summary = ", ".join(
        f"{html.escape(key)}: {value}" for key, value in sorted(sources.items())
    )
    faab_note = (
        "Bid bands remain heuristic and low-confidence; the player-value calculations are simulation-based."
        if state.settings.faab_enabled
        else "This league does not use FAAB; use the objective ranks to order claims."
    )
    weekly_chart = _weekly_band_svg(state, baseline.weekly_scores, top_move)
    delta_histogram = (
        _histogram_svg(top_move.paired_points_delta_outcomes) if top_move else ""
    )
    objective_rows = _objective_leader_rows(state, recommendations)
    move_rows = _move_rows(state, recommendations.moves[:24], primary)
    market_rows = _market_rows(state, recommendations.moves[:10])
    top_move_name = (
        f"Add {html.escape(state.players[top_move.add_player_id].name)}, "
        f"drop {html.escape(state.players[top_move.drop_player_id].name)}"
        if top_move
        else "No simulated move"
    )
    body = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>RosterLab Model Lab — {html.escape(team.name)}</title>
  <style>
    :root {{ --ink:#132019; --muted:#667169; --paper:#f2eee4; --card:#fffdf7; --green:#1d5c3b; --green2:#67a879; --lime:#d7ff70; --line:#d8d1c2; --red:#a0443d; }}
    * {{ box-sizing:border-box; }} body {{ margin:0; color:var(--ink); background:var(--paper); font:14px/1.5 ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
    main {{ width:min(1260px,95vw); margin:0 auto; padding:38px 0 72px; }}
    header {{ display:flex; justify-content:space-between; gap:24px; align-items:end; border-bottom:2px solid var(--ink); padding-bottom:22px; }}
    .eyebrow {{ font-size:11px; font-weight:850; letter-spacing:.17em; text-transform:uppercase; color:var(--green); }}
    h1 {{ margin:5px 0 0; font:700 clamp(34px,6vw,66px)/.95 ui-serif,Georgia,serif; letter-spacing:-.045em; }}
    h2 {{ margin:36px 0 12px; font:700 25px/1.1 ui-serif,Georgia,serif; }} h3 {{ margin:0 0 8px; font:700 17px/1.2 ui-serif,Georgia,serif; }}
    .stamp {{ color:var(--muted); text-align:right; max-width:390px; }}
    .cards {{ display:grid; grid-template-columns:repeat(4,1fr); gap:13px; margin:22px 0; }}
    .card,.panel {{ background:var(--card); border:1px solid var(--line); border-radius:16px; padding:17px; box-shadow:0 7px 22px rgba(35,41,36,.045); }}
    .card span,.metric-label {{ color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:.09em; }}
    .card strong {{ display:block; margin-top:5px; font:700 33px/1 ui-serif,Georgia,serif; }}
    .callout {{ background:var(--green); color:white; border-radius:18px; padding:18px 22px; display:grid; grid-template-columns:auto 1fr; gap:18px; align-items:center; }}
    .callout b {{ color:var(--lime); }} .callout .objective {{ font:700 20px ui-serif,Georgia,serif; }}
    .grid2 {{ display:grid; grid-template-columns:1.15fr .85fr; gap:14px; align-items:stretch; }}
    .chart {{ width:100%; overflow:hidden; }} .chart svg {{ display:block; width:100%; height:auto; }}
    .table-wrap {{ overflow:auto; background:var(--card); border:1px solid var(--line); border-radius:16px; }}
    table {{ border-collapse:collapse; width:100%; min-width:900px; }}
    th,td {{ padding:12px 13px; border-bottom:1px solid var(--line); text-align:right; white-space:nowrap; }}
    th:first-child,td:first-child,th:nth-child(2),td:nth-child(2),th:nth-child(3),td:nth-child(3) {{ text-align:left; }}
    th {{ font-size:10px; letter-spacing:.08em; text-transform:uppercase; color:var(--muted); background:#f9f6ee; position:sticky; top:0; }}
    tr:last-child td {{ border-bottom:0; }} .positive {{ color:var(--green); font-weight:780; }} .negative {{ color:var(--red); font-weight:650; }}
    .rank {{ display:inline-grid; place-items:center; width:25px; height:25px; border-radius:50%; background:var(--lime); font-weight:850; }}
    .badge {{ display:inline-block; border:1px solid var(--line); border-radius:999px; padding:2px 8px; font-size:10px; letter-spacing:.05em; text-transform:uppercase; }}
    .pareto {{ border-color:var(--green2); background:#eaf6e9; color:var(--green); }}
    .objective-table td:nth-child(2) {{ font-weight:750; }} .objective-table td:first-child {{ color:var(--muted); }}
    .market {{ display:grid; grid-template-columns:repeat(2,1fr); gap:12px; }}
    .market-card {{ background:var(--card); border:1px solid var(--line); border-radius:14px; padding:15px; }}
    .market-card .line {{ display:flex; justify-content:space-between; gap:12px; margin-top:7px; }} .market-card .line span:first-child {{ color:var(--muted); }}
    .fine {{ color:var(--muted); font-size:12px; }} .footer {{ margin-top:24px; display:grid; grid-template-columns:1.2fr .8fr; gap:14px; }} .footer p {{ color:var(--muted); margin:7px 0; }}
    @media(max-width:850px) {{ header {{ display:block; }} .stamp {{ text-align:left; margin-top:14px; }} .cards {{ grid-template-columns:repeat(2,1fr); }} .grid2,.footer {{ grid-template-columns:1fr; }} .market {{ grid-template-columns:1fr; }} }}
  </style>
</head>
<body><main>
  <header><div><div class="eyebrow">RosterLab / Multi-objective model lab</div><h1>{html.escape(team.name)}</h1></div><div class="stamp">{html.escape(state.settings.name)}<br>Snapshot {html.escape(state.observed_at or "synthetic")}<br>{recommendations.iterations:,} paired worlds · seed {recommendations.seed}</div></header>
  <section class="cards">
    <div class="card"><span>Make playoffs</span><strong>{_pct(baseline.playoff_probability)}</strong></div>
    <div class="card"><span>Win title</span><strong>{_pct(baseline.title_probability)}</strong></div>
    <div class="card"><span>Win this week</span><strong>{_pct(baseline.current_week_win_probability)}</strong></div>
    <div class="card"><span>Week score p10 / p50 / p90</span><strong style="font-size:25px">{baseline.current_week_score.p10:.0f} / {baseline.current_week_score.p50:.0f} / {baseline.current_week_score.p90:.0f}</strong></div>
  </section>
  <div class="callout"><div><div class="metric-label" style="color:#bde3c4">Primary objective</div><div class="objective">{html.escape(primary.label)}</div></div><span><b>{top_move_name}</b><br>{html.escape(primary.description)} Every other objective is calculated and ranked separately. {html.escape(faab_note)}</span></div>

  <h2>Where the objectives disagree</h2>
  <div class="table-wrap"><table class="objective-table"><thead><tr><th>Objective</th><th>Best move</th><th>Value</th><th>Horizon</th><th>Interpretation</th></tr></thead><tbody>{objective_rows}</tbody></table></div>

  <h2>Score distributions</h2>
  <div class="grid2">
    <div class="panel"><h3>Weekly optimal-lineup distribution</h3><div class="fine">Vertical bars are p10–p90; dots are medians. Green is the primary-objective leader.</div><div class="chart">{weekly_chart}</div></div>
    <div class="panel"><h3>Paired rest-of-season point change</h3><div class="fine">The same simulated worlds are subtracted, candidate minus baseline. Zero is no effect.</div><div class="chart">{delta_histogram}</div>{_distribution_copy(top_move)}</div>
  </div>

  <h2>All simulated moves — ranked by {html.escape(primary.label)}</h2>
  <div class="table-wrap"><table><thead><tr><th>#</th><th>Add</th><th>Drop</th><th>Frontier</th><th>Primary value</th><th>Δ title</th><th>Δ playoffs</th><th>Δ this week</th><th>Next 3</th><th>Floor p10</th><th>Upside p90</th><th>P(helps)</th><th>Comp. advantage</th><th>Primary regret</th></tr></thead><tbody>{move_rows}</tbody></table></div>

  <h2>Opportunity cost and league market</h2>
  <div class="market">{market_rows}</div>

  <section class="footer">
    <div class="panel"><h3>Model semantics</h3><p>There is no blended “overall” score. Title odds, playoff odds, immediate wins, expected points, downside, upside, reliability, and league-relative value remain distinct objective functions. Pareto moves are not dominated across title odds, playoff odds, this-week win probability, downside protection, and comparative advantage.</p><p>Skill-position scores use skewed marginals joined by a Gaussian copula. Shared game, offense, pass, rush, opponent, and persistent player-role factors create correlations within and across weeks.</p></div>
    <div class="panel"><h3>Data and uncertainty</h3><p>Forecast records: {source_summary or "none"}.</p><p>Monte Carlo standard errors measure finite simulation noise only. They do not include projection bias, injury-news errors, or misspecified correlations. Rival gain is a roster-slot-free upper bound, not a prediction of their actual claim.</p></div>
  </section>
</main></body></html>"""
    path.write_text(body, encoding="utf-8")
    return path.resolve()


def _objective_leader_rows(state: LeagueState, recommendations: RecommendationSet) -> str:
    rows = []
    for objective in recommendations.objectives:
        leader = min(
            recommendations.moves,
            key=lambda move: move.objective_ranks[objective.key],
        )
        move_name = (
            f"{html.escape(state.players[leader.add_player_id].name)} "
            f"<span class='fine'>for {html.escape(state.players[leader.drop_player_id].name)}</span>"
        )
        rows.append(
            f"<tr><td>{html.escape(objective.label)}</td><td>{move_name}</td>"
            f"<td class='{_delta_class(leader.objective_scores[objective.key])}'>"
            f"{_format_value(leader.objective_scores[objective.key], objective.unit)}</td>"
            f"<td>{html.escape(objective.horizon)}</td><td class='fine'>{html.escape(objective.description)}</td></tr>"
        )
    return "".join(rows)


def _move_rows(
    state: LeagueState,
    moves: Iterable[MoveEvaluation],
    primary: ObjectiveDefinition,
) -> str:
    rows = []
    for rank, move in enumerate(moves, start=1):
        frontier = "<span class='badge pareto'>Pareto</span>" if move.pareto_optimal else ""
        rows.append(
            f"<tr><td><span class='rank'>{rank}</span></td>"
            f"<td><strong>{html.escape(state.players[move.add_player_id].name)}</strong></td>"
            f"<td>{html.escape(state.players[move.drop_player_id].name)}</td><td>{frontier}</td>"
            f"<td class='{_delta_class(move.objective_scores[primary.key])}'>{_format_value(move.objective_scores[primary.key], primary.unit)}</td>"
            f"<td class='{_delta_class(move.title_delta)}'>{_pp(move.title_delta)}</td>"
            f"<td class='{_delta_class(move.playoff_delta)}'>{_pp(move.playoff_delta)}</td>"
            f"<td class='{_delta_class(move.current_week_win_delta)}'>{_pp(move.current_week_win_delta)}</td>"
            f"<td>{move.short_horizon_points_delta:+.1f}</td><td>{move.floor_delta:+.1f}</td>"
            f"<td>{move.upside_delta:+.1f}</td><td>{_pct(move.probability_points_improve)}</td>"
            f"<td>{move.comparative_advantage:+.1f}</td>"
            f"<td>{_format_value(move.objective_regret[primary.key], primary.unit, signed=False)}</td></tr>"
        )
    return "".join(rows)


def _market_rows(
    state: LeagueState,
    moves: Sequence[MoveEvaluation],
) -> str:
    rows = []
    for move in moves:
        add_name = html.escape(state.players[move.add_player_id].name)
        drop_name = html.escape(state.players[move.drop_player_id].name)
        bid = (
            f"${move.bid_low}–${move.bid_high} ({move.bid_confidence.lower()})"
            if move.bid_low is not None
            else "priority claim"
        )
        rows.append(
            f"<div class='market-card'><h3>{add_name} <span class='fine'>↔ {drop_name}</span></h3>"
            f"<div class='line'><span>Your mean lineup gain</span><b>{move.mean_lineup_delta:+.1f} pts</b></div>"
            f"<div class='line'><span>Largest rival gain if available</span><b>{move.max_rival_gain:+.1f} pts</b></div>"
            f"<div class='line'><span>Comparative advantage</span><b>{move.comparative_advantage:+.1f} pts</b></div>"
            f"<div class='line'><span>Drop externality</span><b>{move.drop_externality:+.1f} pts</b></div>"
            f"<div class='line'><span>Positional scarcity vs next FA</span><b>{move.positional_scarcity:+.1f} pts/week</b></div>"
            f"<div class='line'><span>Top-three objective finishes</span><b>{move.top_three_objectives}/{len(move.objective_ranks)}</b></div>"
            f"<div class='line'><span>FAAB band</span><b>{bid}</b></div></div>"
        )
    return "".join(rows)


def _weekly_band_svg(
    state: LeagueState,
    baseline: Mapping[int, DistributionSummary],
    move: Optional[MoveEvaluation],
) -> str:
    if move is None:
        return ""
    weeks = list(state.weeks_remaining)
    width, height = 760, 275
    left, right, top, bottom = 48, 20, 20, 38
    values = []
    for week in weeks:
        values.extend((baseline[week].p10, baseline[week].p90))
        values.extend((move.candidate_weekly_scores[week].p10, move.candidate_weekly_scores[week].p90))
    low = min(values) - 4.0
    high = max(values) + 4.0
    span = max(1.0, high - low)

    def x(index: int) -> float:
        return left + index * (width - left - right) / max(1, len(weeks) - 1)

    def y(value: float) -> float:
        return top + (high - value) * (height - top - bottom) / span

    parts = [f"<svg viewBox='0 0 {width} {height}' role='img' aria-label='Weekly score distribution chart'>"]
    for grid in range(5):
        value = low + grid * span / 4
        y_pos = y(value)
        parts.append(f"<line x1='{left}' y1='{y_pos:.1f}' x2='{width-right}' y2='{y_pos:.1f}' stroke='#ded8cb' stroke-width='1'/>")
        parts.append(f"<text x='{left-7}' y='{y_pos+4:.1f}' text-anchor='end' font-size='10' fill='#68756d'>{value:.0f}</text>")
    for index, week in enumerate(weeks):
        x_pos = x(index)
        base = baseline[week]
        candidate = move.candidate_weekly_scores[week]
        parts.append(f"<line x1='{x_pos-5:.1f}' y1='{y(base.p10):.1f}' x2='{x_pos-5:.1f}' y2='{y(base.p90):.1f}' stroke='#9ba49d' stroke-width='5' stroke-linecap='round'/>")
        parts.append(f"<circle cx='{x_pos-5:.1f}' cy='{y(base.p50):.1f}' r='3.2' fill='#34443a'/>")
        parts.append(f"<line x1='{x_pos+5:.1f}' y1='{y(candidate.p10):.1f}' x2='{x_pos+5:.1f}' y2='{y(candidate.p90):.1f}' stroke='#67a879' stroke-width='5' stroke-linecap='round'/>")
        parts.append(f"<circle cx='{x_pos+5:.1f}' cy='{y(candidate.p50):.1f}' r='3.2' fill='#1d5c3b'/>")
        parts.append(f"<text x='{x_pos:.1f}' y='{height-13}' text-anchor='middle' font-size='10' fill='#68756d'>W{week}</text>")
    parts.append("<rect x='520' y='5' width='9' height='9' rx='2' fill='#9ba49d'/><text x='534' y='13' font-size='10' fill='#68756d'>Baseline</text>")
    parts.append("<rect x='610' y='5' width='9' height='9' rx='2' fill='#67a879'/><text x='624' y='13' font-size='10' fill='#68756d'>Top move</text></svg>")
    return "".join(parts)


def _histogram_svg(values: Sequence[float], bins: int = 22) -> str:
    if not values:
        return ""
    low, high = min(values), max(values)
    if abs(high - low) < 1e-9:
        low -= 1.0
        high += 1.0
    counts = [0] * bins
    for value in values:
        index = min(bins - 1, int((value - low) / (high - low) * bins))
        counts[index] += 1
    width, height = 520, 250
    left, right, top, bottom = 42, 14, 20, 35
    inner_width = width - left - right
    inner_height = height - top - bottom
    max_count = max(counts)
    bar_width = inner_width / bins
    parts = [f"<svg viewBox='0 0 {width} {height}' role='img' aria-label='Paired point change histogram'>"]
    zero_x = left + (0.0 - low) / (high - low) * inner_width
    if left <= zero_x <= width - right:
        parts.append(f"<line x1='{zero_x:.1f}' y1='{top}' x2='{zero_x:.1f}' y2='{height-bottom}' stroke='#a0443d' stroke-width='2' stroke-dasharray='4 4'/>")
    for index, count in enumerate(counts):
        bar_height = inner_height * count / max_count if max_count else 0
        x_pos = left + index * bar_width
        midpoint = low + (index + 0.5) * (high - low) / bins
        color = "#67a879" if midpoint >= 0 else "#c8857f"
        parts.append(f"<rect x='{x_pos+1:.1f}' y='{height-bottom-bar_height:.1f}' width='{max(1,bar_width-2):.1f}' height='{bar_height:.1f}' rx='2' fill='{color}'/>")
    parts.append(f"<line x1='{left}' y1='{height-bottom}' x2='{width-right}' y2='{height-bottom}' stroke='#68756d'/>")
    for fraction in (0.0, 0.5, 1.0):
        value = low + fraction * (high - low)
        x_pos = left + fraction * inner_width
        parts.append(f"<text x='{x_pos:.1f}' y='{height-12}' text-anchor='middle' font-size='10' fill='#68756d'>{value:+.0f}</text>")
    parts.append("</svg>")
    return "".join(parts)


def _distribution_copy(move: Optional[MoveEvaluation]) -> str:
    if move is None:
        return ""
    summary = move.paired_points_delta
    return (
        f"<div class='fine'><b>{_pct(move.probability_points_improve)}</b> of worlds improve; "
        f"<b>{_pct(move.probability_points_decline)}</b> decline.<br>"
        f"Paired delta p10 / median / p90: <b>{summary.p10:+.1f} / {summary.p50:+.1f} / {summary.p90:+.1f}</b> points.</div>"
    )


def _format_value(value: float, unit: str, signed: bool = True) -> str:
    sign = "+" if signed else ""
    if unit == "probability":
        return f"{value * 100:{sign}.1f} pp"
    if unit == "wins":
        return f"{value:{sign}.2f} wins"
    return f"{value:{sign}.1f} pts"


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _pp(value: float) -> str:
    return f"{value * 100:+.1f} pp"


def _delta_class(value: float) -> str:
    return "positive" if value > 0 else ("negative" if value < 0 else "")
