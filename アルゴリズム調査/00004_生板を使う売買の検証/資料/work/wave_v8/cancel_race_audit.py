"""取消と新規条件の同一行成立を、売買結果を変えない観測器で数える。"""

from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path

import pandas as pd

import model
import cross_research as cross


OUT = Path(__file__).resolve().parent


def targets() -> list[dict]:
    """時間順採用・既知五セッション採用・従来追跡対照の条件を抽出する。

    引数: なし。
    返り値: list[dict]。結果順位全体を含めず、採用された条件だけを返す。
    """
    methods = {"P00_0_追跡1ATR_利益保護"}

    def collect(value: object) -> None:
        """採用キーだけを再帰的に探索する。

        引数: value（object）読込済みJSON。
        返り値: None。外側の採用条件集合へ追加する。
        """
        if isinstance(value, dict):
            if isinstance(value.get("採用"), dict):
                methods.add(value["採用"]["方式"])
            for item in value.values():
                collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)

    for filename in ("時間順選択.json", "既知５セッション選択.json", "二銘柄_時間順選択.json", "二銘柄_既知５セッション選択.json"):
        collect(json.loads((OUT / filename).read_text(encoding="utf-8")))
    result = [config for config in model.configs() + cross.configs() if config["id"] in methods]
    assert len(result) == len(methods)
    return result


def observer() -> tuple[object, list[dict], str]:
    """元関数を変更せず、取消直前の同時閾値成立を記録するコピーを生成する。

    引数: なし。
    返り値: tuple[object, list[dict], str]。観測付き関数、記録先、コピーのSHA256。
    """
    source = inspect.getsource(model.simulate)
    needle = "        if pending and (now - pending['created'] > 1500 or direction == -pending['side']):\n            pending = None"
    replacement = """        if pending and (now - pending['created'] > 1500 or direction == -pending['side']):
            audit_side = pending['side']
            audit_quote = a if audit_side > 0 else b
            if direction == -audit_side and i > pending['created_index'] and audit_side * (audit_quote - pending['threshold']) >= 0:
                _audit_races.append(dict(side=audit_side, seq=int(seq[i]), time_s=now,
                                        old_threshold=pending['threshold'], executable_quote=audit_quote,
                                        old_signal_seq=pending['signal_seq'], old_created=pending['created'],
                                        opposite_signal=direction, expiry_also=now - pending['created'] > 1500))
            pending = None"""
    assert source.count(needle) == 1
    instrumented = source.replace(needle, replacement)
    namespace = dict(model.__dict__)
    events = []
    namespace["_audit_races"] = events
    exec(compile(instrumented, "取消競合の読取り専用観測器", "exec"), namespace)
    return namespace["simulate"], events, hashlib.sha256(instrumented.encode("utf-8")).hexdigest()


def main() -> None:
    """採用候補全セッションに観測器を付け、元関数と取引が完全一致するかも確かめる。

    引数: なし。
    返り値: None。衝突件数と各行の価格・時刻を監査JSONへ保存する。
    """
    initial_hash = hashlib.sha256(Path(model.__file__).read_bytes()).hexdigest()
    instrumented, events, observer_hash = observer()
    conditions = targets()
    cells, races = [], []
    for session in model.SESSIONS:
        inputs = {symbol: cross.load(session, symbol) for symbol in model.SYMBOLS}
        for symbol in model.SYMBOLS:
            other_symbol = model.SYMBOLS[1 - model.SYMBOLS.index(symbol)]
            own, peer = inputs[symbol], inputs[other_symbol]
            cross_signals, _ = cross.cross_directions(own, peer)
            for config in conditions:
                signal = cross_signals[config["family"]] if config["family"].startswith("C") else own["signals"][(config["family"], config["window"])]
                args = (own["tape"], own["features"], signal, own["atr"], own["pressure"], config, session, symbol)
                events.clear()
                observed = instrumented(*args)
                original = model.simulate(*args)
                assert observed == original, "観測器により売買結果が変化した"
                cells.append(dict(銘柄=symbol, セッション=session, 条件=config["id"], 同時成立件数=len(events), 売買結果不変=True))
                races.extend(dict(銘柄=symbol, セッション=session, 条件=config["id"], 時刻=pd.Timestamp(row["time_s"], unit="s", tz="Asia/Tokyo").isoformat(), **row) for row in events)
        print(f"取消競合観測完了: {session}", flush=True)
    assert initial_hash == hashlib.sha256(Path(model.__file__).read_bytes()).hexdigest()
    result = dict(元モデルSHA256=initial_hash, 観測器SHA256=observer_hash, 対象条件=[config["id"] for config in conditions],
                  対象セル数=len(cells), 同時成立延べ件数=len(races), 全売買結果不変=True,
                  セル別=cells, 同時成立の詳細=races,
                  解釈="同一raw行で反対方向取消と旧新規閾値が両方成立した観測件数。取消が確実に先に成立する現モデルの仮定を測る指標であり、実際の注文成立件数や損益差ではない。")
    (OUT / "取消成立競合監査.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"取消と旧新規閾値の同時成立: {len(races)} 件、全再生結果不変。", flush=True)


if __name__ == "__main__":
    main()
