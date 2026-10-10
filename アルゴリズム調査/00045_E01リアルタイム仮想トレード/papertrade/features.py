"""E01の確定足指標と、公開を待った気配中値の短期条件を逐次計算する。"""

from __future__ import annotations

from bisect import bisect_right
from copy import deepcopy
from datetime import datetime
import math


TICKS = {"TOPIX": 0.5, "NK225": 10.0}


def timestamp(value: str | float | int) -> float:
    """機能: タイムゾーン付き日時または秒数を有限のUNIX秒へ変換する。

    引数: value(str|float|int) は日時または秒数。
    返り値: UNIX秒(float)。無効な値ではValueErrorを送出する。
    """
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("日時にはタイムゾーンが必要です")
        result = parsed.timestamp()
    else:
        result = float(value)
    if not math.isfinite(result):
        raise ValueError("日時は有限値で指定してください")
    return result


def _number(value: object) -> float | None:
    """機能: JSON値を有限数へ変換し、欠損や非数を除く。

    引数: value(object) は変換対象。返り値: 有限数またはNone(float|None)。
    """
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _asof(rows: list[dict], clock: float, key: str = "available") -> dict | None:
    """機能: 指定時計以前に公開された最後の値を選ぶ。

    引数: rows(list[dict]) は昇順系列、clock(float) は時計、key(str) は時刻列。
    返り値: 公開済みの一行またはNone(dict|None)。
    """
    index = bisect_right([row[key] for row in rows], clock) - 1
    return rows[index] if index >= 0 else None


def _market() -> dict:
    """機能: 一銘柄の保存可能な初期状態を用意する。

    引数: なし。返り値: JSONで保存できる状態(dict)。
    """
    return {"bars": {"60": {}, "300": {}}, "input_index": -1,
            "block": None, "events": [], "direction": 0, "supported": None,
            "last_release": None, "adverse": 0, "adverse_source": -1,
            "adverse_at": None, "last_quote_time": None, "last_received": None}


