"""登録待機後の39条件を、実腿料金と合算時価で一回だけ比較する。"""

import argparse
from copy import deepcopy
from datetime import datetime,timezone
from pathlib import Path
import time

import numpy as np

import common
import catalog
import control
import join
import prepare

HERE=Path(__file__).resolve().parent
TRIAL_ID='106_第三段階_進行と進行失敗の固定配分及び小利益終了'
ACCOUNTING=common.module('106配分の不変102会計',common.ROOT/'work/wave_v102/accounting.py')
CONTRIBUTIONS=common.module('106配分の寄与分解',common.WAVE/'accounting.py')


def sources() -> dict:
    """
    機能: 条件・接続・数学・人工と不変106執行の版を固定する。
    引数: なし。
    返り値: dict[str,str]は直接依存SHA256。原板へ遡る再hashはしない。
    """
    paths=[HERE/f for f in ('common.py','catalog.py','prepare.py','control.py','join.py','runner.py','artificial.py',
        '複数親の場内停止と固定配分の人工検査.json','全33の固定配分入力.json')]
    paths += [common.WAVE/f for f in ('engine/core.py','engine/interface.py','accounting.py','common.py')]
    paths += [common.ROOT/'work/wave_v102/accounting.py']
    return {str(p.relative_to(common.ROOT)):common.digest(p) for p in paths}


def freeze() -> None:
    """
    機能: 部品差・既知入力・固定39条件を重複照合用の8部品計画へ保存する。
    引数: なし。
    返り値: None。登録又は正式金融を開始しない。
    """
    inp=common.read(HERE/'全33の固定配分入力.json');art=common.read(HERE/'複数親の場内停止と固定配分の人工検査.json')
    assert inp['全合格'] and art['全合格']
    for p,sha in art['source_SHA256'].items():assert common.digest(common.ROOT/p)==sha
    configs=catalog.catalog();before=sources()
    input_manifest=dict(path=str((HERE/'全33の固定配分入力.json').relative_to(common.ROOT)),
        sha256=common.digest(HERE/'全33の固定配分入力.json'))
    plan=dict(id=TRIAL_ID,name='進行と進行失敗の固定配分と小利益終了',purpose='新仮説',
        question='異なる入口を固定配分し小利益で場を終えると、同帯反復損失と利益全返しを両商品で減らせるか。',
        change='Cの進行とRの進行失敗を2固定配分で同時運転。単独Rの同量対照も置き、円額比例を使わず実枚数・別注文費用で再生する。',
        repeat_reason='第一段階は厳しい片道選別が活動不足、同帯禁止が回復利益を失った。第二段階は単独入口の場停止。今回は別性質の入口を同時に運転する部品差を検証する。',
        compares_to=['106_往復帯と初期リスク及び再参加の全33対照','106_第二段階_場中利益と損失予算の36対照'],
        sacrifices=['Cだけの大勝ちを固定配分で薄める','小利益後の大きな順行を放棄する','逆方向同時建てはspreadと両方向全注文料を負担する',
            '目標又は損失枠は判断水準であり次正常quoteで収支が割り込むことがある','無取引は勝ちではなく、既知33場だけで未知の有効性は証明しない'],
        evidence=[dict(path='work/wave_v106/diagnosis/赤字上位場の具体原因.json',sha256=common.digest(common.WAVE/'diagnosis/赤字上位場の具体原因.json'))],
        spec=dict(entry=dict(saved=['C_OWN','C_N30','R_OWN'],price_board_source='保存104の同原行normal eventと自己固定支持・episode根拠',
            entry_filter='追加選別なし。既入口のqualification/reset/時間/cooldownを不変維持'),
            management=dict(configs=[dict(id=c['id'],base_id=c['base_id'],goal_ticks='目標なし' if c['goal_ticks'] is None else c['goal_ticks'],
                loss_ticks='上限なし' if c['loss_ticks'] is None else c['loss_ticks']) for c in configs],
                equity='確定損益+全腿含み損益−全腿新規/残玉返済料。両方向を相殺しない',
                trigger='正常原行の最初の合算equity到達で未約定新規取消・全親次正常気配返済・同場停止'),
            exit=dict(before='全腿106不変B4:固定支持4tickと始値0.1%保険の有利側、始値0.4%の広幅追尾',
                force='limit-60の既知timerから最初正常気配、当該セッション内flat',after='場目標/損失判断後の次正常bid/askで全腿別返済'),
            allocation=dict(variants={b:[c for c in configs if c['id']==b][0]['allocations'] for b in catalog.BASES},
                products={'TOPIX':'TOPIXmini','NK225':'NK225micro'},cap_per_direction={'TOPIX':10,'NK225':20},additional_positions=False),
            costs=dict(per_lot_per_side={'TOPIX':41.8,'NK225':11},rounding='実腿の各注文合計の円未満切捨て、合算注文への再計算なし'),
            execution=dict(entry='判断より後の最初正常quote ask買/bid売',exit='目標判断より後の最初正常quote、保有全親を各別注文',
                pending_cancel='閾値判断rowの未約定新規は取消。既fillをなかったことにしない',delay_stress_seconds=0,overnight=False),
            data=dict(sessions=inp['sessions'],cache_manifest=input_manifest,input_manifests=[input_manifest],
                unknown_sessions=0,current_API_reads=0),implementation=before))
    common.save(HERE/'試行計画.json',plan)
    common.save(HERE/'事前固定.json',dict(全合格=True,trial_id=TRIAL_ID,sessions=inp['sessions'],configs=configs,sources=before,
        timestamp=datetime.now(timezone.utc).isoformat(),new_finance=0,account_count=39*33*2,actual_leg_replays=5*33*2,
        範囲='3基準＋36停止政策。C単独全量の第一結果は報告で再利用し、新しい39へ二重計上しない。',
        判定='root第一段階の安定性基準を継承。新損益から配分・目標・loss値を変更しない。'))
    print('39条件と8部品計画を固定しました。重複登録と根実行通知を待ちます。',flush=True)


