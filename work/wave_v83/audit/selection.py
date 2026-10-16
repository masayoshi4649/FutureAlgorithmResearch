"""前半だけの選定を、親組会計の独立順位で再現する。"""

from accounts import load
from context import *


def rank(packet: dict, criterion: str) -> tuple:
    """機能: 円額を合算せず、活動資格と悪い側の無次元成績で順位を作る。

    引数: packet(dict)、criterion(str)。返り値: 順位tuple。
    """
    accounts=packet['periods']['前16'];enough=True;shares=[];bad=[];eff=[]
    for symbol,scale in [('TOPIX',5000.),('NK225',2000.)]:
        a=accounts[symbol]
        enough=enough and a['cycles']>=20 and a['active_sessions']>=8
        p,l=a['cycle_profit'],a['cycle_loss']
        shares.append(p/(p+l) if p+l else -1.)
        bad.append(a['losing_sessions']/a['active_sessions'] if a['active_sessions'] else 1.)
        eff.append(a['net']/a['cycles']/scale if a['cycles'] else -1e100)
    s,b,e=min(shares),max(bad),min(eff)
    if criterion=='場の安定':return enough,-b,s,e
    if criterion=='親組効率':return enough,e,s,-b
    return enough,s,e,-b


def select(packets: list, criterion: str) -> dict:
    """機能: 同点時のID昇順も含め、一位だけを独立に選ぶ。

    引数: packets(list)、criterion(str)。返り値: 選ばれた保存結果(dict)。
    """
    ordered=sorted(packets,key=lambda p:p['config']['id'])
    best=ordered[0]
    for packet in ordered[1:]:
        if rank(packet,criterion)>rank(best,criterion):best=packet
    return best


def main() -> None:
    """機能: 凍結、全288前半、主3/家族12の選定と元台帳を照合する。

    引数: なし。返り値: なし(None)。後半を使った再選抜は行わない。
    """
    fixed=load(WORK/'results/事前固定.json');chosen=load(WORK/'前半選定.json')
    for name,h in fixed['code_SHA256'].items():assert digest(WORK/name)==h,name
    assert digest(WORK/'prepared/inputs.pkl')==fixed['input_SHA256']
    packets=[load(WORK/'train/results'/f'{c["id"]}.json') for c in fixed['catalog']]
    assert len(packets)==288 and len({p['config']['id'] for p in packets})==288
    for p in packets:
        assert p['run']['sessions']==fixed['前16'] and p['run']['delay']==0.
        assert p['run']['seed']==0 and p['run']['slip_ticks']==0
        assert {r['session'] for r in p['rows']}==set(fixed['前16'])
        assert len(p['rows'])==32
        for symbol in ['TOPIX','NK225']:assert p['periods']['後14'][symbol]['trades']==0
        assert digest(WORK/'train/results'/f'{p["config"]["id"]}.json')==chosen['元結果SHA256'][p['config']['id']]
    checks=[];ids=set()
    for c in chosen['primary']+chosen['families']:
        pool=packets if c in chosen['primary'] else [p for p in packets if p['config']['family']==c['family']]
        winner=select(pool,c['criterion'])
        assert winner['config']['id']==c['id'] and c['config']==winner['config']
        assert c['score']==list(rank(winner,c['criterion']))
        assert c['sufficient']==bool(rank(winner,c['criterion'])[0])
        assert c['common_positive']==(c['sufficient'] and all(a['net']>0 for a in winner['periods']['前16'].values()))
        ids.add(c['id']);checks.append(dict(観点=c['criterion'],家族=c['family'],ID=c['id']))
    assert chosen['selected']==sorted(ids) and len(ids)==chosen['selected_unique']
    originals=0;arrays=0
    for name in sorted(ids):
        f=WORK/'final/delay0/ledgers'/f'{name}.pkl'
        if not f.exists():continue
        final=load(f);train=load(WORK/'train/ledgers'/f'{name}.pkl')
        for key,a in train.items():
            b=final[key]
            for column in ['orders','trades','cycles','stats']:
                np.testing.assert_array_equal(a[column],b[column]);arrays+=1
            assert a['curve_hash']==b['curve_hash'];originals+=1
    result=dict(合格=True,元前半条件数=288,選抜観点数=len(checks),一意代表数=len(ids),
        主観点の一意数=chosen['primary_unique'],固定コード数=len(fixed['code_SHA256']),
        初回と最終の前半完全一致口座=originals,完全一致配列数=arrays,
        選定=checks,後半選定利用口座数=0,
        固定SHA256=digest(WORK/'results/事前固定.json'),選定SHA256=digest(WORK/'前半選定.json'))
    save('前半選定と最終前半再生の独立照合.json',result)
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
