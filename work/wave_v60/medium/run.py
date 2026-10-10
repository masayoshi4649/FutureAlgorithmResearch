"""中期120条件を結果前に固定し、気配主評価と中値参考を独立して再生する。"""

from __future__ import annotations

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
CODE_NAMES = ('features.py', 'signals.py', 'engine.py', 'fees.py', 'run.py', 'check_engine.py', 'prepare_inputs.py')


def digest(path: Path) -> str:
    """機能: ファイル内容の SHA256 を計算する。

    引数: path(Path) はコード・入力・固定仕様のパス。
    返り値: SHA256文字列(str)。
    """
    result = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(4 * 1024 * 1024):
            result.update(block)
    return result.hexdigest()


def clean(value: object) -> object:
    """機能: 台帳配列と NumPy 数値を有限 JSON の型へ変換する。

    引数: value(object) は集計または配列。
    返り値: 辞書・リスト・数値・文字列・None(object)。
    """
    if isinstance(value, dict):
        return {key: clean(item) for key, item in value.items()}
    if isinstance(value, np.ndarray):
        return clean(value.tolist())
    if isinstance(value, (list, tuple)):
        return [clean(item) for item in value]
    if isinstance(value, (np.integer, np.floating)):
        return clean(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def save(path: Path, value: object) -> None:
    """機能: 日本語の結果または検査証跡を UTF-8 JSON で保存する。

    引数: path(Path)、value(object)。
    返り値: なし(None)。非有限数値は null として明示する。
    """
    path.write_text(json.dumps(clean(value), ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def week_of(session: str) -> str:
    """機能: セッション開始日の属する月曜日を週ラベルにする。

    引数: session(str) は保存上のセッション名。
    返り値: 月曜日の日付(str)。金曜ナイトも金曜が属する週へ割り当てる。
    """
    day = datetime.fromisoformat(session.split('_')[0])
    return (day - timedelta(days=day.weekday())).date().isoformat()


def prepare() -> None:
    """機能: 既知25場の特徴と入口だけを生成・監査し、損益前に全条件を固定する。

    引数: なし。
    返り値: なし(None)。実データの売買器は呼び出さない。
    """
    if (HERE / '実行前固定.json').exists():
        verify_freeze()
        return
    inputs, quotes = features.load_inputs()
    frames, candidates, audits = {}, {}, []
    for key, ready in inputs.items():
        frames[key], candidates[key] = {}, {}
        for setting in features.SETTINGS:
            frame = features.build(ready, quotes[key], setting)
            frames[key][setting['id']] = frame
            candidates[key][setting['id']] = {}
            audit = features.audit(ready, quotes[key], setting, frame)
            candidate_audit = {}
            for width_id, fraction in signals.WIDTHS.items():
                found = signals.candidates(frame, float(quotes[key]['mid'][0]), ready['tick'], fraction)
                candidates[key][setting['id']][width_id] = found
                checks = signals.audit(frame, float(quotes[key]['mid'][0]), ready['tick'], fraction, found)
                candidate_audit[width_id] = {'途中切断一致数': checks, '候補数': {name: len(rows) for name, rows in found.items()}}
            audits.append({'セッション': key[0], '銘柄': key[1], '設定': setting['id'], **audit, '入口': candidate_audit})
    (HERE / 'features.pkl').write_bytes(pickle.dumps(frames, protocol=pickle.HIGHEST_PROTOCOL))
    (HERE / '入口候補.pkl').write_bytes(pickle.dumps(candidates, protocol=pickle.HIGHEST_PROTOCOL))
    save(HERE / '特徴入口の因果監査.json', {'合格': True, '口座数': len(inputs), '場数': 25,
                                       '設定別監査': audits, '実データ損益計算': False})
    assert len(signals.methods()) == 120 and sum(value['primary'] for value in signals.methods()) == 5
    assert json.loads((HERE / '売買器の合成監査.json').read_text(encoding='utf-8'))['合格']
    frozen = frozen_content()
    frozen['固定時刻'] = datetime.now(timezone(timedelta(hours=9))).isoformat()
    frozen['実データ損益計算前'] = True
    frozen['既知25場'] = True
    frozen['独立再生'] = '主:買ask/売bidで建値・返済側価格管理。参考:中値で別の管理判断。両者注文ごとに手数料。'
    save(HERE / '実行前固定.json', frozen)
    print(json.dumps({'準備完了': True, '口座数': len(inputs), '条件数': 120, '主条件数': 5, '損益未計算': True}, ensure_ascii=False), flush=True)


def frozen_content() -> dict:
    """機能: 実行コード・親の固定仕様・入力・候補のハッシュを構成する。

    引数: なし。
    返り値: 再現に必要な固定内容(dict)。
    """
    return {'条件': signals.methods(), '主条件': [value['id'] for value in signals.methods() if value['primary']],
            'コードSHA256': {name: digest(HERE / name) for name in CODE_NAMES},
            '調査仕様SHA256': digest(WORK / '調査仕様.json'),
            '入力SHA256': {str(path.relative_to(WORK)): digest(path) for path in (
                WORK / 'inputs.pkl', WORK / 'quotes.pkl', HERE / 'features.pkl', HERE / '入口候補.pkl')},
            '注文列': ORDER_COLUMNS, '返済列': TRADE_COLUMNS, '返済理由': REASONS}


def verify_freeze() -> dict:
    """機能: 計算前の固定内容からコード・条件・入力が変わっていないことを検証する。

    引数: なし。
    返り値: 保存した固定内容(dict)。不一致なら計算を中断する。
    """
    frozen = json.loads((HERE / '実行前固定.json').read_text(encoding='utf-8'))
    current = clean(frozen_content())
    for key, value in current.items():
        if key == '返済理由':
            value = {str(k): v for k, v in value.items()}
        assert frozen[key] == value, f'固定後の変更: {key}'
    return frozen


def summarize(accounts: list[dict]) -> dict:
    """機能: 同銘柄・同約定方式の場別純損益を、週または全期間へ集約する。

    引数: accounts(list[dict]) は場内返済済みの口座。
    返り値: 費用・利益損失・PF・枚数・実保有・時価減少幅の集計(dict)。
    """
    ordered = sorted(accounts, key=lambda a: a['session'])
    all_trades = np.concatenate([account['trades'] for account in ordered]) if ordered else np.empty((0, 22))
    net, quantity = all_trades[:, 8], all_trades[:, 3]
    win_qty, loss_qty = int(quantity[net > 0].sum()), int(quantity[net < 0].sum())
    profit, loss = float(net[net > 0].sum()), float(-net[net < 0].sum())
    mean_win, mean_loss = profit / win_qty if win_qty else None, loss / loss_qty if loss_qty else None
    level = peak = drawdown = 0.
    for account in ordered:
        drawdown = max(drawdown, account['drawdown'], peak - (level + account['equity_min']))
        peak = max(peak, level + account['equity_max'])
        level += account['net']
    total_net = sum(a['net'] for a in accounts)
    gross = sum(a['gross_pnl'] for a in accounts)
    fees = sum(a['fees'] for a in accounts)
    np.testing.assert_allclose(total_net, profit - loss, atol=1e-5)
    np.testing.assert_allclose(total_net, gross - fees, atol=1e-5)
    holds = all_trades[:, 17]
    result = dict(gross_pnl=gross, gross_profit=sum(a['gross_profit'] for a in accounts),
                  gross_loss=sum(a['gross_loss'] for a in accounts), fees=fees, net=total_net,
                  profit=profit, loss=loss, pf=profit / loss if loss else None,
                  cycles=len(all_trades), wins=int((net > 0).sum()), losses=int((net < 0).sum()),
                  win_qty=win_qty, loss_qty=loss_qty, flat_qty=int(quantity[net == 0].sum()),
                  win_rate=float((net > 0).mean()) if len(net) else None,
                  win_rate_excluding_flat=float((net > 0).sum() / (net != 0).sum()) if (net != 0).any() else None,
                  win_per_lot=mean_win, loss_per_lot=mean_loss,
                  payoff=mean_win / mean_loss if mean_win is not None and mean_loss else None,
                  sessions=len(accounts), positive_sessions=sum(a['net'] > 0 for a in accounts),
                  negative_sessions=sum(a['net'] < 0 for a in accounts), active_sessions=sum(a['cycles'] > 0 for a in accounts),
                  without_best=total_net - max((a['net'] for a in accounts), default=0.),
                  drawdown=drawdown, max_long_qty=max((a['max_long_qty'] for a in accounts), default=0),
                  max_short_qty=max((a['max_short_qty'] for a in accounts), default=0),
                  unrealized_start=0., unrealized_end=0., mtm_change=total_net,
                  hold_mean_minutes=float(holds.mean()) if len(holds) else None,
                  hold_median_minutes=float(np.median(holds)) if len(holds) else None,
                  hold_min_minutes=float(holds.min()) if len(holds) else None,
                  hold_max_minutes=float(holds.max()) if len(holds) else None,
                  hold_under_30_minutes=int((holds < 30).sum()),
                  hold_30_to_60_minutes=int(((holds >= 30) & (holds <= 60)).sum()),
                  hold_over_60_minutes=int((holds > 60).sum()),
                  reasons={label: {'cycles': int((all_trades[:, 9] == code).sum()),
                                   'net': float(all_trades[all_trades[:, 9] == code, 8].sum())}
                           for code, label in REASONS.items()})
    return result


def run() -> None:
    """機能: 親の計算GO後に、固定120条件を全既知25場で一度再生する。

    引数: なし。
    返り値: なし(None)。コード変更や結果を見ての条件追加は行わない。
    """
    frozen = verify_freeze()
    output_path = HERE / '売買結果.json'
    if output_path.exists():
        raise RuntimeError('結果が既に存在します。固定条件の結果を上書きしません。')
    inputs, quotes = features.load_inputs()
    candidates = pickle.loads((HERE / '入口候補.pkl').read_bytes())
    results = []
    for number, config in enumerate(signals.methods(), 1):
        accounts = []
        for key in sorted(inputs):
            candidate = candidates[key][config['setting_id']][config['width_id']][config['family']]
            for quote_mode in (True, False):
                account = execute(inputs[key], quotes[key], candidate, int(config['exit_id'][1]), config['minutes'], quote_mode)
                account['week'] = week_of(key[0])
                accounts.append(account)
        item = {**config, 'config': config, 'accounts': accounts, 'summary': {}, 'mid_summary': {}, 'weeks': {}, 'mid_weeks': {}}
        for symbol in ('TOPIX', 'NK225'):
            for mode, summary_key, week_key in (('quote', 'summary', 'weeks'), ('mid', 'mid_summary', 'mid_weeks')):
                chosen = [a for a in accounts if a['symbol'] == symbol and a['price_mode'] == mode]
                item[summary_key][symbol] = summarize(chosen)
                item[week_key][symbol] = {week: summarize([a for a in chosen if a['week'] == week]) for week in sorted(set(a['week'] for a in chosen))}
        results.append(item)
        if number % 10 == 0:
            print(json.dumps({'完了条件数': number, '総条件数': 120}, ensure_ascii=False), flush=True)
    output = {'methods': results, '説明': '全25場は既知。主評価は買ask/売bidの独立再生、参考は中値の独立再生。両方式に実注文単位手数料。',
              '注文列': ORDER_COLUMNS, '返済列': TRADE_COLUMNS, '返済理由': REASONS,
              '週区分': {'2026-09-21': '10場の週', '2026-09-28': '10場の週', '2026-10-05': '5場の途中週'},
              '固定仕様SHA256': digest(HERE / '実行前固定.json'), '親調査仕様SHA256': frozen['調査仕様SHA256'],
              'ATR使用': False, '最終約定値使用': False, '新API取得': False, '今回固定後コード変更': False,
              '仕様改訂記録': frozen.get('改訂記録')}
    save(output_path, output)
    save(HERE / '全件会計の実行監査.json', {'合格': True, '条件数': 120, '口座再生数': len(results) * 100,
                                       '独立約定方式数': 2, '場内返済と次行約定検算': True,
                                       '注文手数料と純損益検算': True, 'コード凍結一致': True,
                                       '結果SHA256': digest(output_path)})
    print(json.dumps({'完了': True, '条件数': 120, '結果': str(output_path)}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true', help='特徴と候補だけ生成し固定する')
    parser.add_argument('--run', action='store_true', help='親のGO後に固定条件を売買再生する')
    args = parser.parse_args()
    if args.prepare == args.run:
        raise SystemExit('--prepare または --run の一方を指定してください')
    prepare() if args.prepare else run()
