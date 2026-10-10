"""発動済み注文列を変えず、ラージ最良気配へ価格だけ置換する感度分析。"""

import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
CACHE = WORK.parent / 'wave_v60/quotes.pkl'
MODELS = ('specified', 'observed')
VALUES = {'TOPIX': 1000., 'NK225': 10.}
MAX_AGE = 30.


def read(path: Path) -> object:
    """機能: 読み取り専用の通常又は圧縮JSONを読む。

    引数: path(Path)。返り値: 保存内容(object)。
    """
    raw = path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix == '.gz' else raw)


def save(name: str, value: object) -> None:
    """機能: 非有限値を拒否し、今回theory配下だけへ有限JSONを保存する。

    引数: name(str)、value(object)。返り値: なし(None)。
    """
    target = HERE / name
    assert target.resolve().is_relative_to(HERE)
    target.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8')
    target.write_bytes(gzip.compress(raw, mtime=0) if target.suffix == '.gz' else raw)


def digest(path: Path) -> str:
    """機能: 元資料を変更せずSHA256を計算する。

    引数: path(Path)。返り値: SHA256文字列(str)。
    """
    result = hashlib.sha256()
    with path.open('rb') as stream:
        while part := stream.read(4 * 1024 * 1024):
            result.update(part)
    return result.hexdigest()


def charge(symbol: str, quantity: int) -> int:
    """機能: 1注文合計の税込片道手数料を整数演算で切り捨てる。

    引数: symbol(str)、quantity(int)。返り値: 円単位の料金(int)。
    """
    assert quantity > 0 and symbol in VALUES
    return quantity * 418 // 10 if symbol == 'TOPIX' else quantity * 11


def load_inputs() -> tuple[dict, list[Path]]:
    """機能: 親が準備した28場56口座の価格入力を変更せず集める。

    引数: なし。返り値: 入力辞書と元ファイル一覧(tuple[dict,list[Path]])。
    """
    inputs, paths = {}, []
    for folder in sorted((WORK / 'prepared').iterdir()):
        path = folder / 'new_inputs.pkl'
        if not path.exists():
            continue
        data = pickle.loads(path.read_bytes())
        assert not set(inputs) & set(data)
        inputs.update(data)
        paths.append(path)
    assert len(inputs) == 56 and len({key[0] for key in inputs}) == 28
    return inputs, paths


def clean_quote(quote: dict) -> dict:
    """機能: 有効な最良気配だけを原板連番順に保持する。

    引数: quote(dict)。返り値: 連番・時計・買売気配の辞書(dict)。
    無効な気配を未来行の気配で埋めず、必要な注文で欠測を明示する。
    """
    seq = np.asarray(quote['seq'], dtype=np.int64)
    time = np.asarray(quote['time_s'], dtype=float)
    bid, ask = np.asarray(quote['bid'], dtype=float), np.asarray(quote['ask'], dtype=float)
    assert seq.ndim == 1 and seq.shape == time.shape == bid.shape == ask.shape
    assert np.all(np.diff(seq) > 0) and np.all(np.diff(time) >= 0)
    mask = np.isfinite(time) & np.isfinite(bid) & np.isfinite(ask) & (bid > 0) & (ask > bid)
    return dict(seq=seq[mask], time_s=time[mask], bid=bid[mask], ask=ask[mask],
                source_rows=len(seq), rejected_rows=int((~mask).sum()))


def load_quotes(inputs: dict) -> tuple[dict, list[Path]]:
    """機能: 既存25場と今回追加3場の保存気配を読み取る。

    引数: inputs(dict)。返り値: 気配辞書と元ファイル一覧(tuple[dict,list[Path]])。
    APIに接続せず、追加場は準備済み約定系列NPZの気配だけを使用する。
    """
    cached = pickle.loads(CACHE.read_bytes())
    quotes, paths = {}, [CACHE]
    missing = []
    for key in sorted(inputs):
        if key in cached:
            quotes[key] = clean_quote(cached[key])
        else:
            path = WORK / 'prepared' / key[0] / 'features' / f'約定系列_{key[1]}_{key[0]}.npz'
            with np.load(path, allow_pickle=False) as saved:
                quotes[key] = clean_quote({name: saved[name] for name in ('seq', 'time_s', 'bid', 'ask')})
            paths.append(path)
            missing.append(key)
    assert len(missing) == 6 and len({key[0] for key in missing}) == 3
    return quotes, paths


