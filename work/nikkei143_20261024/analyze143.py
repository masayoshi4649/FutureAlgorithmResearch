"""日経の方向別・昼夜別成績と、深夜を除く活動を同じ会計から比較する。"""

import argparse
import numpy as np
import common143 as shared

HERE = shared.HERE


def measure(rows):
    """
    機能: 完結親損益を足し、場の負け方・利益集中・保有の和集合を別々に集計する。
    引数: rows(list[dict])は同じ方法の場会計。
    返り値: dictは利益損失比・損失規模・活動と買売別の集計。
    """
    profit = sum(r['profit'] for r in rows)
    loss = sum(r['loss'] for r in rows)
    values = [r['net'] for r in rows]
    negative = [-v for v in values if v < 0.]
    positive = [v for v in values if v > 0.]
    if not rows:
        return dict(sessions=0, pf=None, net=0.)
    result = dict(sessions=len(rows), profit=profit, loss=loss, net=profit-loss, pf=profit/loss if loss else None,
        wins=len(positive), losses=len(negative), flat=len(rows)-len(positive)-len(negative),
        zero_entry=sum(r['entries'] == 0 for r in rows), parent_count=sum(r['parent_count'] for r in rows),
        entries=sum(r['entries'] for r in rows), fees=sum(r['fees'] for r in rows),
        bbo_drag=sum(r['bbo_drag'] for r in rows), midpoint_gross=sum(r['midpoint_gross'] for r in rows),
        mean_net=float(np.mean(values)), median_net=float(np.median(values)), worst=min(values),
        mean_loss=float(np.mean(negative)) if negative else 0., median_loss=float(np.median(negative)) if negative else 0.,
        mean_win=float(np.mean(positive)) if positive else 0., ex_top3=sum(values)-sum(sorted(positive, reverse=True)[:3]),
        mean_holding_ratio=float(np.mean([r['holding_ratio'] for r in rows])),
        time_weighted_holding_ratio=sum(r['held_minutes_excluding_03_06'] for r in rows)/sum(r['evaluation_minutes'] for r in rows),
        average_quantity=float(np.mean([r['average_quantity'] for r in rows])),
        max_per_side=max(r['max_per_side'] for r in rows))
    result['buy_sell'] = {}
    for name in ('買い', '売り'):
        chosen = [r['buy_sell'][name] for r in rows]
        gains, losses = sum(x['profit'] for x in chosen), sum(x['loss'] for x in chosen)
        result['buy_sell'][name] = dict(parents=sum(x['parents'] for x in chosen), profit=gains, loss=losses,
                                       net=gains-losses, pf=gains/losses if losses else None)
    return result


def summarize(rows):
    """
    機能: 全場・昼夜・始終方向の各組合せと全体評価を生成する。
    引数: rows(list[dict])は保存済み全場会計。
    返り値: tuple[list,list]は全条件の全体集計と細分集計。
    """
    summary, groups = [], []
    for method in sorted({r['method'] for r in rows}):
        chosen = [r for r in rows if r['method'] == method]
        assert len({r['session'] for r in chosen}) == len(chosen)
        main = dict(method=method, **measure(chosen))
        for kind in ('全場', 'Day', 'Night'):
            for direction in ('全方向', '上昇', '下落', '同値'):
                subset = [r for r in chosen if (kind == '全場' or r['kind'] == kind) and (direction == '全方向' or r['direction'] == direction)]
                if not subset:
                    continue
                part = dict(method=method, kind=kind, direction=direction, **measure(subset))
                groups.append(part)
                if kind == '全場' and direction in ('上昇', '下落'):
                    main['up' if direction == '上昇' else 'down'] = {k: part[k] for k in ('sessions', 'profit', 'loss', 'net', 'pf', 'losses', 'worst')}
        main['both_directions_positive'] = all(main.get(k, {}).get('net', 0.) > 0. for k in ('up', 'down'))
        main['target_checks'] = dict(pf_2_or_more=main['loss'] > 0. and main['pf'] >= 2.,
                                    mean_holding_50_or_more=main['mean_holding_ratio'] >= .5,
                                    no_zero_entry=main['zero_entry'] == 0,
                                    both_directions_positive=main['both_directions_positive'],
                                    ex_top3_positive=main['ex_top3'] > 0.)
        summary.append(main)
    return summary, groups


def main(stage):
    """
    機能: 完成した巡回結果を読み取り、採否を決める前の全条件一覧を保存する。
    引数: stage(str)は第一巡などの結果接頭辞。
    返り値: None。金融再生と条件選択は行わない。
    """
    raw = shared.read(HERE / f'{stage}結果143.json')
    summary, groups = summarize(raw['rows'])
    shared.save(HERE / f'{stage}集計143.json', dict(summary=summary, groups=groups, rows=raw['rows'], cache=raw['cache']))
    selected = [s for s in summary if not s['method'].startswith(('A', 'E', 'S', 'O'))]
    selected.sort(key=lambda s: (sum(s['target_checks'].values()), min(s['mean_holding_ratio']/.5, 1.)*min((s['pf'] or 0.)/2., 1.), -s['losses']), reverse=True)
    for r in selected[:16]:
        print(r['method'], '収支', r['net'], '比', round(r['pf'] or 0., 3), '赤字', r['losses'],
              '保有', round(100*r['mean_holding_ratio'], 2), '無', r['zero_entry'],
              '大勝ち除外', r['ex_top3'], '上/下', round(r.get('up', {}).get('pf') or 0., 2), round(r.get('down', {}).get('pf') or 0., 2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['第一巡', '第二巡', '第三巡'])
    main(parser.parse_args().stage)
