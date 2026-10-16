"""固定代表を気配差のない仮想市場へ置き、注文管理の基礎を切り分ける。"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import hashlib
import json
import pickle
import numpy as np
import data
import research
from engine import run

HERE = Path(__file__).resolve().parent


def calculate(config, records, fixed):
    """
    機能: 固定代表を現在値の指定約定・実手数料ありで再生する。
    引数: config/records/fixed(dict)。
    返り値: str の条件ID。採用条件の選び直しはしない。
    """
    path = HERE / 'ideal_fee/results' / (config['id'] + '.json')
    if path.exists():
        return config['id']
    rows = []
    ledgers = {}
    settings = dict(delay=0., seed=0, slip_ticks=0., sessions=fixed['全30'],
                    model='各観測のCurrentPriceで必ず即時約定、気配差0、実手数料あり',
                    source_SHA256=fixed['input_SHA256'], code_SHA256=fixed['code_SHA256'])
    for session in fixed['全30']:
        for symbol in research.SYMBOLS:
            key = (session, symbol)
            original = records[key]
            record = dict(original, bid=original['price'], ask=original['price'], quote_valid=original['price_valid'])
            terms = research.CONTRACTS[symbol]
            output = run(data.as_tuple(record), config['family'], config['width_ticks'], config['variant'],
                         terms['cap'], terms['pointvalue'], terms['fee'], 0., 0, 0.)
            summary, cycles = research.account(key, record, output, settings)
            rows.append(summary)
            ledgers[key] = dict(orders=output[0], trades=output[1], cycles=cycles, stats=output[3], events=output[4],
                                curve_hash=hashlib.sha256(output[2].tobytes()).hexdigest())
    periods = {name: {s: research.aggregate(rows, s, sessions) for s in research.SYMBOLS}
               for name, sessions in [('前16', fixed['前16']), ('後14', fixed['後14']), ('対象', fixed['全30'])]}
    result = dict(config=config, run=settings, rows=rows, periods=periods)
    ledger_path = HERE / 'ideal_fee/ledgers' / (config['id'] + '.pkl')
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open('wb') as stream:
        pickle.dump(ledgers, stream, protocol=5)
    research.save_json(path, result)
    return config['id']


def main():
    """
    機能: 現実的約定で固定した代表の論理対照だけを実行する。
    引数: なし。
    返り値: None。通常条件の結果・代表・原本データを変更しない。
    """
    fixed = research.read(research.FIXED)
    for name, digest in fixed['code_SHA256'].items():
        assert data.digest(HERE / name) == digest
    selected = research.read(HERE / '前半選定.json')
    records = data.load_data()
    configs = [c for c in fixed['catalog'] if c['id'] in selected['selected']]
    specification = dict(対象=selected['selected'], 代表の選び直し=False,
                         仮定='現在値で常に全数量約定し、売買気配差ゼロ・手数料は通常と同じ。実行可能性を示す成績ではない。',
                         比較='注文状態も再生するため、通常結果へ費用を足し戻した数値とは違う。損益の上界とも呼ばない。',
                         基礎=input_fingerprint(fixed), code_SHA256=data.digest(Path(__file__)))
    research.save_json(HERE / 'ideal_fee/固定条件.json', specification)
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(calculate, c, records, fixed) for c in configs]
        for i, future in enumerate(as_completed(futures), 1):
            future.result()
            print(f'料金あり論理対照 {i}/{len(configs)} 完了', flush=True)


def input_fingerprint(fixed):
    """
    機能: 原本入力と機械的な仮想価格変換の出所を残す。
    引数: fixed(dict)。
    返り値: dict。元価格は変更せず、bid/askを同じ現在値へ置換する。
    """
    return dict(元入力SHA256=fixed['input_SHA256'], 変換='bid=ask=CurrentPrice、quote_valid=price_valid',
                セッション=fixed['全30'])


if __name__ == '__main__':
    main()