def select_quote(ready: dict, quote: dict, row: int, direction: int) -> dict:
    """機能: 注文約定行と同じ原板連番、又は30秒以内の過去気配だけを選ぶ。

    引数: ready/quote(dict)、row/direction(int)。
    返り値: 価格・採用気配連番・照合方法と欠測理由(dict)。
    同じ約定時計でも、注文行より後の原板連番は使用しない。
    """
    assert 0 <= row < len(ready['seq']) and direction in (-1, 1)
    source_seq, source_time = int(ready['seq'][row]), float(ready['time_s'][row])
    index = int(np.searchsorted(quote['seq'], source_seq, side='right')) - 1
    result = dict(order_seq=source_seq, order_time=source_time, available=False,
                  quote_seq=None, quote_time=None, age_seconds=None, match=None, price=None, missing_reason=None)
    if index < 0:
        result['missing_reason'] = '同一行又は過去の有効気配がない'
        return result
    seq, time = int(quote['seq'][index]), float(quote['time_s'][index])
    assert seq <= source_seq, '未来原板行の気配を使用できません'
    age = source_time - time
    exact = seq == source_seq
    if exact:
        assert abs(age) < 1.e-6, '同じ原板行の時計が入力と気配で異なります'
    result.update(quote_seq=seq, quote_time=time, age_seconds=age, match='exact' if exact else 'past_asof')
    if age < -1.e-6:
        result['missing_reason'] = '原板順は過去だが時計が未来である'
    elif age > MAX_AGE + 1.e-6:
        result['missing_reason'] = '過去気配が30秒より古い'
    else:
        result.update(available=True, price=float(quote['ask'][index] if direction > 0 else quote['bid'][index]))
    return result


def statistics(trades: list[dict], campaigns: list[dict], orders: list[dict]) -> dict:
    """機能: 採点不能を除外して成功扱いせず、決済・枚数・組の損益を集計する。

    引数: trades/campaigns/orders(list[dict])。返り値: 完全性を付した集計(dict)。
    欠測があれば全体収支はNoneとし、採点可能な部分は別欄へ残す。
    """
    available = [trade for trade in trades if trade['available']]
    wins, losses, flats = ([trade for trade in available if trade['net'] > 0],
                          [trade for trade in available if trade['net'] < 0],
                          [trade for trade in available if trade['net'] == 0])
    profit, loss = sum(trade['net'] for trade in wins), -sum(trade['net'] for trade in losses)
    winning_lots, losing_lots, flat_lots = (sum(trade['quantity'] for trade in wins),
                                          sum(trade['quantity'] for trade in losses), sum(trade['quantity'] for trade in flats))
    known_campaigns = [campaign for campaign in campaigns if campaign['available']]
    cw, cl = [campaign for campaign in known_campaigns if campaign['net'] > 0], [campaign for campaign in known_campaigns if campaign['net'] < 0]
    cp, cd = sum(campaign['net'] for campaign in cw), -sum(campaign['net'] for campaign in cl)
    complete = len(available) == len(trades) and all(order['available'] for order in orders)
    selected_orders = [order for order in orders if order['available']]
    baseline_net, known_net = sum(trade['baseline_net'] for trade in trades), profit - loss
    fees = sum(order['fee'] for order in orders)
    result = dict(complete=complete, trades=len(trades), available_trades=len(available),
        missing_trades=len(trades) - len(available), orders=len(orders),
        missing_orders=len(orders) - len(selected_orders), exact_orders=sum(order['match'] == 'exact' and order['available'] for order in orders),
        past_asof_orders=sum(order['match'] == 'past_asof' and order['available'] for order in orders),
        wins=len(wins), losses=len(losses), flats=len(flats),
        win_rate=len(wins) / len(trades) if trades and complete else None,
        available_win_rate=len(wins) / len(available) if available else None,
        winning_lots=winning_lots, losing_lots=losing_lots, flat_lots=flat_lots,
        profit=profit if complete else None, loss=loss if complete else None, net=known_net if complete else None,
        gross=sum(trade['gross'] for trade in available) if complete else None, fees=fees, baseline_net=baseline_net,
        quote_net_change=known_net - baseline_net if complete else None,
        payoff=(profit / len(wins)) / (loss / len(losses)) if complete and wins and losses else None,
        lot_payoff=(profit / winning_lots) / (loss / losing_lots) if complete and winning_lots and losing_lots else None,
        campaigns=len(campaigns), available_campaigns=len(known_campaigns), campaign_wins=len(cw), campaign_losses=len(cl),
        campaign_win_rate=len(cw) / len(campaigns) if campaigns and complete else None,
        campaign_profit=cp if complete else None, campaign_loss=cd if complete else None,
        campaign_payoff=(cp / len(cw)) / (cd / len(cl)) if complete and cw and cl else None,
        available_subtotal=dict(profit=profit, loss=loss, net=known_net, wins=len(wins), losses=len(losses), flats=len(flats)),
        available_order_effect=sum(order['net_effect'] for order in selected_orders))
    if complete:
        np.testing.assert_allclose(result['quote_net_change'], result['available_order_effect'], atol=1.e-5)
        np.testing.assert_allclose(result['gross'] - fees, known_net, atol=1.e-5)
        np.testing.assert_allclose(sum(campaign['net'] for campaign in campaigns), known_net, atol=1.e-5)
    return result


