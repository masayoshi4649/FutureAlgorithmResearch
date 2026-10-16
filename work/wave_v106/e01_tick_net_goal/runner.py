"""元GU実注文を再利用し、登録後だけ一呼値料金差引目標六政策を一回会計する。"""

import argparse
from collections import Counter
from datetime import datetime,timezone
import gzip
import hashlib
import json
import pickle
import socket
import time

import numpy as np

import accounting
import common
import daily
import policy


GU_SOURCE=common.ROOT/'work/wave_v106/e01_trade_gate/finance/結果.json'
BUDGET_SOURCE=common.ROOT/'work/wave_v106/e01_trade_budget/finance/結果.json'
INPUT=common.ROOT/'work/wave_v106/e01_trade_gate/全33場のE01取引更新準備.json'
ARTIFICIAL=common.HERE/'一呼値料金差引目標の最小結合人工.json'
FIXED=common.HERE/'金融前の固定.json'
FIELDS=('収支変化','避けた基準損失','失った基準利益','共通入口の出口変化','新たな入口の収支')


def sources() -> dict:
    """
    機能: 私有exact会計・固定円目標wrapper・driver・人工を結果前に指紋化する。
    引数: なし。
    返り値: dict[str,str]は根相対sourceとSHA256。金融素材の再hashはしない。
    """
    return {p.relative_to(common.ROOT).as_posix():common.digest(p) for p in [common.HERE/n for n in
        ('common.py','daily.py','accounting.py','policy.py','runner.py','artificial.py')]}


def freeze() -> None:
    """
    機能: 六政策の八部品とGU132・二比較264・入力33の一読目的を固定する。
    引数: なし。
    返り値: None。小完成JSONのみ読み、巨大台帳・入力gzip・新金融はまだ読まない。
    """
    assert common.digest(common.HERE/'daily.py')==common.digest(common.ROOT/'work/wave_v106/e01_daily/core.py')
    art=common.read(ARTIFICIAL);assert art['全合格'] and art['source_SHA256']==sources()
    original=common.read(GU_SOURCE);budget=common.read(BUDGET_SOURCE);inputmeta=common.read(INPUT)
    assert original['全合格'] and budget['全合格'] and inputmeta['全合格']
    sessions=original['sessions'];assert len(sessions)==33 and sessions==budget['sessions']==inputmeta['sessions']
    modes={}
    for mode in ('CONFIRM','VETO'):
        gu_id=f'E01_TRADE_W60_{mode}_D0_GU';gu=original['results'][gu_id]
        assert len(gu['ledgers'])==len(gu['rows'])==66
        comparisons={}
        for baseline,source,identifier in (('P1L8',original,f'E01_TRADE_W60_{mode}_D0_P1L8'),
                ('P1L4',budget,f'E01_BUDGET_W60_{mode}_D0_P1_L4')):
            value=source['results'][identifier];assert len(value['ledgers'])==len(value['rows'])==66
            comparisons[baseline]=dict(id=identifier,ledgers={v['session']+'|'+v['symbol']:v for v in value['ledgers']},rows=value['rows'],symbols=value['symbols'])
        modes[mode]=dict(GU_id=gu_id,GU_ledgers={v['session']+'|'+v['symbol']:v for v in gu['ledgers']},comparisons=comparisons)
    manifests=[dict(path=p.relative_to(common.ROOT).as_posix(),sha256=common.digest(p)) for p in (GU_SOURCE,BUDGET_SOURCE,INPUT,ARTIFICIAL)]
    configs=policy.configs();implementation=sources()
    spec=dict(entry=dict(元入口='完成W60CONFIRM/VETOのD0GU実注文132。新規公開60代理秒の票条件・次正常成行価格は不変。',
        conditions=configs,condition_count=6,接頭='日次停止初到達まで元の実新規UID・部分返済を同一に保持。'),
        management=dict(目標='初回一呼値値幅から初回往復料金を差し引いた固定円額を、場全体の費用後清算収支へ適用。',
            注意='各親が建値から一呼値順行したら退出する条件ではない。過去親損失・部分返済料金で必要順行量が変わる。',
            停止='当行までの実fill保持→以後未fill/将来返済取消→次正常quoteで残UID別清算→その場の新規停止。再参加なし。'),
        exit=dict(goal_yen=policy.goals(),goal_formula='tick×初回qty×円倍率−2×floor(初回qty×片道fee)',
            loss_budget_ticks=[4,8,16],損失計算='初回呼値数×初回qty×円倍率。',
            初到達='正常quoteの費用後清算収支が固定円目標以上又は損失予算以下になった最初の行。',
            約定='次の正常ask買/bid売で各残UIDを別注文返済。次quote悪化で黒字目標/損失上限は保証しない。'),
        allocation=dict(quantity=policy.QUANTITY,caps=policy.CAP,比較='二入口×損失4/8/16の六条件。396新政策会計、engine再生0。'),
        costs=dict(片道料金={'TOPIXmini':41.8,'NK225micro':11.},円倍率=daily.VALUE,
            料金='新規料全額を初回に課金。実部分返済はFIFO配分、残UID毎返済料はfloor。注文毎料金の旧数式を変更しない。'),
        execution=dict(新規='保存元GU実fillを使用。元paper/新規engine再生0。',
            途中='当行実fill/部分返済後にfirsthit判定。未来trade/元virtual出口を新実約定へ使用しない。',
            不正='正常気配だけで判断/新返済。時価は直前正常BBO、場末に未返済があれば不合格で架空清算なし。'),
        data=dict(sessions=sessions,input_manifests=manifests,
            read_once='保存GU132と比較P1L8/P1L4の264を各一読、取引更新入力33を各一読。',
            限界='全33既知。原受信時計不明。ラージ気配はmini/micro代理で待ち順位不明。現在snapshot/API/原NPZ/原book読取0。'),
        implementation=implementation)
    plan=dict(id=policy.TRIAL_ID,name='E01一呼値料金差引の固定純目標と損失三予算の六比較',purpose='新仮説',
        question='初回一呼値値幅から往復料を引いた純目標で早く場を終えると、小順行を日次黒字として残せるか。失った利益と勝ち赤字化も測る。',
        change='元W60二入口/D0GU/料金不変、利確円目標をTOP2082/NK780へ変更。損失4/8/16だけ三対照。',
        repeat_reason='一律小損失予算は元勝ちも切った。今回は損失だけ狭めず、呼値と料金から決まる小さな純利益目標へ変更する。',
        compares_to=['106_E01公開時の取引更新代理と二執行24対照','106_E01取引更新60秒二入口の小利益損失予算18対照'],
        prior_similar='旧P1L4/P1L8は初回一呼値の値幅そのものを純利益目標にしていた。今回の純目標は往復料控除後で異なる。',
        spec=spec,evidence=manifests,新政策会計=396,engine再生=0,元paper再生=0)
    common.write(common.HERE/'試行計画.json',plan)
    common.write(FIXED,dict(全合格=True,configs=configs,sessions=sessions,modes=modes,input_cache=inputmeta['cache'],source_SHA256=implementation,
        GU_source_SHA256=common.digest(GU_SOURCE),budget_source_SHA256=common.digest(BUDGET_SOURCE),input_SHA256=common.digest(INPUT),
        plan_SHA256=common.digest(common.HERE/'試行計画.json'),GU一読=132,比較一読=264,input一読=33,新政策会計=396,
        engine再生=0,金融前巨大素材読取=0,新金融再生=0))
    print('固定純目標TOP2082/NK780、六政策396会計の八部品を保存。根登録待ち。')


