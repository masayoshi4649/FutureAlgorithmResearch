"""結果前の24対照を固定し、根の登録後だけ共有feedの実量金融を一回再生する。"""

import argparse
import gc
import time
import traceback

import numpy as np

import common
import catalog
import daily
import data
import interface
import prepare


def aggregate(rows: list[dict], parents: list[dict], sessions: list[str]) -> dict:
    """
    機能: 保存した同商品33場の金額・枚数・活動・上位3場除外を集計する。
    引数: rows/parents(list[dict])、sessions(list[str])は保存会計と固定場順。
    返り値: dictは集計。無取引を黒字・勝ちに含めない。
    """
    assert len(rows)==len(sessions) and {r['session'] for r in rows}==set(sessions)
    totals=daily.metric([p['収支'] for p in parents]);active=[r for r in rows if r['親数']]
    positive=sorted((r for r in rows if r['収支']>0),key=lambda r:r['収支'],reverse=True)
    negative=[r for r in rows if r['収支']<0]
    return dict(**totals,全場=len(rows),活動場=len(active),黒字場=len(positive),赤字場=len(negative),
        無取引場=len(rows)-len(active),中央値=float(np.median([r['収支'] for r in rows])),
        活動場中央値=float(np.median([r['収支'] for r in active])) if active else None,
        上位3利益場除外収支=totals['収支']-sum(r['収支'] for r in positive[:3]),
        最大場損失=max([0.]+[-r['収支'] for r in rows]),
        費用=sum(r['費用'] for r in rows),新規枚数=sum(r['新規枚数'] for r in rows),
        勝ち枚数=sum(r['勝ち枚数'] for r in rows),負け枚数=sum(r['負け枚数'] for r in rows),
        零枚数=sum(r['零枚数'] for r in rows),全33黒字=len(positive)==len(rows))


def delta(before: dict, after: dict) -> dict:
    """
    機能: 不変紙上親cidで入口の削除・新参加・共通親の出口差を分解する。
    引数: before/after(dict)は同枚数の完結親会計。
    返り値: dictは避け損失・失った利益・共通出口・新入口・総差の5寄与。
    """
    a={p['親']:p for p in before['parent']};b={p['親']:p for p in after['parent']}
    removed=a.keys()-b.keys();joined=a.keys()&b.keys();added=b.keys()-a.keys()
    avoid=sum(-a[k]['収支'] for k in removed if a[k]['収支']<0)
    missed=sum(a[k]['収支'] for k in removed if a[k]['収支']>0)
    exit_change=sum(b[k]['収支']-a[k]['収支'] for k in joined);new=sum(b[k]['収支'] for k in added)
    net=after['summary']['収支']-before['summary']['収支']
    assert np.isclose(net,avoid-missed+exit_change+new,atol=1e-5,rtol=0.)
    return dict(収支変化=net,避けた基準損失=avoid,失った基準利益=missed,
                共通入口の出口変化=exit_change,新たな入口の収支=new)


def baseline_metadata(sessions: list[str]) -> dict:
    """
    機能: 保存GU二執行とD20_P1L8の全66行及び台帳指紋を小JSONだけで固定する。
    引数: sessions(list[str])は同じ33場。
    返り値: dictは3保存対照。D0_P1L8は未算定として別に扱う。
    """
    refpath=common.ROOT/'work/wave_v106/e01_reference/結果.json'
    dpath=common.ROOT/'work/wave_v106/e01_daily/finance/結果.json'
    ref,small=common.read(refpath),common.read(dpath);assert ref['全合格'] and small['全合格']
    result={}
    for execution,oldid in (('D0','E01_G_U_BBO'),('D20','L_D20_BBO')):
        rows=ref['results'][oldid]['rows'];assert len(rows)==66
        assert {(r['session'],r['symbol']) for r in rows}=={(s,m) for s in sessions for m in catalog.QUANTITY}
        ledgers={s+'|'+m:dict(path=f'work/wave_v106/e01_reference/ledgers/{oldid}/{s}_{m}.pkl.gz',
                    SHA256=ref['台帳SHA256'][f'ledgers/{oldid}/{s}_{m}.pkl.gz']) for s in sessions for m in catalog.QUANTITY}
        result[execution+'_GU']=dict(id=oldid,rows=rows,ledgers=ledgers,source=dict(path=refpath.relative_to(common.ROOT).as_posix(),sha256=common.digest(refpath)))
    value=small['results']['E01_DAILY_P1_L8'];assert len(value['rows'])==66
    ledgers={i['session']+'|'+i['symbol']:i for i in value['ledgers']};assert len(ledgers)==66
    result['D20_P1L8']=dict(id='E01_DAILY_P1_L8',rows=value['rows'],ledgers=ledgers,
        source=dict(path=dpath.relative_to(common.ROOT).as_posix(),sha256=common.digest(dpath)))
    return result


