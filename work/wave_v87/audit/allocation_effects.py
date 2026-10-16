"""数量の縮小・順行追加・親組床を、複数建値を含む全返済会計で区別する。"""

from collections import defaultdict
import math
import pickle
import numpy as np
from diagnose import ROOT, HERE, read, save, clock
from boundaries import module

ROUND = ROOT / 'work/wave_v87/round6'
shared = module('監査87配分差分部品', HERE / 'effects.py')


def campaigns(ledger):
    """
    機能: 複数の追加建値を同じ親組へ集め、初回の原本行と方向を対応キーにする。
    引数: ledger(dict)。
    返り値: dict[tuple,dict]。一つの新規注文しかないとの仮定を置かない。
    """
    legs = defaultdict(list)
    for item in ledger['net_trades']:
        legs[int(item['組'])].append(item)
    result = {}
    orders = ledger['orders']
    for cid, items in legs.items():
        entries = orders[(orders[:, 2] == cid) & (orders[:, 7] == 1)]
        assert len(entries)
        first = entries[np.argmin(entries[:, 0])]
        key = int(first[0]), int(first[3])
        assert key not in result
        ordered = sorted(items, key=lambda t: (t['新規行'], t['返済行']))
        result[key] = dict(cid=cid, entry=key[0], side=key[1],
            exit=max(int(t['返済行']) for t in items), net=math.fsum(t['収支'] for t in items),
            fee=math.fsum(t['手数料'] for t in items), gross=math.fsum(t['利益損失前'] for t in items),
            legs=ordered, initial_lots=int(first[4]), entry_orders=entries.tolist())
    return result


def load(model, configs):
    """
    機能: 固定十一条件の保存結果と複数建値の親組を読み込む。
    引数: model(str)、configs(list[dict])。
    返り値: tuple[dict,dict,dict]。
    """
    results, records, raw = {}, {}, {}
    for config in configs:
        ident = config['id']
        results[ident] = read(ROUND / model / 'results' / f'{ident}.json')
        raw[ident] = pickle.loads((ROUND / model / 'ledgers' / f'{ident}.pkl').read_bytes())
        records[ident] = {(session, symbol, entry, side): group
            for (session, symbol), ledger in raw[ident].items()
            for (entry, side), group in campaigns(ledger).items()}
    return results, records, raw


def addition_summary(ledgers, config, symbol, names):
    """
    機能: 追加後の全返済結果と料金込み初回予算の実超過を集計する。
    引数: ledgers/config(dict)、symbol(str)、names(list[str])。
    返り値: dict。実予算超過を隠さず、追加のなかった親組と分ける。
    """
    records = []
    scale = 1000 if symbol == 'TOPIX' else 10
    for (session, product), ledger in ledgers.items():
        if product != symbol or session not in names:
            continue
        cycles = {int(c[0]): c for c in ledger['cycles']}
        for (_, side), group in campaigns(ledger).items():
            cid = group['cid']
            events = ledger['allocation_events']
            selected = events[events[:, 1] == cid]
            additions = selected[selected[:, 2] == 2]
            if not len(additions):
                continue
            cycle = cycles[cid]
            budget = group['initial_lots'] * .75 * cycle[5] * scale
            target = -budget if config['floor_mode'] == 1 else 0 if config['floor_mode'] == 2 else None
            floors = selected[selected[:, 2] == 3]
            executed_floor = selected[selected[:, 2] == 4]
            orders = ledger['orders'][ledger['orders'][:, 2] == cid]
            record = dict(セッション=session, 親組=cid, 方向=side,
                初回時刻=clock(group['legs'][0]['新規時刻']), 初回枚数=group['initial_lots'],
                追加発注回数=len(additions), 追加枚数=int(additions[:, 5].sum()),
                最大累計使用枚数=int(additions[:, 7].max()), 全返済収支=group['net'],
                料金前収支=group['gross'], 手数料=group['fee'], 初回損失予算=budget,
                床の目標金額=target, 床発動=len(executed_floor) > 0,
                目標超過額=max(0., target - group['net']) if target is not None else None,
                元初回予算の超過額=max(0., -budget - group['net']),
                最後の床価格=float(floors[-1, 6]) if len(floors) else None,
                返済理由=sorted({int(t['理由']) for t in group['legs']}),
                全返済時刻=clock(max(t['返済時刻'] for t in group['legs'])),
                注文=orders.tolist(), 返済脚=group['legs'])
            records.append(record)
    exceeds = [r for r in records if r['目標超過額'] is not None and r['目標超過額'] > 1e-7]
    return dict(追加が実約定した親組数=len(records),
        追加親組の黒字数=sum(r['全返済収支'] > 0 for r in records),
        追加親組の赤字数=sum(r['全返済収支'] < 0 for r in records),
        追加親組の合計収支=math.fsum(r['全返済収支'] for r in records),
        追加親組の料金前収支=math.fsum(r['料金前収支'] for r in records),
        追加親組の手数料=math.fsum(r['手数料'] for r in records),
        床発動親組数=sum(r['床発動'] for r in records),
        設定床目標を下回った全返済親組数=len(exceeds),
        内実際の床発動あり=sum(r['床発動'] for r in exceeds),
        設定床目標からの超過合計=math.fsum(r['目標超過額'] for r in exceeds),
        最大予算超過例=sorted(exceeds, key=lambda r: r['目標超過額'], reverse=True)[:3],
        追加親組全件=records,
        注記='床は次観測からの返済判断線。価格飛び・有効化前の動き・元の優先返済で、最終損失が床目標を超える場合も、そのまま実額を集計する。')


