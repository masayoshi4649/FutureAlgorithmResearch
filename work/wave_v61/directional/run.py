"""270条件を損益前に固定し、全25既知場の会計と分離台帳を保存する。"""

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np

import features
import signals
from engine import execute, ORDER_COLUMNS, TRADE_COLUMNS, REASONS


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
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
             HERE / 'features.pkl', HERE / '入口候補.pkl')
    return {'条件': signals.methods(), '主条件': [v['id'] for v in signals.methods() if v['primary']],
            'コードSHA256': {name: digest(HERE / name) for name in CODE_NAMES},
            '親仕様SHA256': digest(WORK / '調査仕様.json'), '自枝仕様SHA256': digest(HERE / '詳細仕様.json'),
            '入力SHA256': {str(path.resolve()): digest(path) for path in paths},
            '注文列': ORDER_COLUMNS, '返済列': TRADE_COLUMNS, '返済理由': REASONS}


def verify_freeze() -> dict:
    """機能: 凍結以後のコード・条件・入力変更がないことを検査する。

    引数: なし。
    返り値: 保存済み固定内容(dict)。不一致は例外停止する。
    """
    frozen = json.loads((HERE / '実行前固定.json').read_text(encoding='utf-8'))
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
    if (HERE / '実行前固定.json').exists():
        verify_freeze()
        return
    inputs, quotes = features.load_inputs()
    frames, candidates, audits = {}, {}, []
    for key, ready in inputs.items():
        frame = features.build(ready, quotes[key], features.SETTINGS[0])
        frames[key], candidates[key] = frame, {}
        audit = features.audit(ready, quotes[key], features.SETTINGS[0], frame)
        counts = {}
        for width_id, fraction in signals.WIDTHS.items():
            found = signals.candidates(frame, float(quotes[key]['mid'][0]), ready['tick'], fraction)
            candidates[key][width_id] = found
            checks = signals.audit(frame, float(quotes[key]['mid'][0]), ready['tick'], fraction, found)
            counts[width_id] = {'prefix一致': checks, '候補数': {name: len(rows) for name, rows in found.items()}}
        audits.append({'session': key[0], 'symbol': key[1], **audit, '入口': counts})
    (HERE / 'features.pkl').write_bytes(pickle.dumps(frames, protocol=pickle.HIGHEST_PROTOCOL))
    (HERE / '入口候補.pkl').write_bytes(pickle.dumps(candidates, protocol=pickle.HIGHEST_PROTOCOL))
    save(HERE / '特徴入口の因果監査.json', {'合格': True, '口座数': len(inputs), '実データ損益計算': False, '口座別': audits})
    assert len(signals.methods()) == 270 and sum(v['primary'] for v in signals.methods()) == 5
    assert json.loads((HERE / '売買器の合成監査.json').read_text(encoding='utf-8'))['合格']
    frozen = frozen_content()
    frozen.update(固定時刻=datetime.now(timezone(timedelta(hours=9))).isoformat(), 実データ損益計算前=True,
                  既知25場=True, 未知検証ではない=True, 主気配と中値参考は独立再生=True)
    save(HERE / '実行前固定.json', frozen)
    print(json.dumps({'準備完了': True, '条件数': 270, '実データ損益計算': False}, ensure_ascii=False), flush=True)


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
    np.testing.assert_allclose(result['net'], result['profit'] - result['loss'], atol=1e-5)
    np.testing.assert_allclose(result['net'], result['gross_pnl'] - result['fees'], atol=1e-5)
    return result


def run() -> None:
    """機能: 親GO後に全270条件を気配/中値で独立再生し、会計と台帳を分離保存する。

    引数: なし。
    返り値: なし(None)。結果を見て条件や主条件を差し替えない。
    """
    frozen = verify_freeze()
    target = HERE / '集計結果.json'
    if target.exists() or (HERE / '計算開始.json').exists():
        raise RuntimeError('既に計算開始済みです。既存結果を上書きしません')
    save(HERE / '計算開始.json', {'時刻': datetime.now().astimezone().isoformat(), '親GO後': True})
    inputs, quotes = features.load_inputs()
    candidates = pickle.loads((HERE / '入口候補.pkl').read_bytes())
    (HERE / 'ledgers').mkdir(exist_ok=True)
    methods, norders, ntrades = [], 0, 0
    for number, config in enumerate(signals.methods(), 1):
        accounts, ledgers = [], {}
        ledger_path = HERE / 'ledgers' / f'{config["id"]}.pkl'
        for key in sorted(inputs):
            for mode in (True, False):
                account = execute(inputs[key], quotes[key], candidates[key][config['width_id']][config['family']], config, mode)
                ledger_key = (*key, account['price_mode'])
                orders, trades = account.pop('orders'), account.pop('trades')
                ledgers[ledger_key] = {'orders': orders, 'trades': trades}
                account.update(week=week_of(key[0]), ledger=str(ledger_path.relative_to(HERE)).replace('\\', '/'),
                               ledger_key=list(ledger_key))
                accounts.append(account)
                norders, ntrades = norders + len(orders), ntrades + len(trades)
        ledger_path.write_bytes(pickle.dumps(ledgers, protocol=pickle.HIGHEST_PROTOCOL))
        item = dict(**config, config=config, accounts=accounts, summary={}, weeks={}, mid_summary={}, mid_weeks={},
                    ledger=str(ledger_path.relative_to(HERE)).replace('\\', '/'), ledger_sha256=digest(ledger_path))
        for symbol in ('TOPIX', 'NK225'):
            for mode, sum_key, week_key in (('quote', 'summary', 'weeks'), ('mid', 'mid_summary', 'mid_weeks')):
                chosen = [a for a in accounts if a['symbol'] == symbol and a['price_mode'] == mode]
                item[sum_key][symbol] = summarize(chosen)
                item[week_key][symbol] = {week: summarize([a for a in chosen if a['week'] == week])
                                         for week in sorted(set(a['week'] for a in chosen))}
        methods.append(item)
        if number % 10 == 0:
            print(json.dumps({'完了条件数': number, '条件総数': 270}, ensure_ascii=False), flush=True)
    save(target, {'methods': methods, '注文列': ORDER_COLUMNS, '返済列': TRADE_COLUMNS, '返済理由': REASONS,
                  '説明': '全25場は既知。気配主評価と中値参考は各々独立再生。損益勝敗PFは入口ロット純損益、組勝敗はgroup列。',
                  '積極度': '数量・追加・休止を合わせた事前運用方針の比較。各要素の単独因果ではない。',
                  '週区分': {'2026-09-21': '10場', '2026-09-28': '10場', '2026-10-05': '5場の途中週'},
                  '固定SHA256': digest(HERE / '実行前固定.json'), '親仕様SHA256': frozen['親仕様SHA256'],
                  'API取得': False, 'ATR使用': False, '最終約定値使用': False})
    save(HERE / '全件会計の実行監査.json', {'合格': True, '条件数': 270, '口座数': 270 * 100, '注文数': norders,
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