def inspect(session: str, record: dict, out: dict, total_quantity: int) -> dict:
    """
    機能: 親・玉・注文を旧独立会計と注文由来全行清算で突き合わせる。
    引数: session(str)、record/out(dict)、total_quantity(int)は場名と総配分。
    返り値: dictは金額・決済枚数・活動・最大保有。合計netから勝率を作らない。
    """
    curve,trace=control.economic_path(record,out['orders'])
    np.testing.assert_allclose(curve,out['curve'],atol=1e-4,rtol=0)
    np.testing.assert_array_equal(trace[:,:2],out['target_trace'][:,:2])
    assert out['target_trace'][:,:4].max(initial=0)<=total_quantity and not out['target_trace'][-1].any()
    row=ACCOUNTING.account((session,record['symbol']),out)
    multiplier=1000. if record['symbol']=='TOPIX' else 10.
    row.update(独立全行会計検算=True,budget_unit=out['initial_width']*total_quantity*multiplier,
        goal=out.get('goal'),loss_limit=out.get('loss'),stopped=out.get('stopped',False),
        stop_reason=out.get('stop_reason','目標なし'),decision_time=out.get('decision_time'),
        open_parent_count_at_stop=out.get('open_parent_count_at_stop',0),
        cancelled_pending_entry=out.get('cancelled_pending_entry',0))
    return row


def stored(out: dict, record: dict) -> dict:
    """
    機能: 合算口座の物理事実を保存し、全行時価/保有を変化行へ圧縮する。
    引数: out/record(dict)は新出力と原seq対応。
    返り値: dictは台帳。未採用の元未来leg注文を変更後実注文と混在させない。
    """
    names=('orders','order_columns','trades','trade_columns','growth_cohorts','growth_cohort_columns','events','event_columns',
        'stats','stat_columns','trace_columns','source_names','raw_entry_diagnostics','allocations','initial_width',
        'stopped','stop_reason','decision_row','decision_seq','decision_time','decision_equity','fill_row','goal','loss',
        'open_parent_count_at_stop','cancelled_pending_entry','pending_liquidation','stop_note')
    saved={name:out[name] for name in names if name in out};saved['row_count']=len(record['seq'])
    for name in ('curve','source_curve','target_trace'):
        arr=out[name];changes=np.flatnonzero(np.r_[True,np.diff(arr)!=0] if arr.ndim==1 else np.r_[True,np.any(np.diff(arr,axis=0)!=0,axis=1)])
        saved[name]=dict(rows=changes,values=arr[changes])
    if not out.get('stopped',False):
        legs=out.get('legs',{'R':out} if out.get('entry_id')=='R_OWN' else {})
        saved['leg_judgments']={family:dict(judgments=leg['judgments'],columns=leg['judgment_columns'],
            candidates=leg['candidate_controls'],candidate_columns=leg['candidate_control_columns']) for family,leg in legs.items()}
    return saved


