"""損失低減台帳の売買価格を過去最良気配へ置換し、別実装で会計を検査する。"""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
PRIOR = WORK.parent / 'wave_v67'
VALUES = {'TOPIX': 1000, 'NK225': 10}
BASELINE = 'R01'


def read(path: Path) -> object:
    """機能: 通常または圧縮 JSON を読み取り専用で読む。

    引数: path(Path)。返り値: 保存された内容(object)。
    """
    raw = path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix == '.gz' else raw)


def save(path: Path, value: object) -> None:
    """機能: 有限値のみの JSON を今回 review 内へ保存する。

    引数: path(Path)、value(object)。返り値: なし(None)。
    """
    assert path.resolve().is_relative_to(HERE)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8')
    path.write_bytes(gzip.compress(raw, mtime=0) if path.suffix == '.gz' else raw)


def sha(path: Path) -> str:
    """機能: 読み取り専用で資料の SHA256 を計算する。

    引数: path(Path)。返り値: 指紋の文字列(str)。
    """
    result = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(4 * 1024 * 1024):
            result.update(block)
    return result.hexdigest()


def fee(symbol: str, quantity: int) -> int:
    """機能: 注文合計の片道料金を整数式で切り捨てる。

    引数: symbol(str)、quantity(int)。返り値: 円の料金(int)。
    """
    assert quantity > 0
    return quantity * 418 // 10 if symbol == 'TOPIX' else quantity * 11


def collect() -> tuple[dict, dict, list[Path]]:
    """機能: 前回準備済み入力と原保存気配を API 接続なしで集める。

    引数: なし。返り値: 価格入力、気配、資料パス(tuple[dict,dict,list[Path]])。
    """
    inputs, paths = {}, []
    for path in sorted((PRIOR / 'prepared').glob('*/new_inputs.pkl')):
        part = pickle.loads(path.read_bytes())
        assert not set(part) & set(inputs)
        inputs.update(part)
        paths.append(path)
    cache_path = WORK.parent / 'wave_v60/quotes.pkl'
    cache = pickle.loads(cache_path.read_bytes())
    paths.append(cache_path)
    quotes = {}
    for key in inputs:
        if key in cache:
            raw = cache[key]
        else:
            path = PRIOR / 'prepared' / key[0] / 'features' / f'約定系列_{key[1]}_{key[0]}.npz'
            with np.load(path, allow_pickle=False) as data:
                raw = {name: data[name].copy() for name in ('seq', 'time_s', 'bid', 'ask')}
            paths.append(path)
        valid = np.isfinite(raw['time_s']) & np.isfinite(raw['bid']) & np.isfinite(raw['ask'])
        valid &= (raw['bid'] > 0) & (raw['ask'] > raw['bid'])
        chosen = {name: np.asarray(raw[name])[valid] for name in ('seq', 'time_s', 'bid', 'ask')}
        assert np.all(np.diff(chosen['seq']) > 0) and np.all(np.diff(chosen['time_s']) >= 0)
        quotes[key] = chosen
    assert len(inputs) == len(quotes) == 56
    return inputs, quotes, paths


def quote_at(ready: dict, quote: dict, row: int, side: int) -> dict:
    """機能: 注文原板連番以下の最後の有効気配を採用する。

    引数: ready/quote(dict)、row/side(int)。返り値: 気配選択と欠測理由(dict)。
    同時計の未来原板行、30 秒を超える過去気配、未来時計を使用しない。
    """
    order_seq, order_time = int(ready['seq'][row]), float(ready['time_s'][row])
    index = int(quote['seq'].searchsorted(order_seq, side='right')) - 1
    result = dict(available=False, order_seq=order_seq, order_time=order_time,
                  quote_seq=None, quote_time=None, age_seconds=None, price=None, match=None, missing=None)
    if index < 0:
        result['missing'] = '過去の有効気配なし'
        return result
    seq, time = int(quote['seq'][index]), float(quote['time_s'][index])
    age = order_time - time
    result.update(quote_seq=seq, quote_time=time, age_seconds=age, match='exact' if seq == order_seq else 'past_asof')
    assert seq <= order_seq
    if age < -1.e-6:
        result['missing'] = '気配時計が未来'
    elif age > 30.000001:
        result['missing'] = '気配が30秒超古い'
    else:
        result.update(available=True, price=float(quote['ask' if side > 0 else 'bid'][index]))
        if seq == order_seq:
            assert abs(age) < 1.e-6
    return result


def near(left: float, right: float) -> None:
    """機能: 浮動小数誤差だけを許容して会計を照合する。

    引数: left/right(float)。返り値: なし(None)。
    """
    assert abs(left - right) < 1.e-5, (left, right)


