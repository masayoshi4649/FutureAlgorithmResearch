"""過去10場で選抜された時計修正と、事前定義の連敗制御を組み合わせる。"""

import argparse
import gzip
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = HERE / 'combined'
spec = importlib.util.spec_from_file_location('連敗入口許可', HERE / 'overlay/research.py')
overlay = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = overlay
spec.loader.exec_module(overlay)


def save(name: str, value: object) -> None:
    """機能: 今回組合せ領域内へ結果を保存する。

    引数: name(str)、value(object)。返り値: なし(None)。
    """
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode('utf8')
    path.write_bytes(gzip.compress(data, mtime=0) if path.suffix == '.gz' else data)


def freeze() -> dict:
    """機能: 後半13場の時計修正結果を見る前に組み合わせを固定する。

    引数: なし。返り値: 固定資料(dict)。
    """
    OUT.mkdir(parents=True, exist_ok=True)
    clocks = overlay.read(HERE / 'clock_search/選択.json')['選択条件']
    candidates = [dict(id=c['id'] + '_' + suffix, clock=c['id'], gate='none', risk=risk)
                  for c in clocks for suffix, risk in [('D2', 'day2R'), ('S2', 'loss2stop'), ('P45', 'loss2pause45')]]
    fixed = dict(候補=candidates, 候補数=len(candidates),
                 原理='損切り後に次の準備をできるようにする一方、実際の連敗だけを理由に新規を休む。',
                 順序='時計修正48条件を過去10場で選抜した後、その上位3条件×休止3方式を固定。後半13場を使って組合せを選ばない。',
                 選択='先頭10場の最弱銘柄合計Rで順位。両銘柄7活動場以上20組以上。',
                 制約='E01の独立仮想運転の計画許可だけを変更し、実取引の確定済み損益のみ休止判断に使う。基の仮想時計は維持。',
                 既知期間='全データは研究中に閲覧済みであり、真正な未見成績ではない。')
    path = OUT / '事前固定.json'
    if path.exists():
        assert overlay.read(path) == fixed
    else:
        save('事前固定.json', fixed)
    return fixed


def main() -> None:
    """機能: 組合せ9条件を会計し、先頭10場だけで順位を固定する。

    引数: CLI --freeze(bool)で固定のみ実行。返り値: なし(None)。
    """
    parser = argparse.ArgumentParser(description='時計修正と休止の組合せ')
    parser.add_argument('--freeze', action='store_true')
    args = parser.parse_args()
    fixed = freeze()
    if args.freeze:
        print('時計修正3条件×休止3条件を、後半の時計修正結果を参照せず固定しました')
        return
    inputs, _ = overlay.load()
    models = {key: overlay.bar_model(key) for key in inputs}
    names = sorted({key[0] for key in inputs})
    periods = dict(開発10=names[:10], 検証9=names[10:19], 既知追加4=names[19:], 全23=names)
    results = []
    for candidate in fixed['候補']:
        ledgers = overlay.read(HERE / 'clock_search/ledgers' / (candidate['clock'] + '.json.gz'))
        indexed = {(r['session'], r['symbol']): r for r in ledgers}
        rows, curves, saved_ledgers = [], {}, []
        for key, ready in sorted(inputs.items()):
            result = overlay.evaluate(candidate, ready, indexed[key], models, True)
            curves[key] = result.pop('curve')
            saved_ledgers.append(dict(session=key[0], symbol=key[1], config=indexed[key]['config'],
                **{k: result.pop(k) for k in ('orders', 'trades', 'decisions')}))
            rows.append(result)
        summaries = {label: overlay.aggregate([r for r in rows if r['session'] in selected])
                     for label, selected in periods.items()}
        for label, selected in periods.items():
            for symbol in overlay.SYMBOLS:
                offset = peak = dd = 0.
                for session in selected:
                    curve = curves[session, symbol] + offset
                    high = np.maximum.accumulate(np.maximum(curve, peak))
                    dd = max(dd, float((high - curve).max()))
                    peak = max(peak, float(curve.max()))
                    offset = float(curve[-1])
                summaries[label][symbol]['drawdown_yen'] = dd
        train = summaries['開発10']
        qualified = all(train[s]['active_sessions'] >= 7 and train[s]['cycles'] >= 20 for s in overlay.SYMBOLS)
        results.append(dict(spec=candidate, periods=summaries, sessions=rows,
            eligible=qualified, score=min(train[s]['r'] for s in overlay.SYMBOLS)))
        save('ledgers/' + candidate['id'] + '.json.gz', saved_ledgers)
    ranked = sorted((r for r in results if r['eligible']), key=lambda r: (-r['score'], r['spec']['id']))
    assert ranked
    save('結果.json', dict(全合格=True, 条件数=len(results), 選択=ranked[0]['spec'], 候補=results,
         選択対象=periods['開発10'], 選抜順位=[r['spec']['id'] for r in ranked], API取得数=0))
    print(json.dumps(dict(選択=ranked[0]['spec'], 検証9=ranked[0]['periods']['検証9'],
                         既知追加4=ranked[0]['periods']['既知追加4'], 全23=ranked[0]['periods']['全23']), ensure_ascii=False))


if __name__ == '__main__':
    main()
