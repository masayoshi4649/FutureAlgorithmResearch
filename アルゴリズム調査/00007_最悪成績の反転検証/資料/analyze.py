"""元純益最悪と値動き最悪を区別して、時間順の反転結果を集約する。"""

from __future__ import annotations

import json

import pandas as pd

from selection import COMPLETE, OUT, ROOT, SYMBOLS, save, selections


def aggregate(frame: pd.DataFrame, ids: list[str], sessions: list[str], target: str) -> dict:
    """機能: 指定条件と期間の元売買・反対売買を同じ母集団で合計する。

    引数: frame (DataFrame)、ids/sessions (list[str])、target (str)。
    返り値: 実額・枚数換算額・取引数・費用内訳 (dict)。
    """
    symbols = SYMBOLS if target == '両銘柄' else [target]
    part = frame[frame['方式'].isin(ids) & frame['セッション'].isin(sessions) & frame['銘柄'].isin(symbols)]
    result = {}
    for name in part.columns:
        if name.endswith(('円', '取引数', '未返済数', '勝ち数', '負け数', '数量不足行数', '数量待ち行数', '新規取消数', '返済不成立数')):
            result[name] = float(part[name].sum())
    for prefix in ['元', '理論反転', '容量反転', '次行反転']:
        for metric in ['収支円', '費用倍収支円', '総評価円']:
            name = prefix + metric
            result[prefix + '設定上限換算' + metric] = float((part[name] / part['設定最大枚数']).sum())
    result['対象セル数'] = len(part)
    return result


def main() -> None:
    """機能: 反転成績を選択に戻さず、固定済み三つの選択方針を評価する。

    引数: なし。返り値: None。結果と代表IDを保存し、通信はしない。
    """
    original = pd.read_csv(ROOT/'work/wave_v11/全条件_セッション集計.csv')
    mirror = pd.read_csv(OUT/'反転_全条件セッション集計.csv')
    original = original.merge(mirror[['方式', 'セッション', '銘柄', '元mid値動き益円']],
                              on=['方式', 'セッション', '銘柄'], validate='one_to_one')
    all_choices, tests, fitted, reference = [], [], [], []
    for name, column, normalize in [('元純益最悪・枚数換算', '収支円', True),
                                     ('元純益最悪・実額', '収支円', False),
                                     ('元仲値変化最悪・枚数換算', '元mid値動き益円', True)]:
        choices = selections(original, column, normalize)
        for choice in choices:
            choice['選び方'] = name
            all_choices.append(choice)
            if not choice['選択']:
                continue
            method = choice['選択']['方式']
            base = dict(選び方=name, 対象=choice['対象'], 思想=choice['思想'], 方式=method,
                        学習数=len(choice['学習']), 評価セッション=choice['評価セッション'],
                        選択得点=choice['選択']['得点'])
            values = aggregate(mirror, [method], [choice['評価セッション']], choice['対象'])
            if len(choice['学習']) < 5:
                tests.append(dict(base, **values))
            else:
                reference.append(dict(base, **values))
                fitted.append(dict(base, **aggregate(mirror, [method], COMPLETE, choice['対象'])))
    save(OUT/'反転_全選択記録.json', all_choices)
    ids = sorted({row['選択']['方式'] for row in all_choices if row['選択']})
    save(OUT/'反転_全選択ID.json', ids)
    for name, rows in [('反転_時間順選択評価.csv', tests), ('反転_５完全探索代表.csv', fitted),
                        ('反転_既知ナイト00時02分参考.csv', reference)]:
        pd.DataFrame(rows).to_csv(OUT/name, index=False, encoding='utf-8-sig')
    frame = pd.DataFrame(tests)
    numeric = [c for c in frame.select_dtypes('number').columns if c not in ['学習数', '選択得点']]
    summary = frame.groupby(['選び方', '対象', '思想'])[numeric].sum().reset_index()
    summary.to_csv(OUT/'反転_選択方針要約.csv', index=False, encoding='utf-8-sig')

    # ----------------------------------------
    full = mirror[mirror['セッション'].isin(COMPLETE)]
    columns = [c for c in full.select_dtypes('number').columns if c.endswith(('円', '取引数', '未返済数'))]
    total = full.groupby(['方式', '思想'])[columns].sum().reset_index()
    total.to_csv(OUT/'反転_全条件５完全集計.csv', index=False, encoding='utf-8-sig')
    info = dict(全条件数=len(total), 理論反転黒字数=int((total['理論反転収支円'] > 0).sum()),
                次行反転黒字数=int((total['次行反転収支円'] > 0).sum()),
                次行反転費用倍黒字数=int((total['次行反転費用倍収支円'] > 0).sum()),
                選択記録数=len(all_choices), 選択条件数=len(ids), 条件=ids,
                最良反転探索参考=total.sort_values(['次行反転収支円', '方式'], ascending=[False, True]).head(5).to_dict('records'))
    save(OUT/'反転_要点.json', info)
    print(json.dumps({k:v for k,v in info.items() if k != '最良反転探索参考'}, ensure_ascii=False))
    print(summary[(summary['対象'] == '両銘柄') & (summary['思想'] == '全方式')][
        ['選び方', '元収支円', '次行反転収支円', '次行反転費用倍収支円']].to_string(index=False))


if __name__ == '__main__':
    main()
