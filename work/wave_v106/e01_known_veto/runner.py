"""十分な観測を要求する逆票見送り二出口を結果前固定し、根登録後だけ一回再生する。"""

import argparse
from collections import Counter
import gc
import time
import traceback

import numpy as np
import common
import catalog
import data
import interface
import storage


SOURCE=common.ROOT/'work/wave_v106/e01_trade_gate'
ART=common.HERE/'既知逆票見送りの真偽表と旧経済及び接頭の人工検査.json'
FIELDS=('収支変化','避けた基準損失','失った基準利益','共通入口の出口変化','新たな入口の収支')


def check_clones() -> dict:
    """
    機能: 金融数学と不変接口の私有コピーを、旧sourceの同bytesへ照合する。
    引数: なし。
    返り値: dictは確認済み旧source指紋。旧JITをimport/再コンパイルしない。
    """
    names=('common.py','engine.py','order_kernel.py','daily.py','interface.py','old_engine.py')
    result={}
    for name in names:
        old,new=SOURCE/name,common.HERE/name;assert old.read_bytes()==new.read_bytes(),name
        result[old.relative_to(common.ROOT).as_posix()]=common.digest(old)
    return result


def freeze() -> None:
    """
    機能: 新規採否だけの二条件・既input33・同exit保存VETO対照を八部品へ束縛する。
    引数: なし。
    返り値: None。大型cache/ledgerは読まず、根登録又は金融を実行しない。
    """
    assert not (common.HERE/'試行計画.json').exists();clones=check_clones()
    meta_path=SOURCE/'全33場のE01取引更新準備.json';result_path=SOURCE/'finance/結果.json'
    meta,previous,art=(common.read(p) for p in (meta_path,result_path,ART))
    assert meta['全合格'] and previous['全合格'] and art['全合格'] and art['source_SHA256']==common.sources()
    sessions=meta['sessions'];assert sessions==previous['sessions'] and len(sessions)==33
    baseline={}
    for c in catalog.configs():
        value=previous['results'][c['baseline_id']];assert len(value['rows'])==len(value['ledgers'])==66
        assert {(i['session'],i['symbol']) for i in value['ledgers']}=={(s,y) for s in sessions for y in catalog.QUANTITY}
        baseline[c['id']]=dict(id=c['baseline_id'],rows=value['rows'],symbols=value['symbols'],
            ledgers={i['session']+'|'+i['symbol']:i for i in value['ledgers']})
    manifests=[dict(path=p.relative_to(common.ROOT).as_posix(),sha256=common.digest(p)) for p in (meta_path,result_path,ART)]
    spec=dict(entry=dict(conditions=catalog.configs(),condition_count=2,
            観測='保存W60の新規公開原行当時票。known、direction_votes>=2、side付きbalance>−.25の三条件を全て要求。',
            未知='未知又は二票未満は見送り。強い同方向を要求するCONFIRMとは異なり、弱同向/中立/弱逆向きを許す。',
            包含='公開maskのCONFIRM⊆KNOWN_VETO⊆VETO。実取引集合や実収益の包含は主張しない。'),
        management=dict(影='全後続の元paper feedを不変で順番に運転。拒否してもvcore/部分返済/親の寿命を維持。',
            公開時だけ='新規publishにだけmaskを適用。待機後追加取消/保有後票退出/取得時計修正なし。',
            実建玉='旧単一GUの実UID、FIFO部分返済、旧返済待機busy/quiet/期限を維持。'),
        exit=dict(GU='元GUの紙上部分/全返済判断後の最初正常BBO、場内返済。',
            P1L8='同じ新GUの費用後清算利益が初回一観測呼値分又は損失八呼値分へ初到達した行で判断、次正常BBOで残UID別返済して場停止。',
            円閾値={'TOPIX':{'profit':2500,'loss':20000},'NK225':{'profit':1000,'loss':8000}}),
        allocation=dict(quantity=catalog.QUANTITY,cap=catalog.CAP,engine共有=66,新政策会計=132,出口数=2),
        costs=dict(片道税込料金={'TOPIXmini':41.8,'NK225micro':11.},円倍率={'TOPIX':1000,'NK225':10},
            方式='不変daily/executeの実注文別floor、UID別残返済料、部分返済配分。'),
        execution=dict(入口='D0:offset0/unconditional、公開row当行fillなし、次正常買ask/売bid。',
            同行順='旧engineのquiet/期限取消→既予約返済/新規fill→当行paper公開。gate差以外の順序を変更しない。',
            呼値='ラージ観測TOPIX0.5pt/NK10円。実ミニ/マイクロの二呼値。実商品気配・待ち順位は未確認。'),
        data=dict(sessions=sessions,input_manifests=manifests,
            read_once='既input33の保存feed/同normal気配/当時W60特徴を正式金融開始時に各一回のみ読取。対照ledger132も各一回。',
            窓='CurrentPriceTimeの価格時計代理。候補原seq以下の訂正済み票で、真の攻撃方向/数量や受信時計ではない。',
            未使用='原板/原NPZ/現ナイト不適合取得板/API/元paper再計算は0。過去既知33を再探索する段階。'),
        implementation=common.sources())
    plan=dict(id=catalog.TRIAL_ID,name='十分な観測がある時だけ逆方向を見送るE01二出口',purpose='新仮説',
        question='強い同方向までは待たず、未知/票不足の無根拠な許可だけを消すと活動と損失の両方はどう変わるか。',
        change='W60VETOにknownかつ二票以上を追加。D0/GU/P1L8/数量/料金/約定/clockは固定。',
        repeat_reason='現24のCONFIRMとVETOの中間maskは未測定だった。保存の負け親を単に削らず後続状態を再運転する。',
        compares_to=['106_E01公開時の取引更新代理と二執行24対照'],spec=spec,
        同exit比較={c['id']:c['baseline_id'] for c in catalog.configs()},コピー同値=clones,
        counts=dict(新engine=66,新政策会計=132,保存対照ledger読取=132,既input読取=33,元paper再計算=0),
        limitations=['未知を見送ること自体は方向予測精度の改善ではない。','公開maskの包含は実取引や損益の包含を意味しない。',
            '既知33で損失診断後に追加する条件であり、未見で検証した成功とは呼ばない。',
            '現在ナイトは価格時計不適合で未測定のまま。この条件でclockを救済しない。'])
    common.write(common.HERE/'試行計画.json',plan)
    common.write(common.HERE/'金融事前固定.json',dict(全合格=True,sessions=sessions,configs=catalog.configs(),input_cache=meta['cache'],
        baseline=baseline,source_SHA256=common.sources(),計画SHA256=common.digest(common.HERE/'試行計画.json'),正式金融=0,
        大型input読取=0,旧ledger読取=0,元paper再計算=0,原NPZ読取=0,API=0))
    print('KNOWN_VETO二出口を結果前固定。root登録/金融開始待ち。',flush=True)


