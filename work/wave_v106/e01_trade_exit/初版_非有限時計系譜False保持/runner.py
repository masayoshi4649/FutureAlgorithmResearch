"""反対票と損失の同時条件6政策を結果前固定し、根登録後だけ保存GUから会計する。"""

import argparse
from collections import Counter
import gc
import time
import traceback

import numpy as np

import common
import catalog
import daily
import data
import policy
import prepare
import storage

FIELDS=('収支変化','避けた基準損失','失った基準利益','共通入口の出口変化','新たな入口の収支')


def bindings(sessions: list[str]) -> dict:
    """
    機能: 保存GU/P1L8/P1L4の2入口各66台帳を小metadataだけで固定する。
    引数: sessions(list[str])は旧同33場。
    返り値: dictは保存位置・指紋・源。GU曲線の再読や新金融はしない。
    """
    gu_path=common.ROOT/'work/wave_v106/e01_trade_gate/finance/結果.json'
    budget_path=common.ROOT/'work/wave_v106/e01_trade_budget/finance/結果.json'
    gu,budget=common.read(gu_path),common.read(budget_path)
    assert gu['全合格'] and budget['全合格'] and gu['sessions']==budget['sessions']==sessions
    result={}
    for mode in ('CONFIRM','VETO'):
        ids=dict(GU=f'E01_TRADE_W60_{mode}_D0_GU',P1L8=f'E01_TRADE_W60_{mode}_D0_P1L8',P1L4=f'E01_BUDGET_W60_{mode}_D0_P1_L4')
        result[mode]={}
        for key,id in ids.items():
            root=budget if key=='P1L4' else gu;case=root['results'][id]
            assert len(case['rows'])==len(case['ledgers'])==66
            items={i['session']+'|'+i['symbol']:i for i in case['ledgers']};assert len(items)==66
            result[mode][key]=dict(id=id,ledgers=items,rows=case['rows'])
    return result


