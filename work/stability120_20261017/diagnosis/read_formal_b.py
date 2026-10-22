"""120bだけを正式結果として一読保全し、小会計と最大六cacheの計画を保存する。"""

import hashlib
import json
from pathlib import Path
import statistics


HERE = Path(__file__).resolve().parent / 'formal_b'
ROOT = HERE.parents[3]
EXPECTED = 'c99743d739c9d24a08088f1b5ebdc78af8285b19e9704773965ea05f13890ce1'
METHODS = [tag+'_S2_T1' for tag in ('HEDGE','NET','FLIP','RECYCLE','HARD','ONCE','ALLSIDE')]


def save(path: Path, value: dict) -> None:
    """
    機能: 新しい診断所有域へ標準JSONだけを保存する。
    引数: path(Path)、value(dict)は新規保存先と診断。
    返り値: None。既存診断・金融結果・経済源を上書きしない。
    """
    assert not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')


def main() -> None:
    """
    機能: 指定結果を解析前に保全し、全3840行の集計と基準赤字六場を決める。
    引数: なし。
    返り値: None。NPZ・元prepared・市場・金融実行へ接続しない。
    """
    HERE.mkdir(parents=True, exist_ok=True)
    source=ROOT/'work/stability120_20261017/recovery_b/measurement/段階トレーリングと利益玉部分返済の全四十場.json'
    previous=HERE.parent/'完成後の全四十八小会計と基準赤字六場を読む計画.json'
    save(HERE/'正式b完成結果へ切り替える追加読取計画.json',dict(全合格=True,
        先行計画SHA256=hashlib.sha256(previous.read_bytes()).hexdigest(),結果path=source.relative_to(ROOT).as_posix(),結果SHA256=EXPECTED,
        原本読取=1,解析前同bytes保全=True,停止120='会計不一致停止。有効性へ含めない。',未実行120a='登録のみ金融0。',正式='120bのみ3840口座',
        詳細選択='HEDGE_S2_T1各商品net赤字上位最大3場、net同値はsession順。最大6NPZ。比較NET/FLIP/RECYCLE/HARD/ONCE/ALLSIDE。',
        中値Lastの観点='新規判断の直前採用quoteと判断quoteで、中値は発注方向へ動く一方Last不変又は逆行だった群を分離。中値発火から実約定までの方向変化・新規半spread・往復料も記述。',
        追加図='基準六場のうち純損失が最大の一場。保存curveの実現net/全玉清算時価/長短枚数を描き、約1分標本であることを表示。',
        原市場読取=0,金融再生=0))
    raw=source.read_bytes()
    assert hashlib.sha256(raw).hexdigest()==EXPECTED
    copy=HERE/'正式b結果の同bytes保全.json'
    assert not copy.exists()
    copy.write_bytes(raw)
    result=json.loads(raw)
    assert len(result['runs'])==3840 and len(result['specs'])==48 and len(result['sessions'])==40
    assert len({x['id'] for x in result['specs']})==48
    assert all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==s for p,s in result['source_SHA256'].items())
    summary=[];both=[];strict=[]
    for spec in result['specs']:
        profile={}
        for symbol in ('TOPIX','NK225'):
            rows=[x for x in result['runs'] if x['symbol']==symbol and x['method']==spec['id']]
            assert len(rows)==40 and len({x['session'] for x in rows})==40
            net=sum(x['net'] for x in rows)
            positive=sorted((x['net'] for x in rows if x['net']>0),reverse=True)
            profile[symbol]=dict(net=net,profit=sum(x['profit'] for x in rows),loss=sum(x['loss'] for x in rows),
                fees=sum(x['fees'] for x in rows),median=statistics.median(x['net'] for x in rows),
                trim3_net=net-sum(positive[:3]),black=sum(x['net']>0 for x in rows),red=sum(x['net']<0 for x in rows),
                no_trade=sum(x['entries']==0 for x in rows),active_zero=sum(x['entries']>0 and x['net']==0 for x in rows),
                active=sum(x['entries']>0 for x in rows),worst=min(x['net'] for x in rows),
                mean_black=statistics.mean(positive) if positive else None,
                unclosed=sum(x['unclosed'] for x in rows),closed_lots=sum(x['closed_lots'] for x in rows),
                max_long=max(x['max_long'] for x in rows),max_short=max(x['max_short'] for x in rows),
                max_drawdown=max(x['max_drawdown'] for x in rows),forced_loss=sum(x['forced_loss'] for x in rows),
                forced_profit=sum(x['forced_profit'] for x in rows),trail_net=sum(x['trail_net'] for x in rows))
            assert profile[symbol]['profit']-profile[symbol]['loss']==net
        passed=all(x['net']>0 and x['unclosed']==0 for x in profile.values())
        stronger=passed and all(x['median']>0 and x['trim3_net']>0 for x in profile.values())
        if passed:both.append(spec['id'])
        if stronger:strict.append(spec['id'])
        summary.append(dict(method=spec['id'],profile=profile,both_net_positive_and_flat=passed,
                            both_median_and_trim3_positive_also=stronger))
    baseline=[x for x in result['runs'] if x['method']==METHODS[0]]
    selected=[]
    for symbol in ('TOPIX','NK225'):
        selected.extend(sorted((x for x in baseline if x['symbol']==symbol and x['net']<0),key=lambda x:(x['net'],x['session']))[:3])
    cache={(x['symbol'],x['session']):x for x in result['cache']}
    assert len(cache)==80
    specs={x['id']:i for i,x in enumerate(result['specs'])}
    wanted=[dict(cache[x['symbol'],x['session']],baseline=x,policy_indices={m:specs[m] for m in METHODS}) for x in selected]
    assert len(wanted)<=6
    save(HERE/'正式b基準赤字六場の保存NPZを各一読する計画.json',dict(全合格=True,結果SHA256=EXPECTED,inputs=wanted,
        各cache読取=1,解析前同bytes保全=True,原prepared読取=0,原市場読取=0,金融再生=0,
        注意='NPZ第0列のpolicyidxを除いて列名へ対応。政策間UIDは照合せず、共通実入口だけを別キーで照合。'))
    save(HERE/'全四十八小会計の独立集計と詳細六場.json',dict(全合格=True,結果SHA256=EXPECTED,
        source_SHA256=result['source_SHA256'],summary=summary,両商品合計正かつ未清算なし=both,
        さらに両中央値と上位三場除外も正=strict,selected=selected,
        columns={k:result[k] for k in ('order_columns','lot_columns','curve_columns')},
        原結果読取=1,NPZ読取=0,原市場読取=0,金融再生=0))
    print(json.dumps({'全合格':True,'両net正':both,'詳細場':[(x['symbol'],x['session'],x['net']) for x in selected],
        'HEDGE_S2_T1':next(x for x in summary if x['method']==METHODS[0])},ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
