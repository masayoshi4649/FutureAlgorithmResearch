"""登録後だけ新GU132を共有し、四政策264の実数量会計を生成する。"""

import argparse
from collections import Counter
import gc
import time
import traceback

import numpy as np

import common
import catalog
import data
import daily
import interface
import storage


TRADE=common.ROOT/'work/wave_v106/e01_trade_gate'
BUDGET=common.ROOT/'work/wave_v106/e01_trade_budget'
ART=common.HERE/'予定リスク数量と累積部分返済及び旧同値の人工検査_v2.json'
FIELDS=('収支変化','避けた基準損失','失った基準利益','共通入口の数量/出口差','新たな入口の収支')


def cloned() -> dict:
    """
    機能: 不変会計・UID・公開gate・旧実行を同bytesの私有コピーへ照合する。
    引数: なし。
    返り値: dict は直接使用する旧源のSHA256。旧moduleをimportしない。
    """
    result={}
    for current,previous in (('common.py','common.py'),('daily.py','daily.py'),('order_kernel.py','order_kernel.py'),
                              ('policy.py','policy.py'),('baseline.py','engine.py')):
        source=TRADE/previous;assert (common.HERE/current).read_bytes()==source.read_bytes()
        result[source.relative_to(common.ROOT).as_posix()]=common.digest(source)
    return result


def item(value: dict, id: str) -> dict:
    """
    機能: 保存比較の66行と66台帳参照を、欠測補完なしで取得する。
    引数: value(dict)、id(str) は完成済み旧小結果と正確な条件ID。
    返り値: dict は比較の行・集計・一読台帳参照。
    """
    source=value['results'][id];assert len(source['rows'])==len(source['ledgers'])==66
    keys={r['session']+'|'+r['symbol'] for r in source['rows']}
    specs={r['session']+'|'+r['symbol']:r for r in source['ledgers']};assert set(specs)==keys and len(keys)==66
    return dict(id=id,rows=source['rows'],symbols=source['symbols'],ledgers=specs)


