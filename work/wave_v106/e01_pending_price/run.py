"""固定12政策を登録後だけ全33場で再生する。元紙上の再計算は行わない。"""

import argparse
import gc
import time
import traceback

import numpy as np

import catalog
import common
import data
import engine


daily=common.module('106待機取消の不変UID会計',common.ROOT/'work/wave_v106/e01_daily/core.py')


def aggregate(rows: list[dict], parents: list[dict], sessions: list[str]) -> dict:
    """
    機能: 同じ商品の全33保存親と場損益を、金額と枚数で足し合わせる。
    引数: rows/parents(list[dict])、sessions(list[str])は会計と固定場順。
    返り値: dictは利益損失・活動・中央値・大勝ち除外。無取引を勝ちとしない。
    """
    assert len(rows)==len(sessions) and {r['session'] for r in rows}==set(sessions)
    totals=daily.metric([p['収支'] for p in parents]);active=[r for r in rows if r['親数']>0]
    positive=[r for r in rows if r['収支']>0];negative=[r for r in rows if r['収支']<0]
    ordered=sorted(rows,key=lambda r:r['収支'],reverse=True)
    return dict(**totals,全場=len(rows),活動場=len(active),黒字場=len(positive),赤字場=len(negative),
        無取引場=len(rows)-len(active),中央値=float(np.median([r['収支'] for r in rows])),
        最大場損失=max([0.]+[-r['収支'] for r in rows]),
        赤字率=len(negative)/len(active) if active else None,
        平均赤字=float(-np.mean([r['収支'] for r in negative])) if negative else 0.,
        最大利益場除外収支=totals['収支']-ordered[0]['収支'],
        上位3利益場除外収支=totals['収支']-sum(r['収支'] for r in ordered[:3]),
        最大利益場の全利益場寄与=ordered[0]['収支']/sum(r['収支'] for r in positive) if positive else None,
        費用=sum(r['費用'] for r in rows),新規枚数=sum(r['新規枚数'] for r in rows),
        勝ち枚数=sum(r['勝ち枚数'] for r in rows),負け枚数=sum(r['負け枚数'] for r in rows),
        零枚数=sum(r['零枚数'] for r in rows),全33黒字=len(positive)==len(rows))


def delta(before: dict, after: dict) -> dict:
    """
    機能: 実紙上親cidで照合し、取消が生む入口集合の変化と出口差を分ける。
    引数: before/after(dict)は完結親会計。
    返り値: dictは収支差と5寄与。新実入口も生じ得るのでゼロを仮定しない。
    """
    a={p['親']:p for p in before['parent']};b={p['親']:p for p in after['parent']}
    removed=a.keys()-b.keys();common_keys=a.keys()&b.keys();added=b.keys()-a.keys()
    avoid=sum(-a[k]['収支'] for k in removed if a[k]['収支']<0)
    missed=sum(a[k]['収支'] for k in removed if a[k]['収支']>0)
    exits=sum(b[k]['収支']-a[k]['収支'] for k in common_keys);new=sum(b[k]['収支'] for k in added)
    net=after['summary']['収支']-before['summary']['収支']
    assert np.isclose(net,avoid-missed+exits+new,atol=1e-5)
    return dict(収支変化=net,避けた基準損失=avoid,失った基準利益=missed,共通入口の出口変化=exits,新たな入口の収支=new)


