"""既知となった初回結果を、次の仮説用に系統別診断する。採用の再選択ではない。"""

import json
import plan119 as plan
from root_summary119 import aggregate


def main() -> None:
    """
    機能: 既所有結果の系統別分布と両商品共通条件を診断し、後出し評価と明示する。
    引数: なし。根が既に所有した完成結果だけを再利用する。
    返り値: None。金融再生・元市場の読取・採用条件の変更はしない。
    """
    result = plan.read(plan.HERE / 'root_review/完成結果の同bytes参照.json')
    grouped = {(s, m['id']): [] for s in ('TOPIX', 'NK225') for m in result['specs']}
    for row in result['runs']:
        grouped[row['symbol'], row['method']].append(row)
    data = {key: aggregate(rows) for key, rows in grouped.items()}
    common = []
    for spec in result['specs']:
        top, nk = data['TOPIX', spec['id']], data['NK225', spec['id']]
        if top['収支'] > 0 and nk['収支'] > 0:
            common.append(dict(id=spec['id'], family=spec['family'],
                **{s: {period: aggregate([r for r in grouped[s, spec['id']] if r['session'] in result['splits'][period]])
                    for period in ('全40', '確認13', '追加確認3')} for s in ('TOPIX', 'NK225')}))
    common.sort(key=lambda r: (min(r[s]['全40']['黒字'] for s in ('TOPIX','NK225')),
        min(r[s]['全40']['中央値'] for s in ('TOPIX','NK225'))), reverse=True)
    defaults = {s: {spec['family']: {period: aggregate([r for r in grouped[s,spec['id']] if r['session'] in scenes])
        for period, scenes in result['splits'].items()} for spec in result['specs'] if spec.get('scale') == 20
        and spec['exit_mode'] == 0 and spec['entry_mode'] == 0 and spec['guard'] == 1} for s in ('TOPIX','NK225')}
    plan.write(plan.HERE / 'root_review/系統別と両商品条件の事後診断.json', dict(
        留保='次の仮説のための既知40場診断。正式採用候補を入れ替えず、未知での成功と呼ばない。',
        共通条件=common, 既定六系統=defaults, 新金融=0))
    print(json.dumps(dict(共通黒字条件数=len(common),
        上位五=[dict(id=r['id'], **{s:{p: {k:v for k,v in r[s][p].items() if k in ('場数','黒字','赤字','無取引','収支','中央値','最悪','上位三黒字除外')}
            for p in ('全40','確認13','追加確認3')} for s in ('TOPIX','NK225')}) for r in common[:5]],
        六系統全40={s:{f: {k:v for k,v in periods['全40'].items() if k in ('黒字','赤字','無取引','収支','中央値')} for f,periods in fs.items()} for s,fs in defaults.items()}), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
