"""診断に基づく第1ラウンド21条件を固定し、旧入口と新入口・三出口を対照比較する。"""

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import pickle
import shutil

import numpy as np

import features
import signals
from engine import execute, ORDER_COLUMNS, TRADE_COLUMNS, REASONS


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROUND = HERE / 'round1'
CODE_NAMES = ('features.py', 'signals.py', 'engine.py', 'fees.py', 'run.py', 'check_engine.py')


def digest(path: Path) -> str:
    """機能: コード・入力・仕様の内容をSHA256へ変換する。

    引数: path(Path)。
    返り値: SHA256文字列(str)。
    """
    h = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(4 * 1024 * 1024):
            h.update(block)
    return h.hexdigest()


def clean(value: object) -> object:
    """機能: NumPy型と非有限値を有限JSON表現へ整える。

    引数: value(object)。
    返り値: 辞書・一覧・数値・None等のJSON型(object)。
    """
    if isinstance(value, dict):
        return {key: clean(item) for key, item in value.items()}
    if isinstance(value, np.ndarray):
        return clean(value.tolist())
    if isinstance(value, (tuple, list)):
        return [clean(item) for item in value]
    if isinstance(value, (np.integer, np.floating)):
        return clean(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def save(path: Path, value: object) -> None:
    """機能: UTF-8の日本語JSONを保存する。

    引数: path(Path)、value(object)。
    返り値: なし(None)。
    """
    path.write_text(json.dumps(clean(value), ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def week_of(session: str) -> str:
    """機能: セッション開始日の属する週の月曜日を求める。

    引数: session(str)。
    返り値: YYYY-MM-DD文字列(str)。
    """
    day = datetime.fromisoformat(session.split('_')[0])
    return (day - timedelta(days=day.weekday())).date().isoformat()


def frozen_content() -> dict:
    """機能: 条件とコードと元入力の改変を検出する固定内容を作る。

    引数: なし。
    返り値: SHAと機械条件の辞書(dict)。
    """
    paths = (WORK.parent / 'wave_v60/inputs.pkl', WORK.parent / 'wave_v60/quotes.pkl',
             ROUND / 'features.pkl', ROUND / '入口候補.pkl')
    return {'条件': signals.methods(), '主条件': [v['id'] for v in signals.methods() if v['primary']],
            'コードSHA256': {name: digest(HERE / name) for name in CODE_NAMES},
            '自枝仕様SHA256': digest(ROUND / '仕様.json'),
            '入力SHA256': {str(path.resolve()): digest(path) for path in paths},
            '注文列': ORDER_COLUMNS, '返済列': TRADE_COLUMNS, '返済理由': REASONS}


def verify_freeze() -> dict:
    """機能: 凍結以後のコード・条件・入力変更がないことを検査する。

    引数: なし。
    返り値: 保存済み固定内容(dict)。不一致は例外停止する。
    """
    frozen = json.loads((ROUND / '実行前固定.json').read_text(encoding='utf-8'))
    for key, value in clean(frozen_content()).items():
        if key == '返済理由':
            value = {str(k): v for k, v in value.items()}
        assert value == frozen[key], key
    return frozen


def prepare() -> None:
    """機能: 特徴と候補だけを生成して因果監査し、実売買前に条件を凍結する。

    引数: なし。
    返り値: なし(None)。売買器は実データへ呼び出さない。
    """
    if (ROUND / '実行前固定.json').exists():
        verify_freeze()
        return
    inputs, quotes = features.load_inputs()
    frames, candidates, audits = {}, {}, []
    base = {key: features.build(ready, quotes[key], features.SETTINGS[0]) for key, ready in inputs.items()}
    old = pickle.loads((WORK.parent / 'wave_v61/directional/入口候補.pkl').read_bytes())
    for key, ready in inputs.items():
        other = (key[0], 'NK225' if key[1] == 'TOPIX' else 'TOPIX')
        frame = signals.join_partner(base[key], base[other])
        frames[key] = frame
        audit = features.audit(ready, quotes[key], features.SETTINGS[0], base[key])
        found = signals.candidates(frame, float(quotes[key]['mid'][0]), ready['tick'])
        for n in (0, 1, len(frame) // 2):
            partial = signals.candidates(frame.iloc[:n], float(quotes[key]['mid'][0]), ready['tick'])
            for name in found:
                expected = found[name][:0] if n == 0 else found[name][found[name][:, 0] <= frame.iloc[n - 1]['i']]
                np.testing.assert_array_equal(partial[name], expected)
        found['O2_N'], found['O4_N'] = old[key]['W10']['D2'], old[key]['W10']['D4']
        candidates[key] = found
        audits.append({'session': key[0], 'symbol': key[1], **audit,
                       '候補数': {name: len(rows) for name, rows in found.items()}})
    (ROUND / 'features.pkl').write_bytes(pickle.dumps(frames, protocol=pickle.HIGHEST_PROTOCOL))
    (ROUND / '入口候補.pkl').write_bytes(pickle.dumps(candidates, protocol=pickle.HIGHEST_PROTOCOL))
    save(ROUND / '特徴入口の因果監査.json', {'合格': True, '口座数': len(inputs), '実データ損益計算': False,
                                          '二指数の受信時計不明は参考限定': True, '口座別': audits})
    assert len(signals.methods()) == 21 and sum(v['primary'] for v in signals.methods()) == 2
    assert json.loads((HERE / '売買器の合成監査.json').read_text(encoding='utf-8'))['合格']
    frozen = frozen_content()
    frozen.update(固定時刻=datetime.now(timezone(timedelta(hours=9))).isoformat(), 実データ損益計算前=True,
                  既知25場=True, 未知検証ではない=True, 気配約定のみ=True, 中値利益の採用=False)
    save(ROUND / '実行前固定.json', frozen)
    (ROUND / 'code').mkdir(exist_ok=True)
    for name in CODE_NAMES:
        shutil.copyfile(HERE / name, ROUND / 'code' / name)
    print(json.dumps({'準備完了': True, '条件数': 21, '実データ損益計算': False}, ensure_ascii=False), flush=True)


def summarize(accounts: list[dict]) -> dict:
    """機能: 同銘柄・同約定方式の場を会計し、ロット勝敗と組勝敗を区別する。

    引数: accounts(list[dict]) は同銘柄の口座。
    返り値: 全体又は週の集計(dict)。原本行の資産下落は場別極値から連結する。
    """
    keys = ('gross_pnl', 'gross_profit', 'gross_loss', 'fees', 'net', 'profit', 'loss', 'win_qty', 'loss_qty',
            'flat_qty', 'lot_trades', 'wins', 'losses', 'cycles', 'group_wins', 'group_losses', 'group_profit',
            'group_loss', 'additions', 'added_lot_net', 'initial_lot_net')
    result = {name: sum(a[name] for a in accounts) for name in keys}
    level = peak = drawdown = 0.
    for account in sorted(accounts, key=lambda a: a['session']):
        drawdown = max(drawdown, account['drawdown'], peak - (level + account['equity_min']))
        peak = max(peak, level + account['equity_max'])
        level += account['net']
    win = result['profit'] / result['win_qty'] if result['win_qty'] else None
    loss = result['loss'] / result['loss_qty'] if result['loss_qty'] else None
    holds = np.array([hold for a in accounts for hold in a['group_hold_minutes']])
    result.update(pf=result['profit'] / result['loss'] if result['loss'] else None,
                  payoff=win / loss if win is not None and loss else None, win_per_lot=win, loss_per_lot=loss,
                  win_rate=result['wins'] / result['lot_trades'] if result['lot_trades'] else None,
                  group_win_rate=result['group_wins'] / result['cycles'] if result['cycles'] else None,
                  group_pf=result['group_profit'] / result['group_loss'] if result['group_loss'] else None,
                  sessions=len(accounts), positive_sessions=sum(a['net'] > 0 for a in accounts),
                  negative_sessions=sum(a['net'] < 0 for a in accounts), active_sessions=sum(a['cycles'] > 0 for a in accounts),
                  without_best=result['net'] - max(0., max((a['net'] for a in accounts), default=0)), drawdown=drawdown,
                  max_long_qty=max((a['max_long_qty'] for a in accounts), default=0),
                  max_short_qty=max((a['max_short_qty'] for a in accounts), default=0),
                  unrealized_start=0., unrealized_end=0., mtm_change=result['net'], budget_halt_sessions=sum(a['halted'] for a in accounts),
                  hold_mean_minutes=float(holds.mean()) if len(holds) else None,
                  hold_median_minutes=float(np.median(holds)) if len(holds) else None,
                  hold_min_minutes=float(holds.min()) if len(holds) else None,
                  hold_max_minutes=float(holds.max()) if len(holds) else None,
                  reasons={name: {field: sum(a['reasons'][name][field] for a in accounts) for field in ('cycles', 'net')}
                           for name in REASONS.values()})
    mean_win = result['group_profit'] / result['group_wins'] if result['group_wins'] else None
    mean_loss = result['group_loss'] / result['group_losses'] if result['group_losses'] else None
    result.update(group_mean_win=mean_win, group_mean_loss=mean_loss,
                  group_payoff=mean_win / mean_loss if mean_win is not None and mean_loss else None,
                  max_losing_session=min((a['net'] for a in accounts), default=0),
                  active_rate=result['active_sessions'] / len(accounts) if accounts else None,
                  net_qty=result['win_qty'] - result['loss_qty'])
    np.testing.assert_allclose(result['net'], result['profit'] - result['loss'], atol=1e-5)
    np.testing.assert_allclose(result['net'], result['gross_pnl'] - result['fees'], atol=1e-5)
    return result


def run() -> None:
    """機能: 親の設計GO後に固定21条件を気配で再生し、会計と台帳を分離保存する。

    引数: なし。
    返り値: なし(None)。結果を見て条件や主条件を差し替えない。
    """
    frozen = verify_freeze()
    target = ROUND / '集計結果.json'
    if target.exists() or (ROUND / '計算開始.json').exists():
        raise RuntimeError('既に計算開始済みです。既存結果を上書きしません')
    save(ROUND / '計算開始.json', {'時刻': datetime.now().astimezone().isoformat(), '親GO後': True})
    inputs, quotes = features.load_inputs()
    candidates = pickle.loads((ROUND / '入口候補.pkl').read_bytes())
    (ROUND / 'ledgers').mkdir(exist_ok=True)
    methods, norders, ntrades = [], 0, 0
    for number, config in enumerate(signals.methods(), 1):
        accounts, ledgers = [], {}
        ledger_path = ROUND / 'ledgers' / f'{config["id"]}.pkl'
        for key in sorted(inputs):
            for mode in (True,):
                name = config['family'] + ('_F' if config['spread_filter'] else '_N')
                account = execute(inputs[key], quotes[key], candidates[key][name], config, mode)
                ledger_key = (*key, account['price_mode'])
                orders, trades = account.pop('orders'), account.pop('trades')
                ledgers[ledger_key] = {'orders': orders, 'trades': trades}
                account.update(week=week_of(key[0]), ledger=str(ledger_path.relative_to(ROUND)).replace('\\', '/'),
                               ledger_key=list(ledger_key))
                accounts.append(account)
                norders, ntrades = norders + len(orders), ntrades + len(trades)
        ledger_path.write_bytes(pickle.dumps(ledgers, protocol=pickle.HIGHEST_PROTOCOL))
        item = dict(**config, config=config, accounts=accounts, summary={}, weeks={}, mid_summary={}, mid_weeks={},
                    ledger=str(ledger_path.relative_to(ROUND)).replace('\\', '/'), ledger_sha256=digest(ledger_path))
        for symbol in ('TOPIX', 'NK225'):
            for mode, sum_key, week_key in (('quote', 'summary', 'weeks'),):
                chosen = [a for a in accounts if a['symbol'] == symbol and a['price_mode'] == mode]
                item[sum_key][symbol] = summarize(chosen)
                item[week_key][symbol] = {week: summarize([a for a in chosen if a['week'] == week])
                                         for week in sorted(set(a['week'] for a in chosen))}
        methods.append(item)
        if number % 10 == 0:
            print(json.dumps({'完了条件数': number, '条件総数': 21}, ensure_ascii=False), flush=True)
    save(target, {'methods': methods, '注文列': ORDER_COLUMNS, '返済列': TRADE_COLUMNS, '返済理由': REASONS,
                  '説明': '全25場は既知。気配主評価のみ。採用は全flat組の往復費用後勝率と組平均勝負比で判断。P3は時計限界により参考。',
                  '枚数': '初回TOPIX5/NK10、追加なし、全返済後10分休止。全flatまでを一組。',
                  '週区分': {'2026-09-21': '10場', '2026-09-28': '10場', '2026-10-05': '5場の途中週'},
                  '固定SHA256': digest(ROUND / '実行前固定.json'), '仕様SHA256': frozen['自枝仕様SHA256'],
                  'API取得': False, 'ATR使用': False, '最終約定値使用': False})
    save(ROUND / '全件会計の実行監査.json', {'合格': True, '条件数': 21, '口座数': 21 * 50, '注文数': norders,
                                         '返済ロット数': ntrades, '場内全返済': True, '次有効行約定': True,
                                         '費用配賦と全会計一致': True, '結果SHA256': digest(target)})
    print(json.dumps({'完了': True, '結果': str(target)}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--run', action='store_true')
    args = parser.parse_args()
    if args.prepare == args.run:
        raise SystemExit('--prepare または --run の一方を指定してください')
    prepare() if args.prepare else run()
