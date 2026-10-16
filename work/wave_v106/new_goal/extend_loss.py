"""初回枚数へ損失線も合わせた四条件を、既365主評価へ追加する。"""

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

import reaggregate
from extend_anchor import read


def main() -> None:
    """
    機能: 保存済み数量・利確比較へ比例損失四政策を追加し、最新三基準を計算する。
    引数: なし。新金融小結果と三つの保存集計だけを使用する。
    返り値: None。旧指標は再計算せず、全369主評価IDの合格一覧を保存する。
    """
    path=reaggregate.ROOT/'work/wave_v106/e01_size_loss_anchor/finance/結果.json'
    past=[reaggregate.HERE/name for name in (
        '保存全候補の65比率と赤字頻度及び平均黒字補填力.json',
        '数量四条件追加後の65基準と全候補判定.json',
        '初回受理目標四条件追加後の65基準と全候補判定.json')]
    new=read(path);previous=[read(p) for p in past]
    assert new['全合格'] and new['counts']['新政策会計']==264 and new['source開始終端一致']
    assert new['新GUengine']==0 and new['保存GU再利用']==132
    assert all(v['全合格'] for v in previous) and previous[-1]['summary']['eligible_ids']==365
    combined=dict(previous[0]['cases'])
    for v in previous[1:]:combined.update(v['新候補'])
    configurations={c['id']:c for c in new['configs']};cases={}
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
    # 同じ金融結果を再生せず、新たな停止条件の達否だけを結合する。
    summary=dict(previous[-1]['summary'])
    for field in ('display_cases','distinct_ids','eligible_ids'):summary[field]+=4
    for field in ('both_full_pass','both_robust_pass','both_active_pass','both_robust_active_pass'):
        summary[field]=[i for i,c in combined.items() if not c['ideal_reference'] and c[field]]
    summary['per_symbol']={s:{
        'full_pass':[i for i,c in combined.items() if not c['ideal_reference'] and c['symbols'][s]['full']['pass_all']],
        'robust_pass':[i for i,c in combined.items() if not c['ideal_reference'] and c['symbols'][s]['robust_pass']],
        'active_pass':[i for i,c in combined.items() if not c['ideal_reference'] and c['symbols'][s]['full']['pass_active']],
    } for s in ('TOPIX','NK225')}
    output=reaggregate.HERE/'初回受理損失四条件追加後の65基準と全候補判定.json'
    assert not output.exists()
    result=dict(全合格=True,作成日時=datetime.now(timezone(timedelta(hours=9))).isoformat(),summary=summary,新候補=cases,
        過去資料=[dict(path=p.relative_to(reaggregate.ROOT).as_posix(),sha256=reaggregate.fingerprint(p)) for p in past],
        新金融元=dict(path=path.relative_to(reaggregate.ROOT).as_posix(),sha256=reaggregate.fingerprint(path)),
        集計sourceSHA256=reaggregate.fingerprint(Path(__file__)),旧同値群='旧357範囲の保存値。新12条件の独立標本数ではない。',
        新金融再生=0,原入力読込=0,NPZ読込=0,API取得=0)
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    print('現在の主評価ID',summary['eligible_ids'],'両商品合格',len(summary['both_full_pass']))
    for identifier,case in cases.items():
        for symbol,m in case['symbols'].items():
            v=m['full'];print(identifier,symbol,'P/L/net',v['profit'],v['loss'],v['net'],
                'share',v['profit_share'],'black/red/none',v['green'],v['red'],v['no_trade'],
                '平均黒字',v['mean_green'],'最大赤字',v['worst_red'],'達否',v['tests'],'top3後',m['without_top3']['net'])


if __name__=='__main__':
    main()