def freeze() -> None:
    """
    機能: 純価格観測の人工と入力を結び、金融前に12政策の試行計画を保存する。
    引数: なし。
    返り値: None。金融は登録通知とflagを別に必要とする。
    """
    meta=common.read(common.HERE/'全33場の待機取消準備.json')
    art=common.read(common.HERE/'待機指値取消と元注文接続の人工検査.json')
    fixed=common.read(common.HERE/'入力事前固定.json')
    assert meta['全合格'] and art['全合格'] and meta['新金融']==0
    for path,sha in art['実装SHA256'].items():
        assert common.digest(common.ROOT/path)==sha
    manifests=[dict(path=p.relative_to(common.ROOT).as_posix(),sha256=common.digest(p)) for p in
        (common.HERE/'全33場の待機取消準備.json',common.HERE/'待機指値取消と元注文接続の人工検査.json',
         common.ROOT/'work/wave_v106/e01_pair_filter/UNKNOWN観測定義と原fieldの監査.json')]
    spec=dict(entry=dict(紙上='元E01 GUの保存66 feed。追加参加条件なし。',指値='Last-side*0.2ATR、買floor/売ceilで元tick丸め。公開行は約定不可。',
            枚数={'TOPIX':5,'NK225':10}),
        management=dict(条件=catalog.CONFIGS,未約定取消='相手のみ、または自己相手双方の当時両気配が注文方向と逆へ1呼値以上進むと永久取消',
            同行順序='quiet/期限→前行予約返済→既指値到達fill→なお未約定なら当行pair取消→当行紙上feed。同行fillを消さない。',
            未知='保留。自己一時逆行のみでは取消しない。取消後同じ指値は復活しない。',
            選定='価格観測の論理を財務前に修正。gapのみdraftは未金融として保持。'),
        exit=dict(元GU='紙上部分/全返済判断より後の最初の正常BBOで返済。初回紙上返済は未約定永久取消。',
            P1L8='当時正常BBOの口座清算損益（残UID別fee控除）が1呼値初回金額へ到達、又は8呼値損失予算へ到達→次正常BBOでUID別全返済→その場の新規停止。',
            新途中条件='約定後のpair早期返済は追加しない。元Uquietとセッション内期限を保持。'),
        allocation=dict(初回={'TOPIX':5,'NK225':10},片方向上限={'TOPIX':10,'NK225':20},比較='12条件独立、合算配分なし'),
        costs=dict(片道料金={'TOPIXmini':41.8,'NK225micro':11.},円倍率={'TOPIX':1000.,'NK225':10.},
            料金='各実注文floor。entry全額先払い、部分返済FIFO。UID別残返済料を個別にfloor。'),
        execution=dict(気配='保存同原行bid/ask。買ask、売bid。',
            取消判断='未約定中の当行公表まで。実受信時計は未観測。前行までの到達fillを遡及取消しない。',
            price_qual='端点の有限正bid/ask・ask>bid・場内priceTimeをfield自身で判定。原seq/clock欠測逆行はUNKNOWN。',
            price_window='W10/30/60のfirst新最大公表。自己は当原行以下、相手はstrictpast/asof年齢15秒以内。基準はsourceTime-W以下最新、余分なage15秒以内。',
            excluded_qual='数量/出来高fullqualified、混合PRICE_RESET32/64、途中非normalBBO、publicpricegapは端点差の欠測条件に使わない。',
            unknown_endpoint='非normal端点のNaNを次の正常原行で救済しない。',
            observation_limit='測るのは二つの既知端点差だけ。経路TV/最大逆行/補充/成行量へ解釈を広げない。'),
        data=dict(sessions=meta['sessions'],input_manifests=manifests,
            baseline='保存L_D20_BBOと完了P1L8。元紙上/元金融の再生0。',
            input_fixed=common.digest(common.HERE/'入力事前固定.json'),
            未知確認='全33は既知。結果後の条件探索と未来利益の入力は行わない。'),
        implementation=common.source_hashes())
    plan=dict(id=catalog.TRIAL_ID,name='仮説が逆転した未約定E01指値だけを撤回する純価格観測12対照',purpose='新仮説',
        question='押し戻り待ちの有利指値が方向反転後に残る初期損失を、当時の二市場価格差で減らせるか。',
        change='入場根拠/ATR指値/GUは固定。未約定時の逆方向永久取消を追加。価格観測はquantity/volumeと独立、pricegapを受信断絶としない。',
        repeat_reason='古い指値が両市場上向きになってから売りで約定する保存事例を確認。従来の入場フィルタ/保有撤回とは別仮説。未金融のgap-only draftは観測定義監査で保留。',
        compares_to=['106_E01比較の金額残差許容統一と再開','106_E01の小利益目標とUID別場内停止12対照'],evidence=manifests,
        limitations=['全33既知、未知性能は未確認。ラージBBOをmini/microの価格代理として使用。',
            '真の板受信時計と両市場受信順は不明。priceTime first公表を保守的代理として保持。',
            '取消後に反転前の指値を復活せず、取り逃す元利益も全額示す。'],spec=spec)
    common.write(common.HERE/'試行計画.json',plan)
    common.write(common.HERE/'金融事前固定.json',dict(全合格=True,実装SHA256=common.source_hashes(),
        計画SHA256=common.digest(common.HERE/'試行計画.json'),正式金融=0,実条件=12,実口座=792,
        元paper再生=0,元基準再生=0,未知確認=0))
    print('純価格待機取消12政策を固定。登録通知待ち。',flush=True)


