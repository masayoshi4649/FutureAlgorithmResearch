"""純価格6点の固定26条件を登録後に一回だけ比較する。"""

import argparse
from datetime import datetime,timezone
import math
from pathlib import Path
import time

import numpy as np

import catalog
import common
import interface
import prepare
import selection

HERE=Path(__file__).resolve().parent
TRIAL_ID='106_第六段階_旧基準参照ID修正後の純価格26再開'
BASELINE_IDS={'C_OWN':'C_OWN_B4_TIME_J','R_OWN':'R_OWN_B4_TIME_J'}
ACCOUNT=common.module('106純価格レジームの独立会計',common.WAVE/'accounting.py')
TOTALS=common.module('106純価格レジームの不変102集計',common.ROOT/'work/wave_v102/accounting.py')
TIME=common.module('106純価格レジームの既知静観時計',common.WAVE/'time_guard/time_windows.py')
FIELDS=('収支変化','避けた基準損失','失った基準利益','共通入口の出口変化','新たな入口の収支')


def sources() -> dict:
    """
    機能: 観測修正、所有執行、人工、入力、旧対照資料を同じ版へ結ぶ。
    引数: なし。
    返り値: dict[str,str]は直接依存SHA256。旧巨大原本は再hashしない。
    """
    names=('common.py','features.py','catalog.py','selection.py','core.py','interface.py','prepare.py','runner.py',
        'artificial.py','extension_artificial.py','price_artificial.py','純価格観測資格の修正と複製由来.json',
        '6点レジームと単一口座中心返済の人工検査.json','源切替と支持維持及び保有接頭の追加人工.json',
        '純価格資格と未知端点不救済の人工検査.json','全33の候補当時純価格6点特徴.json','価格時計highwater修正の由来.json')
    paths=[HERE/n for n in names]
    paths+=[common.WAVE/n for n in ('accounting.py','time_guard/time_windows.py','time_guard/results.json',
        'regime/strict未金融と活動不足の固定.json','regime_sample/gapだけ修正の未金融と活動不足の固定.json',
        'e01_pair_filter/UNKNOWN観測定義と原fieldの監査.json')]
    paths+=[common.ROOT/n for n in ('work/wave_v85/time_filter.py','work/wave_v102/accounting.py',
        'アルゴリズム調査/00086_二市場の状態で追従と指値反発を配分/README.md',
        'アルゴリズム調査/00072_二市場の即時板判断と保有管理/README.md')]
    return {str(p.relative_to(common.ROOT)):common.digest(p) for p in paths}


