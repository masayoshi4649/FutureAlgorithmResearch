"""固定した3条件の指値を保持し、不成立ですぐ破棄する仕様と比較する。"""
from pathlib import Path
import hashlib
import pickle
import numpy as np
import data
import research
from persistent_engine import run

HERE = Path(__file__).resolve().parent


def main():
    """
    機能: 主2条件とグリッド代表だけを指値保持の代理モデルへ変更する。
    引数: なし。
    返り値: None。改修の全30場結果を別領域へ保存する。
    """
    fixed = research.read(research.FIXED)
    for name, digest in fixed['code_SHA256'].items():
        assert data.digest(HERE / name) == digest
    selection = research.read(HERE / '前半選定.json')
    ids = sorted({c['id'] for c in selection['primary']} | {c['id'] for c in selection['families'] if c['family'] == 7})
    configs = [c for c in fixed['catalog'] if c['id'] in ids]
    specification = dict(対象=ids, 変数の選び直し=False,
        経緯='全30場の通常結果を確認後、IOC不成立が多い主条件とグリッド代表の指値保持・約定モデルを変更。新しい未知検証ではない。',
        差分='条件成立時の指値を残し、最良対向気配が指値以内になった最初の観測で全量約定したと仮定。価格は元指値とし、後の有利な気配価格への改善は与えない。',
        取消='limit−120秒以上の最初の観測で未約定指値を取り消す。同じ観測での約定より取消を優先。全玉損失停止でも未約定指値を取消。event6で記録。取消は無料。',
        制約='板の待ち順位・部分約定・小型商品の板は未再現。取引所のGTC完全再現ではなく指値保持の代理モデル。板の数量や偏りを方向判断に使わない。',
        新規予約='未約定の指値も片方向保有上限を占有。約定後に返済条件を有効化し、待機中の高安は引き継がない。',
        元固定SHA256=data.digest(research.FIXED), 実装SHA256={name: data.digest(HERE / name) for name in ('persistent.py', 'persistent_engine.py')})
    spec_path = HERE / 'persistent/固定条件.json'
    if spec_path.exists():
        assert research.read(spec_path) == specification
    else:
        research.save_json(spec_path, specification)
    records = data.load_data()
    for number, config in enumerate(configs, 1):
        path = HERE / 'persistent/results' / (config['id'] + '.json')
        if path.exists():
            continue
        rows = []
        ledgers = {}
        settings = dict(delay=0., seed=0, slip_ticks=0., sessions=fixed['全30'],
                        model='指値保持・対向気配到達時に元指値約定・実手数料あり',
                        input_SHA256=fixed['input_SHA256'], code_SHA256=specification['実装SHA256'])
        for session in fixed['全30']:
            for symbol in research.SYMBOLS:
                key = (session, symbol)
                record = records[key]
                terms = research.CONTRACTS[symbol]
                output = run(data.as_tuple(record), config['family'], config['width_ticks'], config['variant'],
                             terms['cap'], terms['pointvalue'], terms['fee'], 0., 0, 0.)
                summary, cycles = research.account(key, record, output, settings)
                rows.append(summary)
                ledgers[key] = dict(orders=output[0], trades=output[1], cycles=cycles, stats=output[3], events=output[4],
                                    curve_hash=hashlib.sha256(output[2].tobytes()).hexdigest())
        periods = {name: {s: research.aggregate(rows, s, sessions) for s in research.SYMBOLS}
                   for name, sessions in [('前16', fixed['前16']), ('後14', fixed['後14']), ('対象', fixed['全30'])]}
        ledger_path = HERE / 'persistent/ledgers' / (config['id'] + '.pkl')
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with ledger_path.open('wb') as stream:
            pickle.dump(ledgers, stream, protocol=5)
        research.save_json(path, dict(config=config, run=settings, rows=rows, periods=periods))
        print(f'指値保持比較 {number}/{len(configs)} 完了', flush=True)


if __name__ == '__main__':
    main()