def replace_account(ready: dict, quote: dict, ledger: dict) -> dict:
    """機能: 注文の数量・行・方向・理由を固定し、売買気配で価格だけ置換する。

    引数: ready/quote/ledger(dict)。返り値: 置換注文・決済損益・組損益と集計(dict)。
    建値変更に応じた発動条件や次回新規の再計算は行わない。
    """
    symbol, value = ready['symbol'], VALUES[ready['symbol']]
    orders, entries, exits = [], {}, {}
    for number, order in enumerate(ledger['orders']):
        row, source, campaign, side, quantity, price, reason, opened = order
        row, source, campaign, side, quantity, reason, opened = map(int, (row, source, campaign, side, quantity, reason, opened))
        assert 0 <= source < row < len(ready['seq']) and side in (-1, 1) and quantity > 0 and opened in (0, 1)
        selected = select_quote(ready, quote, row, side)
        fee = charge(symbol, quantity)
        item = dict(number=number, row=row, source_row=source, campaign=campaign, side=side,
                    action='新規' if opened else '返済', quantity=quantity, original_price=float(price), fee=fee, reason=reason,
                    **selected)
        item['price_difference'] = item['price'] - price if item['available'] else None
        item['net_effect'] = -side * quantity * item['price_difference'] * value if item['available'] else None
        item['closed_gross'] = item['closed_net'] = None
        orders.append(item)
        mapping = entries if opened else exits
        assert (campaign, row) not in mapping, '同じ組・約定行に複数注文があるため独立配賦が必要です'
        mapping[campaign, row] = item
    np.testing.assert_array_equal([order['fee'] for order in orders], ledger['fees'])
    trades = []
    for trade in ledger['trades']:
        cid, erow, xrow, side, qty = (int(trade[name]) for name in ('組', '新規行', '返済行', '方向', '枚数'))
        entry, exit_order = entries[cid, erow], exits[cid, xrow]
        assert entry['side'] == side and exit_order['side'] == -side
        fees = qty * (entry['fee'] / entry['quantity'] + exit_order['fee'] / exit_order['quantity'])
        np.testing.assert_allclose(fees, trade['手数料'], atol=1.e-7)
        available = entry['available'] and exit_order['available']
        gross = side * qty * (exit_order['price'] - entry['price']) * value if available else None
        net = gross - fees if available else None
        item = dict(campaign=cid, side=side, quantity=qty, entry_row=erow, exit_row=xrow,
            entry_seq=int(ready['seq'][erow]), exit_seq=int(ready['seq'][xrow]),
            entry_time=float(ready['time_s'][erow]), exit_time=float(ready['time_s'][xrow]),
            original_entry_price=float(trade['建値']), original_exit_price=float(trade['返済値']),
            entry_price=entry['price'], exit_price=exit_order['price'], reason=int(trade['理由']),
            available=available, missing_order_numbers=[order['number'] for order in (entry, exit_order) if not order['available']],
            gross=gross, fees=fees, net=net, baseline_gross=float(trade['利益損失前']), baseline_net=float(trade['収支']),
            quote_net_change=net - float(trade['収支']) if available else None)
        trades.append(item)
    campaigns = []
    for cycle in ledger['cycles']:
        cid = int(cycle[0])
        selected = [trade for trade in trades if trade['campaign'] == cid]
        complete = all(trade['available'] for trade in selected)
        campaigns.append(dict(campaign=cid, available=complete, trades=len(selected),
            net=sum(trade['net'] for trade in selected) if complete else None,
            baseline_net=sum(trade['baseline_net'] for trade in selected), initial_risk_yen=float(cycle[4]) * value))
    for order in orders:
        if order['action'] == '返済':
            selected = [trade for trade in trades if trade['campaign'] == order['campaign'] and trade['exit_row'] == order['row']]
            assert sum(trade['quantity'] for trade in selected) == order['quantity']
            if all(trade['available'] for trade in selected):
                order['closed_gross'], order['closed_net'] = sum(trade['gross'] for trade in selected), sum(trade['net'] for trade in selected)
    return dict(session=ready['session'], symbol=symbol, orders=orders, trades=trades, campaigns=campaigns,
                summary=statistics(trades, campaigns, orders), missing_orders=[order for order in orders if not order['available']])