def freeze() -> None:
    """
    機能: 全normal票と人工・旧GU単一方向契約・保存対照を完全8部品へ結ぶ。
    引数: なし。
    返り値: None。根のcheck/register/金融開始を実行しない。
    """
    meta=common.read(common.HERE/'全33場の保有中取引更新票.json')
    art=common.read(common.HERE/'全normal票と逆票損失退出の人工検査.json')
    assert meta['全合格'] and art['全合格'] and meta['source_SHA256']==art['source_SHA256']==common.source_hashes()
    bound=bindings(meta['sessions']);manifests=[dict(path=p.relative_to(common.ROOT).as_posix(),sha256=common.digest(p))
        for p in (common.HERE/'全33場の保有中取引更新票.json',common.HERE/'入力測定前の固定.json',
                  common.HERE/'全normal票と逆票損失退出の人工検査.json',
                  common.ROOT/'work/wave_v106/e01_trade_gate/finance/結果.json',
                  common.ROOT/'work/wave_v106/e01_trade_budget/finance/結果.json')]
    spec=dict(entry=dict(保存GU='元W60 CONFIRM/VETOのD0実GU132。実入口/UID/費用/元部分返済は不変更。',
                        入口閾値='CONFIRM既知2票以上side釣合>=.25、VETO既知2票以上side釣合<=−.25だけ拒否。'),
        management=dict(条件=catalog.configs(),追加退出='当行実fill/部分返済後に残玉あり、当時W票known/2票以上/持ちside釣合<=−.25、かつ全口座fee清算<=−4呼値のAND。',
                        未知='追加退出なし。P1利益目標/hard8は維持。flat/未fill/返済済親の方向を使わない。',
                        初先着='正常行でP1又はhard8又はAND早期条件の最初のrow。hard8と早期が同時ならhard8の理由を記録。'),
        exit=dict(profit_ticks=1,hard_loss_ticks=8,opposing_vote_loss_ticks=4,
                  注文='判断までの実注文を保持、次正常quoteで残UID毎別返済、その場停止。',
                  比較='P1L8=追加退出なし、P1L4=4tick価格損失のみ、新6=反対票かつ4tick。保有中の逆票だけの退出は未測定。'),
        allocation=dict(quantity=catalog.QUANTITY,caps=catalog.CAP,比較='6独立政策×66=396。新規engine/元paper再生0。'),
        costs=dict(片道料金=daily.FEE,円倍率=daily.VALUE,方式='実注文単位floor、entry upfront、部分返済FIFO、残UID別floor料を清算時価から引く。'),
        execution=dict(入口='保存実GUのD0買ask/売bidを同原行保持。',
                       返済='判断rowより後の最初qokでUID指定の残qty。判断後票が戻っても予約取消なし。',
                       単一方向='固定GU全新規fillはinventory.sum==0 assert、役割0、返済減量のみ。実GUI132正式合格による源契約。新会計でも混在なしassert。'),
        data=dict(sessions=meta['sessions'],input_manifests=manifests,
                  用途='公開候補票を保有中へ流用せず、修正votes52edのscalar同値full normal票を新目的で測った。',
                  時計='原seq以下のCurrentPriceTime代理窓。未来同clock後半/逆時計/volumeunknownを支持へ補完しない。',
                  範囲='全33既知、rawNPZ66/旧input33を各1読済み。原book/current/API0。'),
        implementation=common.source_hashes())
    plan=dict(id=catalog.TRIAL_ID,name='保有中の反対取引更新と損失4呼値を同時に認めた時だけ降りる',purpose='新仮説',
        question='全時点L4の勝ち喪失を、実残玉の反対票が強まった場面だけの退出で減らせるか。',
        change='入口とP1/hard8は固定。保有中のW10/30/60反対票 AND 4tick損失だけ追加。',
        repeat_reason='L2/L4一律停止は全新16で両商品赤字。損失後の反対更新の当時条件を追加する別仮説。結果後に閾値変更しない。',
        compares_to=['106_E01公開時の取引更新代理と二執行24対照','106_E01取引更新60秒二入口の小利益損失予算18対照'],
        spec=spec,新政策会計=396,engine再生=0,元paper再生=0,
        limitations=['逆票単独の途中退出は未測定。P1L8をその代理対照と呼ばない。',
                     '票は公表出来高正増行Last対直前BBOの1更新1票、真の方向別約定量ではない。',
                     '損失閾値は予約判断基準。次気配悪化で4/8呼値を超過し得る。'])
    common.write(common.HERE/'試行計画.json',plan)
    common.write(common.HERE/'金融前の固定.json',dict(全合格=True,source_SHA256=common.source_hashes(),configs=catalog.configs(),
        sessions=meta['sessions'],bindings=bound,計画SHA256=common.digest(common.HERE/'試行計画.json'),正式金融=0,新政策会計=396))
    print('途中反対票AND損失6条件を固定。根登録/金融開始待ち。',flush=True)


