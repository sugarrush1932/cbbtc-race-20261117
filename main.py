"""Trough-and-Spark: a selective cbBTC bot for agent-fun/bars-replay/v1.

Design stance, set by the post-mortem of the previous race in this
series: the frozen dev window only decides who races, and last time
its leaderboard anti-predicted the live one - the dev podium finished
at the bottom live, while the live race was won by a single good
directional trade on a nearly flat tape. So this bot is built
live-first. It does not maximise dev-window PnL and it does not trade
often. It waits flat for one of two rare, high-conviction shapes,
commits the whole balance when one appears, and lets a conservative
exit stack carry the risk:

  - Trough (primary): a capitulation slide that is still pinned to
    its lows, at either of two timescales - the deep two-hour form
    (120-bar and 60-bar returns both deeply negative, close in the
    bottom slice of the 120-bar range) or a fast one-hour washout
    (60-bar return nearly as deep, close pinned to the bottom of
    the last hour's range, in a tape that is not in an uptrend).
    No confirmation bar is waited for: on these tapes the
    recoveries start at the trough, and the exit stack, not the
    entry timing, is what protects the trade.
  - Spark (secondary): an explosive bar out of a tight, quiet base
    that has not already run - either a single bar jumping hard on a
    wide intrabar range after a rising 5-bar run, or a 3-bar burst
    closing near its high. A fence on the trailing 20-bar return
    keeps the bot from chasing a move that is already extended.

Exits, shared by both entries, whole position only: a hard stop
below the entry price; a climax exit that sells into a vertical
spike once the trade is deep in profit; a trailing stop under the
peak close that arms once the trade is at or above its entry (it
rides the mid-leg pullbacks this tape produces and cuts soft tops);
an EMA(3/21) cross back down after a grace period; and a maximum
hold as a formality. After a losing trade the bot sits out a short
cooldown; after a winner it may re-enter at once.

Every order names a max slippage measured from the latest close, so
a gap through the next open rejects the order instead of filling at
a bad price, and the signal is simply re-evaluated on the next bar.
The bot is deterministic: it reads only the bars and the account the
harness sends, keeps all state in memory, and uses no clock, no
files and no randomness. Standard library only.
"""

import json
import sys

# --- entry: trough (capitulation) -------------------------------------
TROUGH_RET_120 = -230.0   # 120-bar return at most this (bps)
TROUGH_RET_60 = -168.0    # 60-bar return at most this (bps)
TROUGH_POS_120 = 0.12     # close within this bottom slice of 120 range

# --- entry: sharp trough (fast washout, added after the first bench) --
# The first bench of this bot on the 2026-11-17 dev window made no
# trade at all: that tape's deepest 120-bar slide is only -137 bps,
# so the deep trough above can never fire on it, while its one real
# capitulation is a fast one - a -206 bps 60-bar drop into bar ~574
# that never trades a tick lower afterwards and recovers +120 bps
# over the next two hours. A second, faster trough module covers
# that shape: a 60-bar washout nearly as deep as the deep module's,
# with the close pinned to the bottom of the last hour's range, in
# a two-hour tape that is NOT itself in a downtrend. The diagnostic
# that separates the two shapes is the 120-bar return: at the new
# window's washout it sits between -33 and -11 bps (a flat tape that
# round-tripped a spike), while every mid-collapse bar of the older
# tapes has it at -76 or deeper. So the fast module demands the
# 120-bar return inside a band: deep enough to be a real washout
# context, shallow enough to not be a collapse in progress. The
# band's lower edge is set mid-gap at -50: the older tape's one
# cluster inside the old -100 edge was a capitulation that still
# had -190 bps to fall, and it is exactly what the band now refuses.
SHARP_RET_60 = -150.0     # 60-bar return at most this (bps)
SHARP_RET_120_MIN = -50.0   # 120-bar return at least this (not a collapse)
SHARP_RET_120_MAX = 30.0    # 120-bar return at most this (not an uptrend)
SHARP_POS_60 = 0.15       # close within this bottom slice of 60 range
SHARP_POS_120_MIN = 0.0   # close not below the whole 2h range's low
SHARP_POS_120_MAX = 0.25  # ... and in its bottom quarter
# ... and the fall must have stalled: the current close is no lower
# than the lowest of the previous SHARP_STALL_BARS closes. The first
# version of this module fired the moment the washout thresholds
# crossed and, on the older tape, bought a capitulation that still
# had -190 bps to fall; the stall requirement is what separates a
# finished washout from a falling knife, at the cost of entering a
# few bars after the low.
SHARP_STALL_BARS = 3

