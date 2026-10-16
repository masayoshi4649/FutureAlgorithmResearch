"""固定当時取引更新maskだけを変え、単一位置の全後続経路を登録後に再生する。"""

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import pickle
import socket
import time

import numpy as np

import common
import data
import interface
import policy


FIELDS=('収支変化','避けた基準損失','失った基準利益','共通入口の出口変化','新たな入口の収支')
BASELINE=common.ROOT/'work/wave_v106/range_price/finance/results.json'
ACCOUNT=common.module('取引更新確認の私有四引数会計',common.HERE/'engine/accounting.py')
TOTAL=common.module('取引更新確認の不変102集約',common.ROOT/'work/wave_v102/accounting.py')
DIFF=common.module('取引更新確認の不変106寄与',common.ROOT/'work/wave_v106/accounting.py')


def sources() -> dict:
    """
    機能: 入力数学と新金融driver及び会計を、登録前に一つの指紋集合へ結ぶ。
    引数: なし。
    返り値: dict[str,str]はroot相対sourceとSHA256。旧結果の値で条件を選ばない。
    """
    metadata=common.read(data.TARGET);value=dict(metadata['source_SHA256'])
    paths=[common.HERE/n for n in ('runner.py','finance_artificial.py','engine/accounting.py','engine/fixture_snapshot.py')]
    paths += [common.ROOT/n for n in ('work/wave_v102/accounting.py','work/wave_v106/accounting.py')]
    value.update({p.relative_to(common.ROOT).as_posix():common.digest(p) for p in paths})
    return value


def execution_fingerprint(prepared: dict, normal: dict, config: dict,
                          mask: np.ndarray, reasons: np.ndarray) -> str:
    """
    機能: 同口座内の全執行入力同値だけを指紋で確認し、別窓の同じ経済を重複再生しない。
    引数: prepared/normal/config(dict)、mask/reasons(ndarray)は元価格と全当時入力。
    返り値: strはSHA256。表示IDとengine未使用のgate定義だけ除外し、拒否理由も含む。
    """
    assert not config['reentry_band'] and not config['session_brake'] and not config['r_profit']
    excluded={'id','baseline_id','trade_window_seconds','minimum_direction_votes','minimum_direction_balance','gate_scope'}
    relevant={k:v for k,v in config.items() if k not in excluded}
    value=hashlib.sha256(pickle.dumps((relevant,prepared['reference_open'],prepared['signal']['trend_width']),protocol=5))
    for name in sorted(normal):
        if name=='entry_id':continue
        child=normal[name];value.update(name.encode('utf8'))
        if isinstance(child,np.ndarray):
            value.update(str(child.dtype).encode());value.update(pickle.dumps(child.shape));value.update(child.tobytes())
        else:value.update(pickle.dumps(child,protocol=5))
    for child in (mask,reasons):value.update(child.tobytes())
    return value.hexdigest()


def stored(output: dict, normal: dict, record: dict, config: dict, mask: np.ndarray,
           reasons: np.ndarray) -> dict:
    """
    機能: 物理台帳と当時maskを保存し、全行会計は変化行へ疎に圧縮する。
    引数: output/normal/record/config(dict)、mask/reasons(ndarray)は同口座の入力と結果。
    返り値: dictは再監査可能な保存台帳。公開同値aliasも自身の入口IDとmaskを明記する。
    """
    omitted={'curve','source_curve','target_trace','stale_equity'}
    value={k:v for k,v in output.items() if k not in omitted}
    value.update(entry_id=config['id'],config_id=config['id'],row_count=len(record['seq']),selection_diagnostics=normal['decisions'],
        entry_filter=mask,filter_reason=reasons,gate_scope=config['gate_scope'],trade_window_seconds=config['trade_window_seconds'])
    for name in ('curve','source_curve','target_trace'):
        array=output[name];changed=np.r_[True,np.diff(array)!=0] if array.ndim==1 else np.r_[True,np.any(np.diff(array,axis=0)!=0,axis=1)]
        rows=np.flatnonzero(changed);value[name]=dict(rows=rows,values=array[rows])
    return value


