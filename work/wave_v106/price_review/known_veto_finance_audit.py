"""既知中立二出口の小会計全数と固定規則の実玉・停止・後続参加を独立監査する。"""

from collections import defaultdict
from pathlib import Path
import json

import numpy as np

import range_finance_audit as A
from e01_trade_finance_audit import aggregate, contribution, inspect_orders, row_check


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SOURCE = ROOT/'work/wave_v106/e01_known_veto'
OLD = ROOT/'work/wave_v106/e01_trade_gate'
FIELDS = ('収支変化','避けた基準損失','失った基準利益','共通入口の出口変化','新たな入口の収支')


def gate(account: dict, out: dict) -> dict:
    """
    機能: 当時入口の情報資格・初次気配・不変影・部分返済待機を保存値だけで確認する。
    引数: account(dict)、out(dict)は一読packetと新台帳。
    返り値: dictは許可・中立・拒否公開の件数。未来結果から入口を変えない。
    """
    q = account['quotes']; record = account['record']; feed = account['feed']; features = account['trade_features']['60']
    n = len(q['bid']); expected = np.ones(n,bool); reasons = np.zeros(n,np.int32); counter = defaultdict(int)
    for entry in feed[feed[:,7]==1]:
        row = int(entry[0]); value = features[row]
        allow = bool(value['known'] and value['direction_votes']>=2 and value['balance']>-.25)
        expected[row] = allow
        reasons[row] = 0 if allow else 100+value['reason'] if not value['known'] else 200 if value['direction_votes']<2 else 202
        counter['許可' if allow else '拒否'] += 1
        if allow and value['balance']<.25: counter['許可中立'] += 1
        if value['reason']!=2:
            A.check(value['candidate_raw_row']==account['mapping'][row] and value['candidate_raw_seq']==record['seq'][row],'既知入口/原行')
            A.equal(value['candidate_price_time_s'],record['time_s'][row],'既知入口/価格時計')
    for name,value in (('gate_accepted',expected),('gate_reasons',reasons)):
        stored = out[name]; stored = A.expand(stored,n) if isinstance(stored,dict) else stored
        np.testing.assert_array_equal(stored,value); A.COUNT['既知入口/全mask'] += n
    A.check(out['shadow_feed_SHA256']==account['paper_SHA256'],'既知入口/影指紋')
    valid = q['quote_valid']&np.isfinite(q['bid'])&np.isfinite(q['ask'])&(q['bid']>0)&(q['bid']<q['ask'])
    for order in out['shadow_GU_orders'][out['shadow_GU_orders'][:,7]==1]:
        row, decision, cid = map(int,(order[0],order[1],order[2]))
        A.check(expected[decision],'既知入口/実許可')
        candidates = feed[(feed[:,0]==decision)&(feed[:,2]==cid)&(feed[:,7]==1)]
        A.check(len(candidates)==1,'既知入口/公開一意')
        nextrow = decision+1+int(np.flatnonzero(valid[decision+1:])[0])
        A.check(row==nextrow,'既知入口/初次正常気配')
    states = out['execution_states']; states = A.expand(states,n) if isinstance(states,dict) else states
    # ----------------------------------------
    # 拒否した親の紙上数量も全公開/部分返済から更新される。同normal後段の状態を照合する。
    virtual = 0; current = -1; expected_virtual = np.zeros(n,np.int64); expected_parent = np.full(n,-1,np.int64)
    pointer = 0
    for row in range(n):
        while pointer<len(feed) and int(feed[pointer,0])==row:
            entry = feed[pointer]; cid,side,qty,new = map(int,(entry[2],entry[3],entry[4],entry[7])); pointer += 1
            if new: A.check(virtual==0,'既知影/新親前flat'); current = cid
            else: A.check(cid==current,'既知影/返済親')
            virtual += side*qty
        expected_virtual[row] = virtual; expected_parent[row] = current
    np.testing.assert_array_equal(states[:,0],expected_parent); np.testing.assert_array_equal(states[:,1],expected_virtual)
    A.COUNT['既知影/全行数量'] += 2*n
    return dict(counter)


