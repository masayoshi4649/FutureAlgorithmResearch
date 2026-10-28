"""保存済みD07と特徴列を読み、米国前無取引と準備不足を区別する。新しい売買判断はしない。"""

from pathlib import Path
import json
import pickle
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def main():
    """25夜の保存注文を担当別に分類し、公開特徴の成立行数と併記する。

    引数: なし。
    返り値: None。未成立の原因や仮想利益を推測せず、当時の保存列だけを数える。
    """
    rows = []
    for path in sorted((ROOT / 'work/research145_engine/cache').glob('*_Night.pkl')):
        _, data, _, _, _ = pickle.loads(path.read_bytes())
        pre = pickle.loads((ROOT / 'work/preus148/inputs' / path.name).read_bytes())['pre']
        r, q, a = data['ready'], data['quotes'], data['features']
        times = np.asarray(r['time_s'])
        mask = (times >= r['start']) & (times < r['us_open'] - 900)
        known = np.isfinite(a[:, :24]).all(axis=1)
        good = np.asarray(q['quote_valid'], bool) & (q['bid'] > 0) & (q['ask'] > q['bid'])
        ready = mask & known & good
        new = pre[pre[:, 7] == 1]
        roles = {name: int(np.sum((new[:, 2] // 10_000_000) == index)) for index, name in enumerate(('主担当', '追加', '別入口'))}
        rows.append(dict(session=path.stem, pre_new_fills=len(new), pre_role_new_fills=roles,
                         pre_raw_rows=int(mask.sum()), pre_24_known_rows=int((mask & known).sum()),
                         pre_known_and_good_rows=int(ready.sum()),
                         pre_first_known_good=float(times[ready][0]) if ready.any() else None,
                         no_pre_trade=not len(new),
                         meaning='成立した準備行があっても入口段階と持続が成立するとは限らない。行数は時間率でも予測成功率でもない。'))
    value = dict(rows=rows, nights=len(rows), no_pre_trade=sum(x['no_pre_trade'] for x in rows),
                 zero_trade_with_some_ready=sum(x['no_pre_trade'] and x['pre_known_and_good_rows'] > 0 for x in rows),
                 role_new_fills={k: sum(x['pre_role_new_fills'][k] for x in rows) for k in ('主担当', '追加', '別入口')},
                 financial_replays=0, source='研究145キャッシュと148既存前半約定。米国15分前まで。')
    target = HERE / 'engine保存無取引監査149.json'
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in value.items() if k != 'rows'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