def freeze() -> None:
    """
    機能: 四条件・同額旧L2/旧P1L8/旧GU・既入力33を八部品へ束縛する。
    引数: なし。
    返り値: None。小結果だけ読み、根登録・大型cache・金融は実行しない。
    """
    assert not (common.HERE/'試行計画.json').exists()
    meta_path=TRADE/'全33場のE01取引更新準備.json';trade_path=TRADE/'finance/結果.json';budget_path=BUDGET/'finance/結果.json'
    meta,trade,budget,art=(common.read(p) for p in (meta_path,trade_path,budget_path,ART))
    assert all(v['全合格'] for v in (meta,trade,budget,art))
    assert meta['sessions']==trade['sessions']==budget['sessions'] and len(meta['sessions'])==33
    assert art['source_SHA256']==common.sources()
    comparison={};configs=catalog.configs()
    for c in configs:
        comparison[c['id']]=dict(同額固定数量L2=item(budget,c['baseline_id']),
            旧P1L8=item(trade,c['baseline8_id']),旧GU=item(trade,c['GU_id']))
    sources=cloned();availability_path=common.ROOT/'work/wave_v106/size_availability/公開299のATR両気配と予定数量可用性.json'
    availability=common.read(availability_path);assert availability['全合格'] and len(availability['witness'])==299
    manifests=[dict(path=p.relative_to(common.ROOT).as_posix(),sha256=common.digest(p)) for p in (meta_path,trade_path,budget_path,ART,availability_path)]
    spec=dict(entry=dict(conditions=configs,condition_count=4,
        母条件='元E01保存paper新規＋W60 CONFIRM又はVETO。D0新規。publish時の票とATRだけ。',
        数量資格='同normal quote_validかつ有限正bid<ask、公開ATR有限正。UNKNOWNはそのpaper親を見送り。未来正常quoteへ公開審査を移さない。'),
        management=dict(影='元paper5/10の全feedとvcoreは不変。実損益・実数量をpaperの信号や判断へ戻さない。',
            当時余力='同rowの旧予約fill処理後、実注文料と残UID返済見込料を引いた清算EからM=max(0,B+E)。',
            部分返済='累積virtual返済C/Vに対し累積actual返済=floor(Q*C/V)。既予約量との差だけ次quoteへ予約、paper最終全返済は実残量全て。',
            支払='実新規/部分/全返済の注文別floor料を逐次更新。料金・数量はUIDを相殺して省かない。',
            停止='共通GUの実注文接頭からP1/P2又はL2の最初到達を選び、次正常quoteで残UID別全返済し場終了。'),
        exit=dict(元GU='paperの通常途中判断、U静観、期限、partial/全返済を保持。',
            円閾値={'TOPIX':{'P1':2500,'P2':5000,'L2':5000},'NK225':{'P1':1000,'P2':2000,'L2':2000}},
            条件共有='同母gateのGUをP1/P2が共有。各停止後のGU suffixは影診断だけで実政策収支へ足さない。'),
        allocation=dict(base_quantity=catalog.QUANTITY,direction_cap=catalog.CAP,
            予定損失='L(q)=q*(1.0*公開ATR+当行ask−bid)*商品円倍率+2*floor(q*片道税込料)。q=0..baseを列挙。',
            決定='L(q)<=当時Mとなる最大整数qを公開時固定。q0/未知見送りでも全paper feedは継続。次気配での悪化を公開へ戻さない。',
            尺度='原E01出口paperは0.75ATR。新1ATRは保守的な予定数量尺度で、実stop幅/実損失保証ではない。'),
        costs=dict(片道税込={'TOPIXmini':41.8,'NK225micro':11},円倍率=catalog.VALUE,
            実課金='不変daily/UID会計、各実注文floor(qfee)。engine逐次料はTOP209/5、NK11/1の整数分数と同値。',
            相殺='主評価は完結親net正負合計。actual_legsの料金配分後正負も副集計し、親内の相殺を別表示。'),
        execution=dict(新規='公開後最初正常買ask/売bid。未知quote審査拒否、当行新規fillなし。',
            同行='旧timer取消→前行予約の実返済/新規fill→当行paper公開を保持。既fillを遡及取消しない。',
            商品='ラージ観測TOPIX .5pt/NK10円、実mini/microの2呼値。実小型板、待ち順位は未測。'),
        data=dict(sessions=meta['sessions'],input_manifests=manifests,
            使用='既保存33packetを金融開始時のみ各一読。旧比較台帳は引用資料ごと各一読しP1/P2で共有する。',
            可用性='非金融299射影で数量qが正でも実busy/quiet/goal/損失余力を含む活動/収益は未測。',
            時計='価格時計代理/原seq因果順。受信時刻未保存。現ナイト不適合データは未使用。'),
        implementation=common.sources())
    plan=dict(id=catalog.TRIAL_ID,name='予定リスクで初回も数量を選び同円目標を維持するE01',purpose='新仮説',
        question='初回から円リスクを縮めつつ価格揺れへ耐え、固定円利益目標のP1又は同額P2を得られるか。',
        change='2母条件×P1/P2、L2固定。quantityのみ公開当時に可変化。原paper停止幅・途中信号は変更しない。',
        repeat_reason='既L2は固定5/10で価格揺れを狭く止めた。今回はATRとspreadを円損失へ対応させて初回実枚数とpartial丸めを変える新注文経路。',
        compares_to=['106_E01公開時の取引更新代理と二執行24対照','106_E01取引更新と利益損失目標18政策'],
        spec=spec,比較範囲={c['id']:{'同額固定数量L2':c['baseline_id'],'旧P1L8':c['baseline8_id'],'旧GU':c['GU_id']} for c in configs},
        確認済みclone=sources,counts=dict(新GUengine=132,新政策会計=264,旧基準台帳一読=528,既input一読=33,元paper再計算=0),
        limitations=['小数量は固定円目標までの必要値幅を増やす。旧GUがその前に撤回する可能性を含む。',
            '予定リスク枠は次quoteギャップ等で超過可能。実最大赤字を平均黒字以下に保証する線ではない。',
            'P1対L2は2:1、P2対L2は同額。これらは将来の勝率・金額割合を保証しない。',
            'float予定幅の予算隣接誤差留保がある。実299は1e-7円以内の境界例0だが未来も0とは保証しない。',
            '既知33再探索。無取引・q0を成功と扱わず、上位3黒字除外と全場安定性を測る。'])
    common.write(common.HERE/'試行計画.json',plan)
    common.write(common.HERE/'金融事前固定.json',dict(全合格=True,sessions=meta['sessions'],configs=configs,
        input_cache=meta['cache'],comparisons=comparison,source_SHA256=common.sources(),計画SHA256=common.digest(common.HERE/'試行計画.json'),
        新金融=0,大型input読取=0,旧台帳読取=0,原板=0,原NPZ=0,API=0))
    print('数量4条件の結果前固定完了。root登録/金融開始待ち。',flush=True)


