"""dの指定同bytes所有結果を一読し、Last基準の最終対照を保存cへ対応させる。"""

import hashlib
import json
from pathlib import Path
import statistics


HERE=Path(__file__).resolve().parent/'formal_d'
ROOT=HERE.parents[3]
EXPECTED='665cc66e7f5f1788393082a80b2f8dc19468f9b5987f49025f4c813468166c59'


def save(path: Path,value: dict) -> None:
    """
    機能: d限定診断を新規JSONへ保存する。
    引数: path(Path)、value(dict)は出力先と標準型の内容。
    返り値: None。共有経済源や既存成果を書き換えない。
    """
    assert not path.exists();path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')


def main() -> None:
    """
    機能: 指定SHAのd結果を一読保全して24条件を再集計し、各商品COST最悪一場を固定する。
    引数: なし。
    返り値: None。市場・金融・元cacheを読まない。
    """
    HERE.mkdir(parents=True,exist_ok=True)
    source=ROOT/'work/stability120_20261017/audit_result120d/owned/完成結果.json'
    original='work/stability120_20261017/recovery_d/measurement/約定値基準の利益条件付き段階追加と全四十場.json'
    save(HERE/'Last基準最終dの一読と最大二場の読取計画.json',dict(全合格=True,根指定結果=original,同bytes所有読取=source.relative_to(ROOT).as_posix(),
        結果SHA256=EXPECTED,所有結果読取=1,元結果原本追加読取=0,解析前同bytes保全=True,
        対象='全24小会計を_LAST除去で同じc条件へ対応。COST_LAST_S2_T1の各商品net最悪赤字一場ずつ。',
        cache='audit119の同bytes所有copyだけを最大2個各一読。元measurement/元prepared/原市場は0。',
        診断='初回/追加、方向別損失停止の回数とnet、最大損失玉と追加例、追尾起動前損失。観測Lastは完全約定テープと呼ばない。',金融再生=0))
    raw=source.read_bytes();assert hashlib.sha256(raw).hexdigest()==EXPECTED
    copy=HERE/'正式d結果の同bytes保全.json';assert not copy.exists();copy.write_bytes(raw)
    r=json.loads(raw);assert len(r['specs'])==24 and len(r['runs'])==1920
    assert all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==s for p,s in r['source_SHA256'].items())
    cpath=HERE.parent/'formal_c/全二十四小会計と保存b基準の比較.json';c=json.loads(cpath.read_text(encoding='utf8'))
    old={x['method']:x for x in c['summary']};summary=[]
    for spec in r['specs']:
        reference=old[spec['id'].replace('_LAST','')];profile={}
        for symbol in ('TOPIX','NK225'):
            rows=[x for x in r['runs'] if x['method']==spec['id'] and x['symbol']==symbol]
            assert len(rows)==40 and len({x['session'] for x in rows})==40
            net=sum(x['net'] for x in rows);pos=sorted((x['net'] for x in rows if x['net']>0),reverse=True)
            p=dict(net=net,profit=sum(x['profit'] for x in rows),loss=sum(x['loss'] for x in rows),fees=sum(x['fees'] for x in rows),
                median=statistics.median(x['net'] for x in rows),trim3_net=net-sum(pos[:3]),black=sum(x['net']>0 for x in rows),
                red=sum(x['net']<0 for x in rows),no_trade=sum(x['entries']==0 for x in rows),unclosed=sum(x['unclosed'] for x in rows),
                entries=sum(x['entries'] for x in rows),max_long=max(x['max_long'] for x in rows),max_short=max(x['max_short'] for x in rows),
                max_drawdown=max(x['max_drawdown'] for x in rows),worst=min(x['net'] for x in rows),forced_loss=sum(x['forced_loss'] for x in rows),
                trail_net=sum(x['trail_net'] for x in rows),change_from_c=net-reference['profile'][symbol]['net'])
            assert p['profit']-p['loss']==net;profile[symbol]=p
        summary.append(dict(method=spec['id'],reference_c=reference['method'],profile=profile,
            both_net_positive_and_flat=all(p['net']>0 and p['unclosed']==0 for p in profile.values())))
    indexes={x['id']:i for i,x in enumerate(r['specs'])};meta={(x['symbol'],x['session']):x for x in r['cache']};selected=[]
    for symbol in ('TOPIX','NK225'):
        rows=sorted((x for x in r['runs'] if x['symbol']==symbol and x['method']=='COST_LAST_S2_T1' and x['net']<0),key=lambda x:(x['net'],x['session']))
        if rows:
            row=rows[0];item=meta[symbol,row['session']]
            selected.append(dict(item,selected_row=row,policy_index=indexes[row['method']],
                owned_path=f"work/stability120_20261017/audit_result120d/owned/{symbol}/{row['session']}.npz"))
    save(HERE/'COST_LAST最悪二場の監査所有copyを各一読する目録.json',dict(全合格=True,inputs=selected,各所有cache読取=1,
        元cache追加読取=0,原市場読取=0,金融再生=0,解析前同bytes保全=True))
    output=dict(全合格=True,結果SHA256=EXPECTED,source_SHA256=r['source_SHA256'],summary=summary,
        比較元c集計SHA256=hashlib.sha256(cpath.read_bytes()).hexdigest(),両商品net正=[x['method'] for x in summary if x['both_net_positive_and_flat']],
        selected=[x['selected_row'] for x in selected],columns={k:r[k] for k in ('order_columns','lot_columns','curve_columns')},
        監査所有結果読取=1,元結果原本追加読取=0,NPZ読取=0,金融再生=0)
    save(HERE/'Last基準二十四小会計と中値c同条件の比較.json',output)
    print(json.dumps({'全合格':True,'両net正':output['両商品net正'],'S2_T1':[x for x in summary if x['method'].endswith('_S2_T1')],
        '最悪':[(x['symbol'],x['session'],x['selected_row']['net']) for x in selected]},ensure_ascii=False))


if __name__=='__main__':main()
