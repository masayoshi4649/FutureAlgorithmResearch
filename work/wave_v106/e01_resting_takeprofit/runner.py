"""最初実建玉の利確方法十二対照を固定し、根登録後だけ会計を実行する。"""

import argparse
from collections import Counter
import statistics
import time
import traceback

import common
import policy
import prepared


def aggregate(rows: list[dict]) -> dict:
    """
    機能: 同一商品33場の一親損益・決済枚数と無取引を集計する。
    引数: rows(list[dict])は保存された場会計。
    返り値: dictは金額利益割合と活動安定性。無取引を勝ちに数えない。
    """
    assert len(rows)==33;gain=sum(r['利益'] for r in rows);loss=sum(r['損失'] for r in rows)
    active=[r for r in rows if r['親数']];positive=[r['収支'] for r in rows if r['収支']>0];negative=[-r['収支'] for r in rows if r['収支']<0]
    return dict(利益=gain,損失=loss,収支=gain-loss,利益割合=gain/(gain+loss) if gain+loss else None,
        PF=gain/loss if loss else None,全場=33,活動場=len(active),黒字場=len(positive),赤字場=len(negative),
        無取引場=33-len(active),活動黒字率=len(positive)/len(active) if active else None,中央値=statistics.median(r['収支'] for r in rows),
        上位3利益場除外収支=gain-loss-sum(sorted(positive,reverse=True)[:3]),最大場損失=max([0.]+negative),
        勝ち枚数=sum(r['勝ち枚数'] for r in rows),負け枚数=sum(r['負け枚数'] for r in rows),費用=sum(r['費用'] for r in rows),
        平均利益=statistics.mean(positive) if positive else None,平均損失=statistics.mean(negative) if negative else None,
        親数=len(active),勝ち親=len(positive),負け親=len(negative))


def freeze() -> None:
    """
    機能: 最初実新規入力・人工・十二対照を完全八部品と金融前固定へ結ぶ。
    引数: なし。
    返り値: None。根の重複照合・登録・正式金融を実行しない。
    """
    meta=common.read(common.HERE/'最初実新規と場内返済の全33入力.json')
    art=common.read(common.HERE/'常設利確と次気配返済の人工検査.json')
    assert meta['全合格'] and art['全合格'] and meta['source_SHA256']==art['source_SHA256']==common.source_hashes()
    files=[common.HERE/'最初実新規と場内返済の全33入力.json',common.HERE/'入力読取前の固定.json',common.HERE/'常設利確と次気配返済の人工検査.json']
    spec=dict(entry=dict(conditions=policy.configs(),condition_count=12,元入口='元W60CONFIRM/VETO D0GUの場最初の実newfillのみ。最小原fill順で選び勝敗で選ばない。',
        固定='元ask買/bid売の価格・枚数・paper親cid・実UID・公開判断行・fill原seq/価格時計を保持。'),
        management=dict(単一='一場一実親、初回TOP5/NK10。部分決済・追加玉・後続新規・原GU出口なし。',
            利確公開='entryfill時にE±ラージ観測1呼値を固定、entry次行以降だけ接触を観測。',
            予約='損切り又は利確成行判断を不可逆予約。後のtarget接触で損切り予約へ介入しない。'),
        exit=dict(利確二法=['常設指値:正常清算BBOがtargetへ到達した最初行で固定target全量約定を仮定。',
            '接触後成行:同じtarget接触で判断、次正常BBOで全量返済。'],停止=[4,8,16],
            損切り='建値から方向反対stop呼値初接触で判断、次正常BBO返済。fill行でstop破れなら同row判断・次row以降返済。',
            timer='旧同normal Uquiet/quiet_force又は場limitを優先。最初正常気配で全返済。元予約判断とtimer由来を別保存。'),
        allocation=dict(quantity=policy.QUANTITY,cap=policy.CAP,条件数=12,口座数=792,一場一親=True),
        costs=dict(片道税込料金=policy.FEE,円倍率=policy.VALUE,方式='新規一注文・全量返済一注文の各floor、将来の元GU部分返済料は使わない。'),
        execution=dict(観測幅=policy.TICK,実商品呼値={'TOPIXmini':.25,'NK225micro':5},
            用語='ラージ板観測1呼値TOPIX0.5pt/NK10円。実ミニ/マイクロ2呼値であり実商品1呼値の証明ではない。',
            常設='指定価格の到達全量約定を仮定する別モデル。native待ち順位/実小型商品quote不明。実戦で約定できる証明ではない。',
            成行='最初の正常bid売/ask買。注文遅延・queueは今回未モデル化。'),
        data=dict(sessions=meta['sessions'],input_manifests=[dict(path=p.relative_to(common.ROOT).as_posix(),sha256=common.digest(p)) for p in files],
            保存='GU132/input33各一読の最初newfill射影のみ。quote/record/quietを保存し原返済・後続orderを新cacheへ渡さない。',
            時計='CurrentPriceTime代理時計と原seq。真の受信時計は不明。未来正常quoteを入口選抜へ使用しない。'),
        implementation=common.source_hashes())
    plan=dict(id=policy.TRIAL_ID,name='ラージ観測一呼値の常設利確と到達後成行',purpose='新仮説',spec=spec,
        question='小利益接触後の次気配悪化を、常設指値の到達全量仮定ではどれだけ除けるか。',
        change='場全体の利益停止から、最初実建玉の固定一呼値bracketへ切り替える。一場一親。',
        repeat_reason='ticknetで接触後に1観測呼値悪化し黒字目標から赤字へ返済する実例が確認された。今回は注文方法を独立比較する。',
        compares_to=['106_E01取引更新二入口の一呼値料金差引目標6対照','106_E01公開時の取引更新代理と二執行24対照'],
        新金融=0,予定政策会計=792,入口engine再生=0,原paper再計算=0,
        limitations=['常設到達全量はモデルの仮定であり実queue検証ではない。',
            '最初の新規だけへ限定するため、元GU全場損益との差は注文方法だけの効果ではない。',
            '判断後返済の損切り幅は実損失上限ではなく、次気配gapで超過し得る。'])
    common.write(common.HERE/'試行計画.json',plan)
    common.write(common.HERE/'金融前の固定.json',dict(全合格=True,sessions=meta['sessions'],configs=policy.configs(),cache=meta['cache'],
        source_SHA256=common.source_hashes(),計画SHA256=common.digest(common.HERE/'試行計画.json'),予定会計792=792,新金融=0))
    print('常設一呼値12を金融前固定。根の登録と金融開始待ち。',flush=True)


