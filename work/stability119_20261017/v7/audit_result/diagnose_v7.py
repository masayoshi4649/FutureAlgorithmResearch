"""私有保全結果だけから、相対順行の具体的な損失と方向別偏りを示す。"""

from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
import math
from pathlib import Path

import numpy as np


HERE = Path(__file__).resolve().parent
V7 = HERE.parent
BASE = V7.parent
JST = timezone(timedelta(hours=9))
REASONS = {0: '未清算', 1: '中心復帰', 2: '外側2σ', 3: '費用後円損失', 4: '片脚期限', 5: '場末', 6: '入口から逆σ', 7: '残差ピークから1σ戻り'}


def load(path: Path) -> dict:
    """
    機能: 自身が保全したcopyだけを展開する。
    引数: path(Path) は所有済みNPZ。
    返り値: dict は保存配列。元cache又は市場を読まない。
    """
    assert path.resolve().is_relative_to(BASE) and ('owned' in path.parts or 'recovered_owned' in path.parts)
    with np.load(BytesIO(path.read_bytes()), allow_pickle=False) as saved:
        return {key: saved[key].copy() for key in saved.files}


def clock(value: float) -> str:
    """
    機能: 価格時計を日本日時へ表示する。
    引数: value(float) はepoch秒。
    返り値: str は日時。
    """
    return datetime.fromtimestamp(float(value), JST).strftime('%m/%d %H:%M:%S')


def brief(parent: np.ndarray, orders: np.ndarray, quotes: tuple[dict, dict]) -> dict:
    """
    機能: 一親の実価格・当時共同残差・停止時の清算値を独立に抜き出す。
    引数: parent(ndarray[37])、orders(ndarray[:,14])、quotes(tuple[dict,dict]) は所有資料。
    返り値: dict は時刻・価格・費用・二要因・停止時評価。金融再実行を行わない。
    """
    own = orders[orders[:, 0] == parent[0]]
    side, beta, center, delta = parent[2], parent[6], parent[7], parent[9]
    snapshots = []
    for label, now in (('予約', parent[3]), ('返済判断', parent[4])):
        ref = []
        residual, mark = None, 0.
        for leg, (q, multiplier, fee) in enumerate(zip(quotes, (10., 1000.), (11., 41.8))):
            at = int(np.searchsorted(q['time'], now, side='right')) - 1
            b, a, last = q['bid'][at], q['ask'][at], q['last'][at]
            ref.append(dict(last=float(last), bid=float(b), ask=float(a), spread=float(a - b), age=float(now - q['time'][at])))
            selected = own[(own[:, 1] == leg) & (own[:, 6] <= now)]
            entered = selected[selected[:, 2] == 1]
            closed = selected[selected[:, 2] == 2]
            mark -= float(sum(selected[:, 9]))
            if len(entered):
                e = entered[0]
                price = closed[0, 8] if len(closed) else b if e[3] == 1 else a
                mark += e[3] * (price - e[8]) * e[4] * multiplier
                if not len(closed):
                    mark -= math.floor(e[4] * fee + 1e-9)
        residual = math.log(ref[0]['last']) - beta * math.log(ref[1]['last']) - center
        snapshots.append(dict(kind=label, time=clock(now), residual=float(residual),
            signed_progress=float(side * (residual - delta)), liquidation_net=float(mark), quotes=ref))
    a, b = parent[12] * 10. * parent[14], parent[13] * 1000. * parent[15]
    rn, rt = parent[16] / parent[14] - 1., parent[17] / parent[15] - 1.
    relative = side * a * (rn - beta * rt)
    common = side * (beta * a - b) * rt
    return dict(parent=int(parent[0]), side_nk='買' if side == 1 else '売', side_top='売' if side == 1 else '買',
        quantity_nk=int(parent[12]), quantity_top=int(parent[13]), decision=clock(parent[3]), close_decision=clock(parent[4]),
        reason=REASONS[int(parent[5])], entry_nk=float(parent[14]), entry_top=float(parent[15]),
        exit_nk=float(parent[16]), exit_top=float(parent[17]), entry_time_nk=clock(parent[18]), entry_time_top=clock(parent[19]),
        exit_time_nk=clock(parent[20]), exit_time_top=clock(parent[21]), budget=float(parent[10]),
        sigma=float(parent[8]), delta=float(delta), MFE=float(parent[35]), MAE=float(parent[36]), net=float(parent[28]),
        relative=float(relative), common=float(common), fees=float(sum(parent[24:26])), snapshots=snapshots)


