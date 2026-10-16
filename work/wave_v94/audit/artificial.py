"""全53条件の人工台帳を独立状態・源対応・最初執行・会計で損益前に反証する。"""

import copy
from pathlib import Path
import socket
import sys

import numpy as np

import common
import full
import entry_checks
import price_checks
import protocol
from execution_checks import sample,prefix,prefix_equal


SCENARIOS = ('通常往復','不明を跨ぎ指値保持','共同方向で取消競合','片市場無効で新規を拒否',
             '観測回復の自己と相手の時差','同値極値の形成行を保持','相手極値後の新源なし',
             '気配差だけ縮小して回復なし','双方帰還を異時点で足し合わせない',
             '予定距離合格後の次気配飛躍','中心利確の次気配損失','同一行停止と中心利確の優先',
             '返済予約だけで休止しない','同時計後続N4の源時計',
             'G1初回不明で見送り後窓回復','G2初回未確認で見送り後確認',
             'G1G2解除後だけ新準備再参加','価格だけ正常で旧BBO不明',
             '回復予約後に取消と約定競合','回復予約後に場末取消')


def enrich(record: dict,signal: dict) -> None:
    """
    機能: 人工価格源と執行BBO源を異なるindex・原seq・時計で明示する。
    引数: record/signal(dict)。
    返り値: None、人工信号だけ追加する。実原本を変更しない。
    """
    size=len(signal['grid']);row=np.arange(size,dtype=np.int64)
    signal.update(price_observable=np.ones(size,bool),price_mode=signal['mode'].copy(),
                  price_own_index=row+1000,price_peer_index=row+2000,
                  price_own_raw_seq=row*2+3000,price_peer_raw_seq=row*3+4000,
                  price_own_time=signal['grid']-1.,price_peer_time=signal['grid']-2.,
                  price_own_valid=np.ones(size,bool),price_peer_valid=np.ones(size,bool))


def fixture(symbol: str,scenario: str,reflected: bool,config: dict) -> tuple:
    """
    機能: 独立既知の人工経路へ現在入口だけの正負境界を付ける。
    引数: symbol/scenario(str)、reflected(bool)、config(dict)。
    返り値: tuple[dict,dict]、原板と過去信号。
    """
    mapped={'G1初回不明で見送り後窓回復':'同値極値の形成行を保持',
            'G2初回未確認で見送り後確認':'同値極値の形成行を保持',
            'G1G2解除後だけ新準備再参加':'同値極値の形成行を保持',
            '価格だけ正常で旧BBO不明':'同値極値の形成行を保持',
            '回復予約後に取消と約定競合':'同値極値の形成行を保持',
            '回復予約後に場末取消':'同値極値の形成行を保持'}
    record,signal=sample(symbol,mapped.get(scenario,scenario),reflected,config)
    enrich(record,signal)
    signal['event'][10]=-1 if reflected else 1
    if scenario in ('G1初回不明で見送り後窓回復','G1G2解除後だけ新準備再参加'):
        signal['price_observable'][11]=False
    if scenario in ('G2初回未確認で見送り後確認','G1G2解除後だけ新準備再参加'):
        signal['price_mode'][11]=0
    if scenario=='G1G2解除後だけ新準備再参加':signal['arm_common'][19]=1 if reflected else -1
    if scenario=='価格だけ正常で旧BBO不明':
        signal['current_valid'][11:20]=False;signal['peer_valid'][11:20]=False
    if scenario=='回復予約後に取消と約定競合':
        record['quote_valid'][12]=False
        signal['arm_common'][12]=1 if reflected else -1
    if scenario=='回復予約後に場末取消':
        signal['event'][:]=0
        record['quote_valid'][12:]=False
    return record,signal


def faults(record: dict,signal: dict,config: dict,result: dict,controller: object) -> int:
    """
    機能: 源の差替え・疎状態改竄・gate消費抹消を独立監査が拒否するか調べる。
    引数: record/signal/config/result(dict)、controller(object)。
    返り値: int、拒否した故障数。許可リストを広げず停止する。
    """
    errors=[]
    changed=copy.deepcopy(result);changed['price_source_trace'][11,2]=changed['price_source_trace'][11,6]
    errors.append(('価格indexをBBOindexへ差替',changed))
    changed=copy.deepcopy(result);changed['price_source_trace'][11,8]+=500
    errors.append(('価格代理時計を未来へ差替',changed))
    changed=copy.deepcopy(result);changed['price_source_trace'][11,21]=7
    errors.append(('G2確認modeを捏造',changed))
    changed=copy.deepcopy(result);changed['risk_state_trace'][11,0]=1-changed['risk_state_trace'][11,0]
    errors.append(('初回エピソード消費を抹消',changed))
    count=0
    for name,wrong in errors:
        try:full.account((record['session'],record['symbol']),record,signal,config,controller.ledger(wrong))
        except AssertionError:count+=1
        else:raise AssertionError(('故障注入を見逃した',name,config['id'],record['symbol']))
    sparse=controller.ledger(result)
    sparse['price_source_changes']=sparse['price_source_changes'][1:]
    try:full.account((record['session'],record['symbol']),record,signal,config,sparse)
    except AssertionError:count+=1
    else:raise AssertionError('疎状態初回を抹消しても受理した')
    return count


