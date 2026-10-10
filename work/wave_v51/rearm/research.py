"""失敗した価格帯への同方向再試行を制限する24条件を固定し、逐次検証する。"""
from __future__ import annotations

from copy import deepcopy
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BASES = ('K00', 'K04', 'K20', 'K24')
SYMBOLS = ('TOPIX', 'NK225')


def read(path: Path) -> object:
    """機能: 保存JSON又はgzip台帳を読む。

    引数: path(Path)。返り値: object は内容。
    """
    raw = path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix == '.gz' else raw)


def save(path: Path, value: object) -> None:
    """機能: 今回作業領域へ有限JSONを保存する。

    引数: path(Path)、value(object)。返り値: なし(None)。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode('utf8')
    path.write_bytes(gzip.compress(raw, mtime=0) if path.suffix == '.gz' else raw)


def catalog() -> list[dict]:
    """機能: 4基準×3幅×2期限の24条件を成績と無関係に生成する。

    引数: なし。返り値: list[dict] は条件。
    """
    return [dict(id=f'A{base[1:]}_D{round(width * 100):03d}_T{ttl}', base=base,
                 threshold_atr=width, timeout_minutes=ttl)
            for base in BASES for width in (0., .25, .5) for ttl in (30, 90)]


def freeze() -> dict:
    """機能: 比較条件と選抜規則を初回だけ固定する。

    引数: なし。返り値: dict は固定仕様。
    """
    definition = dict(候補数=24, 条件=catalog(), 初回枚数={'TOPIX': 5, 'NK225': 10},
                      片方向上限={'TOPIX': 10, 'NK225': 20}, 費用=0,
                      ブロック開始='実際に採用した組の全返済損益が負になった行だけ。買い/売りの状態を独立に更新。',
                      許可='期限内の次の同方向計画源行価格が、失敗組の新規価格からthreshold_atr×入口ATR以上順行していれば許可。等号を含む。',
                      期限='失敗組の全返済時計から30又は90分。期限と同時刻なら許可。',
                      成功の扱い='成功組を見越して解除しない。実際の成功組でも前のブロック水準を消さず、期限満了又は次の採用損失組で更新する。',
                      時計='不許可組も仮想の基準方式では最後まで継続。実口座の不参加で次の基準計画源行を作り直さない。',
                      選抜='先頭10場で両銘柄7場以上活動かつ20組以上を要件とし、両銘柄合計Rの小さい方を最大化。同値は活動場数、IDの昇順。',
                      評価='次9場と末尾既知4場は順位付け不使用。全23場は過去研究既読で真正未見ではない。',
                      注文='基準の計画源行で許可し、基準の後続約定をそのまま実施。既存台帳の約定条件を変更しない。')
    path = HERE / '事前固定.json'
    if path.exists():
        assert read(path) == definition
    else:
        save(path, definition)
    return definition


class Rearm:
    """現在の計画又は現在完了した組だけを受け、方向別の再試行許可を返す。"""

    def __init__(self, threshold: float, minutes: float):
        """機能: 方向別の制限状態を空で初期化する。

        引数: threshold/minutes(float)。返り値: なし(None)。
        """
        self.threshold, self.seconds = threshold, minutes * 60
        self.blocks = {}

    def on_plan(self, at: float, side: int, price: float) -> tuple[bool, dict | None]:
        """機能: 現在の計画価格が過去失敗の価格帯を越えたかだけで許可する。

        引数: at/price(float)、side(int)。返り値: 許可と参照済み制限(tuple)。
        """
        block = self.blocks.get(side)
        if block is None or at >= block['expires']:
            return True, None
        return side * (price - block['level']) >= 0, block.copy()

    def on_cycle_close(self, at: float, side: int, pnl: float, entry: float, atr: float, cycle: int) -> None:
        """機能: 実採用組の全返済後に、負けた方向の水準と期限を更新する。

        引数: at/pnl/entry/atr(float)、side/cycle(int)。返り値: なし(None)。
        """
        if pnl < 0:
            self.blocks[side] = dict(level=entry + side * self.threshold * atr,
                                     expires=at + self.seconds, cycle=cycle)


def events_for(ledger: dict) -> tuple[list[tuple], dict[int, dict]]:
    """機能: 基準の計画・全返済行を原本行順のイベントへ変換する。

    引数: ledger(dict)。返り値: イベントと既知組情報(tuple)。
    """
    orders = np.asarray(ledger['orders'], float).reshape(-1, 8)
    events, records = [], {}
    previous_close = -1
    for cycle in ledger['cycles']:
        cid = int(cycle[0])
        entry = orders[(orders[:, 2] == cid) & (orders[:, 7] == 1)]
        assert len(entry) == 1
        fill, origin = int(entry[0, 0]), int(entry[0, 1])
        close, side = int(cycle[2]), int(entry[0, 3])
        assert previous_close < origin < fill <= close
        assert side == int(cycle[8]) and cycle[4] > 0 and cycle[5] > 0
        records[cid] = dict(origin=origin, fill=fill, close=close, side=side,
                            entry=float(entry[0, 5]), atr=float(cycle[5]), pnl=float(cycle[3]), risk=float(cycle[4]))
        events.extend([(origin, 0, cid), (close, 1, cid)])
        previous_close = close
    return sorted(events), records


def decisions(spec: dict, ready: dict, ledger: dict, cutoff: int | None = None) -> tuple[list[dict], set[int], dict]:
    """機能: 計画と返済の現在イベントだけで入口許可を逐次更新する。

    引数: spec/ready/ledger(dict)、cutoff(int|None)。返り値: 判断・採用組・終端状態(tuple)。
    """
    state = Rearm(spec['threshold_atr'], spec['timeout_minutes'])
    events, records = events_for(ledger)
    selected, released, output = set(), set(), []
    cumulative_r = 0.
    for index, kind, cid in events:
        if cutoff is not None and index > cutoff:
            break
        row = records[cid]
        at = float(ready['time_s'][index])
        if kind == 0:
            assert all(records[prior]['close'] < index for prior in released)
            allowed, block = state.on_plan(at, row['side'], float(ready['last'][index]))
            output.append(dict(cycle=cid, origin=index, fill=row['fill'], accepted=bool(allowed),
                               source_price=float(ready['last'][index]), block=block, past_r=cumulative_r))
            if allowed:
                selected.add(cid)
        elif cid in selected:
            cumulative_r += row['pnl'] / row['risk']
            state.on_cycle_close(at, row['side'], row['pnl'], row['entry'], row['atr'], cid)
            released.add(cid)
    return output, selected, dict(blocks=deepcopy(state.blocks), r=cumulative_r, released=sorted(released))


def evaluate(spec: dict, ready: dict, ledger: dict, detail: bool = False) -> dict:
    """機能: 採用された組の注文・返済を会計し、必要時は全原本価格で時価下落を求める。

    引数: spec/ready/ledger(dict)、detail(bool)。返り値: dict は会計。
    """
    judgment, chosen, state = decisions(spec, ready, ledger)
    orders = np.asarray(ledger['orders'], float).reshape(-1, 8)
    trades = np.asarray(ledger['trades'], float).reshape(-1, 11)
    kept = trades[np.isin(trades[:, 0], list(chosen))]
    selected_orders = orders[np.isin(orders[:, 2], list(chosen))]
    value = ledger['config']['point_value']
    pnl = kept[:, 2] * kept[:, 3] * (kept[:, 5] - kept[:, 4]) * value
    np.testing.assert_allclose(pnl, kept[:, 10] * value, rtol=0, atol=1e-7)
    win, loss, flat = pnl > 0, pnl < 0, pnl == 0
    result = dict(session=ready['session'], symbol=ready['symbol'], net_yen=float(pnl.sum()),
                  gross_profit_yen=float(pnl[win].sum()), gross_loss_yen=float(-pnl[loss].sum()),
                  profit_units=int(kept[win, 3].sum()), loss_units=int(kept[loss, 3].sum()),
                  zero_units=int(kept[flat, 3].sum()), cycles=len(chosen), r=state['r'],
                  long_cycles=int(sum(row[7] == 1 and row[3] > 0 for row in selected_orders)),
                  short_cycles=int(sum(row[7] == 1 and row[3] < 0 for row in selected_orders)))
    if detail:
        cash, positions = np.zeros(len(ready['last'])), np.zeros(len(ready['last']))
        for order in selected_orders:
            i = int(order[0])
            cash[i] -= order[3] * order[4] * order[5]
            positions[i] += order[3] * order[4]
        positions = np.cumsum(positions)
        curve = (np.cumsum(cash) + positions * ready['last']) * value
        assert positions[-1] == 0 and max(abs(positions), default=0) <= ledger['config']['initial_qty']
        assert abs(curve[-1] - result['net_yen']) < 1e-7
        result.update(curve=curve, drawdown_yen=float((np.maximum.accumulate(np.maximum(curve, 0)) - curve).max()),
                      orders=selected_orders.tolist(), trades=kept.tolist(), decisions=judgment)
    return result


def aggregate(rows: list[dict]) -> dict:
    """機能: 銘柄別に金額・枚数・R・活動場・最大勝ち場除外を集計する。

    引数: rows(list[dict])。返り値: dict は銘柄別集計。
    """
    result = {}
    for symbol in SYMBOLS:
        found = [r for r in rows if r['symbol'] == symbol]
        total = {key: sum(r[key] for r in found) for key in
                 ('net_yen', 'gross_profit_yen', 'gross_loss_yen', 'profit_units', 'loss_units', 'zero_units', 'cycles', 'r', 'long_cycles', 'short_cycles')}
        total.update(active_sessions=sum(r['cycles'] > 0 for r in found), win_sessions=sum(r['net_yen'] > 0 for r in found),
                     sessions=len(found), without_best_yen=total['net_yen'] - max([r['net_yen'] for r in found] + [0]))
        total['profit_factor'] = total['gross_profit_yen'] / total['gross_loss_yen'] if total['gross_loss_yen'] else None
        total['per_unit_win'] = total['gross_profit_yen'] / total['profit_units'] if total['profit_units'] else None
        total['per_unit_loss'] = total['gross_loss_yen'] / total['loss_units'] if total['loss_units'] else None
        total['payoff'] = total['per_unit_win'] / total['per_unit_loss'] if total['per_unit_win'] is not None and total['per_unit_loss'] else None
        result[symbol] = total
    return result


def causal_audit(spec: dict, ready: dict, ledger: dict) -> int:
    """機能: 未来損益改変と途中切断が過去許可を変えないことを確認する。

    引数: spec/ready/ledger(dict)。返り値: int は接頭辞比較数。
    """
    full, chosen, state = decisions(spec, ready, ledger)
    # ----------------------------------------
    # 別実装は各組をまとめて処理し、次組源行が前組全返済後であることを条件に比較する。
    blocks, selected = {}, set()
    previous = -1
    events, records = events_for(ledger)
    for cid, row in records.items():
        assert previous < row['origin']
        at = ready['time_s'][row['origin']]
        block = blocks.get(row['side'])
        allow = block is None or at >= block[1] or row['side'] * (ready['last'][row['origin']] - block[0]) >= 0
        if allow:
            selected.add(cid)
            if row['pnl'] < 0:
                blocks[row['side']] = (row['entry'] + row['side'] * spec['threshold_atr'] * row['atr'],
                                       ready['time_s'][row['close']] + 60 * spec['timeout_minutes'])
        previous = row['close']
    assert selected == chosen
    for fraction in (.35, .7):
        cutoff = int(len(ready['last']) * fraction)
        prefix, _, snapshot = decisions(spec, ready, ledger, cutoff)
        assert prefix == [row for row in full if row['origin'] <= cutoff]
        changed = deepcopy(ledger)
        for cycle in changed['cycles']:
            if int(cycle[2]) > cutoff:
                cycle[3] = -cycle[3] * 13 - 1234
        altered, _, altered_snapshot = decisions(spec, ready, changed, cutoff)
        assert altered == prefix and altered_snapshot == snapshot
    return 2


def main() -> None:
    """機能: 固定24条件を比較し、過去10場上位3条件と4基準の詳細を保存する。

    引数: なし。返り値: なし(None)。API接続は行わない。
    """
    freeze()
    source = HERE.parent / 'overlay/research.py'
    module_spec = importlib.util.spec_from_file_location('rearm_input_adapter', source)
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    inputs, _ = module.load()
    paths = {name: HERE.parent / 'clock_search/ledgers' / f'{name}.json.gz' for name in BASES}
    bases = {name: {(r['session'], r['symbol']): r for r in read(path)} for name, path in paths.items()}
    for ledgers in bases.values():
        assert set(ledgers) == set(inputs)
    sessions = sorted({key[0] for key in inputs})
    groups = dict(開発10=sessions[:10], 比較9=sessions[10:19], 既知追加4=sessions[19:], 全23=sessions)
    results, audit_count = [], 0
    for condition in catalog():
        rows = []
        for key, ready in sorted(inputs.items()):
            ledger = bases[condition['base']][key]
            rows.append(evaluate(condition, ready, ledger))
            audit_count += causal_audit(condition, ready, ledger)
        periods = {name: aggregate([r for r in rows if r['session'] in chosen]) for name, chosen in groups.items()}
        train = periods['開発10']
        eligible = all(train[symbol]['active_sessions'] >= 7 and train[symbol]['cycles'] >= 20 for symbol in SYMBOLS)
        results.append(dict(spec=condition, eligible=eligible, score=min(train[s]['r'] for s in SYMBOLS), periods=periods, sessions=rows))
    ranking = sorted((r for r in results if r['eligible']), key=lambda r: (-r['score'], -sum(r['periods']['開発10'][s]['active_sessions'] for s in SYMBOLS), r['spec']['id']))
    save(HERE / '全候補結果.json', dict(期間=groups, 条件数=24, 候補=results))
    save(HERE / '選択.json', dict(第一候補=ranking[0]['spec'] if ranking else None, 上位3=[r['spec'] for r in ranking[:3]],
                                  有資格候補数=len(ranking), 真正未見=False, 順位=[dict(spec=r['spec'], score=r['score']) for r in ranking]))
    # ----------------------------------------
    # 比較基準は制限幅の到達要求を外し、全組を必ず採用して再会計する。
    details = []
    selected_specs = [r['spec'] for r in ranking[:3]] + [dict(id=base, base=base, threshold_atr=0., timeout_minutes=0.) for base in BASES]
    for condition in selected_specs:
        rows, ledgers, curves = [], [], {}
        for key, ready in sorted(inputs.items()):
            outcome = evaluate(condition, ready, bases[condition['base']][key], True)
            curves[key] = outcome.pop('curve')
            ledger = {name: outcome.pop(name) for name in ('orders', 'trades', 'decisions')}
            ledgers.append(dict(session=key[0], symbol=key[1], **ledger))
            rows.append(outcome)
        periods = {name: aggregate([r for r in rows if r['session'] in chosen]) for name, chosen in groups.items()}
        for name, chosen in groups.items():
            for symbol in SYMBOLS:
                offset = high = worst = 0.
                for session in chosen:
                    curve = curves[session, symbol] + offset
                    worst = max(worst, float((np.maximum.accumulate(np.maximum(curve, high)) - curve).max()))
                    high = max(high, float(curve.max()))
                    offset = float(curve[-1])
                periods[name][symbol]['drawdown_yen'] = worst
        details.append(dict(spec=condition, periods=periods, sessions=rows))
        save(HERE / 'ledgers' / f"{condition['id']}.json.gz", ledgers)
        save(HERE / 'sessions' / f"{condition['id']}.json", rows)
    save(HERE / '詳細結果.json', details)
    save(HERE / '監査.json', dict(全合格=True, 条件口座数=24 * len(inputs), 接頭辞比較数=audit_count,
             独立実装='原本順に計画・返済イベントを処理するRearmと組一括処理の別実装で選択組一致。',
             未来改変='切断後に返済される組の損益を反転・拡大しても、切断時の判断列と制限状態は完全一致。',
             元台帳SHA256={name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in paths.items()},
             実装SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()))
    print(json.dumps(dict(第一候補=ranking[0]['spec'] if ranking else None, 有資格候補数=len(ranking),
                          全23=ranking[0]['periods']['全23'] if ranking else None,
                          既知追加4=ranking[0]['periods']['既知追加4'] if ranking else None), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