def replace(ready: dict, quotes: dict, ledger: dict) -> dict:
    """機能: 数量と注文経路を固定し、気配価格の現金勘定を独立再計算する。

    引数: ready/quotes/ledger(dict)。返り値: 検算済み口座(dict)。
    条件判定・損切り線・トレール線・次回入口の再計算は行わない。
    """
    symbol, value = ledger['symbol'], VALUES[ledger['symbol']]
    orders, mapping, missing = [], {}, []
    cash = baseline_cash = 0.
    position = max_position = 0
    previous_row = -1
    for number, raw in enumerate(ledger['orders']):
        row, trigger, cid, side, quantity, price, reason, opened = raw
        row, trigger, cid, side, quantity, reason, opened = map(int, (row, trigger, cid, side, quantity, reason, opened))
        assert 0 <= trigger < row < len(ready['seq']) and row >= previous_row
        assert side in (-1, 1) and quantity > 0 and opened in (0, 1)
        previous_row = row
        order_fee = fee(symbol, quantity)
        assert order_fee == ledger['fees'][number]
        selected = quote_at(ready, quotes, row, side)
        order = dict(number=number, row=row, trigger_row=trigger, campaign=cid, side=side,
                     quantity=quantity, reason=reason, opened=opened, baseline_price=float(price), fee=order_fee, **selected)
        orders.append(order)
        key = cid, row, opened
        assert key not in mapping
        mapping[key] = order
        baseline_cash -= side * quantity * price * value + order_fee
        if selected['available']:
            cash -= side * quantity * selected['price'] * value + order_fee
        else:
            missing.append(number)
        position += side * quantity
        max_position = max(max_position, abs(position))
        assert abs(position) <= (5 if symbol == 'TOPIX' else 10)
    assert position == 0
    # ----------------------------------------
    # 部分返済には新規注文料金を枚数比例で配賦し、元台帳とも照合する。
    trades = []
    for raw in ledger['trades']:
        cid, erow, xrow, side, qty = (int(raw[name]) for name in ('組', '新規行', '返済行', '方向', '枚数'))
        entry, close = mapping[cid, erow, 1], mapping[cid, xrow, 0]
        assert entry['side'] == side and close['side'] == -side
        costs = qty * (entry['fee'] / entry['quantity'] + close['fee'] / close['quantity'])
        near(costs, raw['手数料'])
        available = entry['available'] and close['available']
        gross = side * qty * (close['price'] - entry['price']) * value if available else None
        trades.append(dict(campaign=cid, entry_row=erow, exit_row=xrow, side=side, quantity=qty,
            available=available, gross=gross, fees=costs, net=gross - costs if available else None,
            baseline_net=float(raw['収支']), reason=int(raw['理由'])))
    for order in orders:
        if order['opened'] == 0:
            selected = [trade for trade in trades if trade['campaign'] == order['campaign'] and trade['exit_row'] == order['row']]
            assert sum(trade['quantity'] for trade in selected) == order['quantity']
    campaigns = []
    for raw in ledger['cycles']:
        cid = int(raw[0])
        selected = [trade for trade in trades if trade['campaign'] == cid]
        assert selected
        complete = all(trade['available'] for trade in selected)
        campaigns.append(dict(campaign=cid, available=complete,
            net=sum(trade['net'] for trade in selected) if complete else None,
            baseline_net=sum(trade['baseline_net'] for trade in selected),
            initial_risk=float(raw[4]) * value, entry_row=int(raw[1]), exit_row=int(raw[2])))
    complete = not missing
    quoted_net = sum(trade['net'] for trade in trades) if complete else None
    near(sum(trade['baseline_net'] for trade in trades), baseline_cash)
    near(sum(trade['fees'] for trade in trades), sum(order['fee'] for order in orders))
    if complete:
        near(cash, quoted_net)
        near(quoted_net, sum(campaign['net'] for campaign in campaigns))
        near(quoted_net - baseline_cash, sum(-order['side'] * order['quantity'] *
             (order['price'] - order['baseline_price']) * value for order in orders))
    return dict(session=ledger['session'], symbol=symbol, orders=orders, trades=trades,
                campaigns=campaigns, complete=complete, missing_orders=missing, net=quoted_net,
                baseline_net=baseline_cash, fees=sum(order['fee'] for order in orders), max_position=max_position)


