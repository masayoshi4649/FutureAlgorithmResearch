"""固定注文価格置換の原気配・数量・料金・現金勘定を別実装で検算する。"""

import gzip
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
VALUES = {'TOPIX': 1000, 'NK225': 10}


def read(path: Path) -> object:
    """機能: 通常又は圧縮された保存JSONを読み取る。

    引数: path(Path)。返り値: 読み取った内容(object)。
    """
    raw = path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix == '.gz' else raw)


def digest(path: Path) -> str:
    """機能: 原資料のSHA256を読み取り専用で求める。

    引数: path(Path)。返り値: SHA256文字列(str)。
    """
    result = hashlib.sha256()
    with path.open('rb') as stream:
        while part := stream.read(4 * 1024 * 1024):
            result.update(part)
    return result.hexdigest()


def near(left: float, right: float) -> None:
    """機能: 浮動小数誤差だけを許容して損益一致を検査する。

    引数: left/right(float)。返り値: なし(None)。
    """
    assert abs(left - right) < 1.e-5, (left, right)


def collect() -> tuple[dict, dict]:
    """機能: 親の価格入力と元気配を独立に読み取る。

    引数: なし。返り値: 入力辞書・気配辞書(tuple[dict,dict])。
    価格置換スクリプトをインポートせず、原板連番で検査する。
    """
    inputs = {}
    for path in sorted((WORK / 'prepared').glob('*/new_inputs.pkl')):
        source = pickle.loads(path.read_bytes())
        assert not set(inputs) & set(source)
        inputs.update(source)
    cache = pickle.loads((WORK.parent / 'wave_v60' / 'quotes.pkl').read_bytes())
    quotes = {}
    for key in inputs:
        if key in cache:
            raw = cache[key]
        else:
            path = WORK / 'prepared' / key[0] / 'features' / f'約定系列_{key[1]}_{key[0]}.npz'
            with np.load(path, allow_pickle=False) as data:
                raw = {name: data[name].copy() for name in ('seq', 'time_s', 'bid', 'ask')}
        valid = np.isfinite(raw['time_s']) & np.isfinite(raw['bid']) & np.isfinite(raw['ask'])
        valid &= (raw['bid'] > 0) & (raw['ask'] > raw['bid'])
        quotes[key] = {name: np.asarray(raw[name])[valid] for name in ('seq', 'time_s', 'bid', 'ask')}
    assert len(inputs) == len(quotes) == 56
    return inputs, quotes


def check_account(original: dict, result: dict, ready: dict, quotes: dict) -> dict:
    """機能: 注文列を原資料へ照合し、気配と現金勘定を別方式で検算する。

    引数: original/result/ready/quotes(dict)。返り値: 検査件数と現金勘定(dict)。
    """
    symbol = result['symbol']
    value = VALUES[symbol]
    assert len(result['orders']) == len(original['orders'])
    assert len(result['trades']) == len(original['trades'])
    cash = baseline_cash = 0.
    position = 0
    exact = past = 0
    max_age = 0.
    previous_row = -1
    fees = []
    order_map = {}
    for index, (source, order) in enumerate(zip(original['orders'], result['orders'])):
        row, activation, campaign, side, quantity, price, reason, opened = source
        row, activation, campaign, side, quantity, reason, opened = map(int, (row, activation, campaign, side, quantity, reason, opened))
        assert (order['row'], order['source_row'], order['campaign'], order['side'], order['quantity'], order['reason']) == (row, activation, campaign, side, quantity, reason)
        assert order['number'] == index and order['action'] == ('新規' if opened else '返済')
        assert order['original_price'] == price and order['available']
        assert 0 <= activation < row and row >= previous_row
        previous_row = row
        order_seq = int(ready['seq'][row])
        order_time = float(ready['time_s'][row])
        assert order['order_seq'] == order_seq and order['order_time'] == order_time
        # ----------------------------------------
        # 連番範囲を先に絞り、最後の過去気配を元配列から独立に検査する。
        candidates = np.flatnonzero(quotes['seq'] <= order_seq)
        assert len(candidates) > 0
        chosen = int(candidates[-1])
        qseq, qtime = int(quotes['seq'][chosen]), float(quotes['time_s'][chosen])
        assert order['quote_seq'] == qseq and order['quote_time'] == qtime
        assert qseq <= order_seq and qtime <= order_time + 1.e-6
        age = order_time - qtime
        assert 0 <= age + 1.e-6 <= 30.000001
        near(age, order['age_seconds'])
        quote_price = float(quotes['ask' if side > 0 else 'bid'][chosen])
        assert order['price'] == quote_price
        if qseq == order_seq:
            assert qtime == order_time and order['match'] == 'exact'
            exact += 1
        else:
            assert order['match'] == 'past_asof'
            past += 1
        max_age = max(max_age, age)
        # ----------------------------------------
        # 注文料金は整数演算で独立計算し、全返済後の現金勘定を照合する。
        fee = quantity * 418 // 10 if symbol == 'TOPIX' else quantity * 11
        assert order['fee'] == original['fees'][index] == fee
        fees.append(fee)
        cash -= side * quantity * quote_price * value + fee
        baseline_cash -= side * quantity * price * value + fee
        position += side * quantity
        assert abs(position) <= (10 if symbol == 'TOPIX' else 20)
        key = campaign, row, bool(opened)
        assert key not in order_map
        order_map[key] = order
    assert position == 0
    quoted_net = original_net = total_fee = 0.
    winning = losing = 0.
    win_lots = loss_lots = wins = losses = 0
    for source, trade in zip(original['trades'], result['trades']):
        side, quantity = int(source['方向']), int(source['枚数'])
        cid, erow, xrow = int(source['組']), int(source['新規行']), int(source['返済行'])
        assert (trade['campaign'], trade['side'], trade['quantity'], trade['entry_row'], trade['exit_row'], trade['reason']) == (cid, side, quantity, erow, xrow, int(source['理由']))
        entry, exit_order = order_map[cid, erow, True], order_map[cid, xrow, False]
        assert trade['entry_price'] == entry['price'] and trade['exit_price'] == exit_order['price']
        assert entry['side'] == side and exit_order['side'] == -side
        gross = (exit_order['price'] - entry['price']) * side * quantity * value
        fee = quantity * (entry['fee'] / entry['quantity'] + exit_order['fee'] / exit_order['quantity'])
        near(fee, source['手数料'])
        near(fee, trade['fees'])
        near(gross, trade['gross'])
        near(gross - fee, trade['net'])
        near(source['収支'], trade['baseline_net'])
        near(trade['net'] - trade['baseline_net'], trade['quote_net_change'])
        assert trade['available'] and not trade['missing_order_numbers']
        quoted_net += gross - fee
        original_net += source['収支']
        total_fee += fee
        if gross - fee > 0:
            winning += gross - fee
            wins += 1
            win_lots += quantity
        elif gross - fee < 0:
            losing -= gross - fee
            losses += 1
            loss_lots += quantity
    near(cash, quoted_net)
    near(baseline_cash, original_net)
    near(total_fee, sum(fees))
    summary = result['summary']
    assert summary['complete'] and summary['missing_orders'] == summary['missing_trades'] == 0
    near(summary['net'], cash)
    near(summary['baseline_net'], baseline_cash)
    near(summary['quote_net_change'], cash - baseline_cash)
    near(summary['profit'], winning)
    near(summary['loss'], losing)
    assert summary['fees'] == sum(fees)
    assert summary['wins'] == wins and summary['losses'] == losses
    assert summary['winning_lots'] == win_lots and summary['losing_lots'] == loss_lots
    if win_lots and loss_lots:
        near(summary['lot_payoff'], (winning / win_lots) / (losing / loss_lots))
    return dict(orders=len(fees), trades=len(result['trades']), exact=exact, past_asof=past, max_age=max_age,
                cash=cash, baseline_cash=baseline_cash, fees=sum(fees))


