"""
services/paper_trading_analytics.py
=====================================
Pure-function analytics for Paper Trading.

compute_stats()        -- full dashboard stats from a trade list
compute_equity_curve() -- chronological (timestamp, cumulative_pnl) pairs
compute_max_drawdown() -- (absolute_dd, pct_dd) from an equity curve
compute_realtime_stats() -- lightweight stats for live header bar
"""

from __future__ import annotations


def compute_stats(trades: list) -> dict:
    closed = [
        t for t in trades
        if t.get("status") == "CLOSED" and t.get("pnl") is not None
    ]
    open_trades = [t for t in trades if t.get("status") == "OPEN"]
    total = len(closed)
    wins   = [t for t in closed if t.get("result") == "WIN"]
    losses = [t for t in closed if t.get("result") == "LOSS"]
    be     = [t for t in closed if t.get("result") == "BREAKEVEN"]

    total_pnl   = sum(t["pnl"] for t in closed)
    win_pnls    = [t["pnl"] for t in wins]
    loss_pnls   = [t["pnl"] for t in losses]
    avg_profit  = (sum(win_pnls)  / len(win_pnls))  if win_pnls  else 0.0
    avg_loss    = (sum(loss_pnls) / len(loss_pnls)) if loss_pnls else 0.0
    win_rate    = (len(wins)   / total * 100.0) if total else 0.0
    loss_rate   = (len(losses) / total * 100.0) if total else 0.0
    risk_reward = (avg_profit / abs(avg_loss)) if avg_loss != 0 else 0.0

    # Consecutive runs
    best_streak, worst_streak = _streaks(closed)

    # Duration
    durations = [t["duration_seconds"] for t in closed if t.get("duration_seconds")]
    avg_duration = (sum(durations) / len(durations)) if durations else 0.0

    # Largest single trade
    best_trade  = max((t["pnl"] for t in closed), default=0.0)
    worst_trade = min((t["pnl"] for t in closed), default=0.0)

    equity_curve = compute_equity_curve(closed)
    max_dd, max_dd_pct = compute_max_drawdown(equity_curve)

    # Profit factor
    gross_profit = sum(p for p in win_pnls if p > 0)
    gross_loss   = abs(sum(p for p in loss_pnls if p < 0))
    profit_factor = (gross_profit / gross_loss) if gross_loss else 0.0

    return {
        "total_trades":   total,
        "open_trades":    len(open_trades),
        "wins":           len(wins),
        "losses":         len(losses),
        "breakevens":     len(be),
        "win_rate":       win_rate,
        "loss_rate":      loss_rate,
        "total_pnl":      total_pnl,
        "avg_profit":     avg_profit,
        "avg_loss":       avg_loss,
        "risk_reward":    risk_reward,
        "profit_factor":  profit_factor,
        "best_trade":     best_trade,
        "worst_trade":    worst_trade,
        "avg_duration_s": avg_duration,
        "best_streak":    best_streak,
        "worst_streak":   worst_streak,
        "max_drawdown":   max_dd,
        "max_drawdown_pct": max_dd_pct,
        "equity_curve":   equity_curve,
    }


def compute_realtime_stats(trades: list, balance: float, floating_pnl: float) -> dict:
    """Lightweight stats suitable for the live header bar (called every 2 s)."""
    closed = [t for t in trades if t.get("status") == "CLOSED" and t.get("pnl") is not None]
    total  = len(closed)
    wins   = sum(1 for t in closed if t.get("result") == "WIN")
    win_rate = (wins / total * 100.0) if total else 0.0
    total_pnl = sum(t["pnl"] for t in closed)
    equity = balance + floating_pnl
    return_pct = ((equity - balance) / balance * 100.0) if balance else 0.0
    return {
        "equity":    equity,
        "floating":  floating_pnl,
        "total_pnl": total_pnl,
        "win_rate":  win_rate,
        "total":     total,
        "return_pct": return_pct,
    }


def compute_equity_curve(closed_trades: list, starting_balance: float = 0.0) -> list:
    ordered = sorted(
        (t for t in closed_trades if t.get("closed_at")),
        key=lambda t: t["closed_at"],
    )
    curve, running = [], starting_balance
    for t in ordered:
        running += t["pnl"]
        curve.append((t["closed_at"], running))
    return curve


def compute_max_drawdown(equity_curve: list) -> tuple:
    if not equity_curve:
        return 0.0, 0.0
    peak = equity_curve[0][1]
    max_dd = max_dd_pct = 0.0
    for _, value in equity_curve:
        if value > peak:
            peak = value
        dd = peak - value
        if dd > max_dd:
            max_dd = dd
            max_dd_pct = (dd / peak * 100.0) if peak else 0.0
    return max_dd, max_dd_pct


def _streaks(closed: list) -> tuple[int, int]:
    """Return (best_win_streak, worst_loss_streak)."""
    if not closed:
        return 0, 0
    ordered = sorted(closed, key=lambda t: t.get("closed_at") or 0)
    best = worst = cur_w = cur_l = 0
    for t in ordered:
        r = t.get("result", "")
        if r == "WIN":
            cur_w += 1; cur_l = 0
        elif r == "LOSS":
            cur_l += 1; cur_w = 0
        else:
            cur_w = cur_l = 0
        best  = max(best,  cur_w)
        worst = max(worst, cur_l)
    return best, worst
