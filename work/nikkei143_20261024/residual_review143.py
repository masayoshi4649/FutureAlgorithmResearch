"""第三巡の保存結果だけから、残玉による同親変化と後続見送りを分けて査読する。"""

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import numpy as np
import common143 as shared


HERE = Path(__file__).resolve().parent
JST = ZoneInfo('Asia/Tokyo')
SELECT = ['F1', 'TG00', 'TG04', 'PP04', 'PG04']
KEYS = ['method', 'sessions', 'net', 'pf', 'losses', 'zero_entry', 'mean_holding_ratio',
        'time_weighted_holding_ratio', 'average_quantity', 'ex_top3', 'worst',
        'mean_loss', 'median_loss', 'buy_sell', 'up', 'down']


def read(name):
    """
    機能: 保存された日本語JSONを読み取る。
    引数: name(str)は作業ディレクトリ内の相対名。
    返り値: dictは保存結果。金融再生は行わない。
    """
    return json.loads((HERE / name).read_text(encoding='utf-8'))


def short(summary):
    """
    機能: 査読に必要な保存集計列だけを取り出す。
    引数: summary(dict)は元集計。
    返り値: dictは比較列。丸める前の値を保持する。
    """
    return {key: summary[key] for key in KEYS if key in summary}


def explanation(changes):
    """
    機能: 同親の損益変化と見送った後続親の損益を足し上げる。
    引数: changes(list[dict])は親別の保存結果差。
    返り値: dictは各機構の件数と円額。新しい売買は計算しない。
    """
    changed = [x for x in changes if x['kind'] == '同親の残玉管理変更']
    absent = [x for x in changes if x['kind'] == '残玉中の後続親見送り']
    improved = [x for x in changed if x['delta'] > 0]
    worsened = [x for x in changed if x['delta'] < 0]
    skipped_win = [x for x in absent if x['old_net'] > 0]
    skipped_loss = [x for x in absent if x['old_net'] < 0]
    return dict(changed_parents=len(changed), improved_parents=len(improved),
        improved_yen=sum(x['delta'] for x in improved), worsened_parents=len(worsened),
        worsened_yen=-sum(x['delta'] for x in worsened),
        same_parent_delta=sum(x['delta'] for x in changed),
        skipped_parents=len(absent), skipped_winners=len(skipped_win),
        skipped_winner_profit=sum(x['old_net'] for x in skipped_win),
        skipped_losers=len(skipped_loss), skipped_loser_loss=-sum(x['old_net'] for x in skipped_loss),
        skipped_delta=sum(x['delta'] for x in absent),
        total_delta=sum(x['delta'] for x in changes))


def order_record(row, ready):
    """
    機能: 保存注文を日本時間・原板行番号付きの根拠へ変換する。
    引数: row(ndarray[10])、ready(dict)は注文と登録済み原行対応。
    返り値: dictは新規返済・判断/約定時刻・原seq・価格・費用。
    """
    fill, decision = int(row[0]), int(row[1])
    return dict(action='新規' if row[7] else '返済', side='買い' if row[3] > 0 else '売り',
        quantity=int(row[4]), price=float(row[5]), reason=int(row[6]), uid=int(row[8]),
        fee=int(row[9]), decision_row=decision, fill_row=fill,
        decision_time=datetime.fromtimestamp(float(ready['time_s'][decision]), JST).isoformat(),
        fill_time=datetime.fromtimestamp(float(ready['time_s'][fill]), JST).isoformat(),
        decision_raw_seq=int(ready['seq'][decision]), fill_raw_seq=int(ready['seq'][fill]),
        decision_raw_line=int(ready['seq'][decision])+1, fill_raw_line=int(ready['seq'][fill])+1)