def main() -> None:
    """
    機能: 指定されたMR対応親・最悪二場・全方向別を所有copyだけで整理する。
    引数: なし。
    返り値: None。新しい除外条件・候補選択・金融再実行は行わない。
    """
    result = json.loads((HERE / 'owned/完成結果.json').read_text(encoding='utf-8'))
    pair = {scene: load(HERE / 'owned/PAIR' / (scene + '.npz')) for scene in result['sessions']}
    quote_cache = {}

    def own_quotes(scene: str) -> tuple:
        """
        機能: 必要な場の旧所有気配だけを再利用する。
        引数: scene(str) は場。
        返り値: tuple はNKとTOPの気配。
        """
        if scene not in quote_cache:
            records = [load(BASE / 'audit_result119/recovered_owned/prepared' / symbol / (scene + '.npz')) for symbol in ('NK225', 'TOPIX')]
            quote_cache[scene] = tuple({key[8:]: value for key, value in r.items() if key.startswith('quotes__')} for r in records)
        return quote_cache[scene]

    comparison = []
    scene = '2026-10-01_Day'
    decision = datetime(2026, 10, 1, 10, 0, tzinfo=JST).timestamp()
    old = load(BASE / 'v5/audit_result/owned/PAIR' / (scene + '.npz'))
    for label, arrays, ident in [('MR60', old, 'OLS_MR_L60'), ('MOM60固定', pair[scene], 'OLS_MOM_L60_X0'), ('MOM60追尾', pair[scene], 'OLS_MOM_L60_X1')]:
        parents = arrays[ident + '__parents']
        matched = parents[parents[:, 3] == decision]
        if len(matched):
            comparison.append(dict(method=label, scene=scene, **brief(matched[0], arrays[ident + '__orders'], own_quotes(scene))))
        else:
            model = arrays[ident + '__models']
            record = model[model[:, 0] == decision]
            comparison.append(dict(method=label, scene=scene, 同予約親なし=True,
                model=None if not len(record) else [None if not np.isfinite(v) else float(v) for v in record[0]]))
    worst_rows = []
    used = set()
    for row in sorted(result['runs'], key=lambda r: (r['net'], r['session'], r['method'])):
        if row['session'] in used:
            continue
        used.add(row['session'])
        arrays = pair[row['session']]
        parents = arrays[row['method'] + '__parents']
        parent = min(parents, key=lambda r: r[28])
        worst_rows.append(dict(method=row['method'], scene=row['session'], session_net=row['net'],
                              **brief(parent, arrays[row['method'] + '__orders'], own_quotes(row['session']))))
        if len(worst_rows) == 2:
            break
    directions = []
    for spec in result['specs']:
        parents = np.concatenate([pair[scene][spec['id'] + '__parents'] for scene in result['sessions']])
        for side in (1, -1):
            selected = parents[(parents[:, 2] == side) & (parents[:, 1] == 1)]
            directions.append(dict(method=spec['id'], side_nk='買' if side == 1 else '売', parents=len(selected),
                profit=float(sum(np.maximum(selected[:, 28], 0.))), loss=float(sum(np.maximum(-selected[:, 28], 0.))),
                net=float(sum(selected[:, 28])), gross=float(sum(selected[:, 22:24].ravel())), fees=float(sum(selected[:, 24:26].ravel())),
                wins=int(np.count_nonzero(selected[:, 28] > 1e-7))))
    data = dict(comparison=comparison, worst=worst_rows, directions=directions,
                原市場読取=0, 原cache再読=0, 金融再実行=0, 読取範囲='既保全PAIR40・旧MR1・必要場の旧所有preparedのみ')
    output = HERE / '対立入口と最悪二場及び方向別の具体診断.json'
    assert not output.exists()
    output.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
