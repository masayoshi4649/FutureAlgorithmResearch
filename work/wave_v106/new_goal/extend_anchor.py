"""数量四条件に続き、初回受理利確四条件を保存候補へ追加する。"""

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

import reaggregate


def read(path: Path) -> dict:
    """
    機能: 完成した集計又は新金融の小JSONを一回で読む。
    引数: path(Path)は保存元。
    返り値: dictは内容。金融・原入力・巨大台帳は読まない。
    """
    return json.loads(path.read_text(encoding='utf-8-sig'))


def main() -> None:
    """
    機能: 初回受理目標四政策を最新三基準に集計し、既361主評価IDへ追加する。
    引数: なし。完成した新金融と二つの過去集計だけを使う。
    返り値: None。365主評価の合格一覧と、新四条件の具体的指標を保存する。
    """
    path=reaggregate.ROOT/'work/wave_v106/e01_size_goal_anchor/finance/結果.json'
    old_path=reaggregate.HERE/'保存全候補の65比率と赤字頻度及び平均黒字補填力.json'
    previous_path=reaggregate.HERE/'数量四条件追加後の65基準と全候補判定.json'
    new,old,previous=(read(p) for p in (path,old_path,previous_path))
    assert new['全合格'] and new['counts']['新政策会計']==264 and new['source開始終端一致']
    assert old['全合格'] and previous['全合格'] and previous['summary']['eligible_ids']==361
    configurations={c['id']:c for c in new['configs']};cases={}
    combined=dict(old['cases'],**previous['新候補'])
    for identifier,account in new['results'].items():
        assert identifier not in combined
        rows=sorted((reaggregate.normalize(r) for r in account['rows']),key=lambda r:(r['symbol'],r['session']))
        value=dict(id=identifier,config=configurations[identifier],rows=rows,
            sources=[path.relative_to(reaggregate.ROOT).as_posix()],ideal_reference=False,saved_alias=False,derived=False,
            monetary_row_hash=hashlib.sha256(json.dumps(rows,sort_keys=True,ensure_ascii=False,allow_nan=False).encode('utf-8')).hexdigest())
        value['symbols']={s:reaggregate.measure([r for r in rows if r['symbol']==s]) for s in ('TOPIX','NK225')}
        for field,test in (
            ('both_full_pass',lambda r:r['full']['pass_all']),('both_robust_pass',lambda r:r['robust_pass']),
            ('both_active_pass',lambda r:r['full']['pass_active']),('both_robust_active_pass',lambda r:r['robust_active_pass'])):
            value[field]=all(test(r) for r in value['symbols'].values())
        value['actual_leg_reference']=account['actual_leg_symbols'];cases[identifier]=value
    combined.update(cases)
    # ----------------------------------------
    # 保存済み旧357と数量4の指標は再計算せず、達否一覧だけを更新する。
    summary=dict(previous['summary'])
    for field in ('display_cases','distinct_ids','eligible_ids'):
        summary[field]+=4
    for field in ('both_full_pass','both_robust_pass','both_active_pass','both_robust_active_pass'):
        summary[field]=[i for i,c in combined.items() if not c['ideal_reference'] and c[field]]
    summary['per_symbol']={s:{
        'full_pass':[i for i,c in combined.items() if not c['ideal_reference'] and c['symbols'][s]['full']['pass_all']],
        'robust_pass':[i for i,c in combined.items() if not c['ideal_reference'] and c['symbols'][s]['robust_pass']],
        'active_pass':[i for i,c in combined.items() if not c['ideal_reference'] and c['symbols'][s]['full']['pass_active']],
    } for s in ('TOPIX','NK225')}
    output=reaggregate.HERE/'初回受理目標四条件追加後の65基準と全候補判定.json'
    assert not output.exists()
    result=dict(全合格=True,作成日時=datetime.now(timezone(timedelta(hours=9))).isoformat(),summary=summary,新候補=cases,
        過去資料=[dict(path=p.relative_to(reaggregate.ROOT).as_posix(),sha256=reaggregate.fingerprint(p)) for p in (old_path,previous_path)],
        新金融元=dict(path=path.relative_to(reaggregate.ROOT).as_posix(),sha256=reaggregate.fingerprint(path)),
        集計sourceSHA256=reaggregate.fingerprint(Path(__file__)),旧同値群='旧357再集計の同値群はその範囲の保存値。新8条件の独立標本数ではない。',
        新金融再生=0,原入力読込=0,NPZ読込=0,API取得=0)
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    print('現在の主評価ID',summary['eligible_ids'],'両商品合格',len(summary['both_full_pass']))
    for identifier,case in cases.items():
        for symbol,measured in case['symbols'].items():
            v=measured['full']
            print(identifier,symbol,'net',v['net'],'share',v['profit_share'],'black/red/none',v['green'],v['red'],v['no_trade'],
                '平均黒字',v['mean_green'],'最大赤字',v['worst_red'],'達否',v['tests'],'top3後',measured['without_top3']['net'])


if __name__=='__main__':
    main()