def freeze() -> None:
    """
    機能: 修正理由と経済8部品を結果前に固定し、登録待機へ移る。
    引数: なし。
    返り値: None。26正式金融を開始せず、旧不採用版も保持する。
    """
    inp=common.read(HERE/'全33の候補当時純価格6点特徴.json');assert inp['全合格']
    for name in ('6点レジームと単一口座中心返済の人工検査.json','源切替と支持維持及び保有接頭の追加人工.json',
                 '純価格資格と未知端点不救済の人工検査.json'):
        art=common.read(HERE/name);assert art['全合格'] and art['人工専用']
        for p,sha in art['source_SHA256'].items():assert common.digest(common.ROOT/p)==sha
    configs=catalog.catalog();before=sources()
    manifest=dict(path=str((HERE/'全33の候補当時純価格6点特徴.json').relative_to(common.ROOT)),
        sha256=common.digest(HERE/'全33の候補当時純価格6点特徴.json'))
    evidence=[dict(path=p,sha256=before[p]) for p in before if p.endswith('UNKNOWN観測定義と原fieldの監査.json')]
    plan=dict(id=TRIAL_ID,name='純価格6点による進行と往復の単一口座選択',purpose='不具合修正',
        question='量資格や最終価格時計停滞を価格状態の欠測へ代用せず測ると、二市場進行と往復の因果的選択は安定性を改善するか。',
        change='C/R元入口は不変更。価格6点に数量/出来高fullqualified・混合reset32/64・間の価格公表gapを適用していた観測定義だけを修正。',
        repeat_reason='strictはknown7/999、gapだけ版26/999で金融せず保持。正常quote更新と価格時計停滞が両立する原field反例を受け、価格状態とC/R数量根拠を分離する。初版はNaNを跨ぐ時刻逆行の資格不備の人工修正を受け、金融0で保持。旧26開始は旧基準引用からTIMEを落としたKeyErrorで、interface.play前・完了0口座のまま停止した。正式保存IDへ参照だけ修正して再開する。26数値/入口/出口/料/人工/入力manifestは不変更。',
        compares_to=['106_第六段階_純価格6点による進行と往復の自動選択26対照',
            '106_往復帯と初期リスク及び再参加の全33対照',
            '106_第三段階_進行と進行失敗の固定配分及び小利益終了',
            '106_第五段階_C系と進行失敗の既知開場静観12対照'],
        prior_similar=dict(公開00086='両市場300秒の全原板path ERと連続10秒確認で旧J2追従/O06指値を選択。今回は6点価格sampleと別C/R支持仮説、R固定中心余地、同一単一状態を全再運転する。',
            公開00072='5秒予定格子の板支持で入口と途中撤退/ドテンを比較。今回は旧episode候補の当時価格分類だけ、保有中のレジーム変化では撤退しない。'),
        sacrifices=['6点間の全tick経路を測らず、sample間の往復を見落とす。','非normal端点BBOの保存NaNを救済せず、活動不足はなお残る。',
            'RANGEでR候補又は金額余地がなくてもCへ救済しない。','中心到達判断後の次quoteは利益を保証せず、entry gapを架空取消しない。',
            '日中開場の利益、フィルタで消える大勝ち、無取引を代償へ記録する。','既知33場であり未見将来の安定性は証明しない。'],
        evidence=evidence,
        spec=dict(entry=dict(saved=['C_OWN','R_OWN'],original='同原行event/support/entry_quality/reset/map/選択済み自己episode根拠をexact保持',
            sample_offsets_seconds=[300,240,180,120,60,0],own='判断原clock以下かつ実rawrow以下のfirst-newmax先頭公表',
            peer='自己clockよりstrictpastのfirst-newmax先頭公表',endpoints='finite正bid/ask・ask>bid・場内finiteclock・asof15秒',
            interval='原seq断裂と全既知価格時計highwaterへの逆行。量/出来高資格と混合reset、途中BBO不正、公表gapを価格サンプルへ代用しない',
            modes=['C_ONLY','R_ONLY','AUTO'],trend_bp=[2,3,5],range_er=[.2,.4],priority='双方ER<=閾値かつsample幅>=4tickならRANGE先、その他双方同方向ret>=bpならC',
            R='新R候補と中心側ask/bid及び費用後中心余地>=1.25倍の正予定初期損失を全て要求'),
            management=dict(state='単一口座・新規時のみC/Rを選び既存玉は元出口を維持',
                conflict='RANGE先、R余地不足をCへ救済しない。同rowC/Rは一意選択。保有/予約中の候補は消費し後で復活しない',
                quiet='全条件日中08:45包含～09:15除外の既知timer見送り・保有返済、NYSE見送りなし',
                cooldown_seconds=30,additional_positions=False,session_loss_brake=False),
            exit=dict(C=['B4','R21'],B4='固定支持4tickと始値0.1%保険の有利側、始値0.4%広幅追尾',
                R21='Cのみ実fill固定の料込R、F+2R発動・1R追尾・F+1R床、不利へ緩めない',
                R='B4支持保険＋当時sample中心の有利方向呼値丸め目標を新規判断時固定、到達後次正常quote返済',
                force='limit-60の既知timer、場内flat、人工端点清算なし'),
            allocation=dict(products={'TOPIX':'TOPIXmini','NK225':'NK225micro'},quantity={'TOPIX':10,'NK225':20},
                cap_per_direction={'TOPIX':10,'NK225':20},simultaneous_C_R=False,portfolio=False),
            costs=dict(per_lot_per_side={'TOPIX':41.8,'NK225':11},rounding='各物理注文合計の円未満切捨て、新規と返済双方'),
            execution=dict(entry='判断原行より後の最初正常ask買/bid売',exit='停止又は中心到達判断後の次正常気配',
                timer='開始既知時刻後の最初正常quote、timer判断原行は直前',entry_gap='実fillを取り消さない',
                delay_stress_seconds=0,overnight=False,board_proxy='ラージBBOをmini/micro執行へ代用、待ち順位や実小商品板は未検証'),
            data=dict(sessions=inp['sessions'],input_manifests=[manifest],known_sessions=33,unknown_sessions=0,current_API_reads=0,
                observation_correction_evidence=evidence),implementation=before))
    common.save(HERE/'試行計画.json',plan)
    common.save(HERE/'事前固定.json',dict(全合格=True,trial_id=TRIAL_ID,sessions=inp['sessions'],configs=configs,
        aliases=catalog.aliases(),sources=before,timestamp=datetime.now(timezone.utc).isoformat(),new_finance=0,
        account_count=26*33*2,display_conditions=36,actual_conditions=26,alias_new_replays=0,
        old_baseline_replays=0,採用='第一段階の両商品安定性と活動条件を継承。結果後にER/窓/余地/枚数/出口を選び直さない。'))
    print('26実条件・10表示再利用・完全8specを固定。登録と根金融許可を待機します。',flush=True)


