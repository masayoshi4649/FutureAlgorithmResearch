"""完成maskedGU実注文から、固定18口座停止政策を登録後に一回再計算する。"""

import argparse
from collections import Counter
from datetime import datetime,timezone
import gzip
import hashlib
import json
from pathlib import Path
import pickle
import socket
import time

import numpy as np

import common
import daily
import policy


SOURCE=common.ROOT/'work/wave_v106/e01_trade_gate/finance/結果.json'
INPUT=common.ROOT/'work/wave_v106/e01_trade_gate/全33場のE01取引更新準備.json'
FIXED=common.HERE/'金融前の固定.json'
FIELDS=('収支変化','避けた基準損失','失った基準利益','共通入口の出口変化','新たな入口の収支')


def dense(value: dict, count: int) -> dict:
    """
    機能: 保存schema2のplateau配列を、元normal全行へ因果的な前方保持でexact復元する。
    引数: value(dict)、count(int)は保存GU台帳とnormal行数。
    返り値: dictは配列の復元。後行へのnearest補完や再売買はしない。
    """
    result=dict(value)
    for name,item in value.items():
        if isinstance(item,dict) and set(item)=={'rows','values','length'}:
            assert item['length']==count;rows=item['rows'];assert rows[0]==0 and np.all(np.diff(rows)>0)
            index=np.searchsorted(rows,np.arange(count),side='right')-1
            result[name]=item['values'][index]
    return result


def stored(value: dict, count: int) -> dict:
    """
    機能: 新政策の実注文・UID・玉だけを公開し、口座価格列をplateau保存する。
    引数: value(dict)、count(int)は新実口座会計とnormal行数。
    返り値: dictはschema2台帳。元影GUのstate/virtual feedを新実状態へ流用しない。
    """
    result=dict(value)
    for name in ('equity_yen','liquidation_yen','reserved_exit_fees','long_qty','short_qty','cumulative_fees'):
        array=value[name];assert len(array)==count;rows=np.r_[0,np.flatnonzero(array[1:]!=array[:-1])+1].astype(np.int64)
        result[name]=dict(rows=rows,values=array[rows],length=count)
    result['schema_version']=2
    return result


def compare(before: dict, after: dict) -> dict:
    """
    機能: 同じ実新規cidの完結親で、基準P1L8に対する5寄与と勝ち→負けを分類する。
    引数: before/after(dict)は完成P1L8保存と新政策の実会計。
    返り値: dictは収支差・以後消失・共通出口・新親及び勝ちの赤字化件数。
    """
    a={p['親']:p for p in before['parent']};b={p['親']:p for p in after['parent']}
    removed=a.keys()-b.keys();added=b.keys()-a.keys();joined=a.keys()&b.keys()
    avoid=sum(-a[k]['収支'] for k in removed if a[k]['収支']<0)
    missed=sum(a[k]['収支'] for k in removed if a[k]['収支']>0)
    exit_change=sum(b[k]['収支']-a[k]['収支'] for k in joined);new=sum(b[k]['収支'] for k in added)
    delta=after['summary']['収支']-before['summary']['収支']
    assert np.isclose(delta,avoid-missed+exit_change+new,atol=1e-5,rtol=0.)
    turned=[dict(parent=int(k),base_net=float(a[k]['収支']),new_net=float(b[k]['収支'])) for k in joined if a[k]['収支']>0 and b[k]['収支']<0]
    rescued=[dict(parent=int(k),base_net=float(a[k]['収支']),new_net=float(b[k]['収支'])) for k in joined if a[k]['収支']<0 and b[k]['収支']>0]
    return dict(収支変化=float(delta),避けた基準損失=float(avoid),失った基準利益=float(missed),共通入口の出口変化=float(exit_change),新たな入口の収支=float(new),
        元勝ち親が赤字化=turned,元負け親が黒字化=rescued,消えた基準親=[int(k) for k in removed],新しい親=[int(k) for k in added])


