"""指定c結果を一読保全し、四管理の小会計とCOST二場の診断計画を作る。"""

import hashlib
import json
from pathlib import Path
import statistics


HERE=Path(__file__).resolve().parent/'formal_c'
ROOT=HERE.parents[3]
EXPECTED='1071dc7f296d8ffbf3483e26b863d79cde48b82bcca986a7b5810c8e18f9ee9f'
METHODS=[x+'_S2_T1' for x in ('CREDIT','ONE','LIMIT','COST')]


def save(path: Path,value: dict) -> None:
    """
    機能: c診断の所有域へ新しい証跡を保存する。
    引数: path(Path)、value(dict)は保存先と標準型の内容。
    返り値: None。既存の金融・診断源を上書きしない。
    """
    assert not path.exists();path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')


def main() -> None:
    """
    機能: 根指定の完成SHAを検証し、解析前保全後に1920小会計だけを集計する。
    引数: なし。
    返り値: None。NPZと市場を読む前に最大二cacheの計画を残す。
    """
    HERE.mkdir(parents=True,exist_ok=True)
    path=ROOT/'work/stability120_20261017/recovery_c/measurement/利益条件付き段階追加と全四十場.json'
    save(HERE/'正式cの一読保全と最悪二場の診断を読む計画.json',dict(全合格=True,
        結果path=path.relative_to(ROOT).as_posix(),結果SHA256=EXPECTED,結果原本読取=1,解析前同bytes保全=True,
        対象='全24条件の小会計、共通S2_T1四管理と保存b基準。COST_S2_T1の各商品最悪赤字一場。',
        cache読取上限=2,cache選択='net<0をnet昇順、同額はsession昇順。商品ごと最大1場。各cacheに含む四管理を同じ読取で射影。',
        b='既所有完成コピーと診断小会計。既所有六NPZに同場があれば再利用、なければb新cacheは追加しない。',
        詳細='最大損失玉、連続停止と再参加、追加予約当時の同方向清算純益と予約済一枚リスク、次気配値飛び、追尾未発動損失、Lastと中値を分離。',
        原市場読取=0,金融再生=0,d結果読取=0))
    raw=path.read_bytes();assert hashlib.sha256(raw).hexdigest()==EXPECTED
    copy=HERE/'正式c結果の同bytes保全.json';assert not copy.exists();copy.write_bytes(raw)
    r=json.loads(raw)
    assert len(r['specs'])==24 and len(r['runs'])==1920 and len(r['sessions'])==40
    assert all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==sha for p,sha in r['source_SHA256'].items())
    bpath=HERE.parent/'formal_b/全四十八小会計の独立集計と詳細六場.json'
    b=json.loads(bpath.read_text(encoding='utf8'))
    baseline=next(x for x in b['summary'] if x['method']=='HEDGE_S2_T1')
    out=[]
    for spec in r['specs']:
        profiles={}
        for symbol in ('TOPIX','NK225'):
            rows=[x for x in r['runs'] if x['symbol']==symbol and x['method']==spec['id']]
            assert len(rows)==40 and len({x['session'] for x in rows})==40
            positive=sorted((x['net'] for x in rows if x['net']>0),reverse=True)
            net=sum(x['net'] for x in rows)
            p=dict(net=net,profit=sum(x['profit'] for x in rows),loss=sum(x['loss'] for x in rows),fees=sum(x['fees'] for x in rows),
                median=statistics.median(x['net'] for x in rows),trim3_net=net-sum(positive[:3]),
                black=sum(x['net']>0 for x in rows),red=sum(x['net']<0 for x in rows),no_trade=sum(x['entries']==0 for x in rows),
                unclosed=sum(x['unclosed'] for x in rows),entries=sum(x['entries'] for x in rows),closed_lots=sum(x['closed_lots'] for x in rows),
                max_long=max(x['max_long'] for x in rows),max_short=max(x['max_short'] for x in rows),
                max_drawdown=max(x['max_drawdown'] for x in rows),worst=min(x['net'] for x in rows),
                forced_loss=sum(x['forced_loss'] for x in rows),trail_net=sum(x['trail_net'] for x in rows))
            assert p['profit']-p['loss']==net
            profiles[symbol]=p
        out.append(dict(method=spec['id'],profile=profiles,both_net_positive_and_flat=all(p['net']>0 and p['unclosed']==0 for p in profiles.values())))
    wanted=[];cache={(x['symbol'],x['session']):x for x in r['cache']};indexes={x['id']:i for i,x in enumerate(r['specs'])}
    assert len(cache)==80
    for symbol in ('TOPIX','NK225'):
        candidates=sorted((x for x in r['runs'] if x['symbol']==symbol and x['method']=='COST_S2_T1' and x['net']<0),key=lambda x:(x['net'],x['session']))
        if candidates:
            scene=candidates[0]
            wanted.append(dict(cache[symbol,scene['session']],selected_row=scene,policy_indices={m:indexes[m] for m in METHODS}))
    save(HERE/'正式cのCOST最悪二場を各一読する目録.json',dict(全合格=True,inputs=wanted,各cache読取=1,解析前同bytes保全=True,原prepared読取=0,原市場読取=0,金融再生=0))
    save(HERE/'全二十四小会計と保存b基準の比較.json',dict(全合格=True,結果SHA256=EXPECTED,source_SHA256=r['source_SHA256'],
        summary=out,baseline_b=baseline,baseline_b_summary_SHA256=hashlib.sha256(bpath.read_bytes()).hexdigest(),
        selected=[x['selected_row'] for x in wanted],columns={k:r[k] for k in ('order_columns','lot_columns','curve_columns')},
        両商品net正=[x['method'] for x in out if x['both_net_positive_and_flat']],元結果原本読取=1,NPZ読取=0,金融再生=0))
    print(json.dumps({'全合格':True,'両net正':[x['method'] for x in out if x['both_net_positive_and_flat']],
        '四管理':[x for x in out if x['method'] in METHODS],
        'COST最悪':[(x['symbol'],x['session'],x['selected_row']['net']) for x in wanted]},ensure_ascii=False))


if __name__=='__main__':main()
