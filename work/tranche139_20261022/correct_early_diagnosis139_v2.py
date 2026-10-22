"""保存済み早期診断の通常補完誤分類を、候補ID集合によって訂正する。"""

from collections import defaultdict
import copy
import json

import numpy as np

from audit139 import HERE, digest, read


def main():
    """
    機能: 再売買せず、単独親と見送り候補の全IDから早期寄与だけを再集計する。
    引数: なし。
    返り値: None。旧資料は残し、訂正JSONと説明MDを新規保存する。
    """
    oldpath = HERE / 'early_diagnosis139.json'
    old = read(oldpath)
    results = read(HERE / 'early_results/結果.json')
    accounts = {(r['session'], r['symbol'], r['method']): r for r in results['rows']}
    skipped = {(r['session'], r['symbol'], r['method']): r['skipped'] for r in results['skips']}
    ordinary = {(r['session'], r['symbol'], r['method']): r
                for folder in ('results', 'extra_results')
                for r in read(HERE / folder / '結果.json')['rows'] if r['method'] in ('B5', 'C04')}
    corrected = copy.deepcopy(old)
    changes = []
    for row in corrected['coverage']:
        scene, symbol, method = row['session'], row['symbol'], row['method']
        source = method.split('_')[-1]
        basekey = method.split('_')[0] if '_' in method else None
        single = accounts[(scene, symbol, source)]
        candidates = {int(p['id']) for p in single['parents']}
        for record in skipped.get((scene, symbol, source), []):
            assert record['kind'] == '早期'
            candidates.add(int(record['parent']))
        baseids = {int(p['id']) for p in ordinary[(scene, symbol, basekey)]['parents']} if basekey else set()
        assert candidates.isdisjoint(baseids)
        account = accounts[(scene, symbol, method)]
        ids = {int(p['id']) for p in account['parents']}
        assert ids <= candidates | baseids, ('候補不明の親', scene, symbol, method, ids - candidates - baseids)
        selected = [p for p in account['parents'] if int(p['id']) in candidates]
        # 旧初回時計はUID0のみで求めており、通常補完UID999は含まれていないことも検査する。
        old_initials = [p for p in account['parents'] if p['id'] >= 20000 and '0' in p['legs']]
        assert {p['id'] for p in old_initials} == {p['id'] for p in selected}
        assert row['early_parents'] == len(selected)
        before = {name: row[name] for name in ('early_gross', 'early_fees', 'early_net')}
        for field, sourcefield in (('early_gross', 'gross'), ('early_fees', 'fees'), ('early_net', 'net')):
            row[field] = sum(p[sourcefield] for p in selected)
        if any(before[k] != row[k] for k in before):
            removed = [p for p in account['parents'] if p['id'] >= 20000 and p['id'] not in candidates]
            changes.append(dict(session=scene, symbol=symbol, method=method, before=before,
                                after={k: row[k] for k in before}, excluded_regular_parents=removed))
        if basekey is None:
            assert before == {k: row[k] for k in before}, '単独口座の数値が変わった'
    groups = defaultdict(list)
    for row in corrected['coverage']:
        for scope in (row['scope'], '全47場'):
            groups[(scope, row['symbol'], row['method'], row['kind'])].append(row)
    summary = []
    for (scope, symbol, method, kind), selected in groups.items():
        values = [r['first_minutes_after_start'] for r in selected if r['first_minutes_after_start'] is not None]
        summary.append(dict(scope=scope, symbol=symbol, method=method, kind=kind, sessions=len(selected),
                            participating_sessions=len(values), early_parents=sum(r['early_parents'] for r in selected),
                            first_minutes_min=float(np.min(values)) if values else None,
                            first_minutes_median=float(np.median(values)) if values else None,
                            first_minutes_max=float(np.max(values)) if values else None,
                            early_gross=sum(r['early_gross'] for r in selected), early_fees=sum(r['early_fees'] for r in selected),
                            early_net=sum(r['early_net'] for r in selected), total_net=sum(r['total_net'] for r in selected)))
    corrected['summary'] = summary
    assert corrected['exit_summary'] == old['exit_summary'] and corrected['worst_sessions'] == old['worst_sessions']
    corrected['correction'] = dict(reason='親IDが20000以上という分類は通常補完親1010000等も含む。元の単独早期親と見送り候補のID集合へ変更。',
                                   changed_accounts=len(changes), changes=changes,
                                   unchanged='売買・全口座収支・参入時刻・単独全16条件の寄与・E01/E15の出口内訳と最悪3場は不変。',
                                   original_sha256=digest(oldpath), source_sha256=digest(HERE / 'early_results/結果.json'),
                                   script_sha256=digest(HERE / 'correct_early_diagnosis139_v2.py'))
    with (HERE / 'early_diagnosis139_v2.json').open('x', encoding='utf-8') as handle:
        json.dump(corrected, handle, ensure_ascii=False, indent=2, allow_nan=False)
    lines = ['# 早期参加の診断・分類訂正版', '',
             '通常補完親を早期寄与へ誤って含めた併用口座の集計を訂正。元候補IDの集合で早期担当を特定した。売買再生は0回。', '',
             f"訂正は {len(changes)} 口座の担当別寄与だけ。全体収支、参入時刻、単独 E01/E15 の損益・損失原因・最悪3場の詳細は変わらない。", '',
             '以下の収支は各口座の「早期担当分」。通常担当分を含む口座全体の収支とは区別する。', '',
             '|手法|銘柄|時間帯|早期参入場/全場|初回中央値（開始後分）|早期費用前|早期費用|早期収支|口座全体収支|',
             '|---|---|---|---:|---:|---:|---:|---:|---:|']
    wanted = {'E01', 'E15', 'B5_E01', 'B5_E15', 'C04_E01', 'C04_E15'}
    for row in summary:
        if row['scope'] == '全47場' and row['method'] in wanted:
            median = f"{row['first_minutes_median']:.1f}" if row['first_minutes_median'] is not None else 'なし'
            lines.append(f"|{row['method']}|{row['symbol']}|{row['kind']}|{row['participating_sessions']}/{row['sessions']}|{median}|{row['early_gross']:,.0f}|{row['early_fees']:,.0f}|{row['early_net']:,.0f}|{row['total_net']:,.0f}|")
    lines += ['', '単独 E01/E15 の最悪3場の詳細は、内容不変で以下に再掲する。']
    oldmd = (HERE / 'early_diagnosis139.md').read_text(encoding='utf-8')
    details = oldmd[oldmd.index('\n## '):]
    lines.append(details)
    with (HERE / 'early_diagnosis139_v2.md').open('x', encoding='utf-8') as handle:
        handle.write('\n'.join(lines) + '\n')
    print(json.dumps(dict(status='合格', changed_accounts=len(changes), financial_replays=0,
                          affected_symbols=sorted({r['symbol'] for r in changes}),
                          affected_sessions=sorted({r['session'] for r in changes})), ensure_ascii=False))


if __name__ == '__main__':
    main()