def aggregate(rows: list[dict], parents: list[dict]) -> dict:
    """
    機能: 同一商品33場の親金額割合と活動安定性・大勝ち除外を再集計する。
    引数: rows/parents(list[dict])は同商品の会計と実親。
    返り値: dictは金額/枚数と黒赤無取引。取引なしを勝ちにしない。
    """
    assert len(rows)==33 and len({r['session'] for r in rows})==33
    total=daily.metric([p['収支'] for p in parents]);active=[r for r in rows if r['親数']>0]
    positive=sorted((r for r in rows if r['収支']>0),key=lambda r:r['収支'],reverse=True);negative=[r for r in rows if r['収支']<0]
    return dict(**total,全場=33,活動場=len(active),黒字場=len(positive),赤字場=len(negative),無取引場=33-len(active),
        活動黒字率=len(positive)/len(active) if active else None,中央値=float(np.median([r['収支'] for r in rows])),
        活動場中央値=float(np.median([r['収支'] for r in active])) if active else None,
        上位3利益場除外収支=total['収支']-sum(r['収支'] for r in positive[:3]),最大場損失=max([0.]+[-r['収支'] for r in rows]),
        最悪場=min(rows,key=lambda r:r['収支'])['session'],費用=sum(r['費用'] for r in rows),新規枚数=sum(r['新規枚数'] for r in rows),
        勝ち枚数=sum(r['勝ち枚数'] for r in rows),負け枚数=sum(r['負け枚数'] for r in rows),零枚数=sum(r['零枚数'] for r in rows),
        注文件数=sum(r['注文件数'] for r in rows),全33黒字=len(positive)==33)


def sources() -> dict:
    """
    機能: 正式金融前の私有exact会計と新wrapper/人工を固定する。
    引数: なし。
    返り値: dict[str,str]はroot相対sourceとSHA256。旧engineはimportしない。
    """
    paths=[common.HERE/n for n in ('common.py','daily.py','policy.py','runner.py','artificial.py')]
    return {p.relative_to(common.ROOT).as_posix():common.digest(p) for p in paths}


def freeze() -> None:
    """
    機能: 完成GU2/同P1L82/入力33の指紋と固定18を八部品へ結び、根登録を待つ。
    引数: なし。
    返り値: None。巨大台帳とquoteはまだ読まない。
    """
    assert common.digest(common.HERE/'daily.py')==common.digest(common.ROOT/'work/wave_v106/e01_daily/core.py')
    art=common.read(common.HERE/'小利益と損失予算の最小結合人工.json');assert art['全合格'] and art['新金融再生']==0 and art['source_SHA256']==sources()
    old=common.read(SOURCE);inputmeta=common.read(INPUT);assert old['全合格'] and inputmeta['全合格'] and old['sessions']==inputmeta['sessions'] and len(old['sessions'])==33
    modes={}
    for mode in ('CONFIRM','VETO'):
        gu=f'E01_TRADE_W60_{mode}_D0_GU';small=f'E01_TRADE_W60_{mode}_D0_P1L8'
        g=old['results'][gu];p=old['results'][small]
        assert len(g['ledgers'])==len(p['ledgers'])==len(g['rows'])==len(p['rows'])==66
        modes[mode]=dict(GU_id=gu,baseline_id=small,GU_ledgers={i['session']+'|'+i['symbol']:i for i in g['ledgers']},
            baseline_ledgers={i['session']+'|'+i['symbol']:i for i in p['ledgers']},baseline_rows=p['rows'],baseline_symbols=p['symbols'])
    manifests=[dict(path=p.relative_to(common.ROOT).as_posix(),sha256=common.digest(p)) for p in (SOURCE,INPUT,common.HERE/'小利益と損失予算の最小結合人工.json')]
    configs=policy.configs();implementation=sources()
    spec=dict(entry=dict(元入口='完成W60自己取引更新CONFIRM/VETOのD0新規。既実GU注文132のみ。紙上feedや公開maskは再生しない。',
        conditions=configs,condition_count=18,copy='実新規UIDと部分返済を閾値初到達まで同一に保持。'),
        management=dict(閾値='全当行実fill後の正常BBO清算時価から残UID別返済料を引く。利益1/2/4初回呼値又は損失2/4/8初回呼値で最初到達。',
            到達後='以後元の未fill/将来返済を取消、次正常quoteで残UID別全返済、その場停止。',
            影='旧GUの実注文接頭だけを再構成。影GU execution_statesやvirtual出口を新実口座へ混同しない。'),
        exit=dict(goal_profit_ticks=[1,2,4],loss_budget_ticks=[2,4,8],計算='呼値数×初回枚数×円倍率。費用後清算損益で比較。',
            約定='判断行当行まで既実注文保持→次正常ask買/bid売へUID毎別返済。',限界='損失予算は判断閾値、次気配悪化による実損失額の上限保証ではない。'),
        allocation=dict(quantity=policy.QUANTITY,caps=policy.CAP,比較='2入口×3利益×3損失の18。P1L8完成2は保存再利用、新16×66=1056政策会計。'),
        costs=dict(片道料金={'TOPIXmini':41.8,'NK225micro':11.},円倍率=daily.VALUE,
            処理='新規料upfront全額、実返済注文単位floor。FIFO部分返済後の各UID残qtyへ別floorで予約返済料。'),
        execution=dict(入口='保存D0実fill価格と原normal seqを保持。新規engine再生0。',
            序列='当行実fill/部分返済→初閾値判断→以後注文取消→次正常quoteの各残UID返済。未来tradeテンプレートを参照しない。',
            不明='不正quoteで判断/新返済をしない。全行時価は直前正常BBOだけ。未決済場末に架空清算しない。'),
        data=dict(sessions=old['sessions'],input_manifests=manifests,
            read_once='完成masked GU132＋P1L8比較用132保存ledgerを各1回、E01取引更新input33を各1回。quoteのみ再利用、原NPZ/current/API0。',
            範囲='全33既知。公開60秒は価格代理時計、実受信鮮度を保証しない。未見確認は0。'),
        implementation=implementation)
    plan=dict(id=policy.TRIAL_ID,name='E01取引更新60秒二入口の小利益と損失予算18比較',purpose='条件比較',
        question='1呼値小利益に対して残る8呼値大損失を2/4へ縮めると、各場利益と金額損小利大を改善できるか。早期停止で元勝ちが負ける数も測る。',
        change='入口W60/D0/GUと料金は固定、口座profit1/2/4及びloss2/4/8だけ比較。P1L8は保存再利用。',
        repeat_reason='前回P1L8は黒字場が増えたが金額利益割合が未達。停止幅変更の損失削減と勝ち赤字化を分離する。',
        compares_to=['106_E01公開時の取引更新代理と二執行24対照'],spec=spec,evidence=manifests,
        完成保存再利用=2,新政策会計=1056,engine再生=0,元paper再生=0)
    common.write(common.HERE/'試行計画.json',plan)
    common.write(FIXED,dict(全合格=True,source_SHA256=implementation,configs=configs,sessions=old['sessions'],input_cache=inputmeta['cache'],modes=modes,
        input_SHA256=common.digest(INPUT),source_result_SHA256=common.digest(SOURCE),plan_SHA256=common.digest(common.HERE/'試行計画.json'),
        GU保存口座=132,基準比較保存口座=132,新政策口座=1056,表示口座=1188,engine再生=0,新金融再生=0))
    print('18条件と1056新政策会計の八部品を固定。根登録待機。')