def stored(value: dict, count: int) -> dict:
    """
    機能: 全normal行と同値のplateau圧縮で大配列だけを保存する。
    引数: value(dict)、count(int)は台帳とnormal行数。
    返り値: dictはschema_version2。rows/values/lengthから前方値保持で復元できる。
    """
    output=dict(value)
    names={'equity_yen','liquidation_yen','reserved_exit_fees','long_qty','short_qty',
           'execution_states','gate_accepted','gate_reasons'}
    for k,v in value.items():
        if k not in names or not isinstance(v,np.ndarray) or len(v)!=count:continue
        changed=np.any(v[1:]!=v[:-1],axis=1) if v.ndim==2 else v[1:]!=v[:-1]
        rows=np.r_[0,np.flatnonzero(changed)+1].astype(np.int64)
        output[k]=dict(rows=rows,values=v[rows],length=count)
    output['schema_version']=2;return output


def freeze() -> None:
    """
    機能: 最終source・人工・票input・保存基準を全8部品へ結ぶ。
    引数: なし。
    返り値: None。根のcheck/register及び金融開始は実行しない。
    """
    meta=common.read(common.HERE/'全33場のE01取引更新準備.json')
    art=common.read(common.HERE/'E01公開maskとUID料金及び接頭の人工検査.json')
    assert meta['全合格'] and art['全合格'] and meta['新金融']==0
    assert common.sources()==meta['source_SHA256']==art['source_SHA256']
    base=baseline_metadata(meta['sessions']);manifests=[dict(path=p.relative_to(common.ROOT).as_posix(),sha256=common.digest(p))
        for p in (common.HERE/'全33場のE01取引更新準備.json',common.HERE/'入力測定前の固定.json',
                  common.HERE/'E01公開maskとUID料金及び接頭の人工検査.json',
                  common.ROOT/'work/wave_v106/trade_gate/窓内資格境界訂正と旧人工委譲_v2.json')]
    manifests+=list({v['source']['path']:v['source'] for v in base.values()}.values())
    spec=dict(entry=dict(紙上='不変E01_G_Uの保存66 feed。拒否時にも影のvcoreと部分返済を継続。',
                        gate='公開当原行の自己取引更新代理。CONFIRMは既知2票以上釣合>=.25、VETOは既知2票以上釣合<=-.25だけ拒否。',
                        windows=[10,30,60],conditions=catalog.configs()),
        management=dict(公開拒否='新規公開時1箇所だけ。待機後追加取消・保有退出へ票を再利用しない。',
                        影='全後続paperを順番に再運転。拒否親が影で返済されるまで影の親状態を維持。',
                        busy='古い実返済待機・実玉があれば新紙上親の実新規を拒否。'),
        exit=dict(GU='元紙上部分/全返済判断後の最初正常BBO。未約定指値は初paper返済で永久取消。',
                  P1L8='当時清算損益1初回呼値又は8呼値損失→次正常BBOで残UID別全返済、その場停止。旧apply_policy exact。',
                  timers='元Uquiet・quiet_force・場内limitを不変更。'),
        allocation=dict(初回=catalog.QUANTITY,片方向上限=catalog.CAP,比較='24独立政策、配分なし。'),
        costs=dict(片道料金={'TOPIXmini':41.8,'NK225micro':11.},円倍率=daily.VALUE,
                   処理='実注文単位floor、FIFO実玉/UID別残返済料。部分返済の合算丸めなし。'),
        execution=dict(D0='offset0、公開行で約定せず次normal買ask/売bid。',
                       D20='公開Last-side*.2ATR、買floor/売ceil指値、次行以降の初BBO到達。',
                       同行順='既知quiet/limit取消→既予約返済/指値fill→当行paper公開mask。',
                       代理='正出来高差usable＋原Last対直前BBOの1更新1票。真の攻撃方向/量ではない。'),
        data=dict(sessions=meta['sessions'],input_manifests=manifests,
                  read_once='旧E01pending33・原NPZ66・Q一資料、原book/current/API0。',
                  clocks='CurrentPriceTime代理窓、候補原seq以下。未来同clock後半不使用。',
                  limits='ReceivedAt未保存、真の到着秒や方向別約定量は未同定。全33既知比較。'),
        implementation=common.sources())
    plan=dict(id=catalog.TRIAL_ID,name='E01公開時の取引更新代理と二執行24対照',purpose='新仮説',
        question='気配だけの方向より実取引更新代理を公開時に確認すると、成行と有利指値の両方で赤字場を減らせるか。',
        change='E01紙上・GU及びP1L8は固定。自己票確認又は強逆向き拒否を公開時だけ追加。D0/D20を別対照。',
        repeat_reason='C/R反発への票確認とは元入口が違う。旧E01待機の価格取消とは判定時点・観測値が違う。',
        compares_to=['106_E01比較の金額残差許容統一と再開','106_E01待機指値の純価格逆方向取消と小利益停止12対照'],
        spec=spec,counts=dict(表示政策=24,新gate執行=792,新政策会計=1584,
            D0_P1L8新基準政策会計=66,会計合計=1650,保存基準再生=0,元paper再生=0),
        limitations=['公開許可は約定や勝ちではない。UNKNOWNもVETOでは元通りであり支持ありと呼ばない。',
                     '同じ代理票はC/R版と共有数学。新しい独立証拠として票人工を二重に数えない。'])
    common.write(common.HERE/'試行計画.json',plan)
    common.write(common.HERE/'金融事前固定.json',dict(全合格=True,実装SHA256=common.sources(),
        計画SHA256=common.digest(common.HERE/'試行計画.json'),基準=base,counts=plan['counts'],正式金融=0))
    print('E01 24対照と新基準66の計画を固定。根の登録/金融許可待ち。',flush=True)