def run(registry: object) -> None:
    """
    機能: 根登録後だけ新GU132を共有して四政策264、同枚数旧基準差を保存する。
    引数: registry(Path) は根が登録する正式試行台帳。
    返り値: None。失敗はFalse保存で自動再開しない。価格入力やpaperを再生成しない。
    """
    fixed=common.read(common.HERE/'金融事前固定.json');plan=common.read(common.HERE/'試行計画.json')
    found=[t for t in common.read(registry)['trials'] if t['id']==catalog.TRIAL_ID]
    assert len(found)==1 and found[0]['spec']==plan['spec'] and common.sources()==fixed['source_SHA256']==plan['spec']['implementation']
    assert common.digest(common.HERE/'試行計画.json')==fixed['計画SHA256'] and cloned()==plan['確認済みclone']
    for m in plan['spec']['data']['input_manifests']:assert common.digest(common.ROOT/m['path'])==m['sha256']
    assert not (common.HERE/'finance').exists()
    common.write(common.HERE/'finance/開始.json',dict(正式1回=True,source_SHA256=fixed['source_SHA256'],新GUengine=132,新政策会計=264))
    configs=fixed['configs'];rows={c['id']:[] for c in configs};parents={k:[] for k in rows};legs={k:[] for k in rows}
    ledgers={k:[] for k in rows};changes={k:[] for k in rows};counts=Counter();started=time.monotonic()
    try:
        for session in fixed['sessions']:
            packet=data.load(fixed['input_cache'][session]);assert packet['session']==session;counts['既input一読']+=1
            for symbol in catalog.QUANTITY:
                account=packet['accounts'][symbol];key=session+'|'+symbol;n=len(account['record']['price'])
                for mode in ('CONFIRM','VETO'):
                    group=[c for c in configs if c['mode']==mode];values=interface.execute(account,group[0]);counts['新GUengine']+=1
                    before={}
                    for c in group:
                        for kind,ref in fixed['comparisons'][c['id']].items():
                            if ref['id'] not in before:
                                before[ref['id']]=data.load(ref['ledgers'][key]);counts['旧基準台帳一読']+=1
                    for c in group:
                        cid=c['id'];fresh=interface.account_output(session,account,c,values);counts['新政策会計']+=1
                        delta={}
                        for kind,ref in fixed['comparisons'][cid].items():
                            previous=before[ref['id']];assert previous['key']==fresh['key']
                            d=storage.delta(previous,fresh);a={p['親']:p for p in previous['parent']};b={p['親']:p for p in fresh['parent']}
                            turned=[dict(parent=int(p),old_net=a[p]['収支'],new_net=b[p]['収支']) for p in a.keys()&b.keys() if a[p]['収支']>0 and b[p]['収支']<0]
                            delta[kind]=dict(baseline_id=ref['id'],**d,元勝ち親が赤字化=turned)
                        changes[cid].append(dict(session=session,symbol=symbol,比較別=delta))
                        rows[cid].append(fresh['summary']);parents[cid].extend(dict(**p,session=session,symbol=symbol) for p in fresh['parent'])
                        legs[cid].extend(dict(**p,session=session,symbol=symbol) for p in fresh['actual_legs'])
                        p=common.HERE/f'finance/ledgers/{cid}/{session}_{symbol}.pkl.gz';common.write(p,storage.stored(fresh,n))
                        ledgers[cid].append(dict(session=session,symbol=symbol,path=p.relative_to(common.ROOT).as_posix(),SHA256=common.digest(p)))
                        del fresh
                    del values,before
            del packet;gc.collect();print(session+' 新GU共有・数量4会計完了',flush=True)
        assert counts==Counter(既input一読=33,新GUengine=132,新政策会計=264,旧基準台帳一読=528)
        assert common.sources()==fixed['source_SHA256']
        results={cid:dict(rows=rows[cid],ledgers=ledgers[cid],symbols={s:storage.aggregate([r for r in rows[cid] if r['symbol']==s],
            [p for p in parents[cid] if p['symbol']==s],fixed['sessions']) for s in catalog.QUANTITY},
            actual_leg_symbols={s:dict(実決済玉数=len([p for p in legs[cid] if p['symbol']==s]),
                **daily.metric([p['収支'] for p in legs[cid] if p['symbol']==s]),
                定義='actual_legs net正負の合計。metricの親数はこの副表では実決済玉数を意味する。主評価は完結親で不変。') for s in catalog.QUANTITY}) for cid in rows}
        diagnosis={cid:{s:{kind:dict(**{f:sum(d['比較別'][kind][f] for d in changes[cid] if d['symbol']==s) for f in FIELDS},
            元勝ち親が赤字化=sum(len(d['比較別'][kind]['元勝ち親が赤字化']) for d in changes[cid] if d['symbol']==s))
            for kind in ('同額固定数量L2','旧P1L8','旧GU')} for s in catalog.QUANTITY} for cid in rows}
        common.write(common.HERE/'finance/結果.json',dict(全合格=True,sessions=fixed['sessions'],configs=configs,results=results,
            diagnosis=diagnosis,各場寄与=changes,counts=dict(counts),新GUengine=132,新政策会計=264,会計口座数=264,
            主評価='完結実親net正負。部分実玉正負はactual_leg_symbolsへ別集計。',
            共通親差の意味='同じpaper親の実数量・部分floor・手数料・停止出口が変わるため共通入口の数量/出口差。',
            source開始終端一致=True,source_SHA256=fixed['source_SHA256'],元paper再計算=0,原板読取=0,原NPZ=0,現在入力読取=0,API=0,
            経過秒=time.monotonic()-started))
    except BaseException:
        common.write(common.HERE/'finance/False.json',dict(全合格=False,原因=traceback.format_exc(),自動再開始=False,counts=dict(counts)));raise


if __name__=='__main__':
    parser=argparse.ArgumentParser();mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--freeze',action='store_true');mode.add_argument('--root-trial-registered',action='store_true')
    parser.add_argument('--registry',type=lambda p:common.ROOT/p,default=common.ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/data/trials.json')
    args=parser.parse_args();freeze() if args.freeze else run(args.registry)