def metrics(accounts: list[dict], sessions: list[str], symbol: str) -> dict:
    """機能: 決済と組の損失、活動率、場末最大下落を銘柄別で集計する。

    引数: accounts(list[dict])、sessions(list[str])、symbol(str)。返り値: 期間集計(dict)。
    一部欠測があれば完全期間の収支・勝敗値は返さない。
    """
    selected = sorted([account for account in accounts if account['symbol'] == symbol and account['session'] in sessions],
                      key=lambda account: sessions.index(account['session']))
    assert len(selected) == len(sessions)
    result = dict(complete=all(account['complete'] for account in selected), sessions=len(selected),
                  active_sessions=sum(bool(account['campaigns']) for account in selected),
                  campaigns=sum(len(account['campaigns']) for account in selected),
                  trades=sum(len(account['trades']) for account in selected),
                  fees=sum(account['fees'] for account in selected),
                  missing_orders=sum(len(account['missing_orders']) for account in selected))
    if not result['complete']:
        return result
    trades = [trade for account in selected for trade in account['trades']]
    campaigns = [campaign for account in selected for campaign in account['campaigns']]
    wins, losses = [trade for trade in trades if trade['net'] > 0], [trade for trade in trades if trade['net'] < 0]
    cw, cl = [campaign for campaign in campaigns if campaign['net'] > 0], [campaign for campaign in campaigns if campaign['net'] < 0]
    profit, loss = sum(trade['net'] for trade in wins), -sum(trade['net'] for trade in losses)
    cp, cd = sum(campaign['net'] for campaign in cw), -sum(campaign['net'] for campaign in cl)
    wl, ll = sum(trade['quantity'] for trade in wins), sum(trade['quantity'] for trade in losses)
    cumulative, peak, dd, run, maxrun = 0., 0., 0., 0, 0
    for account in selected:
        cumulative += account['net']
        peak = max(peak, cumulative)
        dd = max(dd, peak - cumulative)
        run = run + 1 if account['net'] < 0 else 0
        maxrun = max(maxrun, run)
    day_nets = {}
    for account in selected:
        day = account['session'].split('_')[0]
        day_nets[day] = day_nets.get(day, 0.) + account['net']
    best_day = max(day_nets, key=day_nets.get)
    result.update(net=profit-loss, profit=profit, loss=loss, wins=len(wins), losses=len(losses),
        winning_lots=wl, losing_lots=ll, lot_payoff=(profit / wl) / (loss / ll) if wl and ll else None,
        campaign_wins=len(cw), campaign_losses=len(cl), campaign_profit=cp, campaign_loss=cd,
        average_losing_campaign=cd / len(cl) if cl else 0.,
        maximum_losing_campaign=max((-campaign['net'] for campaign in cl), default=0.),
        campaign_payoff=(cp / len(cw)) / (cd / len(cl)) if cw and cl else None,
        campaign_win_rate=len(cw) / len(campaigns) if campaigns else None,
        negative_sessions=sum(account['net'] < 0 for account in selected),
        positive_sessions=sum(account['net'] > 0 for account in selected),
        worst_session=min((account['net'] for account in selected), default=0.),
        settlement_max_drawdown=dd, longest_negative_session_run=maxrun,
        maximum_profit_day=best_day, net_without_maximum_profit_day=profit-loss-day_nets[best_day])
    near(result['net'], sum(account['net'] for account in selected))
    return result


def comparison(candidate: dict, base: dict) -> dict:
    """機能: 損失削減と利益・組数維持を同銘柄の比率で確認する。

    引数: candidate/base(dict)。返り値: 維持率と削減率(dict)。
    """
    result = dict(complete=candidate['complete'] and base['complete'])
    if result['complete']:
        result.update(net_change=candidate['net']-base['net'],
            loss_reduction=1-candidate['loss']/base['loss'] if base['loss'] > 0 else None,
            profit_retention=candidate['profit']/base['profit'] if base['profit'] > 0 else None,
            campaign_loss_reduction=1-candidate['campaign_loss']/base['campaign_loss'] if base['campaign_loss'] > 0 else None,
            campaign_profit_retention=candidate['campaign_profit']/base['campaign_profit'] if base['campaign_profit'] > 0 else None,
            campaign_count_retention=candidate['campaigns']/base['campaigns'] if base['campaigns'] else None,
            settlement_drawdown_change=candidate['settlement_max_drawdown']-base['settlement_max_drawdown'],
            average_loss_change=candidate['average_losing_campaign']-base['average_losing_campaign'])
    return result


def synthetic() -> None:
    """機能: 同時計の未来行拒否と 30 秒制限を合成配列で検査する。

    引数: なし。返り値: なし(None)。
    """
    ready = dict(seq=np.array([20, 40, 0]), time_s=np.array([110., 141., 99.]))
    quote = dict(seq=np.array([10, 11, 21]), time_s=np.array([100., 101., 110.]),
                 bid=np.array([100., 101., 200.]), ask=np.array([102., 103., 202.]))
    result = quote_at(ready, quote, 0, 1)
    assert result['price'] == 103 and result['quote_seq'] == 11
    assert not quote_at(ready, quote, 1, 1)['available']
    assert not quote_at(ready, quote, 2, -1)['available']


