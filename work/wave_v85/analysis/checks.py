"""実成績を読まず、改修有無の対照構造と発動数の集計を検査する。"""
import importlib.util
import json
from pathlib import Path
import sys
import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent


def load(name, path):
    """
    機能: 検査対象を別名で読み込む。
    引数: name (str)、path (Path)。
    返り値: module。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def main():
    """
    機能: 人工会計だけで384対照と時間イベントの集計を検査する。
    引数: なし。
    返り値: None。実結果も凍結研究コードも変更しない。
    """
    compare = load('wave85_compare_test', HERE / 'compare.py')
    catalog = load('wave85_catalog_test', HERE.parent / 'catalog.py').catalog()
    fixed = dict(catalog=catalog, primary=['E01', 'E01_G', 'E01_GPDC'])
    results = {}
    for model in compare.MODELS:
        for config in catalog:
            value = {field: 0 for field in compare.FIELDS}
            value.update(campaign_profit=100 + config['mask'], campaign_loss=20,
                         net=80 + config['mask'], campaign_profit_share=.8)
            results[model, config['id']] = dict(periods={p: {s: value for s in compare.SYMBOLS} for p in compare.PERIODS})
    pairs = compare.components(results, fixed)
    assert len(pairs['pairs']) == 384 and len(pairs['summaries']) == 48
    assert all(r['収支改善数'] == 8 for r in pairs['summaries'])
    # ----------------------------------------
    ledger = dict(orders=np.array([[3, 2, 0, -1, 5, 100., 71, 0.]]),
                  time_events=np.array([[3, 0, 1, 2, 5, 100, 200], [4, -1, 2, 3, 0, 100, 200]]),
                  time_windows=[dict(窓終了後の初観測=True)])
    count = compare.event_count(ledger)
    assert count['時間帯全返済イベント'] == count['時間帯実返済注文'] == 1
    assert count['時間帯実返済枚数'] == 5 and count['時間帯又は古い準備禁止'] == 1
    assert count['時間窓終了後まで有効観測なし'] == 1
    output = dict(全合格=True, 人工条件数=25, 有無対照数=384, 集約数=48, 時間イベント集計=True,
                  実結果読取=False, 新損益計算=False, 分析コードSHA256=compare.sha(HERE / 'compare.py'))
    (HERE / '構文と組合せ検査.json').write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(output, ensure_ascii=False))


if __name__ == '__main__':
    main()