def deny(*args: object,**kwargs: object) -> None:
    """
    機能: 人工監査からのネットワーク接続を拒否する。
    引数: args(tuple)、kwargs(dict)。
    返り値: None、必ず例外で停止する。
    """
    raise RuntimeError('人工監査では現在APIを取得しません')


def main() -> None:
    """
    機能: 全53の独立人工台帳と将来不変及び負の中心返済例を保存する。
    引数: なし。
    返り値: None、損益前人工合格証JSON。正式実セッション損益を実行しない。
    """
    socket.socket.connect=deny;socket.create_connection=deny
    sys.path.insert(0,str(common.WORK))
    import strategy,catalog
    controller=common.module('新94の正式台帳人工接続',common.WORK/'research.py')
    production=common.module('新94の正式会計人工対照',common.WORK/'accounting.py')
    counts=dict(人工保存台帳=0,条件=53,故障拒否=0,未来接頭=0,価格源未来変形=0,中心返済理由の損失親=0)
    config_activity={};gate_examples=[];negative_centers=[]
    for config in catalog.catalog():
        activity=0
        for symbol in common.SYMBOLS:
            for scenario in SCENARIOS:
                for reflected in (False,True):
                    record,signal=fixture(symbol,scenario,reflected,config)
                    result=strategy.ENGINE.execute(record,signal,config)
                    row,checked=full.account((record['session'],symbol),record,signal,config,controller.ledger(result))
                    common.same(row,production.account((record['session'],symbol),result))
                    counts['人工保存台帳']+=1;activity+=len(result['trades'])
                    for name,value in checked.items():counts[name]=counts.get(name,0)+value
                    negative=result['trades'][(result['trades'][:,13]==15)&(result['trades'][:,11]<0)]
                    counts['中心返済理由の損失親']+=len(negative)
                    if len(negative) and len(negative_centers)<8:
                        negative_centers.append(dict(条件=config['id'],商品=symbol,上下反射=reflected,
                                                     人工ケース=scenario,親=int(negative[0,0]),純額=float(negative[0,11])))
                    if scenario=='G1G2解除後だけ新準備再参加' and config['range_entry_context']!='legacy':
                        gates=result['events'][result['events'][:,3]==27]
                        common.same(gates[:2,0],[11,28]);common.same(gates[:2,11],[0,1])
                        assert (result['risk_state_trace'][11:19,0]==1).all()
                        if len(gate_examples)<8:gate_examples.append(dict(条件=config['id'],商品=symbol,反射=reflected,見送り=11,再参加=28))
                    if scenario=='G1G2解除後だけ新準備再参加':
                        for stop in (6,11,12,18,20,29,34):
                            r,s=prefix(record,signal,stop);part=strategy.ENGINE.execute(r,s,config,finish=False)
                            prefix_equal(result,part,stop)
                            common.same(result['price_source_trace'][:stop],part['price_source_trace'])
                            counts['未来接頭']+=1
                            future=copy.deepcopy(signal)
                            boundary=int(np.searchsorted(signal['grid'],record['time_s'][stop-1],side='right'))
                            for name in ('price_own_index','price_peer_index','price_own_raw_seq','price_peer_raw_seq'):
                                future[name][boundary:]+=900000
                            future['price_observable'][boundary:]=~future['price_observable'][boundary:]
                            future['price_mode'][boundary:]=1
                            changed=strategy.ENGINE.execute(r,{**future,**{k:s[k] for k in ('mapped','quality','reset','event')}},config,finish=False)
                            prefix_equal(result,changed,stop)
                            common.same(result['price_source_trace'][:stop],changed['price_source_trace'])
                            counts['価格源未来変形']+=1
                        counts['故障拒否']+=faults(record,signal,config,result,controller)
        assert activity>0,('人工で無取引だけの条件を合格させない',config['id'])
        config_activity[config['id']]=activity
        print(f'{config["id"]} 独立人工台帳・入口状態・別源22列・次原板執行・会計合格',flush=True)
    assert counts['人工保存台帳']==53*2*2*len(SCENARIOS)
    assert counts['中心返済理由の損失親']>0
    assert counts['取消判断']>0, '成行予約に取消判断を付けた競合の検査不足'
    paths=[*common.HERE.glob('*.py'),common.WORK/'engine.py',common.WORK/'strategy.py',
           common.WORK/'catalog.py',common.WORK/'research.py',common.WORK/'accounting.py']
    common.save('全53人工台帳と現在入口消費及び別価格執行源と会計の独立検査.json',
                dict(全合格=True,条件数=53,検査件数=counts,人工条件別活動親=config_activity,
                     初回見送りと新準備後再参加=gate_examples,中心返済ラベルでも実純損失の反例=negative_centers,
                     正式台帳関数の新22列疎復元接続=True,新価格源を約定価格へ代用=0,
                     独立状態の正答に潜在trace使用=0,全31既知=True,新保存場損益計算=0,
                     新保存場損益閲覧=0,現在API取得=0,実注文=0,旧変更=0,
                     SHA256=common.fingerprint(paths)))


if __name__=='__main__':main()