def load(item: dict) -> dict:
    """
    機能: 保存台帳又は入力の同bytesを一回読み、登録済み指紋と照合する。
    引数: item(dict)はroot相対path/SHA256。
    返り値: dictは保存入力。原板・原NPZ・現在snapshotを読まない。
    """
    path=common.ROOT/item['path'];assert path.resolve().is_relative_to((common.ROOT/'work').resolve())
    saved=path.read_bytes();assert hashlib.sha256(saved).hexdigest()==item['SHA256']
    return pickle.loads(gzip.decompress(saved))


def run() -> None:
    """
    機能: 根の完全登録後だけ六政策を保存GU注文から会計し、二基準五寄与を保存する。
    引数: なし。
    返り値: None。新規engineは0、失敗はFalseを保持し自動再実行しない。
    """
    fixed=common.read(FIXED);plan=common.read(common.HERE/'試行計画.json')
    assert fixed['source_SHA256']==sources() and fixed['configs']==policy.configs()
    assert plan['spec']['implementation']==fixed['source_SHA256']
    assert common.digest(common.HERE/'試行計画.json')==fixed['plan_SHA256']
    assert common.digest(GU_SOURCE)==fixed['GU_source_SHA256'] and common.digest(BUDGET_SOURCE)==fixed['budget_source_SHA256'] and common.digest(INPUT)==fixed['input_SHA256']
    registry=common.read(common.ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/data/trials.json')['trials']
    matched=[t for t in registry if t['id']==policy.TRIAL_ID];assert len(matched)==1 and matched[0]['spec']==plan['spec']
    assert not (common.HERE/'finance').exists()
    common.write(common.HERE/'finance/開始.json',dict(時刻=datetime.now(timezone.utc).isoformat(),新政策会計=396,engine再生=0))
    rows={c['id']:[] for c in fixed['configs']};parents={i:[] for i in rows};ledgers={i:[] for i in rows};differences={i:[] for i in rows}
    counts=Counter();started=time.monotonic()
    try:
        for session in fixed['sessions']:
            packet=load(fixed['input_cache'][session]);counts['input一読']+=1
            for symbol in ('TOPIX','NK225'):
                quotes=packet['accounts'][symbol]['quotes'];n=len(quotes['bid'])
                for mode in ('CONFIRM','VETO'):
                    binding=fixed['modes'][mode];key=session+'|'+symbol
                    original=accounting.dense(load(binding['GU_ledgers'][key]),n);counts['GU一読']+=1
                    base=daily.reconstruct((session,symbol),original['orders'],original['order_uids'],quotes)
                    for name in ('equity_yen','liquidation_yen','reserved_exit_fees','long_qty','short_qty','cumulative_fees'):
                        np.testing.assert_allclose(base[name],original[name],atol=1e-7,rtol=0)
                    assert base['summary']==original['summary']
                    baselines={}
                    for baseline in ('P1L8','P1L4'):
                        baselines[baseline]=accounting.dense(load(binding['comparisons'][baseline]['ledgers'][key]),n);counts['比較一読']+=1
                    for config in [c for c in fixed['configs'] if c['mode']==mode]:
                        identifier=config['id'];fresh=policy.apply(base,quotes,config);counts['新政策会計']+=1
                        path=common.HERE/f'finance/ledgers/{identifier}/{session}_{symbol}.pkl.gz';common.write(path,accounting.stored(fresh,n))
                        ledgers[identifier].append(dict(session=session,symbol=symbol,path=path.relative_to(common.ROOT).as_posix(),SHA256=common.digest(path)))
                        rows[identifier].append(fresh['summary']);parents[identifier].extend(dict(**p,session=session,symbol=symbol) for p in fresh['parent'])
                        differences[identifier].append(dict(session=session,symbol=symbol,control=fresh['control'],
                            baseline_controls={b:v.get('control') for b,v in baselines.items()},
                            comparisons={b:accounting.compare(v,fresh) for b,v in baselines.items()}))
                    del original,base,baselines
            del packet
            print(json.dumps(dict(完了場=session,件数=dict(counts)),ensure_ascii=False),flush=True)
        assert counts==Counter(input一読=33,GU一読=132,比較一読=264,新政策会計=396)
        assert sources()==fixed['source_SHA256']
        results={i:dict(rows=rows[i],ledgers=ledgers[i],symbols={s:accounting.aggregate([r for r in rows[i] if r['symbol']==s],[p for p in parents[i] if p['symbol']==s]) for s in ('TOPIX','NK225')}) for i in rows}
        diagnosis={i:{b:{s:dict(**{f:sum(r['comparisons'][b][f] for r in differences[i] if r['symbol']==s) for f in FIELDS},
            元勝ち親が赤字化=sum(len(r['comparisons'][b]['元勝ち親が赤字化']) for r in differences[i] if r['symbol']==s),
            元負け親が黒字化=sum(len(r['comparisons'][b]['元負け親が黒字化']) for r in differences[i] if r['symbol']==s))
            for s in ('TOPIX','NK225')} for b in ('P1L8','P1L4')} for i in rows}
        common.write(common.HERE/'finance/結果.json',dict(全合格=True,sessions=fixed['sessions'],configs=fixed['configs'],results=results,diagnosis=diagnosis,各場寄与=differences,
            source_SHA256=fixed['source_SHA256'],source開始終端一致=True,read_counts=dict(counts),新政策会計=396,
            engine再生=0,元paper再計算=0,原NPZ読取=0,現在snapshot読取=0,原book読取=0,API取得=0,経過秒=time.monotonic()-started))
    except BaseException as error:
        common.write(common.HERE/'finance/False.json',dict(全合格=False,例外=repr(error),完了件数=dict(counts),自動再実行=False));raise


def main() -> None:
    """
    機能: source/八部品固定又は根登録後の一回政策会計をCLIで選ぶ。
    引数: --freeze/--root-trial-registered(bool)は互いに排他的。
    返り値: None。ネットワーク/実注文は禁止する。
    """
    parser=argparse.ArgumentParser();modes=parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--freeze',action='store_true');modes.add_argument('--root-trial-registered',action='store_true');args=parser.parse_args()
    if args.freeze:freeze();return
    def denied(*args: object,**kwargs: object) -> None:
        """
        機能: 保存政策会計からの通信を例外で拒否する。
        引数: args/kwargs(object)は通信要求。
        返り値: None。通信は行わない。
        """
        raise RuntimeError('固定保存実注文のみ、API禁止')
    socket.socket.connect=denied;socket.create_connection=denied;run()


if __name__=='__main__':main()