# --- entry: spark (ignition out of a base) -----------------------------
BASE_LEN = 25             # bars in the base window
BASE_SPAN_BPS = 130.0     # base closes span at most this (bps)
RUN_FENCE_BPS = 8.0       # 20-bar return must be under this (not run)
SPARK1_RET_1 = 35.0       # single-bar jump at least this (bps)
SPARK1_RANGE = 40.0       # ... on an intrabar range at least this
SPARK1_RET_5 = 60.0       # ... after a 5-bar return at least this
SPARK3_RET_3 = 50.0       # or 3-bar return at least this (bps)
SPARK3_RANGE = 35.0       # ... on an intrabar range at least this
SPARK3_CLOSE_LOC = 0.7    # ... closing in the top part of the bar
SPARK3_RET_5 = 25.0       # ... after a 5-bar return at least this

# --- exits --------------------------------------------------------------
STOP_BPS = 150.0          # hard stop below entry price
TRAIL_BPS = 47.0          # trailing stop under peak close (armed >= entry)
CLIMAX_ARM_BPS = 360.0    # climax exit arms at this profit (bps)
CLIMAX_BAR_BPS = 58.0     # ... and sells a bar jumping at least this
EMA_FAST = 3
EMA_SLOW = 21
GRACE_BARS = 20           # EMA cross-down exit only after this many bars
MAX_HOLD_BARS = 1440

# --- sizing / pacing ------------------------------------------------------
SIZE_FRAC = 1.0           # spend this fraction of cash on an entry
COOLDOWN_LOSS = 10        # bars sat out after a losing trade
MAX_SLIPPAGE_BPS = 150    # every order's slippage cap vs latest close