def run() -> None:
    """機能: 親が完成した新台帳を価格置換し、全条件の独立集計を保存する。

    引数: なし。返り値: なし(None)。親の出力形式確定後に実行する。
    """
    fixed = read(WORK / '事前固定.json')
    identifiers = [variant['id'] for variant in fixed['条件']]
    sessions, front, later = fixed['全セッション'], fixed['前16'], fixed['後12']
    assert BASELINE in identifiers
    inputs, quotes, paths = collect()
    synthetic()
    assert not (HERE / '気配価格置換の完了.json').exists()
    freeze = dict(条件ID=identifiers, 初回枚数={'TOPIX': 5, 'NK225': 10}, 最大過去気配秒=30,
        価格='原板連番以下かつ時計以下の最終有効気配。買ask、売bid。',
        位置づけ='固定注文価格感度。発動線や注文経路の再計算ではない。',
        入力SHA={str(path): sha(path) for path in paths}, 実装SHA=sha(Path(__file__)),
        親固定SHA=sha(WORK / '事前固定.json'), 現在API取得=0, 実注文=0)
    save(HERE / '気配価格置換の事前固定.json', freeze)
    summaries, total_orders, total_trades, source_shas = [], 0, 0, {}
    for model in ('observed',):
        group = []
        for identifier in identifiers:
            path = WORK / model / f'{identifier}.json.gz'
            source = read(path)
            assert source['variant']['id'] == identifier and source['model'] == model
            assert len(source['ledgers']) == 56
            source_shas[str(path)] = sha(path)
            accounts = [replace(inputs[(ledger['session'], ledger['symbol'])],
                        quotes[(ledger['session'], ledger['symbol'])], ledger) for ledger in source['ledgers']]
            original = {(row['session'], row['symbol']): row for row in source['rows']}
            for account in accounts:
                near(account['baseline_net'], original[account['session'], account['symbol']]['net'])
            periods = {label: {symbol: metrics(accounts, chosen, symbol) for symbol in VALUES}
                for label, chosen in (('前16', front), ('後12', later), ('全28', sessions), ('直近3', sessions[-3:]))}
            output = HERE / '価格置換' / f'{model}_{identifier}.json.gz'
            save(output, dict(variant=source['variant'], model=model, accounts=accounts, periods=periods,
                             sensitivity_only=True, decisions_recomputed=False, source_SHA=source_shas[str(path)]))
            group.append(dict(id=identifier, base=source['variant'].get('base', identifier),
                              name=source['variant']['name'], model=model, periods=periods,
                              output=str(output.relative_to(HERE))))
            total_orders += sum(len(account['orders']) for account in accounts)
            total_trades += sum(len(account['trades']) for account in accounts)
            print(model, identifier, '気配会計検算完了', flush=True)
        baseline = next(item for item in group if item['id'] == BASELINE)
        for item in group:
            own_base = next(base for base in group if base['id'] == item['base'])
            item['対R01'] = {label: {symbol: comparison(item['periods'][label][symbol], baseline['periods'][label][symbol])
                                   for symbol in VALUES} for label in item['periods']}
            item['対応基準比較'] = {label: {symbol: comparison(item['periods'][label][symbol], own_base['periods'][label][symbol])
                                       for symbol in VALUES} for label in item['periods']}
        summaries.extend(group)
    save(HERE / '気配価格置換の集計.json', dict(methods=summaries, 条件数=len(identifiers), 現在API取得=0, 実注文=0))
    save(HERE / '気配価格置換の完了.json', dict(全合格=True, モデル='observed', 条件数=len(identifiers), 口座数=56*len(identifiers),
        注文検算数=total_orders, 決済検算数=total_trades, 入力結果SHA=source_shas,
        独立検査=['原板seqと時計の未来不使用', '30秒気配期限', '同時計未来行拒否の合成検査',
        '注文合計料金切捨て', '部分決済の新規料金配賦', '売買現金勘定一致', '終端残枚数ゼロ',
        '初回5/10枚超保有なし', '全組会計と全決済会計一致'],
        位置づけ=freeze['位置づけ'], 発動判断再計算=False, 現在API取得=0, 実注文=0))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='損失低減の固定注文価格感度と独立会計検査')
    parser.add_argument('stage', choices=('synthetic', 'run'))
    run() if parser.parse_args().stage == 'run' else synthetic()