def aggregate(accounts: list[dict], symbol: str, sessions: list[str]) -> dict:
    """機能: 同銘柄の期間損益・勝率・枚数当たり勝敗比を全口座から合算する。

    引数: accounts(list[dict])、symbol(str)、sessions(list[str])。返り値: 完全性付き期間集計(dict)。
    """
    selected = [account for account in accounts if account['symbol'] == symbol and account['session'] in sessions]
    result = statistics([trade for account in selected for trade in account['trades']],
                        [campaign for account in selected for campaign in account['campaigns']],
                        [order for account in selected for order in account['orders']])
    result.update(sessions=len(selected), complete_sessions=sum(account['summary']['complete'] for account in selected),
                  positive_sessions=sum(account['summary']['complete'] and account['summary']['net'] > 0 for account in selected),
                  negative_sessions=sum(account['summary']['complete'] and account['summary']['net'] < 0 for account in selected),
                  active_sessions=sum(account['summary']['trades'] > 0 for account in selected))
    return result


def synthetic() -> dict:
    """機能: 同時計未来行の拒否・過去30秒制限・注文料金配賦を合成データで検査する。

    引数: なし。返り値: 検査結果(dict)。現在APIと親結果にはアクセスしない。
    """
    ready = dict(seq=np.asarray([10, 12, 20, 40]), time_s=np.asarray([100., 102., 110., 135.]))
    quote = clean_quote(dict(seq=np.asarray([10, 11, 21]), time_s=np.asarray([100., 101., 110.]),
                            bid=np.asarray([100., 101., 200.]), ask=np.asarray([102., 103., 202.])))
    assert select_quote(ready, quote, 0, 1)['match'] == 'exact'
    prior = select_quote(ready, quote, 1, 1)
    assert prior['match'] == 'past_asof' and prior['quote_seq'] == 11 and prior['price'] == 103.
    same_clock = select_quote(ready, quote, 2, -1)
    assert same_clock['quote_seq'] == 11 and same_clock['price'] == 101., '同時計でも未来行を拒否します'
    stale_ready = dict(seq=np.asarray([20]), time_s=np.asarray([140.]))
    assert not select_quote(stale_ready, quote, 0, 1)['available']
    early_ready = dict(seq=np.asarray([0]), time_s=np.asarray([99.]))
    assert not select_quote(early_ready, quote, 0, 1)['available']
    # ----------------------------------------
    # 5枚新規・2枚利確・3枚損切りで、料金切捨てと全注文価格差の一致を確認する。
    account_ready = dict(session='合成', symbol='TOPIX', seq=np.arange(4, dtype=np.int64), time_s=np.arange(4, dtype=float))
    account_quote = clean_quote(dict(seq=np.arange(4, dtype=np.int64), time_s=np.arange(4, dtype=float),
                                    bid=np.asarray([99., 99., 109., 89.]), ask=np.asarray([101., 101., 111., 91.])))
    ledger = dict(orders=[[1, 0, 0, 1, 5, 100., 20, 1], [2, 1, 0, -1, 2, 110., 7, 0], [3, 2, 0, -1, 3, 90., 1, 0]],
                  fees=[209, 83, 125], cycles=[[0, 1, 3, 1, 50.]],
                  trades=[dict(組=0, 新規行=1, 返済行=2, 方向=1, 枚数=2, 建値=100., 返済値=110., 理由=7,
                               手数料=166.6, 利益損失前=20000., 収支=19833.4),
                          dict(組=0, 新規行=1, 返済行=3, 方向=1, 枚数=3, 建値=100., 返済値=90., 理由=1,
                               手数料=250.4, 利益損失前=-30000., 収支=-30250.4)])
    actual = replace_account(account_ready, account_quote, ledger)
    np.testing.assert_allclose(actual['summary']['net'], -20417., atol=1.e-7)
    np.testing.assert_allclose(actual['summary']['quote_net_change'], -10000., atol=1.e-7)
    assert actual['summary']['fees'] == 417 and actual['summary']['wins'] == actual['summary']['losses'] == 1
    return dict(全合格=True, 検査=['同一原板行', '過去気配', '同時計の未来行拒否', '30秒超気配拒否',
        '過去気配なしを欠測', '注文合計料金切捨て', '部分返済への料金配賦', '全注文価格差と損益変化一致'],
        現在API取得=0, 主結果参照=0)


