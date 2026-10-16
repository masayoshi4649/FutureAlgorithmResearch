"""全24保存実親の5寄与と、注目P1L8の全赤字場を具体的に診断する。"""

from collections import Counter
import hashlib
from pathlib import Path
import time

import numpy as np

import tools

PRIMARY='E01_TRADE_W60_VETO_D0_P1L8'
FIVE=('収支変化','避けた基準損失','失った基準利益','共通入口の出口変化','新たな入口の収支')


def checked(item: dict) -> dict:
    """
    機能: 台帳又は新入力cacheを同一bytes一読して固定指紋を確認する。
    引数: item(dict)はpath/SHA256。
    返り値: dictは保存値。元原NPZ・paper・金融の再生を呼ばない。
    """
    value,sha=tools.read(tools.ROOT/item['path']);assert sha==item['SHA256'],item['path']
    return value


def expand(value: object, count: int) -> np.ndarray:
    """
    機能: 保存曲線のplateau圧縮だけをnormal全行へ復元する。
    引数: value(object)はndarray又はrows/values/length辞書、count(int)は行数。
    返り値: ndarrayは保存時価。新しい売買判断や価格の補完はしない。
    """
    if isinstance(value,np.ndarray):assert len(value)==count;return value
    assert value['length']==count and value['rows'][0]==0
    indices=np.searchsorted(value['rows'],np.arange(count),side='right')-1
    return value['values'][indices]


def vote_group(value: dict) -> str:
    """
    機能: 判定当時の代理票を事前の閾値区分へ分ける。
    引数: value(dict)は保存votes.measure。
    返り値: strは未知/2票未満/強同向/強逆向/中間。事後の勝敗を分類へ使わない。
    """
    if not value['known']:return '未知'
    if value['direction_votes']<2:return '既知2票未満'
    if value['balance']>=.25:return '既知2票以上・強同向'
    if value['balance']<=-.25:return '既知2票以上・強逆向'
    return '既知2票以上・中間'


def explain(ledger: dict, account: dict, cid: int, cfg: dict, extrema: bool=True) -> dict:
    """
    機能: 実親の公開・約定・部分返済・当時票と呼値/ATR尺度を記録する。
    引数: ledger/account/cfg(dict)、cid(int)、extrema(bool)は実親と事後時価を測るか。
    返り値: dictは実測。予定Last/ATRを実約定価格や真の受信秒と混同しない。
    """
    p=tools.parents(ledger)[cid];orders=ledger['orders'];selected=np.flatnonzero(orders[:,2]==cid)
    new=selected[orders[selected,7]==1];assert len(new)==1,'GUの単一新規UID契約'
    first=orders[new[0]];row=int(first[0]);publish=int(first[1]);side=int(first[3]);tick=float(account['record']['tick'])
    paper=account['feed'][(account['feed'][:,2]==cid)&(account['feed'][:,7]==1)]
    assert len(paper)==1 and int(paper[0,0])==publish and int(paper[0,3])==side
    vote=account['trade_features'][str(cfg['window_seconds'])][publish];atr=float(paper[0,9])
    q=account['quotes'];fee_paid=sum(tools.fee(int(orders[i,4]),account['symbol']) for i in selected)
    unit=int(first[4])*tick*tools.VALUE[account['symbol']]
    result=dict(親=cid,方向='買い' if side>0 else '売り',実枚数=int(first[4]),収支=p['収支'],
        公開=tools.clock(account,publish),公開Last=float(paper[0,5]),公開bid=float(q['bid'][publish]),公開ask=float(q['ask'][publish]),
        新規=tools.clock(account,row),実新規価格=float(first[5]),
        最終返済=tools.clock(account,int(p['最終返済行'])),
        返済注文=[dict(判断=tools.clock(account,int(o[1])),実返済=tools.clock(account,int(o[0])),
            価格=float(o[5]),枚数=int(o[4]),理由=int(o[6])) for o in orders[selected] if o[7]==0],
        代理票=vote,当時判定区分=vote_group(vote),ATR価格幅=atr,ATR呼値=atr/tick,
        実往復料金=fee_paid,実料金呼値=fee_paid/unit,料金後収支呼値=p['収支']/unit,
        公開気配差呼値=float((q['ask'][publish]-q['bid'][publish])/tick),
        公開Lastから実新規まで不利呼値=side*(float(first[5])-float(paper[0,5]))/tick,
        P1目標呼値=1 if cfg['exit']=='P1L8' else None,P1損失予算呼値=8 if cfg['exit']=='P1L8' else None,
        損失予算ATR比=8*tick/atr if cfg['exit']=='P1L8' else None)
    if extrema:result['事後親清算経路']=tools.parent_path(ledger,account,cid)
    return result