class Bot:
    """One bot instance per run; state comes only from hello + batches."""

    def __init__(self, hello):
        sym = hello["symbols"][0]
        self.symbol = sym["symbol"]
        self.price_scale = sym["price_scale"]
        self.qty_scale = sym["qty_scale"]
        self.quote_scale = hello["capital"]["quote_scale"]
        self.min_notional = int(hello["fees"]["min_notional_quote_units"])
        self.closes = []            # every close seen, oldest first
        self.ema_fast = None
        self.ema_slow = None
        self._fast_seed = []
        self._slow_seed = []
        self._prev_spread = None    # previous EMA fast-minus-slow
        self.peak_close = 0         # highest close since entry
        self.filled_bar = -1        # bar count when the position appeared
        self.cash_before_entry = None
        self.holding_last = False
        self.rest_until = -10 ** 9  # cooldown: no entries before this bar
        self.orders_sent = 0
        self.bars_seen = 0

    # -- small helpers ----------------------------------------------------

    def _next_id(self):
        self.orders_sent += 1
        return "ord-%d" % self.orders_sent

    def _ema(self, span, value, seed, close):
        """EMA with an SMA seed over the first `span` closes."""
        if value is not None:
            k = 2.0 / (span + 1)
            return value + k * (close - value), seed
        seed = seed + [close]
        if len(seed) == span:
            return sum(seed) / span, seed
        return None, seed

    def _ret(self, n):
        """Return over the last n bars, in bps; 0 until n+1 closes exist."""
        if len(self.closes) <= n:
            return 0.0
        return (self.closes[-1] / self.closes[-1 - n] - 1.0) * 10000.0

    def _range_pos(self, n):
        """Where the current close sits in the prior n closes' range."""
        if len(self.closes) < n + 1:
            return 0.5
        window = self.closes[-n - 1:-1]
        lo, hi = min(window), max(window)
        if hi <= lo:
            return 0.5
        return (self.closes[-1] - lo) / (hi - lo)

    def _entry_price(self, qty, cost_units):
        """Average fill price (wire price units) implied by qty and cost."""
        return cost_units * 10 ** (self.qty_scale + self.price_scale) \
            // (qty * 10 ** self.quote_scale)

    # -- signals ------------------------------------------------------------

    def _trough(self):
        if len(self.closes) < 121:
            return False
        return self._ret(120) <= TROUGH_RET_120 \
            and self._ret(60) <= TROUGH_RET_60 \
            and self._range_pos(120) <= TROUGH_POS_120

    def _sharp_trough(self):
        if len(self.closes) < 121:
            return False
        if not (self._ret(60) <= SHARP_RET_60
                and SHARP_RET_120_MIN <= self._ret(120) <= SHARP_RET_120_MAX
                and self._range_pos(60) <= SHARP_POS_60
                and SHARP_POS_120_MIN <= self._range_pos(120)
                <= SHARP_POS_120_MAX):
            return False
        recent = self.closes[-SHARP_STALL_BARS - 1:-1]
        return self.closes[-1] >= min(recent)

    def _spark(self, high, low, close):
        if len(self.closes) < BASE_LEN + 1:
            return False
        base = self.closes[-BASE_LEN - 1:-1]
        if (max(base) / min(base) - 1.0) * 10000.0 > BASE_SPAN_BPS:
            return False
        if self._ret(20) >= RUN_FENCE_BPS:
            return False
        bar_range = (high / low - 1.0) * 10000.0 if low > 0 else 0.0
        if self._ret(1) >= SPARK1_RET_1 and bar_range >= SPARK1_RANGE \
                and self._ret(5) >= SPARK1_RET_5:
            return True
        if high > low:
            close_loc = (close - low) / (high - low)
        else:
            close_loc = 0.5
        return self._ret(3) >= SPARK3_RET_3 and bar_range >= SPARK3_RANGE \
            and close_loc >= SPARK3_CLOSE_LOC and self._ret(5) >= SPARK3_RET_5

    # -- the per-bar decision -------------------------------------------------

    def on_batch(self, batch):
        account = batch["account"]
        cash = int(account["cash_quote_units"])
        equity = int(account["equity_quote_units"])
        held = None
        for position in account["positions"]:
            if position["symbol"] == self.symbol and int(position["qty"]) > 0:
                held = position
        bar = None
        for candidate in batch["bars"]:
            if candidate["symbol"] == self.symbol:
                bar = candidate
        if bar is None:
            return []

        close = int(bar["c"])
        high = int(bar["h"])
        low = int(bar["l"])
        self.closes.append(close)
        self.bars_seen += 1
        self.ema_fast, self._fast_seed = self._ema(
            EMA_FAST, self.ema_fast, self._fast_seed, float(close))
        self.ema_slow, self._slow_seed = self._ema(
            EMA_SLOW, self.ema_slow, self._slow_seed, float(close))
        spread = None
        if self.ema_fast is not None and self.ema_slow is not None:
            spread = self.ema_fast - self.ema_slow
        crossed_down = spread is not None and self._prev_spread is not None \
            and spread < 0 and self._prev_spread >= 0
        self._prev_spread = spread

        holding = held is not None
        if holding and not self.holding_last:
            self.filled_bar = self.bars_seen
            self.peak_close = close
        if not holding and self.holding_last:
            # The position closed on an earlier reply: rest after a loss.
            if self.cash_before_entry is not None \
                    and cash - self.cash_before_entry <= 0:
                self.rest_until = self.bars_seen + COOLDOWN_LOSS
            self.peak_close = 0
            self.cash_before_entry = None
        self.holding_last = holding

        if holding:
            return self._exit_decision(held, close, crossed_down)
        if self.bars_seen < self.rest_until:
            return []
        if not (self._trough() or self._sharp_trough()
                or self._spark(high, low, close)):
            return []
        notional = int(cash * SIZE_FRAC)
        if notional > equity:
            notional = equity
        if notional < max(1000000, self.min_notional):
            return []
        self.cash_before_entry = cash
        return [{"side": "buy", "client_id": self._next_id(),
                 "symbol": self.symbol,
                 "notional_quote_units": str(notional),
                 "max_slippage_bps": MAX_SLIPPAGE_BPS}]

    def _exit_decision(self, held, close, crossed_down):
        qty = int(held["qty"])
        entry = self._entry_price(qty, int(held["cost_quote_units"]))
        if entry <= 0:
            return []
        if close > self.peak_close:
            self.peak_close = close
        profit_bps = (close / entry - 1.0) * 10000.0
        held_bars = self.bars_seen - self.filled_bar
        sell = False
        if profit_bps <= -STOP_BPS:
            sell = True
        elif profit_bps >= CLIMAX_ARM_BPS and self._ret(1) >= CLIMAX_BAR_BPS:
            sell = True
        elif profit_bps >= 0.0 \
                and close <= self.peak_close * (1.0 - TRAIL_BPS / 10000.0):
            sell = True
        elif crossed_down and held_bars > GRACE_BARS:
            sell = True
        elif held_bars >= MAX_HOLD_BARS:
            sell = True
        if not sell:
            return []
        return [{"side": "sell", "client_id": self._next_id(),
                 "symbol": self.symbol, "qty": str(qty),
                 "max_slippage_bps": MAX_SLIPPAGE_BPS}]


def main():
    bot = None
    stream = sys.stdout
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        message = json.loads(line)
        kind = message.get("type")
        if kind == "hello":
            bot = Bot(message)
        elif kind == "batch":
            orders = bot.on_batch(message)
            reply = {"type": "reply", "seq": message["seq"], "orders": orders}
            stream.write(json.dumps(reply, separators=(",", ":")) + "\n")
            stream.flush()
        elif kind == "done":
            return


if __name__ == "__main__":
    main()