def main() -> None:
    """機能: 全32結果1792口座の独立検査と重点2条件の補足集計を保存する。

    引数: なし。返り値: なし(None)。出力先は今回theoryのみとする。
    """
    completed = read(HERE / '気配価格置換の完了.json')
    fixed = read(HERE / '気配価格置換の事前固定.json')
    for name, expected in completed['入力結果SHA'].items():
        assert digest(Path(name)) == expected
    inputs, quotes = collect()
    verified = []
    focus = []
    for model in fixed['モデル']:
        for vid in fixed['条件ID']:
            original = read(WORK / model / f'{vid}.json.gz')
            result = read(HERE / '気配価格置換' / f'{model}_{vid}.json.gz')
            assert result['sensitivity_only'] and not result['decisions_recomputed']
            originals = {(item['session'], item['symbol']): item for item in original['ledgers']}
            assert len(result['accounts']) == len(originals) == 56
            for account in result['accounts']:
                key = account['session'], account['symbol']
                audit = check_account(originals[key], account, inputs[key], quotes[key])
                verified.append(dict(model=model, variant=vid, session=key[0], symbol=key[1], **audit))
            # ----------------------------------------
            # 主結果と同じ最大利益場の除外だけを補足し、条件選択には使用しない。
            if vid in ('E01', 'R01'):
                for symbol in VALUES:
                    selected = [item for item in result['accounts'] if item['symbol'] == symbol and item['session'] in fixed['後12']]
                    excluded = next(item for item in selected if item['session'] == '2026-10-01_Night')
                    total = result['periods']['後12'][symbol]
                    focus.append(dict(model=model, variant=vid, symbol=symbol,
                        後12収支=total['net'], 後12元収支=total['baseline_net'],
                        除外セッション='2026-10-01_Night', 除外気配収支=excluded['summary']['net'],
                        後12除外後収支=total['net'] - excluded['summary']['net'],
                        後12除外後元収支=total['baseline_net'] - excluded['summary']['baseline_net']))
    assert len(verified) == 1792
    out = dict(全合格=True, 検算口座数=len(verified), 検算注文数=sum(item['orders'] for item in verified),
        検算決済数=sum(item['trades'] for item in verified), 完全一致気配=sum(item['exact'] for item in verified),
        過去補完気配=sum(item['past_asof'] for item in verified), 最大気配年齢秒=max(item['max_age'] for item in verified),
        欠測注文数=0, 独立検査=['元注文の数量・行・方向・順序・理由を保持', '元気配の最後の過去連番へ直接照合',
        '未来連番と未来時計不使用', '整数切捨て手数料を全注文で保持', '買売現金勘定と決済損益を照合',
        '全口座の終端残枚数ゼロ', '枚数当たり損益比を独立再計算', '入力32結果のSHA不変'],
        重点条件最大利益場除外=focus, 口座検算=verified,
        発動判定再計算=False, 現在API取得=0, 実注文=0)
    path = HERE / '気配価格置換の独立検算.json'
    assert not path.exists()
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print('独立検算合格:', len(verified), '口座、', out['検算注文数'], '注文、', out['検算決済数'], '決済')
    print('完全一致気配:', out['完全一致気配'], '過去補完:', out['過去補完気配'], '欠測:0')
    for item in focus:
        print(item)


if __name__ == '__main__':
    main()