def prepare() -> None:
    """機能: 主結果を採点する前に16条件×2モデルの価格置換契約を固定する。

    引数: なし。返り値: なし(None)。既存固定の上書きとAPI取得はしない。
    """
    target = HERE / '気配価格置換の事前固定.json'
    assert not target.exists()
    fixed = read(WORK / '事前固定.json')
    inputs, input_paths = load_inputs()
    _, quote_paths = load_quotes(inputs)
    save('気配価格置換の合成監査.json', synthetic())
    paths = [Path(__file__), WORK / '事前固定.json', HERE / '気配価格置換の合成監査.json', *input_paths, *quote_paths]
    save(target.name, dict(時刻=datetime.now(timezone.utc).isoformat(), 条件ID=[value['id'] for value in fixed['条件']],
        モデル=list(MODELS), 全セッション=fixed['全セッション'], 前16=fixed['前16'], 後12=fixed['後12'],
        条件数=16, 口座数=56, 予定口座計算数=1792, 最大過去気配秒=MAX_AGE,
        価格='新規買ask・売bid、返済も注文売買方向に従う。原板seq完全一致優先、欠測時は現在seq以下・時計以下・30秒以内の最終有効気配。',
        欠測='欠測注文と採点不能決済を全件記録。欠測をゼロ損益・勝ちとしない。完全期間収支はNone、採点可能部分を別欄へ。',
        固定するもの='親指定/observed結果の注文数量・発動行・発動時刻・方向・並び・理由・料金。',
        再計算しないもの='入口判定・約定値変更に伴う損切り線や追跡線・途中の枚数判断・再エントリー。',
        位置づけ='固定注文列の価格感度分析。気配を使って判断全体を再生成したバックテストや小商品実注文の証明ではない。',
        約定限界='ラージ気配をmini/microへ代用。板を食う数量・発注遅延・実小商品スプレッドは再現しない。過去asofは実約定可能価格を保証しない。',
        会計='元注文合計floor料金を維持し、新規料金を返済枚数で按分。注文別の収支影響=-売買符号×枚数×価格差×円倍率。',
        ファイルSHA={str(path): digest(path) for path in paths}, 現在API取得=0, 実注文=0))
    print('16条件×2モデル×56口座の固定注文価格置換を準備しました。主結果の実行GOを待ちます。')