def run(registry) -> None:
    """
    機能: 根登録後に12執行組×66を一回再生し、24政策と新D0小利益基準を保存する。
    引数: registry(Path)は根が登録した試行台帳。
    返り値: None。旧paper/旧engine/原板を再生せず、同出口の5寄与を保存する。
    """
    fixed=common.read(common.HERE/'金融事前固定.json');plan=common.read(common.HERE/'試行計画.json')
    matches=[t for t in common.read(registry)['trials'] if t['id']==catalog.TRIAL_ID]
    assert len(matches)==1 and matches[0]['spec']==plan['spec']
    assert common.sources()==fixed['実装SHA256']==plan['spec']['implementation']
    assert common.digest(common.HERE/'試行計画.json')==fixed['計画SHA256']
    for m in plan['spec']['data']['input_manifests']:assert common.digest(common.ROOT/m['path'])==m['sha256']
    assert not (common.HERE/'finance/開始.json').exists() and not (common.HERE/'finance/結果.json').exists()
    common.write(common.HERE/'finance/開始.json',dict(全合格=True,正式1回=True,計画SHA256=fixed['計画SHA256'],時刻=time.time()))
    sessions=plan['spec']['data']['sessions'];rows={c['id']:[] for c in catalog.configs()};parents={i:[] for i in rows};ledgers={i:[] for i in rows}
    differences={i:[] for i in rows};newbase_rows=[];newbase_parents=[];newbase_ledgers=[];checks=[];engine_count=0;started=time.monotonic()
    try:
        for session in sessions:
            packet=data.load_session(session)
            for symbol in catalog.QUANTITY:
                a=packet['accounts'][symbol];q=a['quotes'];old={}
                for key,item in fixed['基準'].items():
                    before=prepare.load(item['ledgers'][session+'|'+symbol]);assert tuple(before['key'])==(session,symbol)
                    old[key]=before
                base=daily.reconstruct((session,symbol),old['D0_GU']['orders'],old['D0_GU']['order_uids'],q)
                assert np.isclose(base['summary']['収支'],old['D0_GU']['summary']['収支'],atol=1e-7,rtol=0.)
                assert base['summary']['費用']==old['D0_GU']['summary']['費用']
                assert base['summary']['親数']==old['D0_GU']['summary']['親数']
                old['D0_P1L8']=daily.apply_policy(base,q,dict(profit_ticks=1,loss_ticks=8))
                newbase_rows.append(old['D0_P1L8']['summary']);newbase_parents.extend(dict(**p,session=session,symbol=symbol) for p in old['D0_P1L8']['parent'])
                path=common.HERE/f'finance/new_baseline/D0_P1L8/{session}_{symbol}.pkl.gz';common.write(path,stored(old['D0_P1L8'],len(q['bid'])))
                newbase_ledgers.append(dict(session=session,symbol=symbol,path=path.relative_to(common.ROOT).as_posix(),SHA256=common.digest(path)))
                for window in (10,30,60):
                    for mode in ('CONFIRM','VETO'):
                        for execution in ('D0','D20'):
                            configs=[c for c in catalog.configs() if c['window_seconds']==window and c['mode']==mode and c['execution']==execution]
                            values=interface.execute(a,configs[0]);engine_count+=1
                            for config in configs:
                                ident=config['id'];fresh=interface.account_output(session,a,config,values)
                                before=old[execution+'_'+config['exit']];diff=delta(before,fresh)
                                rows[ident].append(fresh['summary']);parents[ident].extend(dict(**p,session=session,symbol=symbol) for p in fresh['parent']);differences[ident].append(dict(session=session,symbol=symbol,**diff))
                                path=common.HERE/f'finance/ledgers/{ident}/{session}_{symbol}.pkl.gz';common.write(path,stored(fresh,len(q['bid'])))
                                ledgers[ident].append(dict(session=session,symbol=symbol,path=path.relative_to(common.ROOT).as_posix(),SHA256=common.digest(path)))
                                checks.append(dict(id=ident,session=session,symbol=symbol,全会計合格=True))
                            del values,fresh
                print(session+' '+symbol+' E01票24政策完了',flush=True);del old,base;gc.collect()
            del packet
        assert engine_count==792 and len(checks)==1584 and len(newbase_rows)==66 and common.sources()==fixed['実装SHA256']
        results={i:dict(rows=rows[i],ledgers=ledgers[i],symbols={s:aggregate([r for r in rows[i] if r['symbol']==s],[p for p in parents[i] if p['symbol']==s],sessions) for s in catalog.QUANTITY}) for i in rows}
        diagnosis={i:{s:{k:sum(d[k] for d in differences[i] if d['symbol']==s) for k in ('収支変化','避けた基準損失','失った基準利益','共通入口の出口変化','新たな入口の収支')} for s in catalog.QUANTITY} for i in rows}
        common.write(common.HERE/'finance/結果.json',dict(全合格=True,sessions=sessions,configs=catalog.configs(),results=results,
            diagnosis=diagnosis,各場寄与=differences,new_D0_P1L8=dict(rows=newbase_rows,ledgers=newbase_ledgers,
                symbols={s:aggregate([r for r in newbase_rows if r['symbol']==s],[p for p in newbase_parents if p['symbol']==s],sessions) for s in catalog.QUANTITY}),
            会計検査=checks,新gateengine=engine_count,新政策会計=1584,新基準政策会計=66,合計会計=1650,
            元paper再計算=0,旧engine再生=0,原book=0,API=0,source開始終端一致=True,経過秒=time.monotonic()-started))
    except Exception:
        common.write(common.HERE/'finance/False.json',dict(全合格=False,原因=traceback.format_exc(),完了会計=len(checks),engine再生=engine_count,自動再開始=False));raise


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--freeze',action='store_true');parser.add_argument('--root-trial-registered',action='store_true')
    parser.add_argument('--registry',type=lambda p:common.ROOT/p,default=common.ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/data/trials.json')
    args=parser.parse_args();assert args.freeze!=args.root_trial_registered
    if args.freeze:freeze()
    else:run(args.registry)
