"""E01の独立仮想運転を維持し、実口座の入口許可と連敗休止を比較する。"""

from __future__ import annotations

import csv
from datetime import datetime
import gzip
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SYMBOLS = ('TOPIX', 'NK225')
GATES = ('none', 'own5', 'both5', 'both15', 'both5_15', 'eff20', 'both5_eff20', 'slow_now')
RISKS = ('none', 'day2R', 'loss2stop', 'loss2pause45')


def read(path: Path) -> object:
    """機能: 検証済み保存結果を読み込む。

    引数: path(Path)。返り値: JSON内容(object)。
    """
    data = path.read_bytes()
    return json.loads(gzip.decompress(data) if path.suffix == '.gz' else data)


def save(name: str, value: object) -> None:
    """機能: 今回作業内に有限JSONを保存する。

    引数: name(str)、value(object)。返り値: なし(None)。
    """
    (HERE / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')


def catalog() -> list[dict]:
    """機能: 成績を見る前に入口8条件と休止4条件の直積を作る。

    引数: なし。返り値: 条件一覧(list[dict])。
    """
    return [dict(id=f'O{i * len(RISKS) + j:02}', gate=gate, risk=risk)
            for i, gate in enumerate(GATES) for j, risk in enumerate(RISKS)]


def load() -> tuple[dict, dict]:
    """機能: 23場の検証済み価格列とE01台帳を重複なしで集める。

    引数: なし。返り値: 価格入力と台帳(tuple[dict,dict])。
    """
    inputs = pickle.loads((ROOT / 'work/wave_v47/inputs.pkl').read_bytes())
    folders = [ROOT / 'work/wave_v48' / n for n in ('update_20260930', 'update_20261001')]
    updates = read(ROOT / 'work/wave_v50/追加結果一覧.json')
    folders += [ROOT / 'work/wave_v50' / n for n in updates]
    for folder in folders:
        extra = pickle.loads((folder / 'new_inputs.pkl').read_bytes())
        assert not set(extra).intersection(inputs)
        inputs.update(extra)
    ledgers = []
    for folder in [ROOT / 'work/wave_v49/early'] + [ROOT / 'work/wave_v50' / n for n in updates]:
        ledgers += read(folder / 'ledgers/E01.json.gz')
    indexed = {(r['session'], r['symbol']): r for r in ledgers}
    assert len(inputs) == len(indexed) == 46 and set(inputs) == set(indexed)
    return inputs, indexed


def bar_model(key: tuple) -> dict:
    """機能: 確定1分足を開始120秒後から利用する指標へ変換する。

    引数: key(tuple[str,str])。返り値: 公開時刻と過去指標(dict)。
    """
    path = ROOT / 'candle_1min' / key[1] / (key[0] + '.csv')
    with path.open(encoding='utf-8-sig', newline='') as stream:
        rows = [row for row in csv.DictReader(stream) if row['closed'].lower() == 'true']
    time = np.array([datetime.fromisoformat(r['time']).timestamp() + 120 for r in rows])
    close = np.array([float(r['close']) for r in rows])
    assert (np.diff(time) > 0).all()
    slow = np.empty(len(close))
    for i, value in enumerate(close):
        slow[i] = value if i == 0 else slow[i - 1] + 2 / 61 * (value - slow[i - 1])
    result = dict(time=time, close=close, slow=np.full(len(time), np.nan), er=np.full(len(time), np.nan))
    result['slow'][62:] = slow[62:] - slow[59:-3]
    for minutes in (5, 15):
        index = np.searchsorted(time, time - minutes * 60, side='right') - 1
        valid = (index >= 0) & (time - time[np.maximum(index, 0)] <= (minutes + 1) * 60)
        values = np.full(len(time), np.nan)
        values[valid] = close[valid] - close[index[valid]]
        result[f'r{minutes}'] = values
    for i in range(20, len(time)):
        if time[i] - time[i - 20] <= 1260:
            path_length = np.abs(np.diff(close[i - 20:i + 1])).sum()
            result['er'][i] = abs(close[i] - close[i - 20]) / path_length if path_length else 0.
    return result


def snapshot(model: dict, at: float, delay: float = 0) -> dict:
    """機能: 当時公開済みの指標だけを返し、古い指標を欠損扱いにする。

    引数: model(dict)、at/delay(float)。返り値: 指標値(dict)。
    """
    index = int(np.searchsorted(model['time'] + delay, at, side='right')) - 1
    valid = index >= 0 and at - model['time'][index] - delay <= 180
    return {key: float(model[key][index]) if valid else float('nan') for key in ('r5', 'r15', 'er', 'slow')}


def allow_entry(spec: dict, own: dict, peer: dict, direction: int, state: dict, at: float) -> bool:
    """機能: 現在の指標と確定済み実損益だけから注文準備の許可を返す。

    引数: spec/own/peer/state(dict)、direction(int)、at(float)。返り値: 許可(bool)。
    """
    gate, risk = spec['gate'], spec['risk']
    if risk == 'day2R' and state['r'] <= -2:
        return False
    if risk == 'loss2stop' and state['losses'] >= 2:
        return False
    if risk == 'loss2pause45' and at < state['until']:
        return False
    own5 = direction * own['r5'] > 0
    both5 = own5 and direction * peer['r5'] > 0
    both15 = direction * own['r15'] > 0 and direction * peer['r15'] > 0
    efficient = own['er'] >= .25 and peer['er'] >= .25
    return {'none': True, 'own5': own5, 'both5': both5, 'both15': both15,
            'both5_15': both5 and both15, 'eff20': efficient,
            'both5_eff20': both5 and efficient,
            'slow_now': direction * own['slow'] > 0 and direction * peer['slow'] > 0}[gate]


def evaluate(spec: dict, ready: dict, ledger: dict, models: dict, detail: bool = False) -> dict:
    """機能: 仮想E01の組ごとに実注文を許可し、実際に選んだ組だけ会計する。

    引数: spec/ready/ledger/models(dict)、detail(bool)。返り値: セッション会計(dict)。
    """
    key = ready['session'], ready['symbol']
    peer = key[0], 'NK225' if key[1] == 'TOPIX' else 'TOPIX'
    orders = np.asarray(ledger['orders'], float).reshape(-1, 8)
    trades = np.asarray(ledger['trades'], float).reshape(-1, 11)
    state = dict(r=0., losses=0, until=0.)
    chosen, decisions = [], []
    previous_close = -1
    for cycle in ledger['cycles']:
        cid = int(cycle[0])
        entry = orders[(orders[:, 2] == cid) & (orders[:, 7] == 1)]
        assert len(entry) == 1
        origin, fill = int(entry[0, 1]), int(entry[0, 0])
        assert previous_close < origin < fill
        at = ready['time_s'][origin]
        own_values, peer_values = snapshot(models[key], at), snapshot(models[peer], at, 60)
        allowed = allow_entry(spec, own_values, peer_values, int(cycle[8]), state, at)
        decisions.append(dict(cycle=cid, origin=origin, fill=fill, accepted=bool(allowed), past_r=state['r']))
        if allowed:
            chosen.append(cid)
            state['r'] += cycle[3] / cycle[4]
            state['losses'] = state['losses'] + 1 if cycle[3] < 0 else 0
            if spec['risk'] == 'loss2pause45' and state['losses'] >= 2:
                state['until'] = ready['time_s'][int(cycle[2])] + 2700
                state['losses'] = 0
        previous_close = int(cycle[2])
    kept = trades[np.isin(trades[:, 0], chosen)]
    selected_orders = orders[np.isin(orders[:, 2], chosen)]
    multiplier = ledger['config']['point_value']
    pnl = kept[:, 2] * kept[:, 3] * (kept[:, 5] - kept[:, 4]) * multiplier
    np.testing.assert_allclose(pnl, kept[:, 10] * multiplier, rtol=0, atol=1e-8)
    wins, losses, zeros = pnl > 1e-8, pnl < -1e-8, abs(pnl) <= 1e-8
    result = dict(session=key[0], symbol=key[1], net_yen=float(pnl.sum()),
                  gross_profit_yen=float(pnl[wins].sum()), gross_loss_yen=float(-pnl[losses].sum()),
                  profit_units=int(kept[wins, 3].sum()), loss_units=int(kept[losses, 3].sum()),
                  zero_units=int(kept[zeros, 3].sum()), cycles=len(chosen), r=state['r'],
                  long_cycles=sum(int(c[8] > 0) for c in ledger['cycles'] if int(c[0]) in chosen),
                  short_cycles=sum(int(c[8] < 0) for c in ledger['cycles'] if int(c[0]) in chosen))
    if detail:
        delta_cash, delta_position = np.zeros(len(ready['last'])), np.zeros(len(ready['last']))
        for order in selected_orders:
            index = int(order[0])
            delta_cash[index] -= order[3] * order[4] * order[5]
            delta_position[index] += order[3] * order[4]
        position = np.cumsum(delta_position)
        curve = (np.cumsum(delta_cash) + position * ready['last']) * multiplier
        assert position[-1] == 0 and max(abs(position), default=0) <= ledger['config']['initial_qty']
        assert abs(curve[-1] - result['net_yen']) < 1e-6
        result.update(drawdown_yen=float((np.maximum.accumulate(np.maximum(curve, 0)) - curve).max()),
                      curve=curve, orders=selected_orders.tolist(), trades=kept.tolist(), decisions=decisions)
    return result


def aggregate(rows: list[dict]) -> dict:
    """機能: 金額・R・活動場数・1枚平均勝敗比を銘柄別に集計する。

    引数: rows(list[dict])。返り値: 集計値(dict)。
    """
    result = {}
    for symbol in SYMBOLS:
        selected = [r for r in rows if r['symbol'] == symbol]
        sums = {key: sum(r[key] for r in selected) for key in
                ('net_yen', 'gross_profit_yen', 'gross_loss_yen', 'profit_units', 'loss_units', 'zero_units', 'cycles', 'r', 'long_cycles', 'short_cycles')}
        sums.update(active_sessions=sum(r['cycles'] > 0 for r in selected),
                    win_sessions=sum(r['net_yen'] > 0 for r in selected), sessions=len(selected),
                    without_best_yen=sums['net_yen'] - max((r['net_yen'] for r in selected), default=0))
        sums['payoff'] = ((sums['gross_profit_yen'] / sums['profit_units']) /
                          (sums['gross_loss_yen'] / sums['loss_units'])) if sums['profit_units'] and sums['loss_units'] else None
        result[symbol] = sums
    return result


def main() -> None:
    """機能: 32固定条件を過去10場で選び、残り9場・既知4場を区別して検証する。

    引数: なし。返り値: なし(None)。条件、全候補結果、選択候補台帳を保存する。
    """
    HERE.mkdir(parents=True, exist_ok=True)
    specs = catalog()
    fixed = dict(候補=specs, 条件数=len(specs), データ='保存23セッションのみ。API取得0。既知データの再探索。',
                 実装SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                 注文='独立仮想E01の注文計画が更新される行で許可判定。不許可なら実口座にはその組を建てない。途中返済と次組の時計は仮想E01で維持。',
                 未来制約='発注元行より前の確定損益と公開確定足だけを使用。自市場開始120秒後、相手180秒後。',
                 選択='先頭10場で両銘柄とも7場以上活動・20組以上。両銘柄の合計Rの小さい方を最大化。同値は活動場数、ID順。9場と既知4場は選択不使用。',
                 限界='E01仮想エンジンは保存済み因果監査を継承。入口許可だけの注文列再生であり、新しい入口時計の探索ではない。')
    save('条件固定.json', fixed)
    inputs, ledgers = load()
    models = {key: bar_model(key) for key in inputs}
    names = sorted({key[0] for key in inputs})
    groups = dict(開発10=names[:10], 検証9=names[10:19], 既知追加4=names[19:], 全23=names)
    results = []
    for spec in specs:
        rows = [evaluate(spec, ready, ledgers[key], models) for key, ready in sorted(inputs.items())]
        periods = {name: aggregate([r for r in rows if r['session'] in sessions]) for name, sessions in groups.items()}
        train = periods['開発10']
        eligible = all(train[s]['active_sessions'] >= 7 and train[s]['cycles'] >= 20 for s in SYMBOLS)
        score = min(train[s]['r'] for s in SYMBOLS)
        results.append(dict(spec=spec, eligible=eligible, score=score, periods=periods, sessions=rows))
    selected = sorted((r for r in results if r['eligible']), key=lambda r: (-r['score'], -sum(r['periods']['開発10'][s]['active_sessions'] for s in SYMBOLS), r['spec']['id']))
    assert selected
    save('全候補結果.json', dict(条件数=len(specs), 期間=groups, 候補=results, 過去十場だけの選択=selected[0]['spec']))
    baseline = next(r for r in results if r['spec']['id'] == 'O00')
    stored = {m['spec']['id']: m for m in read(ROOT / 'work/wave_v50/報告データ.json')['候補']}['E01']
    for row in baseline['sessions']:
        expected = next(r for r in stored['sessions'] if (r['session'], r['symbol']) == (row['session'], row['symbol']))
        for field in ('net_yen', 'gross_profit_yen', 'gross_loss_yen', 'profit_units', 'loss_units', 'zero_units'):
            assert abs(row[field] - expected[field]) < 1e-7
    selected_ids = list(dict.fromkeys([r['spec']['id'] for r in selected[:3]] + ['O00']))
    details = []
    for identifier in selected_ids:
        spec = next(s for s in specs if s['id'] == identifier)
        curves, rows, ledger_rows = {}, [], []
        for key, ready in sorted(inputs.items()):
            result = evaluate(spec, ready, ledgers[key], models, True)
            curves[key] = result.pop('curve')
            ledger_rows.append({k: result.pop(k) for k in ('orders', 'trades', 'decisions')} | dict(session=key[0], symbol=key[1]))
            rows.append(result)
        summary = next(r for r in results if r['spec']['id'] == identifier)
        for group, sessions in groups.items():
            for symbol in SYMBOLS:
                offset = high = drawdown = 0.
                for session in sessions:
                    curve = curves[session, symbol] + offset
                    peaks = np.maximum.accumulate(np.maximum(curve, high))
                    drawdown = max(drawdown, float((peaks - curve).max()))
                    high = max(high, float(curve.max()))
                    offset = float(curve[-1])
                summary['periods'][group][symbol]['drawdown_yen'] = drawdown
        (HERE / (identifier + '_台帳.json.gz')).write_bytes(gzip.compress(json.dumps(ledger_rows, ensure_ascii=False).encode('utf8'), mtime=0))
        details.append(summary | dict(sessions=rows))
    # ----------------------------------------
    # 公開されていない足の終値を変えても、当時の入口判断が変わらないことを確認します。
    for key, model in models.items():
        at = float(model['time'][len(model['time']) // 2])
        before = snapshot(model, at)
        mutated = {k: v.copy() for k, v in model.items()}
        for field in ('r5', 'r15', 'er', 'slow'):
            mutated[field][mutated['time'] > at] = 999999
        after = snapshot(mutated, at)
        for field in before:
            assert before[field] == after[field] or np.isnan(before[field]) and np.isnan(after[field])
    save('選択結果.json', dict(全合格=True, 固定候補数=len(specs), 選択=selected[0]['spec'],
         有資格候補数=len(selected), E01四十六口座会計一致=True, 将来指標非参照=True,
         既知追加期間を未見と呼ばない=True, 候補=details))
    print(json.dumps(dict(選択=selected[0]['spec'], 全23=selected[0]['periods']['全23'], 既知追加4=selected[0]['periods']['既知追加4']), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