def missing_reason(ledger: dict, account: dict, cid: int, cfg: dict, reference: dict) -> dict:
    """
    機能: 消えた基準実親の当時mask・場停止・実busyを保存証跡から区別する。
    引数: ledger/account/cfg/reference(dict)、cid(int)は変更台帳と基準親。
    返り値: dictは原因。許可されただけの候補を回避した実損失と呼ばない。
    """
    orders=reference['orders'];new=orders[(orders[:,2]==cid)&(orders[:,7]==1)];assert len(new)==1
    pub=int(new[0,1]);vote=account['trade_features'][str(cfg['window_seconds'])][pub]
    n=len(account['record']['price']);mask=expand(ledger['gate_accepted'],n)
    if not mask[pub]:return dict(原因='公開時の取引更新代理で拒否',判定=tools.clock(account,pub),代理票=vote)
    control=ledger.get('control',{})
    if control.get('発動') and pub>control['判断行']:
        return dict(原因='P1L8の場停止後',停止=control,公開=tools.clock(account,pub),代理票=vote)
    proof=ledger['limit_events'];rows=proof[(proof[:,2]==cid)&(proof[:,1]==1)]
    if len(rows):
        assert len(rows)==1
        code=int(rows[0,17]);cancelled=bool(rows[0,14])
        if cancelled:return dict(原因='実保有又は返済予約busy' if code==94 else '既知静観又は期限等による公開拒否',公開理由=code,代理票=vote)
        tail=proof[(proof[:,2]==cid)&np.isin(proof[:,1],[3,4])]
        if len(tail):return dict(原因='指値到達前に紙上返済又は既知timerで永久取消',取消証跡=tail.tolist(),代理票=vote)
    return dict(原因='実入口なし、追加原因を推測しない',代理票=vote)


def group_add(groups: dict, name: str, parent: dict) -> None:
    """
    機能: 同じ当時票区分に属する実親の勝ち反証と金額を全数集計する。
    引数: groups(dict)、name(str)、parent(dict)は観測区分と実親。
    返り値: None。n/Nは決済実親を分母にする。
    """
    v=groups.setdefault(name,dict(決済親=0,勝ち親=0,負け親=0,利益=0.,損失=0.,収支=0.))
    net=parent['収支'];v['決済親']+=1;v['勝ち親']+=int(net>0);v['負け親']+=int(net<0)
    v['利益']+=max(0.,net);v['損失']+=max(0.,-net);v['収支']+=net


def scene(before: dict, after: dict, account: dict, cfg: dict, diff: dict) -> dict:
    """
    機能: 最悪場の最大損失・避け損失・失った利益・新親を各2例保存する。
    引数: before/after/account/cfg/diff(dict)は同出口対照と保存観測。
    返り値: dictは具体原行・価格と5寄与。例の勝敗だけで有効性を断定しない。
    """
    a,b=tools.parents(before),tools.parents(after)
    losing=sorted((p for p in b.values() if p['収支']<0),key=lambda p:p['収支'])[:2]
    avoided=sorted((a[k] for k in diff['消えた親'] if a[k]['収支']<0),key=lambda p:p['収支'])[:2]
    sacrificed=sorted((a[k] for k in diff['消えた親'] if a[k]['収支']>0),key=lambda p:p['収支'],reverse=True)[:2]
    return dict(基準=before['summary'],変更=after['summary'],寄与5={k:diff[k] for k in FIVE},
        最大損失2親=[explain(after,account,int(p['親']),cfg) for p in losing],
        避けた損失2例=[dict(実親=explain(before,account,int(p['親']),cfg),原因=missing_reason(after,account,int(p['親']),cfg,before)) for p in avoided],
        失った勝ち2例=[dict(実親=explain(before,account,int(p['親']),cfg),原因=missing_reason(after,account,int(p['親']),cfg,before)) for p in sacrificed],
        新親=[explain(after,account,k,cfg) for k in diff['新しい親'][:2]])


