"""第3ラウンドの相対的な板確認待ちを結果前固定し、24条件だけ再生する。"""

import argparse
from datetime import datetime
import json
from pathlib import Path
import pickle
import shutil

import numpy as np
import pandas as pd

import board_round3 as board_signals
import engine_round2 as engine
import features
import run as common


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
ROUND = HERE / 'round3'
SOURCES = ('board_round3.py', 'board_signals.py', 'engine_round2.py', 'run_round3.py', 'check_round2.py', 'features.py', 'fees.py', 'signals.py', 'run.py')


def fixed() -> dict:
    """機能: 第3ラウンドで使用する全コード・入力・条件のSHAを構成する。

    引数: なし。
    返り値: 固定内容(dict)。
    """
    return {'条件': board_signals.methods(), 'コード': {n: common.digest(HERE / n) for n in SOURCES},
            '仕様': common.digest(ROUND / '仕様.json'),
            '入力': {str(p): common.digest(p) for p in (ROOT / 'board_features.pkl',
                    ROOT.parent / 'wave_v60/inputs.pkl', ROOT.parent / 'wave_v60/quotes.pkl',
                    HERE / 'round1/入口候補.pkl', ROUND / '入口候補.pkl')}}


def prepare() -> None:
    """機能: 旧結果で選んだ改善理由を固定した上で、新規候補だけを生成し因果監査する。

    引数: なし。
    返り値: なし(None)。実データ売買は呼び出さない。
    """
    if (ROUND / '実行前固定.json').exists():
        assert json.loads((ROUND / '実行前固定.json').read_text(encoding='utf-8'))['固定'] == fixed()
        return
    inputs, quotes = features.load_inputs()
    board = pickle.loads((ROOT / 'board_features.pkl').read_bytes())
    p2s = pickle.loads((HERE / 'round1/入口候補.pkl').read_bytes())
    candidates, audits = {}, []
    for key, ready in inputs.items():
        table = board[key]
        p2 = p2s[key]['P2_F']
        full = board_signals.candidates(table, ready, quotes[key]['mid'][0], p2)
        candidates[key] = full
        checks = 0
        for n in (max(3, len(table) // 3), max(3, len(table) * 2 // 3)):
            short = table.iloc[:n]
            last_seq = float(short.iloc[-1]['seq'])
            prior_i = int(np.searchsorted(ready['seq'], last_seq))
            p2prefix = p2[p2[:, 0] <= prior_i]
            part = board_signals.candidates(short, ready, quotes[key]['mid'][0], p2prefix)
            for name in full:
                np.testing.assert_array_equal(part[name], full[name][full[name][:, 0] <= prior_i])
                checks += 1
        audits.append({'session': key[0], 'symbol': key[1], 'prefix比較': checks,
                       '候補数': {name: len(rows) for name, rows in full.items()}})
    (ROUND / '入口候補.pkl').write_bytes(pickle.dumps(candidates, protocol=pickle.HIGHEST_PROTOCOL))
    common.save(ROUND / '因果監査.json', {'合格': True, '口座数': len(inputs), '同銘柄seqのみ': True, '口座別': audits})
    assert json.loads((HERE / 'round2/売買器の合成監査.json').read_text(encoding='utf-8'))['合格']
    common.save(ROUND / '実行前固定.json', {'固定': fixed(), '時刻': datetime.now().astimezone().isoformat(), '損益前': True})
    (ROUND / 'code').mkdir(exist_ok=True)
    for name in SOURCES:
        shutil.copyfile(HERE / name, ROUND / 'code' / name)
    print('第3ラウンド24条件を結果前固定しました')


def run() -> None:
    """機能: 凍結後の24条件をquote/passiveに分け、全場・週会計と台帳を保存する。

    引数: なし。
    返り値: なし(None)。中値約定・実APIは使用しない。
    """
    assert json.loads((ROUND / '実行前固定.json').read_text(encoding='utf-8'))['固定'] == fixed()
    target = ROUND / '集計結果.json'
    assert not target.exists() and not (ROUND / '計算開始.json').exists()
    common.save(ROUND / '計算開始.json', {'固定照合': True, '時刻': datetime.now().astimezone().isoformat()})
    inputs, quotes = features.load_inputs()
    candidates = pickle.loads((ROUND / '入口候補.pkl').read_bytes())
    (ROUND / 'ledgers').mkdir(exist_ok=True)
    methods = []
    for config in board_signals.methods():
        accounts, ledgers = [], {}
        path = ROUND / 'ledgers' / f'{config["id"]}.pkl'
        for key in sorted(inputs):
            result = engine.execute(inputs[key], quotes[key], candidates[key][config['family']], config, True)
            ledger_key = (*key, result['price_mode'])
            ledgers[ledger_key] = {'orders': result.pop('orders'), 'trades': result.pop('trades')}
            result.update(week=common.week_of(key[0]), ledger=f'ledgers/{config["id"]}.pkl', ledger_key=list(ledger_key))
            accounts.append(result)
        path.write_bytes(pickle.dumps(ledgers, protocol=pickle.HIGHEST_PROTOCOL))
        item = dict(**config, config=config, accounts=accounts, summary={}, weeks={}, ledger=f'ledgers/{config["id"]}.pkl')
        for symbol in ('TOPIX', 'NK225'):
            chosen = [a for a in accounts if a['symbol'] == symbol]
            item['summary'][symbol] = common.summarize(chosen)
            item['weeks'][symbol] = {w: common.summarize([a for a in chosen if a['week'] == w]) for w in sorted(set(a['week'] for a in chosen))}
        methods.append(item)
    common.save(target, {'methods': methods, '注文列': engine.ORDER_COLUMNS, '返済列': engine.TRADE_COLUMNS,
                         '返済理由': engine.REASONS, '固定SHA': common.digest(ROUND / '実行前固定.json'),
                         '価格': 'quote=新規/返済次行気配。passive=新規だけ事前指値、1呼値通過時に指値で全約定する追加仮定、返済は次行気配。',
                         '重要': '同じ銘柄の原本順のみ。執行側は代理で心理/真aggressorとは断定しない。中値利益を採用しない。'})
    print('第3ラウンド24条件が完了しました')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--run', action='store_true')
    args = parser.parse_args()
    if args.prepare == args.run:
        raise SystemExit('--prepare又は--runの一方を指定してください')
    prepare() if args.prepare else run()
