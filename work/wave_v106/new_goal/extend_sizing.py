"""保存済み旧再集計へ新数量四条件だけを追加する。再売買はしない。"""

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

import reaggregate


def main() -> None:
    """
    機能: 新四政策の全264会計を三基準へ集計し、旧357主評価IDへ追加する。
    引数: なし。完成金融小JSONと保存済み旧再集計だけを読む。
    返り値: None。最新版と新四候補の指標を保存し、金融・原入力を再生しない。
    """
    path = reaggregate.ROOT/'work/wave_v106/e01_risk_sizing/finance/結果.json'
    old_path = reaggregate.HERE/'保存全候補の65比率と赤字頻度及び平均黒字補填力.json'
    new = json.loads(path.read_text(encoding='utf-8-sig'))
    old = json.loads(old_path.read_text(encoding='utf-8-sig'))
    assert new['全合格'] and new['counts']['新政策会計'] == 264 and new['source開始終端一致']
    configs = {c['id']: c for c in new['configs']}
    cases = {}
    for ident, account in new['results'].items():
        assert ident not in old['cases']
        rows = sorted((reaggregate.normalize(r) for r in account['rows']), key=lambda r:(r['symbol'],r['session']))
        value = dict(id=ident, config=configs[ident], rows=rows, sources=[path.relative_to(reaggregate.ROOT).as_posix()],
                     ideal_reference=False, saved_alias=False, derived=False,
                     monetary_row_hash=hashlib.sha256(json.dumps(rows,sort_keys=True,ensure_ascii=False,allow_nan=False).encode('utf-8')).hexdigest())
        value['symbols'] = {s: reaggregate.measure([r for r in rows if r['symbol']==s]) for s in ('TOPIX','NK225')}
        for field, test in (('both_full_pass',lambda r:r['full']['pass_all']),
                            ('both_robust_pass',lambda r:r['robust_pass']),
                            ('both_active_pass',lambda r:r['full']['pass_active']),
                            ('both_robust_active_pass',lambda r:r['robust_active_pass'])):
            value[field] = all(test(r) for r in value['symbols'].values())
        value['actual_leg_reference'] = account['actual_leg_symbols']
        cases[ident] = value
    # ----------------------------------------
    # 過去の同じ集計を再計算せず、新規比較の達否だけ結合する。
    combined = dict(old['cases'], **cases)
    summary = dict(old['summary'])
    summary['display_cases'] += 4
    summary['distinct_ids'] += 4
    summary['eligible_ids'] += 4
    for field in ('both_full_pass','both_robust_pass','both_active_pass','both_robust_active_pass'):
        summary[field] = [i for i,c in combined.items() if not c['ideal_reference'] and c[field]]
    summary['per_symbol'] = {s: {
        'full_pass':[i for i,c in combined.items() if not c['ideal_reference'] and c['symbols'][s]['full']['pass_all']],
        'robust_pass':[i for i,c in combined.items() if not c['ideal_reference'] and c['symbols'][s]['robust_pass']],
        'active_pass':[i for i,c in combined.items() if not c['ideal_reference'] and c['symbols'][s]['full']['pass_active']],
    } for s in ('TOPIX','NK225')}
    output = reaggregate.HERE/'数量四条件追加後の65基準と全候補判定.json'
    assert not output.exists()
    result = dict(全合格=True,作成日時=datetime.now(timezone(timedelta(hours=9))).isoformat(),
        summary=summary,新候補=cases,
        過去再集計=dict(path=old_path.relative_to(reaggregate.ROOT).as_posix(),sha256=reaggregate.fingerprint(old_path)),
        新金融元=dict(path=path.relative_to(reaggregate.ROOT).as_posix(),sha256=reaggregate.fingerprint(path)),
        集計sourceSHA256=reaggregate.fingerprint(Path(__file__)),新金融再生=0,原入力読込=0,NPZ読込=0,API取得=0)
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    print('現在の主評価ID',summary['eligible_ids'],'両商品合格',len(summary['both_full_pass']))
    for i,c in cases.items():
        for s,r in c['symbols'].items():
            v=r['full'];print(i,s,'net',v['net'],'share',v['profit_share'],'red',v['red'],'none',v['no_trade'],
                             '平均黒字',v['mean_green'],'最大赤字',v['worst_red'],'達否',v['tests'])


if __name__ == '__main__':
    main()