def run(registry) -> None:
    """
    機能: 登録後に六つの取消スケジュールと二出口を全33場で再生する。
    引数: registry(Path)は根登録の試行正本。
    返り値: None。元paper再計算せず、全後続保存feedを新状態で処理する。
    """
    assert not (common.HERE/'finance/結果.json').exists() and not (common.HERE/'finance/失敗.json').exists()
    plan=common.read(common.HERE/'試行計画.json');fixed=common.read(common.HERE/'金融事前固定.json')
    assert any(t['id']==catalog.TRIAL_ID for t in common.read(registry)['trials'])
    assert common.source_hashes()==fixed['実装SHA256']==plan['spec']['implementation']
    assert common.digest(common.HERE/'試行計画.json')==fixed['計画SHA256']
    for item in plan['spec']['data']['input_manifests']:
        assert common.digest(common.ROOT/item['path'])==item['sha256']
    inputfixed=common.read(common.HERE/'入力事前固定.json');qspec=inputfixed['quotes']
    assert common.digest(common.ROOT/qspec['path'])==qspec['SHA256'];quotes=common.read(common.ROOT/qspec['path'])
    sessions=plan['spec']['data']['sessions'];rows={c['id']:[] for c in catalog.CONFIGS}
    parents={i:[] for i in rows};ledgers={i:[] for i in rows};control={i:[] for i in rows};differences={i:[] for i in rows}
    checkpoints=[];started=time.monotonic()
    common.write(common.HERE/'finance/開始.json',dict(全合格=True,時刻=time.time(),正式1回=True,
        実装SHA256=fixed['実装SHA256'],計画SHA256=fixed['計画SHA256']))
    try:
        for session in sessions:
            value=data.load_session(session)
            for symbol in ('TOPIX','NK225'):
                q=quotes[session,symbol];account=value['accounts'][symbol];record=account['normal_record']
                for name in ('seq','time_s'):
                    np.testing.assert_array_equal(record[name],q[name])
                relative=f'ledgers/L_D20_BBO/{session}_{symbol}.pkl.gz';path=common.REFERENCE/relative
                assert common.digest(path)==inputfixed['baseline'][relative];base=common.read(path)
                daily_source=common.ROOT/f'work/wave_v106/e01_daily/finance/ledgers/E01_DAILY_P1_L8/{session}_{symbol}.pkl.gz'
                daily_before=common.read(daily_source)
                for mode in ('N','P'):
                    for window in (10,30,60):
                        observed=account['windows'][str(window)]
                        values=engine.simulate(q['time_s'],record['price'],q['bid'],q['ask'],q['quote_valid'],
                            account['feed'],account['quiet'],account['quiet_force'],record['limit'],
                            daily.CAP[symbol],record['tick'],.2,False,observed['own']['direction'],observed['peer']['direction'],
                            1 if mode=='N' else 2)
                        original=daily.reconstruct((session,symbol),values[0],values[5],q)
                        for exit_id in ('GU','P1L8'):
                            config=next(c for c in catalog.CONFIGS if c['mode']==mode and c['window_seconds']==window and c['exit']==exit_id)
                            ident=config['id'];new=original if exit_id=='GU' else daily.apply_policy(original,q,dict(profit_ticks=1,loss_ticks=8))
                            proof=values[8];cancels=proof[proof[:,1]==5]
                            new=dict(new,case=config,limit_events=proof,cancel_events=cancels,
                                保存paperSHA256=account['paper_SHA256'],price_window=window,price_only=True)
                            rows[ident].append(new['summary']);parents[ident].extend(dict(**p,symbol=symbol,session=session) for p in new['parent'])
                            before=base if exit_id=='GU' else daily_before
                            difference=dict(session=session,symbol=symbol,**delta(before,new));differences[ident].append(difference)
                            detail=[]
                            for cancel in cancels:
                                row=int(cancel[0]);pubown=int(observed['own']['public_index'][row]);pubpeer=int(observed['peer']['public_index'][row])
                                detail.append(dict(判断行=row,判断原seq=int(q['seq'][row]),価格時計=float(q['time_s'][row]),
                                    紙上親=int(cancel[2]),公開行=int(cancel[3]),指値方向=int(cancel[4]),指値価格=float(cancel[8]),
                                    own_public_index=pubown,peer_public_index=pubpeer,
                                    own_direction=int(observed['own']['direction'][row]),peer_direction=int(observed['peer']['direction'][row])))
                            control[ident].append(dict(session=session,symbol=symbol,取消=detail,
                                日次停止=new.get('control',{}),寄与=difference))
                            destination=common.HERE/f'finance/ledgers/{ident}/{session}_{symbol}.pkl.gz';common.write(destination,new)
                            ledgers[ident].append(dict(session=session,symbol=symbol,path=destination.relative_to(common.ROOT).as_posix(),SHA256=common.digest(destination)))
                            checkpoints.append(dict(id=ident,session=session,symbol=symbol,全会計合格=True))
                        del values,original
                print(session+' '+symbol+' 純価格待機取消12政策完了',flush=True)
                del base,daily_before
                gc.collect()
        results={i:dict(rows=rows[i],symbols={s:aggregate([r for r in rows[i] if r['symbol']==s],
            [p for p in parents[i] if p['symbol']==s],sessions) for s in ('TOPIX','NK225')},ledgers=ledgers[i]) for i in rows}
        diagnosis={i:{s:{key:sum(r[key] for r in differences[i] if r['symbol']==s) for key in
            ('収支変化','避けた基準損失','失った基準利益','共通入口の出口変化','新たな入口の収支')}
            for s in ('TOPIX','NK225')} for i in rows}
        assert len(checkpoints)==792 and common.source_hashes()==fixed['実装SHA256']
        common.write(common.HERE/'finance/結果.json',dict(全合格=True,sessions=sessions,configs=catalog.CONFIGS,
            results=results,diagnosis=diagnosis,取消と日次停止=control,会計検査=checkpoints,
            元paper再生=0,元金融再生=0,新取消engine口座=396,実政策口座=792,新cache読取=33,
            正式1回=True,source開始終端一致=True,原本=0,API=0,未知確認=0,経過秒=time.monotonic()-started))
        print('純価格待機取消12政策の全33会計完了',flush=True)
    except Exception:
        common.write(common.HERE/'finance/失敗.json',dict(全合格=False,原因=traceback.format_exc(),
            完成口座=len(checkpoints),自動再実行=False,既完成台帳保持=True))
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='E01待機指値の純価格逆方向永久取消')
    parser.add_argument('--freeze',action='store_true')
    parser.add_argument('--root-trial-registered',action='store_true')
    parser.add_argument('--registry',type=lambda p:common.ROOT/p,
        default=common.ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/data/trials.json')
    args=parser.parse_args()
    if args.freeze:
        assert not args.root_trial_registered
        freeze()
    else:
        assert args.root_trial_registered,'根の登録通知前は正式金融を実行しない'
        run(args.registry)