def stored(out: dict, record: dict, decisions: list) -> dict:
    """
    機能: 実注文、全判断、元候補のレジーム採否と源別時価を保存する。
    引数: out/record(dict)、decisions(list)は金融出力と当時分類全候補。
    返り値: dictは圧縮前台帳。時価/保有は変化原行を保持する。
    """
    names=('orders','order_columns','trades','trade_columns','growth_cohorts','growth_cohort_columns','events','event_columns',
        'judgments','judgment_columns','candidate_controls','candidate_control_columns','candidate_integer_keys','candidate_integer_columns',
        'control_events','control_event_columns','raw_entry_diagnostics','stats','stat_columns','trace_columns','source_names')
    value={n:out[n] for n in names};value.update(row_count=len(record['seq']),selection_diagnostics=decisions)
    for name in ('curve','source_curve','target_trace'):
        a=out[name];changed=np.flatnonzero(np.r_[True,np.diff(a)!=0] if a.ndim==1 else np.r_[True,np.any(np.diff(a,axis=0)!=0,axis=1)])
        value[name]=dict(rows=changed,values=a[changed])
    return value


def range_actual(record: dict, out: dict, diagnostic: list, initial_width: float) -> list:
    """
    機能: Rの判断時余地と実fill時の予定リスクを別値として保存する。
    引数: record/out(dict)、diagnostic(list)、initial_width(float)は同場入力と当時審査。
    返り値: list[dict]は実R親のgap差。将来の値を入口審査へ戻さない。
    """
    byrow={d['row']:d for d in diagnostic};result=[];tick=float(record['tick'])
    m,unit=(1000.,41.8) if record['symbol']=='TOPIX' else (10.,11.)
    for trade in out['trades']:
        if int(trade[1])!=1:continue
        decision=int(trade[15]);d=byrow[decision];order=d['range_order'];E=float(trade[6]);side=int(trade[4]);q=int(trade[5])
        support=next(v['fixed_support_price'] for v in out['raw_entry_diagnostics'] if int(v['parent_id'])==int(trade[0]))
        stop=max(support-4*tick,E-initial_width) if side==1 else min(support+4*tick,E+initial_width)
        fee=2*math.floor(q*unit+1e-8)
        result.append(dict(parent_id=int(trade[0]),decision_row=decision,entry_row=int(trade[2]),
            planned=order,actual_entry=E,actual_planned_stop=stop,
            fill_to_unrounded_centre_net=side*(order['centre']-E)*q*m-fee,
            actual_planned_initial_loss=side*(E-stop)*q*m+fee,
            realised_net=float(trade[11]),注意='実fill時予定値は次quote損失上限ではなく、意思決定後の約定悪化を可視化する。'))
    return result