class FeatureEngine:
    """セッション内で指標を保持し、既知の入力だけをJSON保存可能にする。"""

    def __init__(self, session_id: str, start_timestamp: float, state: dict | None = None):
        """機能: 新しいセッションまたは保存状態から特徴量器を作る。

        引数: session_id(str)、start_timestamp(float)、state(dict|None) は保存状態。
        返り値: なし(None)。セッションを跨ぐ状態流用は拒否する。
        """
        self.session_id = session_id
        self.start = timestamp(start_timestamp)
        self.markets = {symbol: _market() for symbol in TICKS}
        self._models: dict[str, dict] = {}
        if state is not None:
            if state.get("version") != 1 or state.get("session_id") != session_id or state.get("start") != self.start:
                raise ValueError("特徴量の保存状態と対象セッションが一致しません")
            self.markets = deepcopy(state["markets"])

    @classmethod
    def from_state(cls, state: dict) -> FeatureEngine:
        """機能: dump_stateの結果から特徴量器を復元する。

        引数: state(dict) は保存状態。返り値: 復元した器(FeatureEngine)。
        """
        return cls(state["session_id"], state["start"], state)

    def dump_state(self) -> dict:
        """機能: 未公開ブロックを含めて再開に必要な状態を複製する。

        引数: なし。返り値: 有限JSONへ変換できる状態(dict)。
        """
        return {"version": 1, "session_id": self.session_id, "start": self.start,
                "markets": deepcopy(self.markets)}

    def reset_short_history(self, symbol: str | None = None) -> None:
        """機能: 通信断後の短期根拠を破棄し、足と観測連番は維持する。

        引数: symbol(str|None) は対象銘柄。Noneなら両銘柄。
        返り値: なし(None)。保存済みの古い支持を新しい接続へ持ち込まない。
        """
        for selected in (TICKS if symbol is None else (symbol,)):
            market = self.markets[selected]
            for name in ("block", "supported", "last_release", "adverse_at"):
                market[name] = None
            market.update(events=[], direction=0, adverse=0, adverse_source=-1)

    def ingest_candles(self, symbol: str, interval_seconds: int,
                       rows: list[dict], received_at: float) -> int:
        """機能: 確定足を保存し、未確定足と過去の確定値の書換えを拒む。

        引数: symbol(str)、interval_seconds(int) は60または300、
        rows(list[dict]) はcontrollerのdata配列、received_at(float) は実受信時計。
        返り値: 初めて受信した確定足の数(int)。足の取得だけで売買は発生しない。
        """
        if interval_seconds not in (60, 300):
            raise ValueError("1分足または5分足だけを受け付けます")
        received = timestamp(received_at)
        stored = self.markets[symbol]["bars"][str(interval_seconds)]
        pending = {}
        for raw in rows:
            if raw.get("closed") is not True:
                continue
            start = timestamp(raw["time"])
            if start < self.start:
                continue
            values = [_number(raw.get(name)) for name in ("open", "high", "low", "close")]
            if any(value is None or value <= 0 for value in values):
                raise ValueError("確定足の価格が不正です")
            opened, high, low, closed = values
            if high < max(opened, low, closed) or low > min(opened, high, closed):
                raise ValueError("確定足の高安関係が不正です")
            if start + interval_seconds > received + 5:
                raise ValueError("実受信時点より未来の確定足です")
            key = str(start)
            bar = {"time": start, "open": opened, "high": high, "low": low,
                   "close": closed, "received": received}
            existing = stored.get(key, pending.get(key))
            if existing is not None:
                if any(existing[name] != bar[name] for name in ("open", "high", "low", "close")):
                    raise ValueError("取得済みの確定足が変更されました。世代変更を確認してください")
                continue
            pending[key] = bar
        # ----------------------------------------
        # 一括取得の途中で異常を見つけた場合は、正常に見えた前半も反映しない。
        stored.update(pending)
        if pending:
            self._models.pop(symbol, None)
        return len(pending)

    def _model(self, symbol: str) -> dict:
        """機能: セッションの足からATRとEMA方向の公開時系列を作る。

        引数: symbol(str) は銘柄。返り値: ATRと主方向の公開系列(dict)。
        ATRはTRのalpha=1/12平滑・3本以上・最低2呼値。
        EMAはadjust=Falseの15/60本、長期の3本差。初回値は最初の終値。
        過去足をまとめて暖機しても、算出値の利用開始は実受信後である。
        """
        if symbol in self._models:
            return self._models[symbol]
        market = self.markets[symbol]
        atr_rows, main_rows = [], []
        previous = running = None
        received_prefix = self.start
        for index, bar in enumerate(sorted(market["bars"]["300"].values(), key=lambda row: row["time"])):
            high, low, close = (bar[name] for name in ("high", "low", "close"))
            tr = high - low if previous is None else max(high - low, abs(high - previous), abs(low - previous))
            running = tr if running is None else running * (11 / 12) + tr * (1 / 12)
            previous = close
            received_prefix = max(received_prefix, bar["received"])
            nominal = bar["time"] + 360
            atr_rows.append({"nominal": nominal, "available": max(nominal, received_prefix),
                             "value": max(running, 2 * TICKS[symbol]) if index >= 2 else None})
        # ----------------------------------------
        # 過去の各1分足には、その足の公開時計までの5分ATRを対応させる。
        fast = slow = None
        slow_history = []
        direction = 0
        received_prefix = self.start
        available_prefix = self.start
        for index, bar in enumerate(sorted(market["bars"]["60"].values(), key=lambda row: row["time"])):
            close = bar["close"]
            fast = close if fast is None else fast * (1 - 2 / 16) + close * (2 / 16)
            slow = close if slow is None else slow * (1 - 2 / 61) + close * (2 / 61)
            slow_history.append(slow if index >= 59 else None)
            received_prefix = max(received_prefix, bar["received"])
            nominal = bar["time"] + 120
            atr_row = _asof(atr_rows, nominal, "nominal")
            atr = atr_row["value"] if atr_row else None
            available_prefix = max(available_prefix, nominal, received_prefix,
                                   atr_row["available"] if atr_row else self.start)
            gap = (fast - slow) / atr if atr and index >= 59 else None
            prior_slow = slow_history[index - 3] if index >= 3 else None
            slope = (slow - prior_slow) / atr if atr and prior_slow is not None else None
            if gap is None:
                direction = 0
            else:
                if direction * gap < 0:
                    direction = 0
                if slope is not None:
                    if gap > 0.15 and slope > 0.02:
                        direction = 1
                    elif gap < -0.15 and slope < -0.02:
                        direction = -1
            main_rows.append({"nominal": nominal, "available": available_prefix,
                              "direction": direction, "gap": gap, "slope": slope,
                              "fast": fast if index >= 14 else None,
                              "slow": slow if index >= 59 else None})
        result = {"atr": atr_rows, "main": main_rows}
        self._models[symbol] = result
        return result

    def snapshot(self, symbol: str, at: float) -> dict:
        """機能: 指定時点までに実際に利用可能なATRと両市場方向を返す。

        引数: symbol(str)、at(float) は判定時計。
        返り値: ATR・主方向・相手方向・足公開時刻など(dict)。
        相手は自市場への公開からさらに60秒待つ。欠測は方向0とする。
        """
        now = timestamp(at)
        model = self._model(symbol)
        own = _asof(model["main"], now)
        atr_row = _asof(model["atr"], now)
        peer_symbol = "NK225" if symbol == "TOPIX" else "TOPIX"
        peer = _asof(self._model(peer_symbol)["main"], now - 60)
        atr = atr_row["value"] if atr_row else None
        own_direction = own["direction"] if own else 0
        peer_direction = peer["direction"] if peer else 0
        allowed = own_direction if own_direction == peer_direction else 0
        if now < self.start + 1200 or not atr:
            allowed = 0
        return {"atr": atr, "main_direction": own_direction,
                "peer_direction": peer_direction, "allowed_direction": allowed,
                "ema_fast": own["fast"] if own else None,
                "ema_slow": own["slow"] if own else None,
                "main_available": own["available"] if own else None,
                "main_nominal": own["nominal"] if own else None,
                "peer_available": peer["available"] + 60 if peer else None,
                "peer_nominal": peer["nominal"] + 60 if peer else None,
                "atr_available": atr_row["available"] if atr_row else None,
                "atr_nominal": atr_row["nominal"] if atr_row else None}

    def _release(self, symbol: str, received: float, source: dict, index: int,
                 indicators: dict) -> None:
        """機能: 前の取引時刻の最終中値を公開し、H019とB00を更新する。

        引数: symbol(str)、received(float)、source(dict)、index(int)、indicators(dict)。
        返り値: なし(None)。中値は同時刻の最後を次の取引時刻まで封印する。
        """
        market = self.markets[symbol]
        events = market["events"]
        usable = source["mid"] is not None and 0 <= received - source["time"] <= 60
        gap = bool(events and received - events[-1]["available"] > 60)
        event = {"available": received, "source_time": source["time"], "mid": source["mid"],
                 "usable": usable, "gap": gap, "index": index}
        events.append(event)
        # ----------------------------------------
        # 120秒窓の前方参照と最大60秒の鮮度検査に必要な履歴だけを残す。
        while len(events) > 1 and events[1]["available"] < received - 240:
            del events[0]
        if len(events) > 4096:
            del events[:-4096]
        atr = indicators["atr"]
        long_ref = _asof(events, received - 120)
        short_ref = _asof(events, received - 30)
        allowed = indicators["allowed_direction"]
        last_release = market["last_release"]
        supported = market["supported"]
        if (last_release is None or received - last_release > 120 or supported is None
                or received - supported > 120 or market["direction"] != allowed):
            market["direction"] = 0
        # 欠測を跨ぐ古い価格差を新しい30秒の支持として採用しない。
        short_window = [row for row in events if row["available"] > received - 30]
        support_valid = (usable and short_ref and short_ref["usable"] and short_ref["mid"] is not None
                         and received - 30 - short_ref["available"] <= 30
                         and all(row["usable"] and not row["gap"] for row in short_window))
        if not usable or gap:
            market["direction"] = 0
            market["supported"] = None
        if support_valid and atr:
            short = (event["mid"] - short_ref["mid"]) / atr
            if allowed * short > 0.05:
                market["direction"], market["supported"] = allowed, received
        market["last_release"] = received
        # ----------------------------------------
        # B00は120秒と30秒の価格反応が同符号で閾値以上の場合に限る。
        window = [row for row in events if row["available"] > received - 120]
        long_fresh = bool(long_ref and received - 120 - long_ref["available"] <= 60)
        short_fresh = bool(short_ref and received - 30 - short_ref["available"] <= 60)
        valid = (usable and atr and long_fresh and short_fresh and long_ref["usable"]
                 and len(window) >= 5 and all(row["usable"] and not row["gap"] for row in window))
        candidate = 0
        if valid:
            long_change = event["mid"] - long_ref["mid"]
            short_change = event["mid"] - short_ref["mid"]
            long_limit = max(0.25 * atr, 2 * TICKS[symbol])
            short_limit = max(0.1 * atr, TICKS[symbol])
            for side in (-1, 1):
                if side * long_change >= long_limit and side * short_change >= short_limit:
                    candidate = side
        market.update(adverse=candidate, adverse_source=index, adverse_at=received)

    def on_book(self, symbol: str, payload: dict, received_at: float) -> dict:
        """機能: 一件の板PUSHから、その観測後に使える特徴量を返す。

        引数: symbol(str)、payload(dict) は生JSON、received_at(float) は実受信時計。
        返り値: 戦略の入力および監査用時刻・品質(dict)。
        CurrentPriceTimeの逆行・時刻欠損・不正価格は例外とし連番を進めない。
        鮮度上限によるPUSH破棄と接続断後の新規待機は呼出し側で管理する。
        """
        received = timestamp(received_at)
        quoted = timestamp(payload["CurrentPriceTime"])
        price = _number(payload.get("CurrentPrice"))
        if price is None or price <= 0:
            raise ValueError("現在価格が不正です")
        if quoted > received + 5:
            raise ValueError("未来の価格時刻です")
        market = self.markets[symbol]
        if market["last_quote_time"] is not None and quoted < market["last_quote_time"]:
            raise ValueError("価格時刻が逆行しました")
        if market["last_received"] is not None and received < market["last_received"]:
            raise ValueError("受信時計が逆行しました")
        bid_row, ask_row = payload.get("Buy1") or {}, payload.get("Sell1") or {}
        bid, ask = _number(bid_row.get("Price")), _number(ask_row.get("Price"))
        bid_qty, ask_qty = _number(bid_row.get("Qty")), _number(ask_row.get("Qty"))
        valid_quote = (bid is not None and ask is not None and 0 < bid < ask
                       and bid_qty is not None and ask_qty is not None and bid_qty > 0 and ask_qty > 0)
        indicators = self.snapshot(symbol, received)
        index = market["input_index"] + 1
        block = market["block"]
        if block is None or quoted != block["time"]:
            if block and block["mid"] is not None and valid_quote:
                self._release(symbol, received, block, index, indicators)
            block = {"time": quoted, "mid": None}
            market["block"] = block
        if valid_quote:
            block["mid"] = (bid + ask) / 2
        # ----------------------------------------
        # 板イベントのない間にも主方向の撤回と120秒の支持期限を判定する。
        supported = market["supported"]
        if (supported is None or received - supported > 120
                or market["direction"] != indicators["allowed_direction"]):
            market["direction"] = 0
        adverse_valid = market["adverse_at"] is not None and received - market["adverse_at"] <= 60
        market.update(input_index=index, last_quote_time=quoted, last_received=received)
        quality = "有効" if valid_quote else "板不正"
        if indicators["atr"] is None:
            quality = "ATR暖機中"
        elif not indicators["main_direction"] or not indicators["peer_direction"]:
            quality = "方向未確定"
        return {**indicators, "timestamp": received, "price": price, "quote_time": quoted,
                "input_index": index, "direction": market["direction"] if valid_quote else 0,
                "adverse": market["adverse"] if adverse_valid and valid_quote else 0,
                "adverse_source": market["adverse_source"] if adverse_valid and valid_quote else -1,
                "quality": quality, "bid": bid, "ask": ask}