def load(item: dict) -> dict:
    """
    機能: 保存ledger又はinputの同bytesを一回読み、指紋を確認する。
    引数: item(dict)はroot相対path/SHA256。
    返り値: dictは不変完成資料。原bookと現在snapshotを読まない。
    """
    path=common.ROOT/item['path'];assert path.resolve().is_relative_to((common.ROOT/'work').resolve())
    saved=path.read_bytes();assert hashlib.sha256(saved).hexdigest()==item['SHA256']
    return pickle.loads(gzip.decompress(saved))


def run() -> None:
    """
    機能: 根の登録後だけ、完成実注文接頭から新16政策を一回会計し保存2を再利用する。
    引数: なし。
    返り値: None。新金融engine/原本/APIは使わず、失敗を保持して再開始しない。
    """
    fixed=common.read(FIXED);plan=common.read(common.HERE/'試行計画.json')
    assert fixed['source_SHA256']==sources() and fixed['configs']==policy.configs() and common.digest(common.HERE/'試行計画.json')==fixed['plan_SHA256']
    assert common.digest(INPUT)==fixed['input_SHA256'] and common.digest(SOURCE)==fixed['source_result_SHA256']
    registry=common.read(common.ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/data/trials.json')['trials']
    registered=[t for t in registry if t['id']==policy.TRIAL_ID];assert len(registered)==1 and registered[0]['spec']==plan['spec']
    assert not (common.HERE/'finance').exists()
    common.write(common.HERE/'finance/開始.json',dict(時刻=datetime.now(timezone.utc).isoformat(),新政策会計=1056,保存再利用=132,engine再生=0))
    rows={c['id']:[] for c in fixed['configs']};parents={i:[] for i in rows};ledgers={i:[] for i in rows};differences={i:[] for i in rows}
    counts=Counter();started=time.monotonic()
    try:
        for session in fixed['sessions']:
            packet=load(fixed['input_cache'][session]);counts['保存input一読']+=1
            for symbol in ('TOPIX','NK225'):
                quotes=packet['accounts'][symbol]['quotes'];n=len(quotes['bid'])
                for mode in ('CONFIRM','VETO'):
                    binding=fixed['modes'][mode];key=session+'|'+symbol
                    gu_item=binding['GU_ledgers'][key];old=dense(load(gu_item),n);counts['保存GU一読']+=1
                    gu=daily.reconstruct((session,symbol),old['orders'],old['order_uids'],quotes)
                    for name in ('equity_yen','liquidation_yen','reserved_exit_fees','long_qty','short_qty','cumulative_fees'):
                        np.testing.assert_allclose(gu[name],old[name],atol=1e-7,rtol=0.)
                    assert gu['summary']==old['summary']
                    baseline_item=binding['baseline_ledgers'][key];base=dense(load(baseline_item),n);counts['P1L8保存比較一読']+=1
                    for config in [c for c in fixed['configs'] if c['mode']==mode]:
                        identifier=config['id']
                        if config['saved_alias']:
                            fresh=base;item=dict(baseline_item,saved_alias=True,source_id=config['baseline_id']);counts['保存P1L8再利用']+=1
                        else:
                            fresh=daily.apply_policy(gu,quotes,config);counts['新政策会計']+=1
                            path=common.HERE/f'finance/ledgers/{identifier}/{session}_{symbol}.pkl.gz';common.write(path,stored(fresh,n))
                            item=dict(session=session,symbol=symbol,path=path.relative_to(common.ROOT).as_posix(),SHA256=common.digest(path),saved_alias=False)
                        rows[identifier].append(fresh['summary']);parents[identifier].extend(dict(**p,session=session,symbol=symbol) for p in fresh['parent']);ledgers[identifier].append(item)
                        diff=compare(base,fresh);differences[identifier].append(dict(session=session,symbol=symbol,control=fresh.get('control'),**diff))
                    del old,gu,base
            del packet
            print(json.dumps(dict(完了場=session,件数=dict(counts)),ensure_ascii=False),flush=True)
        assert counts['新政策会計']==1056 and counts['保存P1L8再利用']==132 and sources()==fixed['source_SHA256']
        results={i:dict(rows=rows[i],ledgers=ledgers[i],symbols={s:aggregate([r for r in rows[i] if r['symbol']==s],[p for p in parents[i] if p['symbol']==s]) for s in ('TOPIX','NK225')}) for i in rows}
        diagnosis={i:{s:dict(**{f:sum(r[f] for r in differences[i] if r['symbol']==s) for f in FIELDS},
            元勝ち親が赤字化=sum(len(r['元勝ち親が赤字化']) for r in differences[i] if r['symbol']==s),元負け親が黒字化=sum(len(r['元負け親が黒字化']) for r in differences[i] if r['symbol']==s)) for s in ('TOPIX','NK225')} for i in rows}
        common.write(common.HERE/'finance/結果.json',dict(全合格=True,sessions=fixed['sessions'],configs=fixed['configs'],results=results,diagnosis=diagnosis,各場寄与=differences,
            source_SHA256=fixed['source_SHA256'],source開始終端一致=True,read_counts=dict(counts),表示18条件=True,保存再利用2条件=True,新政策会計=1056,engine再生=0,
            原NPZ読取=0,現在snapshot読取=0,原book読取=0,API取得=0,元paper再計算=0,経過秒=time.monotonic()-started))
    except BaseException as error:
        common.write(common.HERE/'finance/False.json',dict(全合格=False,例外=repr(error),完了件数=dict(counts),自動再開始=False));raise


def main() -> None:
    """
    機能: 金融前固定又は根の登録後一回実行を選択する。
    引数: CLI --freeze/--root-trial-registered(bool)。
    返り値: None。実注文やAPIは行わない。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--freeze',action='store_true');parser.add_argument('--root-trial-registered',action='store_true')
    args=parser.parse_args();assert args.freeze!=args.root_trial_registered
    if args.freeze:freeze();return
    def denied(*args: object,**kwargs: object) -> None:
        """
        機能: 保存口座停止に不要なネットワーク接続を拒否する。
        引数: args/kwargs(object)は通信要求。
        返り値: None。常に例外で拒否する。
        """
        raise RuntimeError('保存政策会計はAPI禁止')
    socket.create_connection=denied;socket.socket.connect=denied;run()


if __name__=='__main__':main()
