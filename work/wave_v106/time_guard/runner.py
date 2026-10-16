"""保存済みB4基準に対する、開場静観だけの12対照を登録後に実行する。"""

import argparse
from datetime import datetime,timezone
from pathlib import Path
import time

import numpy as np

import catalog
import common
import interface
import time_windows

HERE=Path(__file__).resolve().parent
TRIAL_ID='106_第五段階_C系と進行失敗の既知開場静観12対照'
ACCOUNT=common.module('106時間静観の独立会計',common.WAVE/'accounting.py')


def sources() -> dict:
    """
    機能: 時刻定義、所有執行、人工、入力資料、基準結果を版へ結ぶ。
    引数: なし。
    返り値: dict[str,str]は直接依存SHA256。旧原本を再hashしない。
    """
    paths=[HERE/n for n in ('common.py','time_windows.py','catalog.py','core.py','interface.py','artificial.py','fixture.py','runner.py',
        '開場静観timerと不変B4の人工検査.json','複製由来.json')]
    paths += [common.WAVE/n for n in ('input/全33場の因果特徴準備.json','input/data.py','portfolio/全33の固定配分入力.json',
        'portfolio/prepare.py','finance/results.json','portfolio/results.json','accounting.py')]
    paths += [common.ROOT/'work/wave_v85/time_filter.py',common.ROOT/'work/wave_v102/accounting.py']
    return {str(p.relative_to(common.ROOT)):common.digest(p) for p in paths}


def freeze() -> None:
    """
    機能: 12静観対照の完全8部品仕様を重複照合前に固定する。
    引数: なし。
    返り値: None。正式金融と追加入力再抽出は開始しない。
    """
    inp=common.read(common.WAVE/'input/全33場の因果特徴準備.json')
    port=common.read(common.WAVE/'portfolio/全33の固定配分入力.json')
    art=common.read(HERE/'開場静観timerと不変B4の人工検査.json')
    assert inp['全合格'] and port['全合格'] and art['全合格'] and inp['sessions']==port['sessions']
    for p,sha in art['source_SHA256'].items():assert common.digest(common.ROOT/p)==sha
    configs=catalog.catalog();before=sources()
    manifests=[dict(path=str(p.relative_to(common.ROOT)),sha256=common.digest(p)) for p in
        (common.WAVE/'input/全33場の因果特徴準備.json',common.WAVE/'portfolio/全33の固定配分入力.json')]
    plan=dict(id=TRIAL_ID,name='C系と進行失敗の開場急変静観',purpose='新仮説',
        question='日中・NYSE開場時刻の新価格形成を静観すると、両商品の反復損失を減らせるか。',
        change='4入口のB4全量は不変。日中08:45～09:15/NYSE09:30現地前後15分/両方だけを見送る。保有と未約定新規も開始予定で整理する。',
        repeat_reason='旧E01の時刻回避は既知だが、新C/R入口で同じ基準出口への作用は未検証。C_N30赤字3場の08:58～09:18の親を具体的に確認したため独立部品として比較する。',
        compares_to=['106_往復帯と初期リスク及び再参加の全33対照','106_第三段階_進行と進行失敗の固定配分及び小利益終了'],
        sacrifices=['静観窓で始まる大勝ちと早朝利益も見送る','予定返済後の回復を失い、次気配が悪化して損失が増えることがある',
            'NYSE休場/夏冬日程は保存2026定義だけ。未知年は拒否','既知33場だけの対照であり、日付固有に調整しない'],
        evidence=[dict(path=str((common.WAVE/'diagnosis/赤字上位場の具体原因.json').relative_to(common.ROOT)),
            sha256=common.digest(common.WAVE/'diagnosis/赤字上位場の具体原因.json'))],
        spec=dict(entry=dict(saved=list(catalog.ENTRIES),unchanged='同原行event/support/資格/reset/自己根拠',
            quiet_modes=['J','U','JU'],J='日中08:45包含～09:15除外',U='NYSE営業日現地09:30の前後15分'),
            management=dict(timer='開始予定epochで新規予約取消・保有返済予約。候補は当時一回消費、終了後復活なし',
                resume='静観終了後の別新pulse、元30秒cooldownを維持',session_force='同rowなら元limit-60を優先'),
            exit=dict(B4='支持4tickと始値0.1%保険の有利側、始値0.4%幅の広い追尾。幅は不変',
                quiet_exit='予定開始の最初の正常quote。判断rowは予約処理row直前、decision_timeは既知開始epoch',
                flat='セッション末まで全返済、架空端点清算なし'),
            allocation=dict(products={'TOPIX':'TOPIXmini','NK225':'NK225micro'},quantity={'TOPIX':10,'NK225':20},
                cap_per_direction={'TOPIX':10,'NK225':20},portfolio=False,additional_positions=False),
            costs=dict(per_lot_per_side={'TOPIX':41.8,'NK225':11},rounding='実注文合計の円未満切捨て'),
            execution=dict(entry='判断原行より後の最初正常ask買/bid売',scheduled_exit='既知timer到達後の最初正常quote。開始rowで正常なら同row可',
                priority='cut取消・場末force・静観取消/返済予約・通常予約fill・元価格判断・当時候補',overnight=False,worst_delay_seconds=0),
            data=dict(sessions=inp['sessions'],input_manifests=manifests,known_sessions=33,unknown_sessions=0,current_API_reads=0,
                calendar=dict(path='work/wave_v85/time_filter.py',sha256=common.digest(common.ROOT/'work/wave_v85/time_filter.py'))),
            implementation=before))
    common.save(HERE/'試行計画.json',plan)
    common.save(HERE/'事前固定.json',dict(全合格=True,trial_id=TRIAL_ID,sessions=inp['sessions'],configs=configs,sources=before,
        timestamp=datetime.now(timezone.utc).isoformat(),new_finance=0,account_count=12*33*2,基準金融再生=0,
        採用='第一段階の両商品安定性条件を継承。実結果から静観時刻や停止幅を変更しない。'))
    print('12条件の事前固定完了。登録と根金融許可を待機します。',flush=True)


