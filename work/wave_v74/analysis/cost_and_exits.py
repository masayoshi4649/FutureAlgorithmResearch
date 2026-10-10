"""固定売買の気配差と出口理由を診断する。入口・選定は変更しない。"""

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import pickle
import socket

import numpy as np


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = HERE.parents[2]
ZONE = timezone(timedelta(hours=9))
REASONS = {1: '初期損切り', 2: 'トレーリング返済', 3: '六十分返済判断', 4: '場内全返済', 5: '基準方向の反転'}


def load(path: Path) -> object:
    """機能: 保存済みの入力又は検証結果を読み取る。

    引数: path(Path)。返り値: 保存内容(object)。
    """
    return pickle.loads(path.read_bytes()) if path.suffix == '.pkl' else json.loads(path.read_text(encoding='utf8'))


def deny(*args: object, **kwargs: object) -> None:
    """機能: 保存診断からのネットワーク接続を禁止する。

    引数: args(tuple)、kwargs(dict)。返り値: なし(None)、例外を送出する。
    """
    raise RuntimeError('保存診断からの通信は禁止')


def pack(rows: list[dict]) -> dict:
    """機能: 同じ売買時点の中値置換と実気配約定の差を相殺せず集計する。

    引数: rows(list[dict])。返り値: 会計と気配差の集計(dict)。
    中値では入口及び出口を再判定しない。実行可能な成績とは扱わない。
    """
    net = np.array([a['収支'] for a in rows], dtype=float)
    spread = np.array([a['気配差負担'] for a in rows], dtype=float)
    fees = np.array([a['手数料'] for a in rows], dtype=float)
    mid = net + spread
    original_last = np.array([a['同時点約定値置換損益'] for a in rows], dtype=float)
    return dict(取引数=len(rows), 利益=float(net[net > 0].sum()), 損失=float(-net[net < 0].sum()),
        収支=float(net.sum()), 手数料=float(fees.sum()), 手数料なし気配収支=float((net + fees).sum()),
        気配差負担=float(spread.sum()), 同じ売買時点の中値収支=float(mid.sum()),
        中値かつ手数料なし=float((mid + fees).sum()),
        同じ売買時点の約定値置換収支=float(original_last.sum()),
        気配差だけで黒字から赤字へ転じた数=int(((mid > 0) & (net < 0)).sum()),
        気配差だけで黒字から赤字へ転じた損失=float(-net[(mid > 0) & (net < 0)].sum()),
        新規気配差平均呼値=float(np.mean([a['新規気配差呼値'] for a in rows])) if rows else None,
        返済気配差平均呼値=float(np.mean([a['返済気配差呼値'] for a in rows])) if rows else None,
        新規気配差二呼値超の数=sum(a['新規気配差呼値'] > 2.000001 for a in rows),
        返済気配差二呼値超の数=sum(a['返済気配差呼値'] > 2.000001 for a in rows),
        新規気配差最大呼値=max((a['新規気配差呼値'] for a in rows), default=0.),
        返済気配差最大呼値=max((a['返済気配差呼値'] for a in rows), default=0.),
        約定時刻差平均秒=float(np.mean([a['新規判断から約定秒'] for a in rows])) if rows else None,
        返済時刻差平均秒=float(np.mean([a['返済判断から約定秒'] for a in rows])) if rows else None,
        平均保有分=float(np.mean([a['保有分'] for a in rows])) if rows else None)


def snapshot(i: int, r: dict, f: dict) -> dict:
    """機能: 指定済み行の約定値と両気配を原本由来の配列から記録する。

    引数: i(int)、r/f(dict)。返り値: 時刻及び価格(dict)。
    """
    return dict(行=i, 連番=int(r['seq'][i]), 時計=datetime.fromtimestamp(float(r['time_s'][i]), ZONE).isoformat(),
        約定値=float(r['last'][i]), 買気配=float(f['bid'][i]), 売気配=float(f['ask'][i]))


