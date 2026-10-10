"""途中判断の最終資料を結合し、復元比較で初回減量が変わっていないか検算する。"""

from __future__ import annotations

from pathlib import Path

import mid_design as design

HERE, ROOT = design.HERE, design.ROOT


def run() -> dict:
    """機能: 全13結果・指紋・由来と、104口座群の同じ減量注文を照合する。

    引数: なし。返り値: 最終資料の独立整合証拠(dict)。新たな売買は行わない。
    """
    complete=design.read(HERE/'mid_complete.json');result=design.read(HERE/'mid_result.json')
    refs=dict(complete['参照資料SHA256'])
    refs.update(complete['出力SHA256'])
    refs.update(design.read(HERE/'mid_analysis_source_fixed.json')['SHA256'])
    refs.update(result['参照資料SHA256'])
    for name,sha in refs.items():assert design.digest(ROOT/name)==sha,name
    assert complete['全合格'] and result['全合格']
    specs={s['id']:s for s in design.catalog()}
    assert {r['id'] for r in result['条件別']}==set(specs) and len(result['条件別'])==13
    keys={(n,s) for n in design.rules()['全セッション'] for s in ('TOPIX','NK225')}
    assert len(result['全セッション'])==338
    assert {(r['id'],r['session'],r['symbol']) for r in result['全セッション']}=={(i,*k) for i in specs for k in keys}
    books={i:{(r['session'],r['symbol']):r for r in design.read(HERE/'mid_results/ledgers'/(i+'.json.gz'))} for i in specs}
    rows=[]
    for gate in (0.,1.5):
        for fraction in (25,50):
            ids=[design.identifier(gate,fraction,m) for m in design.MODES]
            for key in sorted(keys):
                orders=[[o for o in books[i][key]['orders'] if o[6]==30 and o[7]==0] for i in ids]
                assert orders[0]==orders[1]==orders[2],(gate,fraction,key,'初回減量の差')
                rows.append(dict(gate=gate,fraction=fraction,session=key[0],symbol=key[1],
                    減量約定数=len(orders[0]),全8列同値=True))
    assert len(rows)==104
    for p in (Path(__file__),HERE/'mid_result.json',HERE/'mid_complete.json',HERE/'mid_analysis_source_fixed.json'):
        refs[p.relative_to(ROOT).as_posix()]=design.digest(p)
    return dict(全合格=True,全条件数=13,全入力数=338,全指定波数=104,
        既知9と未試行4を区別=True,成果再利用条件数=7,既知互換再生条件数=2,
        復元方式間の初回減量照合数=104,全減量約定の時刻価格方向数量同値=True,減量照合=rows,
        全資料SHA一致=True,参照資料SHA256=refs,新Night使用=False,新売買再生=False)


if __name__=='__main__':
    value=run();design.save(HERE/'mid_result_check.json',value)
    print('途中判断13条件の資料と104口座群の初回減量が一致',flush=True)