def run() -> None:
    """
    機能: 登録済み26条件を同33入力各一回で再運転し、同枚数対照へ寄与を分解する。
    引数: なし。
    返り値: None。旧金融、原板、NPZ、現在APIは再生・取得しない。
    """
    fixed=common.read(HERE/'事前固定.json');assert fixed['全合格'] and fixed['sources']==sources()
    trials=common.read(common.ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/data/trials.json')['trials']
    assert any(t['id']==TRIAL_ID for t in trials);assert not (HERE/'finance/results.json').exists()
    prior=common.read(common.WAVE/'time_guard/results.json');assert prior['全合格']
    cases={c['id']:dict(rows=[],ledgers={}) for c in fixed['configs']}
    diagnosis={c['id']:{s:{k:0. for k in FIELDS} for s in ('TOPIX','NK225')} for c in fixed['configs']}
    begin=time.monotonic()
    for session in fixed['sessions']:
        packet=prepare.load_session(session);session_diffs={}
        for symbol in ('TOPIX','NK225'):
            p=packet['prepared'][symbol];record=p['record'];window=TIME.features(record,'J');memo={}
            baselines={entry:ACCOUNT.trade_map(common.unpack(prior['cases'][BASELINE_IDS[entry]]['ledgers'][session][symbol]),record)
                       for entry in ('C_OWN','R_OWN')}
            for config in fixed['configs']:
                normal,diags=selection.build(p,packet['cases'][symbol],packet['measured'][symbol],config)
                normal.update(quiet=window['quiet'],quiet_start_s=window['quiet_start_s'])
                out=interface.play(p,normal,config,quantity=config['quantity'][symbol]);row=ACCOUNT.inspect((session,symbol),record,out)
                row.update(budget_unit=out['initial_width']*config['quantity'][symbol]*out['economics']['multiplier'],
                    original_candidate_rows=len(diags),selected_C=sum(d['chosen']=='C' for d in diags),selected_R=sum(d['chosen']=='R' for d in diags),
                    R_actual_gap=range_actual(record,out,diags,out['initial_width']))
                cases[config['id']]['rows'].append(row)
                path=HERE/'finance/ledger'/config['id']/f'{session}_{symbol}.pkl.gz';sha=common.pack(path,stored(out,record,diags))
                cases[config['id']]['ledgers'].setdefault(session,{})[symbol]=dict(path=str(path.relative_to(common.ROOT)),SHA256=sha)
                mapping=ACCOUNT.trade_map(out,record);memo[config['id']]=mapping
                base='R_OWN' if config['mode']=='R_ONLY' else 'C_OWN'
                diff=ACCOUNT.contribution(baselines[base],mapping);diff['基準']=BASELINE_IDS[base]
                session_diffs.setdefault(config['id'],{})[symbol]=diff
                for key in FIELDS:diagnosis[config['id']][symbol][key]+=diff[key]
                del out,normal,diags
            for config in fixed['configs']:
                if config['mode']=='AUTO':
                    counterpart=catalog.setting('C_ONLY',config['trend_bp'],config['range_er'],config['C_exit'])['id']
                    session_diffs[config['id']][symbol]['AUTO対C_ONLY']=ACCOUNT.contribution(memo[counterpart],memo[config['id']])
        common.save(HERE/'finance/session_contributions'/f'{session}.json',session_diffs)
        print(session+'：26単一選択、次気配/全行会計/候補系譜と対照寄与一致',flush=True)
        del packet
    assert fixed['sources']==sources()
    for case in cases.values():
        case['summary']={s:TOTALS.aggregate(case['rows'],s,fixed['sessions']) for s in ('TOPIX','NK225')}
    common.save(HERE/'finance/results.json',dict(全合格=True,sessions=fixed['sessions'],configs=fixed['configs'],cases=cases,
        aliases=fixed['aliases'],diagnosis=diagnosis,account_count=26*33*2,actual_financial_conditions=26,display_conditions=36,
        alias_replays=0,baseline_replays=0,stage='第六段階_純価格6点の進行と往復選択',unknown_sessions=0,
        current_API_reads=0,actual_orders=0,elapsed_seconds=time.monotonic()-begin))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='純価格レジームの事前固定と一回金融')
    parser.add_argument('action',choices=('freeze','run'));parser.add_argument('--root-finance-approved',action='store_true')
    args=parser.parse_args()
    if args.action=='freeze':freeze()
    else:assert args.root_finance_approved;run()
