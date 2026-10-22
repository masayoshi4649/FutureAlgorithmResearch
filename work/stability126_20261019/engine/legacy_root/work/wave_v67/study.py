"""E01十六条件を旧探索場と後続場に分け、手数料込みで再評価する。"""

import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path
import pickle
import socket

import numpy as np

import replay

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SYMBOLS = ('TOPIX', 'NK225')
VALUES = {'TOPIX': 1000, 'NK225': 10}
FEES = {'TOPIX': 41.8, 'NK225': 11.0}


def save(path: Path, value: object) -> None:
    """機能: 新作業内へ有限JSONを保存する。

    引数: path(Path)、value(object)。返り値: なし(None)。
    """
    assert path.resolve().is_relative_to(HERE)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2).encode('utf8')
    path.write_bytes(gzip.compress(raw, mtime=0) if path.suffix == '.gz' else raw)


def read(path: Path) -> object:
    """機能: 通常又は圧縮JSONを読む。

    引数: path(Path)。返り値: 格納値(object)。
    """
    raw = path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix == '.gz' else raw)


def freeze() -> dict:
    """機能: 条件・会計・選び方を今回の経済再生前に固定する。

    引数: なし。返り値: 固定書(dict)。
    """
    sessions = sorted(p.stem for p in (ROOT / 'book/NK225').glob('*.jsonl'))
    fixed = dict(条件=replay.catalog(), 全セッション=sessions, 前16=sessions[:16], 後12=sessions[16:],
        初回枚数={'TOPIX': 5, 'NK225': 10}, 片方向上限={'TOPIX': 10, 'NK225': 20},
        手数料=FEES, 円倍率=VALUES, 手数料計算='新規・返済とも注文合計の小数円を切捨て',
        主約定='元00044のラージ最終約定値と呼値。前行計画は次の保存行以降で指定条件価格に執行。料金を追加。',
        観測値追試='発動行のラージ最終約定値で約定、建値と返済線をその約定値で再生成。料金を追加。小商品での実約定の証明ではない。',
        見送り='観測行の可否はその行後の計画へ反映。前行の有効注文は当行の取消に遡って削除しない。',
        時計統一='R10以降のreset指定は出口影の終了から5分待機。実建玉だけが予算返済した場合は出口影終了まで待つ。',
        比較選定='前16場だけで各銘柄20組以上・8場以上活動・両銘柄黒字・組平均利益損失比1超を満たす改修のうち、銘柄別平均Rの小さい方が最大。該当なしなら採用候補なし。',
        既知範囲='前16は元E01の探索範囲。後12も本研究までに一部又は全部を閲覧済み。時間順の耐性確認であり、完全な未見検証とは呼ばない。',
        API取得数=0, 実注文数=0,
        原本SHA256={str(p.relative_to(ROOT)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest()
            for folder in ('candle_1min', 'candle_5min') for symbol in SYMBOLS
            for p in sorted((ROOT / folder / symbol).glob('*.csv'))},
        実装SHA256={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (HERE / 'replay.py', Path(__file__))})
    assert len(sessions) == 28 and len(fixed['後12']) == 12
    target = HERE / '事前固定.json'
    if target.exists():
        assert read(target) == fixed
    else:
        save(target, fixed)
    return fixed


def load_inputs() -> tuple:
    """機能: 旧二十三場と新五場の入力・信号を重複なく集める。

    引数: なし。返り値: 入力・信号・原本指紋(dict,dict,dict)。
    """
    inputs, signals, hashes = {}, {'entry': {}, 'B00': {}, 'B01': {}}, {}
    for folder in sorted((HERE / 'prepared').iterdir()):
        if not (folder / 'signals.pkl').exists():
            continue
        current = pickle.loads((folder / 'new_inputs.pkl').read_bytes())
        assert not set(current) & set(inputs)
        inputs.update(current)
        current_signals = pickle.loads((folder / 'signals.pkl').read_bytes())
        for code in signals:
            signals[code].update(current_signals[code])
        for name in ('new_inputs.pkl', 'signals.pkl'):
            p = folder / name
            hashes[str(p.relative_to(HERE))] = hashlib.sha256(p.read_bytes()).hexdigest()
    replay.prior.activate(inputs, signals)
    return inputs, signals, hashes


def columns_for(variant: dict, key: tuple, ready: dict, models: dict) -> tuple:
    """機能: 元E01の十列を作り、入口の可否だけを現在の公開指標で変更する。

    引数: variant/ready/models(dict)、key(tuple)。返り値: 十列と品質(tuple)。
    """
    columns, valid = replay.early.source.replay.new_columns(replay.base_spec(), key)
    if variant['gate'] != 'none':
        own, peer = replay.gate.expanded(key, models, ready['time_s'])
        gate_spec = dict(kind=variant['gate'], window=5)
        mask = replay.gate.gate_mask(gate_spec, columns[0], own, peer)
        columns = (np.where(mask, columns[0], 0).astype(np.int8), *columns[1:])
    return columns, valid


def account(ready: dict, result: dict, config: dict) -> tuple:
    """機能: 全注文に料金を課し、決済別・組別・時価の会計を検算する。

    引数: ready/result/config(dict)。返り値: 集計・台帳・料金後時価(tuple)。
    """
    symbol = ready['symbol']
    orders, trades, cycles = result['orders'], result['trades'], result['cycles']
    scale, fee = VALUES[symbol], FEES[symbol]
    charge = np.floor(orders[:, 4] * fee + 1e-8)
    entries = {(int(o[2]), int(o[0])): (int(o[4]), f, float(o[5]))
        for o, f in zip(orders, charge) if o[7] == 1}
    exit_charge = {(int(o[2]), int(o[0])): f / o[4] for o, f in zip(orders, charge) if o[7] == 0}
    nets, details = [], []
    for trade in trades:
        cid, qty, entry_row, exit_row = int(trade[0]), int(trade[3]), int(trade[6]), int(trade[7])
        initial_qty, entry_fee, price = entries[cid, entry_row]
        assert abs(price - trade[4]) < 1e-8
        gross = float(trade[10] * scale)
        allocated = qty * (entry_fee / initial_qty + exit_charge[cid, exit_row])
        net = gross - allocated
        nets.append(net)
        details.append(dict(組=cid, 方向=int(trade[2]), 枚数=qty, 新規行=entry_row, 返済行=exit_row,
            新規原本行=int(ready['seq'][entry_row]), 返済原本行=int(ready['seq'][exit_row]),
            新規時刻=float(ready['time_s'][entry_row]), 返済時刻=float(ready['time_s'][exit_row]),
            建値=float(trade[4]), 返済値=float(trade[5]), 理由=int(trade[9]), 利益損失前=gross, 手数料=allocated, 収支=net))
    nets = np.asarray(nets)
    q = trades[:, 3]
    assert abs(float(nets.sum()) - (float(trades[:, 10].sum() * scale) - float(charge.sum()))) < 1e-5
    grouped = np.asarray([sum(t['収支'] for t in details if t['組'] == int(c[0])) for c in cycles])
    risk = np.asarray([c[4] * scale for c in cycles])
    fee_curve = np.zeros(len(ready['last']))
    np.add.at(fee_curve, orders[:, 0].astype(int), charge)
    equity = result['curve'][:, 0] * scale - np.cumsum(fee_curve)
    assert abs(equity[-1] - nets.sum()) < 1e-5
    assert result['stats'][9] == 0
    running = np.maximum.accumulate(np.maximum(equity, 0))
    row = dict(session=ready['session'], symbol=symbol, gross=float(trades[:, 10].sum() * scale),
        fees=int(charge.sum()), net=float(nets.sum()), profit=float(nets[nets > 0].sum()), loss=float(-nets[nets < 0].sum()),
        wins=int((nets > 0).sum()), losses=int((nets < 0).sum()), flats=int((nets == 0).sum()),
        winning_lots=int(q[nets > 0].sum()), losing_lots=int(q[nets < 0].sum()), flat_lots=int(q[nets == 0].sum()),
        campaigns=len(cycles), campaign_wins=int((grouped > 0).sum()), campaign_losses=int((grouped < 0).sum()),
        campaign_profit=float(grouped[grouped > 0].sum()), campaign_loss=float(-grouped[grouped < 0].sum()),
        sum_r=float((grouped / risk).sum()) if len(risk) else 0.,
        max_drawdown=float((running - equity).max(initial=0)),
        max_long=int(result['stats'][2]), max_short=int(result['stats'][3]),
        reason_counts={str(r): sum(t['理由'] == r for t in details) for r in (1, 2, 7, 8, 9, 30, 32)})
    row['win_rate'] = row['wins'] / max(1, row['wins'] + row['losses'] + row['flats'])
    row['payoff'] = (row['profit'] / row['wins']) / (row['loss'] / row['losses']) if row['wins'] and row['losses'] else None
    row['lot_payoff'] = (row['profit'] / row['winning_lots']) / (row['loss'] / row['losing_lots']) if row['winning_lots'] and row['losing_lots'] else None
    row['campaign_payoff'] = (row['campaign_profit'] / row['campaign_wins']) / (row['campaign_loss'] / row['campaign_losses']) if row['campaign_wins'] and row['campaign_losses'] else None
    return row, dict(session=ready['session'], symbol=symbol, config=config, orders=orders.tolist(), trades=details,
        cycles=cycles.tolist(), fees=charge.tolist()), equity


def aggregate(rows: list, symbol: str, names: list) -> dict:
    """機能: 同銘柄の利益・損失・枚数を期間内で合算する。

    引数: rows(list)、symbol(str)、names(list[str])。返り値: 集計(dict)。
    """
    subset = [r for r in rows if r['symbol'] == symbol and r['session'] in names]
    additive = ('gross', 'fees', 'net', 'profit', 'loss', 'wins', 'losses', 'flats', 'winning_lots', 'losing_lots',
        'flat_lots', 'campaigns', 'campaign_wins', 'campaign_losses', 'campaign_profit', 'campaign_loss', 'sum_r')
    value = {n: sum(r[n] for r in subset) for n in additive}
    value.update(positive_sessions=sum(r['net'] > 0 for r in subset), negative_sessions=sum(r['net'] < 0 for r in subset),
        active_sessions=sum(r['campaigns'] > 0 for r in subset), sessions=len(subset),
        max_session_drawdown=max((r['max_drawdown'] for r in subset), default=0))
    value['win_rate'] = value['wins'] / max(1, value['wins'] + value['losses'] + value['flats'])
    value['mean_r'] = value['sum_r'] / max(1, value['campaigns'])
    for key, wins, losses, gain, loss in (
        ('payoff', 'wins', 'losses', 'profit', 'loss'),
        ('lot_payoff', 'winning_lots', 'losing_lots', 'profit', 'loss'),
        ('campaign_payoff', 'campaign_wins', 'campaign_losses', 'campaign_profit', 'campaign_loss')):
        value[key] = (value[gain] / value[wins]) / (value[loss] / value[losses]) if value[wins] and value[losses] else None
    return value


def run(identifiers: list[str], model: str, allow_partial: bool) -> None:
    """機能: 固定した条件を全場へ再生し、旧E01の完全一致と新会計を保存する。

    引数: identifiers(list[str])、model(str)、allow_partial(bool)。返り値: なし(None)。
    """
    fixed = freeze()
    replay.integration.reference.initialize()
    inputs, _, hashes = load_inputs()
    if not allow_partial:
        assert len(inputs) == 56, ('全28場の準備待ち', len(inputs))
    models = {key: replay.gate.model(ready) for key, ready in inputs.items()}
    save(HERE / '入力指紋.json', hashes)
    old = []
    folders = [ROOT / 'work/wave_v49/early']
    folders += [ROOT / 'work/wave_v50' / n for n in read(ROOT / 'work/wave_v50/追加結果一覧.json')]
    for folder in folders:
        old += read(folder / 'ledgers/E01.json.gz')
    old = {(l['session'], l['symbol']): l for l in old}
    for variant in replay.catalog():
        if identifiers and variant['id'] not in identifiers:
            continue
        target = HERE / model / (variant['id'] + '.json.gz')
        if target.exists():
            completed = read(target)
            if len(completed['rows']) == len(inputs):
                print(model, variant['id'], '保存済み', flush=True)
                continue
        rows, ledgers = [], []
        for key, ready in sorted(inputs.items()):
            columns, valid = columns_for(variant, key, ready, models)
            actual = replay.play(variant, ready, columns, valid, observed=model == 'observed')
            result, _, _, _, config = actual
            if model == 'specified' and variant['id'] == 'E01' and key in old:
                for field in ('orders', 'cycles', 'trades'):
                    np.testing.assert_array_equal(result[field], np.asarray(old[key][field]).reshape(result[field].shape), err_msg=str((key, field)))
            for order in result['orders']:
                assert 0 <= int(order[1]) < int(order[0]) < len(ready['last'])
            row, ledger, _ = account(ready, result, config)
            assert row['max_long'] <= config['initial_qty'] and row['max_short'] <= config['initial_qty']
            rows.append(row)
            ledgers.append(ledger)
            del actual, result
        periods = {label: {s: aggregate(rows, s, names) for s in SYMBOLS}
            for label, names in [('前16', fixed['前16']), ('後12', fixed['後12']), ('全28', fixed['全セッション']),
                ('直近3', fixed['全セッション'][-3:])]}
        save(target, dict(variant=variant, model=model, rows=rows, ledgers=ledgers, periods=periods,
            旧E01台帳一致口座数=len(old) if variant['id'] == 'E01' and model == 'specified' else None))
        print(model, variant['id'], len(rows), '口座完了', flush=True)


def main() -> None:
    """機能: 通信を拒否した固定比較を引数で実行する。

    引数: コマンドライン(str)。返り値: なし(None)。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--freeze', action='store_true')
    parser.add_argument('--ids', default='')
    parser.add_argument('--model', choices=['specified', 'observed'], default='specified')
    parser.add_argument('--partial', action='store_true')
    args = parser.parse_args()
    socket.socket.connect = replay.prior.previous.deny
    socket.create_connection = replay.prior.previous.deny
    if args.freeze:
        freeze()
        print('十六条件・会計・選定基準を固定しました')
        return
    run(args.ids.split(',') if args.ids else [], args.model, args.partial)


if __name__ == '__main__':
    main()