def base_ledger(first: dict, portfolio: dict, entry: str, session: str, symbol: str) -> dict:
    """
    機能: 完了済み各B4基準の台帳を一回読む。
    引数: first/portfolio(dict)、entry/session/symbol(str)は基準結果と口座名。
    返り値: dictは既存金融。基準を再生しない。
    """
    source=portfolio if entry=='R_OWN' else first
    return common.unpack(source['cases'][entry+'_B4']['ledgers'][session][symbol])


def save_ledger(path: Path, out: dict, record: dict, window: dict) -> str:
    """
    機能: 時刻付き注文、自己支持判断、拒否、既知静観予定を保存する。
    引数: path(Path)、out/record/window(dict)は新台帳と入力・予定時計。
    返り値: strは圧縮台帳SHA256。時価は変化行だけ保存する。
    """
    names=('orders','order_columns','trades','trade_columns','growth_cohorts','growth_cohort_columns','events','event_columns',
        'judgments','judgment_columns','candidate_controls','candidate_control_columns','candidate_integer_keys','candidate_integer_columns',
        'control_events','control_event_columns','raw_entry_diagnostics','stats','stat_columns','trace_columns')
    saved={k:out[k] for k in names};saved['row_count']=len(record['seq']);saved['windows']=window['windows']
    for name in ('curve','target_trace'):
        arr=out[name];changes=np.flatnonzero(np.r_[True,np.diff(arr)!=0] if arr.ndim==1 else np.r_[True,np.any(np.diff(arr,axis=0)!=0,axis=1)])
        saved[name]=dict(rows=changes,values=arr[changes])
    return common.pack(path,saved)