def main() -> None:
    """機能: 固定代表と全条件の費用診断を保存する。

    引数: なし。返り値: なし(None)。売買の再判定及び条件追加は行わない。
    """
    socket.socket.connect = deny
    socket.create_connection = deny
    fixed = load(WORK / '事前固定.json')
    selected = load(WORK / '前半選定.json')
    diag = load(HERE / '基準制限と休止の効果分析.json')
    meta = load(WORK / 'inputs/refmetadata.json')
    ready, features = {}, {}
    for name, target in (('ready', ready), ('features', features)):
        for path in meta['input_paths'][name]:
            target.update(load(ROOT / path))
    all_results = [load(path) for path in sorted((WORK / 'results').glob('*.json'))]
    assert len(all_results) == 480
    groups = defaultdict(list)
    for data in all_results:
        groups[data['config']['group']].append(data)
    distributions = {}
    for group, conditions in groups.items():
        periods = {}
        for period in ('前16', '後13', '全29'):
            periods[period] = {}
            for symbol in ('TOPIX', 'NK225'):
                amounts = [a['periods'][period][symbol]['net'] for a in conditions]
                best = max(conditions, key=lambda a: a['periods'][period][symbol]['net'])
                periods[period][symbol] = dict(条件数=len(amounts), 黒字数=sum(a > 0 for a in amounts),
                    同値数=sum(a == 0 for a in amounts), 赤字数=sum(a < 0 for a in amounts),
                    最大収支=max(amounts), 最小収支=min(amounts),
                    説明用最大収支ID=best['config']['id'],
                    最大収支ID取引数=best['periods'][period][symbol]['trades'])
            periods[period]['両銘柄黒字数'] = sum(all(a['periods'][period][s]['net'] > 0 for s in ('TOPIX', 'NK225')) for a in conditions)
        distributions[group] = periods
    # ----------------------------------------
    # 前半で固定された三代表だけを同じ売買時点で会計診断する。
    output = {}
    examples = []
    for choice in selected['代表']:
        ident = choice['id']
        result = load(WORK / 'results' / (ident + '.json'))
        ledger = load(WORK / 'ledgers' / (ident + '.pkl'))
        records, by_scene = [], {}
        for key, account in sorted(ledger.items()):
            r, f = ready[key], features[key]
            value = 1000. if key[1] == 'TOPIX' else 10.
            opens = {int(a[2]): a for a in account['orders'] if a[7] == 1}
            closes = {int(a[2]): a for a in account['orders'] if a[7] == 0}
            for trade in account['trades']:
                cid, i, e, side = (int(trade[k]) for k in (0, 1, 2, 3))
                o, x = opens[cid], closes[cid]
                qty = int(trade[4])
                entry_spread = float(f['ask'][i] - f['bid'][i])
                exit_spread = float(f['ask'][e] - f['bid'][e])
                assert entry_spread >= 0 and exit_spread >= 0
                spread = (entry_spread + exit_spread) / 2. * qty * value
                entry_mid = (f['bid'][i] + f['ask'][i]) / 2.
                exit_mid = (f['bid'][e] + f['ask'][e]) / 2.
                net_mid = side * (exit_mid - entry_mid) * qty * value - trade[7] - trade[8]
                assert abs(float(trade[10]) + spread - net_mid) < 1e-5
                a = dict(ID=ident, セッション=key[0], 銘柄=key[1], 取引番号=cid,
                    収支=float(trade[10]), 手数料=float(trade[7] + trade[8]), 気配差負担=spread,
                    同時点約定値置換損益=side * float(r['last'][e] - r['last'][i]) * qty * value - float(trade[7] + trade[8]),
                    新規気配差呼値=entry_spread / r['tick'], 返済気配差呼値=exit_spread / r['tick'],
                    新規判断から約定秒=float(r['time_s'][i] - r['time_s'][int(o[1])]),
                    返済判断から約定秒=float(r['time_s'][e] - r['time_s'][int(x[1])]),
                    保有分=float(r['time_s'][e] - r['time_s'][i]) / 60., 出口理由=REASONS[int(x[6])],
                    新規判断=snapshot(int(o[1]), r, f), 新規約定=snapshot(i, r, f),
                    返済判断=snapshot(int(x[1]), r, f), 返済約定=snapshot(e, r, f))
                records.append(a)
                by_scene[(key[0], key[1], cid)] = a
        periods = {}
        for period in ('前16', '後13', '全29'):
            periods[period] = {}
            for symbol in ('TOPIX', 'NK225'):
                part = [a for a in records if a['セッション'] in fixed[period] and a['銘柄'] == symbol]
                a = pack(part)
                b = result['periods'][period][symbol]
                assert abs(a['収支'] - b['net']) < 1e-5 and abs(a['気配差負担'] - b['spread_drag']) < 1e-5
                reasons = {name: pack([a for a in part if a['出口理由'] == name]) for name in REASONS.values()}
                periods[period][symbol] = dict(全取引=a, 出口別=reasons)
        output[ident] = periods
        example = next(a for a in diag['顕著な赤字場三例'] if a['ID'] == ident)
        scene, symbol = example['セッション'], example['銘柄']
        key = (scene, symbol)
        r, f = ready[key], features[key]
        rows = [a for a in records if a['セッション'] == scene and a['銘柄'] == symbol]
        widths = next(a['width'] for a in result['rows'] if a['session'] == scene and a['symbol'] == symbol)
        examples.append(dict(ID=ident, セッション=scene, 銘柄=symbol, 追跡幅=widths,
            始値=meta['references']['|'.join(key)]['ref_open']['value'],
            前保存終値=meta['references']['|'.join(key)]['ref_prev']['value'],
            気配診断=pack(rows), 固定例の最大負け=by_scene[(scene, symbol, example['最大負けの当時ラベルと後続結果']['取引番号'])],
            全取引の順序=rows))
    # ----------------------------------------
    # 中値置換は約定感度の説明であり、指値約定や将来心理の証明ではない。
    out = dict(選定変更なし=True, 新条件なし=True, API取得数=0, 実注文数=0,
        気配差定義='同じ新規と返済の実約定行を中値へ置換した差。入口と出口、トレール、休止、枚数を再計算していない。',
        検査='各取引の中値置換差を両約定行の半気配差合計で独立再計算し、保存済みspread_drag及び費用後収支と全期間で一致。',
        最良IDの意味='全条件の黒字分布を説明するための事後的な最大値。代表の変更及び推奨には用いない。',
        返済理由の意味='観測された同一売買の結果分類。出口を変更した因果効果は別対照で確認する。',
        固定代表の会計診断=output, 全条件の黒字分布=distributions, 既存三例の原本気配追跡=examples)
    target = HERE / '気配差と出口の独立診断.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')
    print(json.dumps(dict(全検査通過=True, 条件数=len(all_results), 固定代表数=len(output), 気配追跡例数=len(examples)), ensure_ascii=False))


if __name__ == '__main__':
    main()