def main():
    """
    機能: 主仮説を変更せず、少枚数だけ・追加だけ・床だけの比較を分離する。
    引数: なし。
    返り値: None。保存結果のみを使用し、売買や閾値探索は再実行しない。
    """
    fixed = read(ROUND / '事前固定.json')
    comparisons = [('初回数量のみ', 'A_GU', 'A_S1'), ('初回数量のみ', 'A_GU', 'A_S2'),
        ('追加のみ・新床なし', 'A_S2', 'A_J1_N'), ('初回予算床の追加', 'A_J1_N', 'A_J1_R'),
        ('ゼロ床の追加', 'A_J1_N', 'A_J1_Z'), ('一括追加の床をゼロへ', 'A_J1_R', 'A_J1_Z'),
        ('段階追加の床をゼロへ', 'A_D05_R', 'A_D05_Z'), ('少枚数段階の床をゼロへ', 'A_L05_R', 'A_L05_Z'),
        ('初回2枚から主仮説へ', 'A_S2', 'A_D05_R'), ('初回1枚から段階追加へ', 'A_S1', 'A_L05_R')]
    models = {}
    for model in fixed['models']:
        results, records, raw = load(model, fixed['catalog'])
        summaries, parts, reductions = [], [], []
        for config in fixed['catalog']:
            ident = config['id']
            periods = {}
            for period in ('前16', '後14', '全30'):
                product = {}
                for symbol in ('TOPIX', 'NK225'):
                    new = results[ident]['periods'][period][symbol]
                    old = results['A_GU']['periods'][period][symbol]
                    product[symbol] = dict(集計={k: new[k] for k in shared.FIELDS},
                        元GUとの差={k: new[k] - old[k] if new[k] is not None and old[k] is not None else None for k in shared.FIELDS},
                        買売=shared.directional(records[ident], symbol, fixed[period]),
                        親組対応=shared.matching(records['A_GU'], records[ident], symbol, fixed[period]),
                        順行追加と予算超過=addition_summary(raw[ident], config, symbol, fixed[period]))
                periods[period] = product
            summaries.append(dict(条件=ident, 固定主仮説=ident == 'A_D05_R', 期間別=periods,
                全30場差={s: shared.session_difference(results['A_GU'], results[ident], s) for s in ('TOPIX', 'NK225')}))
        for title, before, after in comparisons:
            for period in ('前16', '後14', '全30'):
                for symbol in ('TOPIX', 'NK225'):
                    a = results[before]['periods'][period][symbol]
                    b = results[after]['periods'][period][symbol]
                    parts.append(dict(変更=title, 元=before, 新=after, 期間=period, 商品=symbol,
                        差={k: b[k] - a[k] if a[k] is not None and b[k] is not None else None for k in shared.FIELDS},
                        同初回入口の対応=shared.matching(records[before], records[after], symbol, fixed[period])))
        for ident, ratio in (('A_S1', .2), ('A_S2', .4)):
            for symbol in ('TOPIX', 'NK225'):
                a = results['A_GU']['periods']['全30'][symbol]
                b = results[ident]['periods']['全30'][symbol]
                reductions.append(dict(条件=ident, 商品=symbol, 初回枚数倍率=ratio,
                    元料金前収支=a['gross'], 単純比例なら料金前収支=a['gross'] * ratio,
                    実際料金前収支=b['gross'], 比例値との差=b['gross'] - a['gross'] * ratio,
                    手数料=b['fees'], 料金後収支=b['net'], 最大下落=b['max_drawdown'],
                    注記='最低1枚を残す半減、先頭枠の整数切捨て、一注文の手数料丸めがあるため、全会計の単純比例とは限らない。'))
        models[model] = dict(全11条件=summaries, 部品を揃えた比較=parts, 単純な数量縮小との違い=reductions)
        print(model, '数量・追加・床の原因分解完了', flush=True)
    save('全11数量条件の縮小追加と床の独立分解_会計修正版.json', dict(主仮説='A_D05_R', 結果で主仮説を変更=False,
        モデル別=models, 注記=['全30場は既知。期間と買売別の分解は診断であり採用する時間帯を選び直していない。',
            '一つの親組に初回と複数追加を含める。最初の新規行と方向が一致する親組だけ対応する。',
            '観測約定は当該有効CurrentPrice、指定約定は有効な注文線。気配約定や固定5秒待ちを加えていない。']))


if __name__ == '__main__':
    main()