def bind() -> None:
    """
    機能: 完成入力と最小結合人工を八部品計画へ固定し、根の照合登録を待つ。
    引数: なし。
    返り値: None。正式金融を実行せず、既36設定を変更しない。
    """
    metadata=common.read(data.TARGET);proofpath=common.HERE/'金融結合の不変委譲_v2.json'
    proof=common.read(proofpath);assert metadata['全合格'] and proof['全合格'] and proof['新金融再生']==0
    assert common.digest(common.HERE/'engine/accounting.py')==common.digest(common.ROOT/'work/wave_v106/range_price/engine/accounting.py')
    for name,sha in metadata['source_SHA256'].items():assert common.digest(common.ROOT/name)==sha,name
    configs=policy.configs();assert configs==metadata['configs']
    implementation=sources()
    for name,sha in proof['source_SHA256'].items():assert common.digest(common.ROOT/name)==sha,name
    base_meta=common.read(BASELINE);assert base_meta['全合格'] and base_meta['sessions']==metadata['sessions']
    baselines=sorted({c['baseline_id'] for c in configs})
    assert len(baselines)==4 and all(i in base_meta['cases'] for i in baselines)
    registry=common.read(common.ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/data/trials.json')['trials']
    assert not any(t['id']==policy.TRIAL_ID for t in registry)
    evidence=[dict(path=p.relative_to(common.ROOT).as_posix(),sha256=common.digest(p)) for p in
        (proofpath,common.HERE/'窓内資格境界訂正と旧人工委譲_v2.json',common.HERE/'入力測定前の固定_v2.json',
         common.ROOT/'work/wave_v106/trade_confirmation/約定更新代理の可用性と指値観測差の小結.json')]
    entry=dict(conditions=configs,condition_count=36,
        原入口='元AUTO_ER40：二市場価格6点RANGE優先、範囲内25%と両BBO1tick反発/料金RR1.25以上。非RANGEでは同方向2bp C_OWN。元数学exact。',
        取引更新確認='自己窓(cTime−W,cTime]・rawseq<=候補。usable出来高正増時のLast対直前BBOを1票。Last>=ask買票、<=bid売票、内側票0。',
        採否='方向票2以上かつside*(買票−売票)/(買票＋売票)>=0.25。未知は確認対象入口だけ拒否。',
        unknown='観測開始不足、窓内seq/価格highwater逆行又は時計欠測、volume reset/usable不能、正増行のLast/直前BBO欠測。',
        scope='Rのみ/Cのみ/BOTH。対象外入口は常時元exact。sameclock未来後半を現在票へ戻さない。')
    spec=dict(entry=entry,
        management=dict(方針='未約定中は元quiet/cut先→livefill先→未fillだけknownTREND又は固定stopで取消。新gateは公開時一度だけ。',
            保有='支持/固定stop/target/保険/広追尾/force元exact、モード変化や取引更新gateだけでは返済しない。',
            再参加='全後続候補を単一口座で再生。全返済後30秒休止、拒否候補の将来復活なし。'),
        exit=dict(C='支持4tickと始値0.1%保険、0.4%広追尾、場内force。',R='判断時固定中心targetと帯外1/2tick stop。条件到達後の次正常quote返済。',
            boundaries='新規[start+300,limit−300)、force limit−60。J静観08:45〜09:15。旧場内区切り不変更。'),
        allocation=dict(quantity={'TOPIXmini':5,'NK225micro':10},caps={'TOPIXmini':10,'NK225micro':20},
            保有='C/R共有単一位置、追加なし、同時両建てなし。',対照='元AUTO_ER40_M1/M2_MARKET/LIMITの4保存結果を同量5/10で再利用。基準再生0。'),
        cost=dict(TOPIXmini_oneway_yen=41.8,NK225micro_oneway_yen=11,規則='注文毎floor、初回/返済双方に課金。',
            気配='ラージBBOによる代理約定の気配差を含む。'),
        execution=dict(C='公開行後の次正常ask買/bid売。',R_MARKET='公開行後の次正常ask買/bid売。',R_LIMIT='公開当行禁止。固定bid買/ask売のlive注文が最初に到達する正常ask買/bid売。',
            fillrace='同行到達fillがknownTREND/stop取消より先。元quiet/cut取消はfill前。',
            遅延='追加遅延ストレスなし。注文/queue/mini板の真の成立保証はない。',
            再利用='同口座の全normal数値/拒否理由/外部maskと実行設定が完全同値の場合のみ経済台帳reuse。mask違いの事後取引削除はしない。'),
        data=dict(sessions=metadata['sessions'],input_manifests=[dict(path=p.relative_to(common.ROOT).as_posix(),sha256=common.digest(p)) for p in (data.TARGET,BASELINE)],
            scope='9/21Day〜10/13Day既知33場。未見確認0。現在Night/snapshot/APIは読まない。',
            clocks='WはCurrentPriceTime代理秒。ReceivedAt不在で実受信経過秒や二市場受信先後は不明。TradingVolumeTime停滞を出来高0としない。',
            代理='Last対直前BBO＋累計正増は攻撃側代理。増加量全体を一側へ割当てず、真の約定方向/取消/補充を同定しない。'),
        implementation=implementation)
    plan=dict(id=policy.TRIAL_ID,name='自己取引更新を確認するR/C/両入口36比較',purpose='新仮説',
        question='気配反発だけでは未確認の取引更新支持を当時入口に加えると、両商品毎場の小中利益と損失抑制を改善するか。',
        change='元AUTO4数学・出口を不変、自己取引更新1票方向確認をR/C/BOTH公開時だけ追加。',
        repeat_reason='同row更新なしは虚偽反発ではないという限界を保ち、過去取引更新の条件を出口変更と分けて比較する。',
        compares_to=['106_純価格レンジ境界反発と二市場AUTO24対照'],evidence=evidence,spec=spec,
        状態='固定36、完成33入力、最小結合人工完了。根check/register後のみ金融許可。')
    common.write(common.HERE/'試行計画_v2.json',plan)
    fixed=dict(全合格=True,configs=configs,sessions=metadata['sessions'],source_SHA256=implementation,
        input_metadata_SHA256=common.digest(data.TARGET),baseline_results_SHA256=common.digest(BASELINE),
        plan_SHA256=common.digest(common.HERE/'試行計画_v2.json'),proof_SHA256=common.digest(proofpath),
        full_account_count=2376,new_finance=0,API=0,original_book=0)
    common.write(common.HERE/'金融開始前の固定_v2.json',fixed);print('36条件v2の八部品とdriverを固定。根登録待機。')


def run() -> None:
    """
    機能: 根の登録済み36条件だけを33入力各一読で全後続再生し、四基準との寄与を保存する。
    引数: なし。
    返り値: None。実注文・原本/APIを使わず、失敗は保持し自動再実行しない。
    """
    fixed=common.read(common.HERE/'金融開始前の固定_v2.json');plan=common.read(common.HERE/'試行計画_v2.json')
    assert common.digest(common.HERE/'試行計画_v2.json')==fixed['plan_SHA256'] and fixed['configs']==policy.configs()
    assert common.digest(data.TARGET)==fixed['input_metadata_SHA256'] and common.digest(BASELINE)==fixed['baseline_results_SHA256']
    assert sources()==fixed['source_SHA256']
    registry=common.read(common.ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/data/trials.json')['trials']
    registered=[t for t in registry if t['id']==policy.TRIAL_ID];assert len(registered)==1 and registered[0]['spec']==plan['spec']
    assert not (common.HERE/'finance').exists(),'一回限定・既存金融結果は再実行しない'
    common.write(common.HERE/'finance/開始.json',dict(trial_id=policy.TRIAL_ID,条件数=36,対象口座=2376,時刻=datetime.now(timezone.utc).isoformat()))
    prior=common.read(BASELINE);base_ids=sorted({c['baseline_id'] for c in fixed['configs']});cases={c['id']:dict(rows=[],ledgers={}) for c in fixed['configs']}
    totals={i:{s:{f:0. for f in FIELDS} for s in ('TOPIX','NK225')} for i in cases}
    finished=0;actual=0;aliases=[];started=time.monotonic()
    try:
        for session in fixed['sessions']:
            packet=data.load_session(session);contributions={};baselines={s:{} for s in ('TOPIX','NK225')}
            for symbol in ('TOPIX','NK225'):
                prepared=packet['prepared'][symbol];record=prepared['record'];memo={}
                for identifier in base_ids:
                    old=common.unpack(prior['cases'][identifier]['ledgers'][session][symbol]);baselines[symbol][identifier]=DIFF.trade_map(old,record);del old
                for config in fixed['configs']:
                    selected=data.for_case(packet,symbol,config);normal=selected['normal'];mask=selected['entry_filter'];reasons=selected['filter_reason']
                    fingerprint=execution_fingerprint(prepared,normal,config,mask,reasons)
                    if fingerprint in memo:
                        output,original=memo[fingerprint];alias=dict(session=session,symbol=symbol,id=config['id'],reused_from=original,input_SHA256=fingerprint)
                        aliases.append(alias)
                    else:
                        output=interface.play(prepared,normal,config,quantity=config['quantity'][symbol],entry_filter=mask,filter_reason=reasons)
                        memo[fingerprint]=(output,config['id']);actual+=1;alias=None
                    # ----------------------------------------
                    # 外部maskは独立四引数会計の元数学に追加せず、実entry判断rowで明示照合する。
                    for order in output['orders'][output['orders'][:,7]!=0]:assert mask[int(order[1])]
                    row=ACCOUNT.inspect((session,symbol),record,output,normal)
                    row.update(selected_C=int(np.count_nonzero((normal['entry_families']==1)&mask)),selected_R=int(np.count_nonzero((normal['entry_families']==2)&mask)),
                        economic_alias=alias,budget_unit=prepared['reference_open']*.001*config['quantity'][symbol]*(1000. if symbol=='TOPIX' else 10.))
                    cases[config['id']]['rows'].append(row)
                    path=common.HERE/'finance/ledger'/config['id']/f'{session}_{symbol}.pkl.gz'
                    ledger=stored(output,normal,record,config,mask,reasons);ledger['economic_alias']=alias;ledger['execution_input_SHA256']=fingerprint
                    common.write(path,ledger);cases[config['id']]['ledgers'].setdefault(session,{})[symbol]=dict(path=path.relative_to(common.ROOT).as_posix(),SHA256=common.digest(path))
                    changed=DIFF.trade_map(output,record);delta=DIFF.contribution(baselines[symbol][config['baseline_id']],changed)
                    contributions.setdefault(config['id'],{})[symbol]=delta
                    for f in FIELDS:totals[config['id']][symbol][f]+=delta[f]
                    finished+=1
                del memo
            common.write(common.HERE/'finance/contributions'/(session+'.json'),contributions)
            del packet
            print(json.dumps(dict(完了場=session,対象口座=finished,実再生口座=actual,同全入力経済reuse=len(aliases)),ensure_ascii=False),flush=True)
        assert finished==2376 and sources()==fixed['source_SHA256']
        for case in cases.values():case['summary']={s:TOTAL.aggregate(case['rows'],s,fixed['sessions']) for s in ('TOPIX','NK225')}
        common.write(common.HERE/'finance/results.json',dict(全合格=True,sessions=fixed['sessions'],configs=fixed['configs'],cases=cases,diagnosis=totals,
            baseline_ids=base_ids,baseline_replays=0,account_count=finished,actual_financial_accounts=actual,economic_aliases=aliases,
            input_session_reads=33,input_metadata_SHA256=fixed['input_metadata_SHA256'],source_SHA256=fixed['source_SHA256'],開始終端source一致=True,
            original_book_reads=0,current_API_reads=0,actual_orders=0,unknown_sessions=0,elapsed_seconds=time.monotonic()-started))
    except BaseException as error:
        common.write(common.HERE/'finance/停止.json',dict(全合格=False,例外=repr(error),完了口座数=finished,実再生口座数=actual,自動再試行=0));raise


def main() -> None:
    """
    機能: 金融前束縛又は根の明示許可後一回金融を選択する。
    引数: CLI action(str:bind/run)、--root-finance-approved(bool)。
    返り値: None。登録不一致や再実行は拒否し、APIを禁止する。
    """
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=('bind','run'));parser.add_argument('--root-finance-approved',action='store_true')
    args=parser.parse_args()
    if args.action=='bind':bind();return
    assert args.root_finance_approved
    def denied(*args: object, **kwargs: object) -> None:
        """
        機能: 保存金融に不要なネットワーク接続を拒否する。
        引数: args/kwargs(object)は通信要求。
        返り値: None。常に例外で拒否する。
        """
        raise RuntimeError('保存金融はAPI禁止')
    socket.create_connection=denied;socket.socket.connect=denied;run()


if __name__=='__main__':main()