def run() -> None:
    """
    機能: 登録済み39条件の正式金融を33場各一入力で一回だけ実行する。
    引数: なし。
    返り値: None。結果・台帳・同量基準への5寄与を保存する。旧原板/APIは使用しない。
    """
    fixed=common.read(HERE/'事前固定.json');assert fixed['全合格'] and fixed['sources']==sources()
    trials=common.read(common.ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/data/trials.json')['trials']
    assert any(t['id']==TRIAL_ID for t in trials);assert not (HERE/'results.json').exists()
    engine=common.module('106固定配分の現interface',common.WAVE/'engine/interface.py')
    cases={c['id']:dict(rows=[],ledgers={}) for c in fixed['configs']}
    contribution_fields=('収支変化','避けた基準損失','失った基準利益','共通入口の出口変化','新たな入口の収支')
    diagnosis={c['id']:{s:{k:0. for k in contribution_fields} for s in ('TOPIX','NK225')} for c in fixed['configs']}
    start=time.monotonic();sessions=fixed['sessions'];base_configs={c['id']:c for c in fixed['configs'] if c['id']==c['base_id']}
    for session in sessions:
        packet=prepare.load_session(session);session_results={}
        for symbol in ('TOPIX','NK225'):
            prepared=packet['prepared'][symbol];record=prepared['record'];memo={};bases={};base_maps={}
            for base,cfg in base_configs.items():
                legs={}
                for entry,q in zip(cfg['components'],cfg['allocations'][symbol],strict=True):
                    key=(entry,q)
                    if key not in memo:memo[key]=engine.play(prepared,packet['cases'][entry][symbol],cfg,quantity=q)
                    legs['C' if entry.startswith('C') else 'R']=memo[key]
                if len(legs)==2:
                    out=join.join_portfolio_outputs(legs,tuple(cfg['allocations'][symbol]),symbol)
                    out.update(initial_width=legs['C']['initial_width'],entry_id=cfg['entry_id'])
                else:out=dict(legs['R'],allocations=tuple(cfg['allocations'][symbol]))
                bases[base]=out;base_maps[base]=control.trade_map(out,record)
            assert len(memo)==5
            for cfg in fixed['configs']:
                out=bases[cfg['base_id']]
                tick_value=cfg['quantity'][symbol]*record['tick']*(1000. if symbol=='TOPIX' else 10.)
                if cfg['goal_ticks'] is not None:
                    out=control.simulate(record,out,tick_value*cfg['goal_ticks'],None if cfg['loss_ticks'] is None else tick_value*cfg['loss_ticks'])
                row=inspect(session,record,out,cfg['quantity'][symbol]);cases[cfg['id']]['rows'].append(row)
                path=HERE/'ledger'/cfg['id']/f'{session}_{symbol}.pkl.gz';sha=common.pack(path,stored(out,record))
                cases[cfg['id']]['ledgers'].setdefault(session,{})[symbol]=dict(path=str(path.relative_to(common.ROOT)),SHA256=sha)
                diff=CONTRIBUTIONS.contribution(base_maps[cfg['base_id']],control.trade_map(out,record))
                for k in contribution_fields:diagnosis[cfg['id']][symbol][k]+=diff[k]
                session_results.setdefault(cfg['id'],{})[symbol]=diff
            del prepared,record,memo,bases,base_maps
        common.save(HERE/'session_contributions'/f'{session}.json',session_results)
        print(session+'：39条件、実腿別料・両建て全親・全行清算・基準差一致',flush=True)
        del packet
    assert fixed['sources']==sources()
    common.save(HERE/'results.json',dict(全合格=True,sessions=sessions,configs=fixed['configs'],cases=cases,diagnosis=diagnosis,
        account_count=39*33*2,actual_leg_replays=5*33*2,stage='第三段階_固定配分と小利益終了',
        unknown_sessions=0,current_API_reads=0,actual_orders=0,elapsed_seconds=time.monotonic()-start))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='第三段階の事前固定と登録後の正式一回')
    parser.add_argument('action',choices=('freeze','run'));parser.add_argument('--root-finance-approved',action='store_true')
    args=parser.parse_args()
    if args.action=='freeze':freeze()
    else:assert args.root_finance_approved;run()
