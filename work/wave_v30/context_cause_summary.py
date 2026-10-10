"""固定比較で保存した全原因を、選別せず数え直して説明資料へ整理する。"""

from __future__ import annotations

from collections import Counter, defaultdict
import json
from pathlib import Path

import context_comparison as comparison

HERE = Path(__file__).resolve().parent


def category(row: dict) -> str:
    """機能: 共通状態から最初に分かれた約定を注文理由で分類する。

    引数: row (dict) は一対の分岐。返り値: 分岐の種類 (str)。後続取引は対応させない。
    """
    if row['注文台帳同一']:
        return '全注文同一'
    left, right = row['同じ分岐行のC注文'], row['同じ分岐行のS注文']
    if left is not None and left['理由'] == 10 and right is None:
        return 'Cだけが中立返済'
    if right is not None and right['理由'] == 13 and left is None:
        return 'Sだけが反転返済'
    if right is not None and right['理由'] == 10 and left is None:
        return 'Sだけが中立返済'
    if left is not None and left['理由'] == 13 and right is None:
        return 'Cだけが反転返済'
    return '同時約定の理由又は価格・数量の差' if left is not None and right is not None else 'その他の片側先行約定'


def main() -> None:
    """機能: 既に保存した全84診断の原因頻度と時系列先頭例を作る。

    引数: なし。返り値: なし (None)。再生・探索・追加取得はせず説明例を収益で選ばない。
    """
    result = comparison.runner.read(HERE / 'context_comparison.json')
    fixed = comparison.runner.read(HERE / '探索条件の固定.json')
    values = [comparison.runner.read(HERE / 'context_causes' / (spec['id'] + '.json.gz')) for spec in fixed['signals']]
    sources = {str(path.relative_to(HERE)): comparison.runner.digest(path)
               for path in [HERE / 'context_comparison.json'] + [HERE / 'context_causes' / (spec['id'] + '.json.gz') for spec in fixed['signals']]}
    counts = defaultdict(Counter)
    neutral = {}
    examples = defaultdict(list)
    all_rows = []
    for value in values:
        for branch in value['最初のCS分岐']:
            label = category(branch)
            counts[(branch['mode'], branch['symbol'])][label] += 1
            all_rows.append(dict(branch, 分類=label))
            if label != '全注文同一':
                examples[label].append(branch)
        for row in value['全区間の参加と中立']:
            manager = row['id'].split('__')[1]
            if manager == 'L000':
                continue
            key = (manager, row['symbol'])
            group = neutral.setdefault(key, {'管理': manager, '銘柄': row['symbol'], '連続0区間数': 0,
                                             '原因が交代した区間数': 0, '全中立秒': 0., '全中立秒の原因内訳': Counter(),
                                             '中立返済数': 0, '判断前に原因が交代した返済数': 0,
                                             '返済判断までの原因秒': Counter(), '返済判断の原因種類': Counter()})
            for run in row['連続中立']:
                group['連続0区間数'] += 1
                group['原因が交代した区間数'] += int(run['原因交代数'] > 0)
                group['全中立秒'] += run['秒']
                for piece in run['原因区間']:
                    group['全中立秒の原因内訳'][piece['原因']] += piece['秒']
                for decision in run['中立返済判断']:
                    group['中立返済数'] += 1
                    pieces = decision['判断までの原因区間']
                    if len(pieces) > 1:
                        group['判断前に原因が交代した返済数'] += 1
                        examples['中立返済前の原因交代'].append({'id': row['id'], 'session': row['session'], 'symbol': row['symbol'],
                                                            '連続0開始': run['開始'], **decision})
                    for piece in pieces:
                        group['返済判断までの原因秒'][piece['原因']] += piece['秒']
                    positive_causes = sorted({piece['原因'] for piece in pieces if piece['秒'] > 0})
                    group['返済判断の原因種類']['＋'.join(positive_causes)] += 1
    first_examples = {}
    for label, rows in examples.items():
        rows.sort(key=lambda row: (row['session'], row.get('最初の分岐行', row.get('判断行', 0)),
                                   row.get('signal', row.get('id', '')), row['symbol']))
        first_examples[label] = rows[:3]
    output = {'目的': '全84の固定対応比較に対する説明用集計。新しい選抜や未知検証ではない。',
              '単位注意': '最初の共通状態にある現金・時価は価格pt×枚数。円換算はTOPIX1000/NK22510。',
              '原因の限界': '相手不一致と相手方向未提供は保存contextだけでは分けず併記。自己中立と相手不一致が連続0中に交代した分を期間全体で数える。',
              '頻度の限界': '同じ13セッションに12入口を繰り返した件数。独立した相場サンプル数ではない。',
              '説明例の順序': '分類ごとにセッション・原本行・ID・銘柄の昇順先頭3件。収益では選ばない。',
              '全分岐比較数': len(all_rows),
              '最初の分岐分類': [{'mode': mode, 'symbol': symbol, '件数': dict(counter)} for (mode, symbol), counter in sorted(counts.items())],
              '全中立原因集計': list(neutral.values()), '最初の分岐全件': all_rows, '時系列先頭例': first_examples,
              '全12入口の等重み集計': result['全12入口の等重み集計'],
              'EMAを統合した5思想の等重み': result['EMAを統合した5思想の等重み'],
              '資料SHA256': sources, 'API取得': 0, '現在保存物使用': False}
    assert len(all_rows) == 936 and all(sum(row['件数'].values()) == 156 for row in output['最初の分岐分類'])
    comparison.runner.save(HERE / 'context_cause_summary.json', output)
    lines = ['# 相手不一致と自己撤回の原因', '', '全84条件を全13セッションで比較。原因件数は同じ相場の繰返しであり、独立標本数ではない。', '',
             '|撤回|銘柄|最初の分岐分類と件数|', '|---|---|---|']
    for row in output['最初の分岐分類']:
        labels = '、'.join(f'{label} {count}' for label, count in row['件数'].items())
        lines.append(f"|{row['mode']}|{row['symbol']}|{labels}|")
    lines += ['', '|管理|銘柄|連続中立区間|原因交代区間|中立返済|うち判断前に原因交代|', '|---|---|---:|---:|---:|---:|']
    for row in output['全中立原因集計']:
        lines.append(f"|{row['管理']}|{row['銘柄']}|{row['連続0区間数']}|{row['原因が交代した区間数']}|{row['中立返済数']}|{row['判断前に原因が交代した返済数']}|")
    lines += ['', '中立時計は原因が変わっても0が続く間は継続する。返済瞬間の原因だけへ10分間の全体を帰属させていない。',
              '最初の分岐だけが共通の保有・現金・時価からの比較。分岐後のcampaign番号を対応させる説明は行わない。',
              '共通状態の現金・時価の単位は円ではなく価格pt×枚数。相手不一致と相手方向未提供は保存列では分離できない。', '']
    for label, rows in first_examples.items():
        lines += [f'## {label}の時系列先頭例', '', '```json', json.dumps(rows, ensure_ascii=False, indent=2), '```', '']
    (HERE / 'context_cause_summary.md').write_text('\n'.join(lines), encoding='utf-8')
    print('全936比較の原因要約を保存。現在再生・新規APIなし。', flush=True)


if __name__ == '__main__':
    main()