def stop(out: dict, account: dict) -> None:
    """
    機能: 新GU実注文の当時清算から、場目標P1L8の先着とUID返済を独立検算する。
    引数: out(dict)、account(dict)はP1L8台帳と一読入力。
    返り値: None。次quote待ちや停止後新規を実注文から確認する。
    """
    symbol = account['symbol']; quotes = account['quotes']; unit = 2500 if symbol=='TOPIX' else 1000
    shadow = dict(orders=out['shadow_GU_orders'],order_uids=out['shadow_GU_uids'])
    _,_,path = inspect_orders(shadow,quotes,symbol,False)
    hits = np.flatnonzero(path['valid']&((path['liquidation']>=unit)|(path['liquidation']<=-8*unit)))
    control = out['control']; A.check(control['発動']==bool(len(hits)),'既知停止/発動')
    if not len(hits):
        np.testing.assert_array_equal(out['orders'],shadow['orders']); return
    decision = int(hits[0]); A.check(control['判断行']==decision,'既知停止/当時先着')
    prefix = shadow['orders'][:,0]<=decision
    np.testing.assert_array_equal(out['orders'][:prefix.sum()],shadow['orders'][prefix])
    np.testing.assert_array_equal(out['order_uids'][:prefix.sum()],shadow['order_uids'][prefix])
    A.equal(control['判断時清算利益'],path['liquidation'][decision],'既知停止/時価')
    A.check(not np.any(out['orders'][(out['orders'][:,0]>decision)&(out['orders'][:,7]==1)]),'既知停止/新規なし')
    remaining = out['orders'][prefix.sum():]
    if len(remaining):
        nextrow = decision+1+int(np.flatnonzero(path['valid'][decision+1:])[0])
        A.check(np.all(remaining[:,0]==nextrow) and np.all(remaining[:,1]==decision),'既知停止/残UID次quote')
        A.check(np.all(out['exit_target_uids'][prefix.sum():]>=0),'既知停止/残UID明示')
    A.check(control['以後新規なし'] and not control['未来返済テンプレート参照'],'既知停止/接頭')