def run(registry: object) -> None:
    """
    機能: 根登録後だけ共有GU66を再運転し、二出口132と同exitVETO対照の五寄与を保存する。
    引数: registry(Path)は根が登録した試行台帳。
    返り値: None。大型input33各一読。失敗はFalseを保存し自動再生しない。
    """
    fixed=common.read(common.HERE/'金融事前固定.json');plan=common.read(common.HERE/'試行計画.json')
    found=[t for t in common.read(registry)['trials'] if t['id']==catalog.TRIAL_ID]
    assert len(found)==1 and found[0]['spec']==plan['spec']
    assert common.sources()==fixed['source_SHA256']==plan['spec']['implementation']
    assert fixed['計画SHA256']==common.digest(common.HERE/'試行計画.json') and check_clones()==plan['コピー同値']
    for m in plan['spec']['data']['input_manifests']:assert common.digest(common.ROOT/m['path'])==m['sha256']
    assert not (common.HERE/'finance').exists()
    common.write(common.HERE/'finance/開始.json',dict(正式1回=True,source_SHA256=fixed['source_SHA256'],新engine=66,新政策会計=132))
    configs=fixed['configs'];rows={c['id']:[] for c in configs};parents={i:[] for i in rows};ledgers={i:[] for i in rows};differences={i:[] for i in rows}
    counts=Counter();started=time.monotonic()
    try:
        for session in fixed['sessions']:
            packet=data.load(fixed['input_cache'][session]);counts['既input一読']+=1;assert packet['session']==session
            for symbol in catalog.QUANTITY:
                a=packet['accounts'][symbol];q=a['quotes'];n=len(q['bid'])
                values=interface.execute(a,configs[0]);counts['新gateengine']+=1
                for c in configs:
                    id=c['id'];fresh=interface.account_output(session,a,c,values);counts['新政策会計']+=1
                    before=data.load(fixed['baseline'][id]['ledgers'][session+'|'+symbol]);counts['対照ledger一読']+=1
                    assert before['key']==fresh['key']
                    change=storage.delta(before,fresh);oldparents={p['親']:p for p in before['parent']};newparents={p['親']:p for p in fresh['parent']}
                    turned=[dict(parent=int(p),base_net=oldparents[p]['収支'],new_net=newparents[p]['収支']) for p in oldparents.keys()&newparents.keys()
                        if oldparents[p]['収支']>0 and newparents[p]['収支']<0]
                    differences[id].append(dict(session=session,symbol=symbol,**change,元勝ち親が赤字化=turned))
                    rows[id].append(fresh['summary']);parents[id].extend(dict(**p,session=session,symbol=symbol) for p in fresh['parent'])
                    path=common.HERE/f'finance/ledgers/{id}/{session}_{symbol}.pkl.gz';common.write(path,storage.stored(fresh,n))
                    ledgers[id].append(dict(session=session,symbol=symbol,path=path.relative_to(common.ROOT).as_posix(),SHA256=common.digest(path)))
                    del before,fresh
                del values
            del packet;gc.collect();print(session+' KNOWN_VETO二出口完了',flush=True)
        assert counts==Counter(既input一読=33,新gateengine=66,新政策会計=132,対照ledger一読=132)
        assert common.sources()==fixed['source_SHA256']
        results={i:dict(rows=rows[i],ledgers=ledgers[i],symbols={s:storage.aggregate([r for r in rows[i] if r['symbol']==s],
            [p for p in parents[i] if p['symbol']==s],fixed['sessions']) for s in catalog.QUANTITY}) for i in rows}
        diagnosis={i:{s:dict(**{f:sum(d[f] for d in differences[i] if d['symbol']==s) for f in FIELDS},
            元勝ち親が赤字化=sum(len(d['元勝ち親が赤字化']) for d in differences[i] if d['symbol']==s)) for s in catalog.QUANTITY} for i in rows}
        common.write(common.HERE/'finance/結果.json',dict(全合格=True,sessions=fixed['sessions'],configs=configs,results=results,diagnosis=diagnosis,各場寄与=differences,
            counts=dict(counts),新gateengine=66,新政策会計=132,会計口座数=132,source開始終端一致=True,source_SHA256=fixed['source_SHA256'],
            元paper再計算=0,原板読取=0,原NPZ読取=0,現在入力読取=0,API=0,経過秒=time.monotonic()-started))
    except BaseException:
        common.write(common.HERE/'finance/False.json',dict(全合格=False,原因=traceback.format_exc(),自動再開始=False,counts=dict(counts)));raise


if __name__=='__main__':
    parser=argparse.ArgumentParser();m=parser.add_mutually_exclusive_group(required=True)
    m.add_argument('--freeze',action='store_true');m.add_argument('--root-trial-registered',action='store_true')
    parser.add_argument('--registry',type=lambda p:common.ROOT/p,default=common.ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/data/trials.json')
    args=parser.parse_args();freeze() if args.freeze else run(args.registry)