def run() -> None:
    """
    機能: 目的固定後に保存24全数を一回読んで、寄与・具体赤字場・勝ち反証を保存する。
    引数: なし。
    返り値: None。金融/原NPZ/原book/APIなし。条件や源を変更しない。
    """
    root,sha=tools.read(tools.SOURCE/'finance/結果.json');assert root['全合格']
    fixed,_=tools.read(tools.SOURCE/'金融事前固定.json');meta,_=tools.read(tools.SOURCE/'全33場のE01取引更新準備.json')
    assert root['sessions']==meta['sessions'] and len(root['configs'])==24
    ledger_specs={c['id']:{z['session']+'|'+z['symbol']:z for z in root['results'][c['id']]['ledgers']} for c in root['configs']}
    base_specs={k:v['ledgers'] for k,v in fixed['基準'].items()}
    base_specs['D0_P1L8']={z['session']+'|'+z['symbol']:z for z in root['new_D0_P1L8']['ledgers']}
    worst={c['id']:{s:{r['session'] for r in sorted((r for r in root['results'][c['id']]['rows'] if r['symbol']==s and r['収支']<0),key=lambda r:r['収支'])[:3]} for s in ('TOPIX','NK225')} for c in root['configs']}
    output={c['id']:{s:dict(全33の5寄与={k:0. for k in FIVE},各場寄与={},最悪3場={},買売={},当時票区分={}) for s in ('TOPIX','NK225')} for c in root['configs']}
    focused={s:dict(赤字全場={},黒字反証全場={},全実親のATR呼値=[],全実親の料金呼値=[]) for s in ('TOPIX','NK225')}
    reads=Counter();started=time.monotonic()
    for session in root['sessions']:
        packet=checked(meta['cache'][session]);reads['新準備cache']+=1
        for symbol in ('TOPIX','NK225'):
            account=packet['accounts'][symbol];key=session+'|'+symbol
            bases={b:checked(spec[key]) for b,spec in base_specs.items()};reads['基準台帳']+=4
            for cfg in root['configs']:
                id=cfg['id'];ledger=checked(ledger_specs[id][key]);reads['新台帳']+=1
                before=bases[cfg['execution']+'_'+cfg['exit']];d=tools.contribution(before,ledger);target=output[id][symbol]
                target['各場寄与'][session]={k:d[k] for k in FIVE}
                for k in FIVE:target['全33の5寄与'][k]+=d[k]
                for cid,p in tools.parents(ledger).items():
                    obs=explain(ledger,account,cid,cfg,False)
                    group_add(target['買売'],obs['方向'],p);group_add(target['当時票区分'],obs['当時判定区分'],p)
                    if id==PRIMARY:
                        focused[symbol]['全実親のATR呼値'].append(obs['ATR呼値'])
                        focused[symbol]['全実親の料金呼値'].append(obs['実料金呼値'])
                if session in worst[id][symbol]:target['最悪3場'][session]=scene(before,ledger,account,cfg,d)
                if id==PRIMARY:
                    n=len(account['record']['price']);liq=expand(ledger['liquidation_yen'],n);control=ledger.get('control',{})
                    day=dict(収支=ledger['summary']['収支'],利益=ledger['summary']['利益'],損失=ledger['summary']['損失'],
                        実親数=ledger['summary']['親数'],実全場最大清算利益=float(liq.max()),
                        実最大利益時刻=tools.clock(account,int(np.argmax(liq))),停止=control,
                        影GU収支=ledger['shadow_GU_summary']['収支'],影GUを実利益と数えない=True,
                        寄与5={k:d[k] for k in FIVE})
                    negative=sorted((p for p in tools.parents(ledger).values() if p['収支']<0),key=lambda p:p['最終返済行'])
                    if ledger['summary']['収支']<0:
                        day['初負け親']=explain(ledger,account,int(negative[0]['親']),cfg) if negative else None
                        day['実親の時系列']=[explain(ledger,account,int(p['親']),cfg) for p in sorted(tools.parents(ledger).values(),key=lambda p:p['新規行'])]
                        day['最大損失場診断']=scene(before,ledger,account,cfg,d)
                        focused[symbol]['赤字全場'][session]=day
                    elif ledger['summary']['収支']>0:
                        day['実親の時系列']=[explain(ledger,account,int(p['親']),cfg,False) for p in sorted(tools.parents(ledger).values(),key=lambda p:p['新規行'])]
                        focused[symbol]['黒字反証全場'][session]=day
                del ledger
            del bases
        print(session+' 保存E01親診断完了、金融0',flush=True)
    assert reads==Counter(新準備cache=33,基準台帳=264,新台帳=1584)
    for id,case in output.items():
        for symbol,value in case.items():
            for k in FIVE:assert np.isclose(value['全33の5寄与'][k],root['diagnosis'][id][symbol][k],atol=1e-5,rtol=0.)
    for symbol,value in focused.items():
        for k in ('全実親のATR呼値','全実親の料金呼値'):
            values=value[k];value[k]=dict(親数=len(values),最小=min(values) if values else None,中央値=float(np.median(values)) if values else None,最大=max(values) if values else None)
        value['当時票区分の全親勝ち反証']=output[PRIMARY][symbol]['当時票区分']
    proof=dict(全合格=True,金融再生=0,原NPZ読取=0,原book=0,API=0,読取件数=dict(reads),results=output,
        重点条件=PRIMARY,重点条件の全赤字場と黒字反証=focused,
        source=dict(path='work/wave_v106/e01_trade_gate/finance/結果.json',sha256=sha),
        診断source_SHA256={p.relative_to(tools.ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in tools.HERE.glob('*.py')},
        限界=['親の利益ピークは実注文経路の事後観測であり、その値で約定する新出口の利益ではない。',
            'P1L8台帳の影GU注文・stateは実政策を止める対照。停止後の影GU利益を実利益へ混ぜない。',
            '票区分の勝ち反証は粗い同一判定区分で、全数値・その後経路が同一ではない。',
            '価格時計は板受信時計でない。8tick予算を実損失上限と呼ばず次正常BBOの超過を残す。'],経過秒=time.monotonic()-started)
    print(tools.write('全24の5寄与と赤字上位場及びW60成行P1L8の具体原因.json',proof),flush=True)


if __name__=='__main__':run()