def run():
    """
    機能: 全50場の保存会計を分解し、最大変化例の原行根拠と短い査読を保存する。
    引数: なし。
    返り値: None。既存金融結果と凍結済み売買コードは変更しない。
    """
    third, first = read('第三巡集計143.json'), read('第一巡集計143.json')
    result = read('第三巡結果143.json')
    saved = {(x['method'], x['session']): x for x in result['rows']}
    sessions = sorted(x['session'] for x in result['cache'])
    summaries = {x['method']: x for x in first['summary'] + third['summary']}
    changes, scene_deltas, traces = [], [], []
    for scene in sessions:
        old, new = saved['TG00', scene], saved['TG04', scene]
        before = {p['id']:p for p in old['parent_records']}
        after = {p['id']:p for p in new['parent_records']}
        assert set(after) <= set(before), '残玉方式から元に無い新規親が生まれています'
        for parent, a in before.items():
            b = after.get(parent)
            if b is not None and a['net'] == b['net']:
                continue
            sleeve = ('CG', 'A3', 'CS')[int(parent)//10_000_000]
            change = dict(session=scene, period=old['kind'], parent=int(parent), sleeve=sleeve,
                source_parent=int(parent)%10_000_000, old_net=a['net'], new_net=b['net'] if b else 0.,
                kind='同親の残玉管理変更' if b else '残玉中の後続親見送り',
                side='買い' if a['side'] > 0 else '売り', delta=(b['net'] if b else 0.)-a['net'])
            assert sleeve != 'A3', '変更していない追加源に差があります'
            changes.append(change)
        chosen = [x for x in changes if x['session'] == scene]
        assert sum(x['delta'] for x in chosen) == new['net']-old['net']
        scene_deltas.append(dict(session=scene, old_net=old['net'], new_net=new['net'],
            delta=new['net']-old['net'], decomposition=explanation(chosen)))
        with np.load(HERE/'round3/traces'/f'NK225_{scene}.npz') as archive:
            for sleeve in ('CG', 'CS'):
                trace = archive[sleeve+'04']
                reasons = {str(int(reason)):int(np.sum((trace[:, 2] == 4)&(trace[:, 5] == reason)))
                           for reason in np.unique(trace[trace[:, 2] == 4, 5])}
                blocked = trace[(trace[:, 2] == 1)&(trace[:, 5] == 14384)]
                traces.append(dict(session=scene, sleeve=sleeve,
                    retained=int(np.sum(trace[:, 2] == 2)), budget_confirmed=int(np.sum(trace[:, 2] == 3)),
                    budget_failed=int(np.sum((trace[:, 2] == 3)&(trace[:, 5] == 14382))),
                    skipped=int(len(blocked)), skipped_source_parent=[int(v) for v in blocked[:, 1]],
                    exit_reasons=reasons))
                expected = sorted(x['source_parent'] for x in chosen if x['sleeve'] == sleeve and x['kind']=='残玉中の後続親見送り')
                assert expected == sorted(int(v) for v in blocked[:, 1])
    # ----------------------------------------
    # 最大変化場の約定は保存配列から取り、原入力は時計とseq対応の参照だけに用いる。
    packet_items, _, _ = shared.material()
    packets = {x['session']:x for x in packet_items}
    extremes = sorted(scene_deltas, key=lambda x:x['delta'])[:2] + sorted(scene_deltas, key=lambda x:x['delta'], reverse=True)[:2]
    examples = []
    for scene_record in extremes:
        scene = scene_record['session']
        packet = shared.packet_from(packets[scene])
        ready = packet['inputs'][scene, 'NK225']
        with np.load(HERE/'round3/measurement'/f'NK225_{scene}.npz') as archive:
            old, new = archive['TG00'], archive['TG04']
        parent_cases = sorted([x for x in changes if x['session'] == scene], key=lambda x:abs(x['delta']), reverse=True)
        expanded = []
        for change in parent_cases:
            parent = change['parent']
            expanded.append(dict(change, before_orders=[order_record(r,ready) for r in old[old[:, 2]==parent]],
                after_orders=[order_record(r,ready) for r in new[new[:, 2]==parent]]))
        examples.append(dict(scene_record, parent_changes=expanded,
            raw_basis='登録済み原板対応seq。原文の行番号はseq+1。価格時計であり受信時計ではない。',
            packet_reference=packets[scene]))
    groups = [dict(short(x), kind=x['kind'], direction=x['direction']) for x in third['groups']
              if x['method'] in ('TG00','TG04','PP04','PG04','CG04','CS04','CA04')
              and x['kind'] in ('Day','Night')]
    groups += [dict(short(x), kind=x['kind'], direction=x['direction']) for x in first['groups']
               if x['method']=='A3' and x['kind'] in ('Day','Night')]
    totals = explanation(changes)
    assert totals['total_delta'] == summaries['TG04']['net']-summaries['TG00']['net']
    both_red = [x for x in scene_deltas if x['old_net'] < 0 and x['new_net'] < 0]
    red_cohort = dict(count=len(both_red), old_loss=-sum(x['old_net'] for x in both_red),
        new_loss=-sum(x['new_net'] for x in both_red), worsened=sum(x['delta'] < 0 for x in both_red),
        improved=sum(x['delta'] > 0 for x in both_red), unchanged=sum(x['delta'] == 0 for x in both_red),
        loss_to_profit=[x for x in scene_deltas if x['old_net'] < 0 <= x['new_net']],
        profit_to_loss=[x for x in scene_deltas if x['new_net'] < 0 <= x['old_net']])
    report = dict(scope='既知開発50場の保存会計だけの査読。新規金融再生なし。',
        candidates=[short(summaries[x]) for x in SELECT], groups=groups,
        red_session_same_cohort=red_cohort,
        total_change=totals, change_by_period={k:explanation([x for x in changes if x['period']==k]) for k in ('Day','Night')},
        change_by_sleeve={k:explanation([x for x in changes if x['sleeve']==k]) for k in ('CG','CS')},
        converted_parent_losses=[x for x in changes if x['kind']=='同親の残玉管理変更' and x['new_net'] < 0],
        parent_changes=changes, scene_changes=scene_deltas, trace_counts=traces,
        largest_session_changes=examples,
        limitations=['全50場は既に開発に用いた。未見検証ではない。',
            '平均保有率は各場比率の単純平均であり、時間加重平均とも夜間だけの保有率とも異なる。',
            '利益予算は判断時の床であり、次板の飛び越え損失を保証しない。',
            '上昇場・下落場の双方黒字と、買い・売りの成績が対称であることを混同しない。'])
    shared.save(HERE/'第三巡候補の敵対査読143.json', report)
    print(json.dumps(dict(total=totals, period=report['change_by_period'],
        red_cohort=red_cohort, extremes=extremes), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    run()