def run() -> None:
    """機能: 親の両約定モデル完成後に1792口座の価格置換と期間集計を行う。

    引数: なし。返り値: なし(None)。原資料は変更せず、条件選択や実注文をしない。
    """
    fixed = read(HERE / '気配価格置換の事前固定.json')
    amendment = read(HERE / '気配価格置換の実装補正.json') if (HERE / '気配価格置換の実装補正.json').exists() else None
    for name, expected in fixed['ファイルSHA'].items():
        actual = digest(Path(name))
        if Path(name).resolve() == Path(__file__).resolve() and amendment is not None:
            assert expected == amendment['補正前SHA'] and actual == amendment['補正後SHA']
            assert amendment['条件変更'] is False and amendment['補正内容'] == 'theory配下の出力サブフォルダを保存前に作成する。計算条件・気配選択・料金式は不変。'
        else:
            assert actual == expected, (name, '事前固定から変更されています')
    assert not (HERE / '気配価格置換の完了.json').exists()
    sources = {(model, identifier): WORK / model / f'{identifier}.json.gz'
               for model in MODELS for identifier in fixed['条件ID']}
    assert all(path.exists() for path in sources.values()), '指定/観測の全32結果が完成するまで実行しません'
    inputs, _ = load_inputs()
    quotes, _ = load_quotes(inputs)
    summaries, missing_all, fingerprints = [], [], {}
    account_count = 0
    for (model, identifier), path in sources.items():
        source = read(path)
        assert source['model'] == model and source['variant']['id'] == identifier
        assert len(source['rows']) == len(source['ledgers']) == 56
        assert {(ledger['session'], ledger['symbol']) for ledger in source['ledgers']} == set(inputs)
        fingerprints[str(path)] = digest(path)
        accounts = []
        original = {(row['session'], row['symbol']): row for row in source['rows']}
        for ledger in source['ledgers']:
            key = ledger['session'], ledger['symbol']
            account = replace_account(inputs[key], quotes[key], ledger)
            np.testing.assert_allclose(account['summary']['baseline_net'], original[key]['net'], atol=1.e-5)
            account['baseline_summary'] = original[key]
            accounts.append(account)
            missing_all.extend(dict(model=model, variant=identifier, session=key[0], symbol=key[1], **order)
                               for order in account['missing_orders'])
        periods = {label: {symbol: aggregate(accounts, symbol, sessions) for symbol in VALUES}
                   for label, sessions in (('前16', fixed['前16']), ('後12', fixed['後12']),
                       ('全28', fixed['全セッション']), ('直近3', fixed['全セッション'][-3:]))}
        output = f'気配価格置換/{model}_{identifier}.json.gz'
        save(output, dict(variant=source['variant'], origin_model=model, accounts=accounts, periods=periods,
                         sensitivity_only=True, decisions_recomputed=False, source_SHA=fingerprints[str(path)]))
        summaries.append(dict(variant=source['variant'], origin_model=model, periods=periods,
                              result_file=output, result_SHA=digest(HERE / output)))
        account_count += len(accounts)
        print(model, identifier, '価格置換完了', '欠測注文', sum(account['summary']['missing_orders'] for account in accounts), flush=True)
    assert account_count == 1792
    save('気配価格置換の集計.json', dict(methods=summaries, 全合格=True, 口座計算数=account_count,
        モデル数=2, 条件数=16, 場数=28, 欠測注文数=len(missing_all),
        位置づけ=fixed['位置づけ'], 再計算しないもの=fixed['再計算しないもの'], 現在API取得=0, 実注文=0))
    save('気配価格置換の全欠測注文.json', dict(件数=len(missing_all), 全件=missing_all,
        注記='欠測注文の価格を未来気配・理想価格・ゼロで埋めていない。'))
    save('気配価格置換の完了.json', dict(全合格=True, 口座計算数=account_count, 欠測注文数=len(missing_all),
        固定SHA=digest(HERE / '気配価格置換の事前固定.json'), 入力結果SHA=fingerprints,
        出力SHA={name: digest(HERE / name) for name in ('気配価格置換の集計.json', '気配価格置換の全欠測注文.json')},
        原資料変更=False, 発動判定再計算=False, 現在API取得=0, 実注文=0))
    print('全1792口座の固定注文価格置換を完了しました。')


def main() -> None:
    """機能: ネット無しの事前準備と親GO後の全結果価格置換を選択する。

    引数: コマンド引数stage(str)。返り値: なし(None)。
    """
    parser = argparse.ArgumentParser(description='固定注文列の最良気配による価格感度分析。')
    parser.add_argument('stage', choices=('prepare', 'run'))
    args = parser.parse_args()
    prepare() if args.stage == 'prepare' else run()


if __name__ == '__main__':
    main()