def run() -> None:
    """
    機能: 根登録後だけ十二条件792を新単一bracketで会計し、利確二法の差を保存する。
    引数: なし。
    返り値: None。元入口engine/原GU返済/部分返済/原NPZ/APIを再生しない。
    """
    fixed=common.read(common.HERE/'金融前の固定.json');plan=common.read(common.HERE/'試行計画.json')
    assert fixed['source_SHA256']==common.source_hashes()==plan['spec']['implementation']
    assert fixed['計画SHA256']==common.digest(common.HERE/'試行計画.json')
    registry=common.read(common.ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/data/trials.json')['trials']
    found=[v for v in registry if v['id']==policy.TRIAL_ID];assert len(found)==1 and found[0]['spec']==plan['spec']
    for v in plan['spec']['data']['input_manifests']:assert common.digest(common.ROOT/v['path'])==v['sha256']
    assert not (common.HERE/'finance').exists()
    common.write(common.HERE/'finance/開始.json',dict(正式1回=True,source_SHA256=fixed['source_SHA256'],新政策会計=792,入口engine再生=0))
    rows={c['id']:[] for c in fixed['configs']};ledgers={i:[] for i in rows};comparisons=[];started=time.monotonic();counts=Counter()
    try:
        for session in fixed['sessions']:
            packet=prepared.load(fixed['cache'][session]);counts['新input読取']+=1
            for symbol,account in packet['accounts'].items():
                outputs={}
                for c in fixed['configs']:
                    r=policy.play(account,account['entries'][c['mode']],c);counts['新bracket会計']+=1;outputs[c['id']]=r
                    row=r['summary'];rows[c['id']].append(row)
                    # ----------------------------------------
                    # 単一玉の大曲線をplateau化する。元GUのstateや部分決済を混ぜない。
                    saved=dict(r)
                    for name in ('equity_yen','liquidation_yen','long_qty','short_qty'):
                        a=r[name];import numpy as np
                        idx=np.r_[0,np.flatnonzero(a[1:]!=a[:-1])+1].astype(np.int64)
                        saved[name]=dict(rows=idx,values=a[idx],length=len(a))
                    path=common.HERE/f'finance/ledgers/{c["id"]}/{session}_{symbol}.pkl.gz';common.write(path,saved)
                    ledgers[c['id']].append(dict(session=session,symbol=symbol,path=path.relative_to(common.ROOT).as_posix(),SHA256=common.digest(path)))
                for mode in ('CONFIRM','VETO'):
                    for stop in (4,8,16):
                        a=outputs[f'E01_FIRST_W60_{mode}_TP1_S{stop}_NEXT_MARKET'];b=outputs[f'E01_FIRST_W60_{mode}_TP1_S{stop}_RESTING']
                        delta=b['summary']['収支']-a['summary']['収支']
                        comparisons.append(dict(session=session,symbol=symbol,mode=mode,stop=stop,成行=a['summary'],常設=b['summary'],
                            収支変化=delta,避けた基準損失=0.,失った基準利益=0.,共通入口の出口変化=delta,新たな入口の収支=0.,
                            元勝ち親が赤字化=int(a['summary']['収支']>0 and b['summary']['収支']<0)))
            print(session+' 常設利確12完了',flush=True)
        assert counts==Counter(新input読取=33,新bracket会計=792) and common.source_hashes()==fixed['source_SHA256']
        cases={i:dict(rows=rows[i],ledgers=ledgers[i],symbols={s:aggregate([r for r in rows[i] if r['symbol']==s]) for s in policy.QUANTITY}) for i in rows}
        common.write(common.HERE/'finance/結果.json',dict(全合格=True,sessions=fixed['sessions'],configs=fixed['configs'],results=cases,
            利確二法の各場比較=comparisons,read_counts=dict(counts),source_SHA256=fixed['source_SHA256'],source開始終端一致=True,
            新政策会計=792,入口engine再生=0,元GU出口使用=0,原NPZ=0,API=0,経過秒=time.monotonic()-started))
    except BaseException:
        common.write(common.HERE/'finance/False.json',dict(全合格=False,原因=traceback.format_exc(),自動再開始=False,件数=dict(counts)));raise


if __name__=='__main__':
    p=argparse.ArgumentParser();a=p.add_mutually_exclusive_group(required=True)
    for flag in ('fix-input','prepare-input','freeze','root-trial-registered'):a.add_argument('--'+flag,action='store_true')
    args=p.parse_args()
    if args.fix_input:prepared.fix()
    elif args.prepare_input:prepared.run()
    elif args.freeze:freeze()
    else:run()