def run() -> None:
    """
    機能: 登録済み12条件を同33場で一回比較し、既基準への5寄与を保存する。
    引数: なし。
    返り値: None。4基準の金融再生、原本抽出、API取得は行わない。
    """
    fixed=common.read(HERE/'事前固定.json');assert fixed['全合格'] and fixed['sources']==sources()
    trials=common.read(common.ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/data/trials.json')['trials']
    assert any(t['id']==TRIAL_ID for t in trials);assert not (HERE/'results.json').exists()
    first=common.read(common.WAVE/'finance/results.json');port=common.read(common.WAVE/'portfolio/results.json')
    cmeta=common.read(common.WAVE/'input/全33場の因果特徴準備.json');rmeta=common.read(common.WAVE/'portfolio/全33の固定配分入力.json')
    cases={c['id']:dict(rows=[],ledgers={}) for c in fixed['configs']};fields=('収支変化','避けた基準損失','失った基準利益','共通入口の出口変化','新たな入口の収支')
    diagnosis={c['id']:{s:{k:0. for k in fields} for s in ('TOPIX','NK225')} for c in fixed['configs']};start=time.monotonic()
    for session in fixed['sessions']:
        packet=common.unpack(cmeta['cache'][session]);rpacket=common.unpack(rmeta['cache'][session]);common.immutable(packet);common.immutable(rpacket)
        session_diffs={}
        for symbol in ('TOPIX','NK225'):
            prepared=packet['prepared'][symbol];record=prepared['record']
            for k,v in record.items():
                if isinstance(v,np.ndarray):np.testing.assert_array_equal(v,rpacket['prepared'][symbol]['record'][k])
                else:assert v==rpacket['prepared'][symbol]['record'][k]
            windows={mode:time_windows.features(record,mode) for mode in ('J','U','JU')}
            for entry in catalog.ENTRIES:
                case=(rpacket if entry=='R_OWN' else packet)['cases'][entry][symbol]
                original=base_ledger(first,port,entry,session,symbol)
                baseline=ACCOUNT.trade_map(original,record)
                for cfg in (c for c in fixed['configs'] if c['entry_id']==entry):
                    window=windows[cfg['quiet_mode']];normal=dict(case,quiet=window['quiet'],quiet_start_s=window['quiet_start_s'])
                    out=interface.play(prepared,normal,cfg,quantity=cfg['quantity'][symbol])
                    row=ACCOUNT.inspect((session,symbol),record,out)
                    row.update(budget_unit=out['initial_width']*cfg['quantity'][symbol]*out['economics']['multiplier'],
                        quiet_mode=cfg['quiet_mode'],quiet_rejections=int(np.count_nonzero(out['candidate_controls'][:,6]==10)),
                        quiet_timer_exits=int(np.count_nonzero(out['trades'][:,13]==9)))
                    cases[cfg['id']]['rows'].append(row)
                    path=HERE/'ledger'/cfg['id']/f'{session}_{symbol}.pkl.gz';sha=save_ledger(path,out,record,window)
                    cases[cfg['id']]['ledgers'].setdefault(session,{})[symbol]=dict(path=str(path.relative_to(common.ROOT)),SHA256=sha)
                    diff=ACCOUNT.contribution(baseline,ACCOUNT.trade_map(out,record));session_diffs.setdefault(cfg['id'],{})[symbol]=diff
                    for k in fields:diagnosis[cfg['id']][symbol][k]+=diff[k]
                    del out
        common.save(HERE/'session_contributions'/f'{session}.json',session_diffs)
        print(session+'：12静観、既基準再利用、時刻予約/正常気配/全行会計/5寄与一致',flush=True)
        del packet,rpacket
    assert fixed['sources']==sources()
    common.save(HERE/'results.json',dict(全合格=True,sessions=fixed['sessions'],configs=fixed['configs'],cases=cases,diagnosis=diagnosis,
        account_count=12*33*2,stage='第五段階_既知開場静観',baseline_replays=0,unknown_sessions=0,current_API_reads=0,
        actual_orders=0,elapsed_seconds=time.monotonic()-start))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='既知開場静観の事前固定と一回金融')
    parser.add_argument('action',choices=('freeze','run'));parser.add_argument('--root-finance-approved',action='store_true')
    args=parser.parse_args()
    if args.action=='freeze':freeze()
    else:assert args.root_finance_approved;run()