def main() -> None:
    """
    機能: 全132小会計と規則固定の抽出台帳及び二旧入口比較を一回監査する。
    引数: なし。金融再生・原板・原NPZ・現在APIは使用しない。
    返り値: Noneは所有領域の証跡。抽出だけの確認を全台帳確認と呼ばない。
    """
    target = HERE/'known_veto_全132小会計と抽出実玉停止及び二入口比較の独立監査.json'
    A.check(not target.exists(),'既知監査/重複なし')
    result = A.read_json(SOURCE/'finance/結果.json'); fixed = A.read_json(SOURCE/'金融事前固定.json'); plan = A.read_json(SOURCE/'試行計画.json')
    old = A.read_json(OLD/'finance/結果.json'); meta = A.read_json(OLD/'全33場のE01取引更新準備.json')
    A.check(result['全合格'] and result['新gateengine']==66 and result['新政策会計']==132,'既知監査/金融数')
    A.check(result['source_SHA256']==fixed['source_SHA256']==plan['spec']['implementation'],'既知監査/固定源')
    source = {p:A.sha(ROOT/p) for p in fixed['source_SHA256']}; A.check(source==fixed['source_SHA256'],'既知監査/源現状')
    A.check(result['sessions']==fixed['sessions']==plan['spec']['data']['sessions']==meta['sessions'],'既知監査/場')
    A.check(result['configs']==fixed['configs']==plan['spec']['entry']['conditions'],'既知監査/条件')
    A.check(fixed['input_cache']==meta['cache'],'既知監査/入力資格固定')
    sessions = result['sessions']; configs = {c['id']:c for c in result['configs']}; stability = {}; rows = {}; ledgers = {}; samples = set()
    for ident,case in result['results'].items():
        A.check(len(case['rows'])==len(case['ledgers'])==66,'既知監査/66行')
        ledgers[ident] = {(p['session'],p['symbol']):p for p in case['ledgers']}; stability[ident] = {}
        baseline = old['results'][configs[ident]['baseline_id']]
        for symbol in ('TOPIX','NK225'):
            selected = [r for r in case['rows'] if r['symbol']==symbol]
            A.check([r['session'] for r in selected]==sessions,'既知監査/33場順')
            for r in selected: row_check(r,5 if symbol=='TOPIX' else 10); rows[ident,r['session'],symbol] = r
            stability[ident][symbol] = aggregate(selected,case['symbols'][symbol])
            active = [r for r in selected if r['親数']]; red = [r for r in selected if r['収支']<0]
            if active: samples.add((ident,active[0]['session'],symbol))
            if red: samples.add((ident,min(red,key=lambda r:(r['収支'],r['session']))['session'],symbol))
            oldrows = {r['session']:r for r in baseline['rows'] if r['symbol']==symbol}
            biggest = max(selected,key=lambda r:(abs(r['収支']-oldrows[r['session']]['収支']),-sessions.index(r['session'])))
            samples.add((ident,biggest['session'],symbol))
        summed = {s:defaultdict(float) for s in ('TOPIX','NK225')}
        for d in result['各場寄与'][ident]:
            symbol = d['symbol']; baseline_row = next(r for r in baseline['rows'] if r['session']==d['session'] and r['symbol']==symbol)
            A.equal(d['収支変化'],rows[ident,d['session'],symbol]['収支']-baseline_row['収支'],'既知全場/差')
            A.equal(d['収支変化'],d['避けた基準損失']-d['失った基準利益']+d['共通入口の出口変化']+d['新たな入口の収支'],'既知全場/五寄与')
            for f in FIELDS: summed[symbol][f] += d[f]
        for symbol in summed:
            for f in FIELDS: A.equal(result['diagnosis'][ident][symbol][f],summed[symbol][f],'既知集計/五寄与')
    sample_plan = dict(抽出=[list(x) for x in sorted(samples)],規則='各二出口・商品で初活動、最悪赤字、VETOとの差の絶対値最大場。重複排除。',抽出上限=12,全小会計=132,金融再生=0,原NPZ=0,API=0)
    sample_path = HERE/'known_veto_保存台帳の独立抽出計画.json'; A.check(not sample_path.exists(),'既知抽出/一回')
    sample_path.write_text(json.dumps(sample_plan,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    # ----------------------------------------
    # 旧二政策は保存結果だけを比較する。新条件を金融再生し直して一致させない。
    reads = {}; inputs = {}; reviewed = []; comparisons = []; account_gates = {}
    for session in sessions:
        selected = [x for x in sorted(samples) if x[1]==session]
        if not selected: continue
        packet = A.unpack(fixed['input_cache'][session],inputs)
        for ident,_,symbol in selected:
            config = configs[ident]; a = packet['accounts'][symbol]
            out = A.unpack(ledgers[ident][session,symbol],reads); parents,_,_ = inspect_orders(out,a['quotes'],symbol)
            account_gates[ident+'|'+session+'|'+symbol] = gate(a,out)
            if config['exit']=='P1L8': stop(out,a)
            for mode in ('VETO','CONFIRM'):
                oldid = 'E01_TRADE_W60_'+mode+'_D0_'+config['exit']; oldcase = old['results'][oldid]
                olditem = next(p for p in oldcase['ledgers'] if p['session']==session and p['symbol']==symbol)
                before = A.unpack(olditem,reads); before_parents,_,_ = inspect_orders(before,a['quotes'],symbol)
                delta = contribution(before_parents,parents)
                if mode=='VETO':
                    saved = next(d for d in result['各場寄与'][ident] if d['session']==session and d['symbol']==symbol)
                    for f in FIELDS: A.equal(saved[f],delta[f],'既知抽出/実五寄与')
                    turned = [dict(parent=k,base_net=before_parents[k]['net'],new_net=parents[k]['net']) for k in before_parents.keys()&parents.keys() if before_parents[k]['net']>0 and parents[k]['net']<0]
                    assert sorted(turned,key=lambda p:p['parent'])==sorted(saved['元勝ち親が赤字化'],key=lambda p:p['parent'])
                comparisons.append(dict(id=ident,session=session,symbol=symbol,比較=mode,**delta))
            reviewed.append(dict(id=ident,session=session,symbol=symbol,注文=len(out['orders']),親=len(parents),費用=out['summary']['費用'],収支=out['summary']['収支'],停止=out.get('control')))
    A.check(len(reviewed)==len(samples)<=12,'既知抽出/件数')
    proof = dict(全合格=True,範囲='二出口132小会計全数と結果前固定規則の抽出実玉。旧二入口比較は保存資料のみ。全132大台帳を再検算した主張ではない。',
        検査件数=sum(A.COUNT.values()),分類別検査=dict(A.COUNT),source_SHA256=source,レビューsource_SHA256=A.sha(Path(__file__)),
        結果SHA256=A.sha(SOURCE/'finance/結果.json'),旧結果SHA256=A.sha(OLD/'finance/結果.json'),計画SHA256=A.sha(SOURCE/'試行計画.json'),
        全小会計=132,抽出台帳件数=len(reviewed),読取台帳=len(reads),読取packet=len(inputs),小会計安定性=stability,
        入口資格=account_gates,抽出=reviewed,二入口との実親五寄与=comparisons,新金融=0,新engine=0,原板=0,原NPZ=0,API=0,
        留意点=['入口maskの包含は実取引集合の包含ではない。新規見送り後の後続参加と全場停止も含めた実親差を検算した。',
            'knownと二票以上は情報資格で、方向的な支持や予測精度改善そのものではない。中立許可群を支持ありと数えない。',
            '初回はTOPIXミニ5枚/日経マイクロ10枚、上限10/20。実注文別料金とUID別残返済料を含む。'])
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print('既知中立の独立保存監査合格',len(reviewed),len(reads),len(inputs),A.sha(target))


if __name__=='__main__': main()