def run() -> None:
    """
    機能: 根登録後に保存GU接頭から6政策396を一回会計し、二対照の寄与を残す。
    引数: なし。
    返り値: None。金融engine・paper・原NPZ/APIを再生・読取しない。
    """
    fixed=common.read(common.HERE/'金融前の固定.json');plan=common.read(common.HERE/'試行計画.json')
    assert fixed['source_SHA256']==common.source_hashes()==plan['spec']['implementation']
    assert common.digest(common.HERE/'試行計画.json')==fixed['計画SHA256']
    registry=common.read(common.ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/data/trials.json')['trials']
    registered=[t for t in registry if t['id']==catalog.TRIAL_ID];assert len(registered)==1 and registered[0]['spec']==plan['spec']
    for i in plan['spec']['data']['input_manifests']:assert common.digest(common.ROOT/i['path'])==i['sha256']
    assert not (common.HERE/'finance').exists()
    common.write(common.HERE/'finance/開始.json',dict(正式1回=True,source_SHA256=fixed['source_SHA256'],時刻=time.time(),新政策会計=396,engine再生=0))
    rows={c['id']:[] for c in fixed['configs']};parents={i:[] for i in rows};ledgers={i:[] for i in rows}
    diff={i:{b:[] for b in ('P1L8','P1L4')} for i in rows};reads=Counter();started=time.monotonic()
    try:
        for session in fixed['sessions']:
            packet=data.load_session(session);reads['保有票cache読取']+=1
            for symbol in ('TOPIX','NK225'):
                account=packet['accounts'][symbol];q=account['quotes'];n=len(q['bid']);key=session+'|'+symbol
                for mode in ('CONFIRM','VETO'):
                    b=fixed['bindings'][mode];gu=storage.dense(prepare.load(b['GU']['ledgers'][key]),n);reads['GU台帳読取']+=1
                    base=daily.reconstruct((session,symbol),gu['orders'],gu['order_uids'],q)
                    assert base['summary']==gu['summary']
                    for name in ('equity_yen','liquidation_yen','long_qty','short_qty','reserved_exit_fees'):
                        np.testing.assert_allclose(base[name],gu[name],atol=1e-7,rtol=0.)
                    originals={k:prepare.load(b[k]['ledgers'][key]) for k in ('P1L8','P1L4')};reads['比較台帳読取']+=2
                    for config in (c for c in fixed['configs'] if c['mode']==mode):
                        id=config['id'];fresh=policy.apply_policy(base,q,account['votes'][str(config['window_seconds'])],config)
                        reads['新政策会計']+=1;rows[id].append(fresh['summary'])
                        parents[id].extend(dict(**p,session=session,symbol=symbol) for p in fresh['parent'])
                        for comparison_name in originals:diff[id][comparison_name].append(dict(session=session,symbol=symbol,control=fresh.get('control'),**storage.compare(originals[comparison_name],fresh)))
                        path=common.HERE/f'finance/ledgers/{id}/{session}_{symbol}.pkl.gz';common.write(path,storage.stored(fresh,n))
                        ledgers[id].append(dict(session=session,symbol=symbol,path=path.relative_to(common.ROOT).as_posix(),SHA256=common.digest(path)))
                    del gu,base,originals
            del packet;gc.collect();print(session+' 途中票6政策完了',flush=True)
        assert reads['新政策会計']==396 and common.source_hashes()==fixed['source_SHA256']
        results={i:dict(rows=rows[i],ledgers=ledgers[i],symbols={s:storage.aggregate([r for r in rows[i] if r['symbol']==s],[p for p in parents[i] if p['symbol']==s]) for s in ('TOPIX','NK225')}) for i in rows}
        diagnosis={i:{b:{s:dict(**{k:sum(d[k] for d in diff[i][b] if d['symbol']==s) for k in FIELDS},
            元勝ち親が赤字化=sum(len(d['元勝ち親が赤字化']) for d in diff[i][b] if d['symbol']==s)) for s in ('TOPIX','NK225')} for b in diff[i]} for i in rows}
        common.write(common.HERE/'finance/結果.json',dict(全合格=True,sessions=fixed['sessions'],configs=fixed['configs'],results=results,
            diagnosis=diagnosis,各場寄与=diff,read_counts=dict(reads),新政策会計=396,engine再生=0,元paper再生=0,
            原NPZ読取=0,原book=0,API=0,source開始終端一致=True,source_SHA256=fixed['source_SHA256'],経過秒=time.monotonic()-started))
    except Exception:
        common.write(common.HERE/'finance/False.json',dict(全合格=False,原因=traceback.format_exc(),完了件数=dict(reads),自動再開始=False));raise


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--freeze',action='store_true');parser.add_argument('--root-trial-registered',action='store_true')
    args=parser.parse_args();assert args.freeze!=args.root_trial_registered
    if args.freeze:freeze()
    else:run()
