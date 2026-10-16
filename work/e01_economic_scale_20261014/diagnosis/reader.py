"""根の金融完了後だけ、完成小会計と公開会計を各一読して実損失を整理する。"""

import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import traceback
from zoneinfo import ZoneInfo

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
STUDY=HERE.parent
SYMBOLS=('TOPIX','NK225')
TICKS={'TOPIX':.5,'NK225':10.}
REASONS={90:'新規FAK約定',91:'元paper返済',92:'予定静観',93:'場内期限',
    140:'親純利益目標',141:'親純損失停止',142:'親利益追尾',143:'場純損失停止',144:'四分の一部分返済'}
FIXED_CASES=('E01_SCALE_SELECTED_FULL_TARGET','E01_SCALE_SELECTED_FULL_TRAIL')


def sha(payload: bytes) -> str:
    """
    機能: 一回読取したバイトをSHA256へ結ぶ。
    引数: payload(bytes) は小source又は小会計。
    返り値: str は指紋。再読取を行わない。
    """
    return hashlib.sha256(payload).hexdigest()


def sources() -> dict:
    """
    機能: 金融源とは別の診断source集合を拘束する。
    引数: なし。
    返り値: dict[str,str] は診断所有域二sourceの指紋。
    """
    return {p.relative_to(ROOT).as_posix():sha(p.read_bytes()) for p in sorted(HERE.glob('*.py'))}


def write(name: str, value: dict) -> None:
    """
    機能: 診断所有域へ新規証跡を保存し、旧成功又はFalseを上書きしない。
    引数: name(str)、value(dict) は資料名とJSON構造。
    返り値: None。NaNを拒否し金融/公開/共通を書き換えない。
    """
    path=HERE/name
    assert not path.exists() and path.resolve().is_relative_to(HERE)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')


def timed(value: object) -> object:
    """
    機能: 保存された価格代理epochへ日本日付のJSTを併記する。
    引数: value(object) は小系譜。Noneはそのまま残す。
    返り値: object は時刻併記済み構造。受信/注文応答時刻に置換しない。
    """
    if isinstance(value,list):return [timed(v) for v in value]
    if not isinstance(value,dict):return value
    result={k:timed(v) for k,v in value.items()}
    for key,v in value.items():
        if key.endswith('price_time_s') and isinstance(v,(int,float)) and math.isfinite(v):
            result[key+'_JST']=datetime.fromtimestamp(v,ZoneInfo('Asia/Tokyo')).isoformat()
    return result


def vote_band(votes: object) -> str:
    """
    機能: 実親公開時の方向票を事前指定の件数帯へ写す。
    引数: votes(object) は保存票数。欠落は未保存として区別する。
    返り値: str は二票/三〜四/五〜九/十以上又は未保存。
    """
    if votes is None:return '未保存'
    assert isinstance(votes,(int,float)) and int(votes)==votes and votes>=2
    return '2票' if votes==2 else '3〜4票' if votes<=4 else '5〜9票' if votes<=9 else '10票以上'


def profile(parent: dict, config: dict) -> dict:
    """
    機能: 完結実親の公開/入口/極値/返済判断と約定を保存情報だけで整理する。
    引数: parent/config(dict) は完成小射影と固定条件。
    返り値: dict は損失タグと時刻/気配/料/線。事後極値を救済利益へしない。
    """
    entry=parent['entry'];symbol=parent['symbol'];side=parent['side'];net=parent['net_yen']
    assert side in (1,-1) and entry['quantity']==parent['entry_quantity']>0
    assert sum(e['quantity'] for e in parent['exits'])==parent['entry_quantity']
    assert entry['fee_yen']+sum(e['fee_yen'] for e in parent['exits'])==parent['fees_yen']
    assert math.isclose(entry['price'],entry['ask' if side>0 else 'bid'],abs_tol=1e-8)
    cap=parent['published_price_cap'];inside=entry['price']<=cap+1e-8 if side>0 else entry['price']>=cap-1e-8
    assert inside
    spread=entry['ask']-entry['bid'];assert spread>0
    worst=parent['worst_parent_liquidation_yen'];best=parent['best_parent_liquidation_yen']
    assert worst<=best and parent['first_parent_liquidation_argmin']['parent_liquidation_yen']==worst
    assert parent['first_parent_liquidation_argmax']['parent_liquidation_yen']==best
    price_adverse=max(0.,-parent['liquidation_side_mae_price'])
    extra=max(0.,price_adverse-spread)
    pub_bid,pub_ask=entry.get('source_bid'),entry.get('source_ask')
    pub_spread=pub_ask-pub_bid if isinstance(pub_bid,(int,float)) and isinstance(pub_ask,(int,float)) else None
    multiplier=1000. if symbol=='TOPIX' else 10.
    initial_cost=spread*parent['entry_quantity']*multiplier+entry['fee_yen']
    remaining_fee=(parent['entry_quantity']*209//5) if symbol=='TOPIX' else parent['entry_quantity']*11
    tags=[]
    if net<0:
        tags.append('費用後黒字を観測せず' if best<=0 else '費用後黒字を返して赤字')
        tags.append('初期気配差からの追加逆行が一観測呼値以内' if extra<=TICKS[symbol]+1e-8 else '初期気配差を超える追加逆行が一観測呼値超')
    final=parent['exits'][-1]['reason']
    if final in (92,93):tags.append(REASONS[final]+'による終了')
    target=parent['target_yen'] if config['exit_id']=='TARGET' else None
    exits=[dict(e,理由=REASONS.get(e['reason'],'保存番号'+str(e['reason']))) for e in parent['exits']]
    return timed(dict(**parent,票帯=vote_band(parent.get('published_direction_votes')),入口FAK価格内=inside,
        公開時気配差=pub_spread,実初期気配差=spread,初回料込即時全返済見積損失円=initial_cost+remaining_fee,
        初期気配費用で親損失線到達=initial_cost+remaining_fee>=parent['parent_stop_yen'],
        初期気配差からの追加逆行値幅=extra,
        追加逆行観測呼値=extra/TICKS[symbol],有効純利益目標円=target,
        事後ピーク目標比=best/target if target is not None and target>0 else None,
        事後ピークから最終netへ返した額=max(0.,best-net),観測タグ=tags,返済系譜=exits,
        最終返済理由=REASONS.get(final,'保存番号'+str(final)),
        解釈='価格極値は実保有期間の事後観測。追加逆行一呼値は説明用の区分で、相場の心理/真の方向/別出口成功の証明ではない。'))


def grouped(parents: list[dict], config: dict) -> dict:
    """
    機能: 実親全数を票帯/観測タグ/返済理由別に正しい分母で集計する。
    引数: parents(list[dict])、config(dict) は同商品/同caseの全完結親。
    返り値: dict は件数と親net正負。重なるタグを排他的原因の内訳と呼ばない。
    """
    transformed=[profile(p,config) for p in parents];bands={};tags=Counter();reasons=Counter()
    for band in ('2票','3〜4票','5〜9票','10票以上','未保存'):
        own=[p for p in transformed if p['票帯']==band]
        bands[band]=dict(親数=len(own),全実親分母=len(parents),利益親=sum(p['net_yen']>0 for p in own),
            損失親=sum(p['net_yen']<0 for p in own),利益円=sum(max(0.,p['net_yen']) for p in own),
            損失円=sum(max(0.,-p['net_yen']) for p in own),収支円=sum(p['net_yen'] for p in own))
    for p in transformed:tags.update(p['観測タグ']);reasons.update([p['最終返済理由']])
    assert sum(v['親数'] for v in bands.values())==len(parents)
    return dict(全実親数=len(parents),利益親=sum(p['net_yen']>0 for p in transformed),
        損失親=sum(p['net_yen']<0 for p in transformed),票帯=bands,重複する観測タグ=dict(tags),最終返済理由=dict(reasons),
        黒字反証='各票帯の利益親も全数保存。赤字上位場の例だけから新条件の有効性を断定しない。')


def build(finance: dict, public: dict|None, fixed: dict) -> dict:
    """
    機能: 全量目標/追尾と事前規則の商品別選択から赤字上位三場・損失上位三親を選ぶ。
    引数: finance/fixed(dict)、public(dict|None) は根完了後の小資料と任意公開会計。
    返り値: dict は対象全親の小集計と具体損失。元台帳/入力を探索しない。
    """
    assert finance['全合格'] and finance['source開始終端一致']
    assert finance['source_SHA256']==fixed['金融source_SHA256'] and finance['case_SHA256']==fixed['case_SHA256']
    assert finance['sessions']==fixed['sessions'] and len(finance['sessions'])==33
    selected=fixed['根通知参考選択']
    if public is not None:
        assert public['全合格'] and public['金融source_SHA256']==finance['source_SHA256']
        assert public['case_SHA256']==finance['case_SHA256'] and public['sessions']==finance['sessions']
        assert public['sources']['selection_plan']==fixed['選定規則SHA256'] and public['pair']['selected']==selected
    configs={c['id']:c for c in finance['configs']};output={}
    assert set(selected)==set(SYMBOLS)
    for symbol in SYMBOLS:
        roles=[('全量目標',FIXED_CASES[0]),('全量追尾',FIXED_CASES[1]),('事前規則による商品別選択',selected[symbol])]
        for role,cid in roles:
            assert cid in configs
            rows=[r for r in finance['results'][cid]['rows'] if r['symbol']==symbol]
            pp=[p for p in finance['actual_parent_diagnostics'][cid] if p['symbol']==symbol]
            assert len(rows)==33 and len(pp)==sum(r['親数'] for r in rows)
            assert math.isclose(sum(r['収支'] for r in rows),sum(p['net_yen'] for p in pp),abs_tol=1e-5)
            if public is not None:
                shown=[r for r in public['cases'][cid]['rows'] if r['symbol']==symbol]
                assert {(r['session'],r['収支']) for r in rows}=={(r['session'],r['net']) for r in shown}
            worst=sorted((r for r in rows if r['収支']<0),key=lambda r:(r['収支'],r['session']))[:3]
            detail=[]
            for row in worst:
                own=[p for p in pp if p['session']==row['session']]
                assert math.isclose(sum(p['net_yen'] for p in own),row['収支'],abs_tol=1e-5)
                losses=sorted((p for p in own if p['net_yen']<0),key=lambda p:(p['net_yen'],p['parent']))[:3]
                detail.append(dict(session=row['session'],場会計=row,全親数=len(own),
                    損失上位親=[profile(p,configs[cid]) for p in losses],
                    同場黒字親数=sum(p['net_yen']>0 for p in own),同場黒字親net=sum(max(0.,p['net_yen']) for p in own)))
            key=symbol+'|'+role
            output[key]=dict(symbol=symbol,role=role,case_id=cid,全33集計=grouped(pp,configs[cid]),赤字上位場=detail)
    return dict(全合格=True,商品別選択=selected,選択の扱い='根の事前v2選定による参考RISK_GU。主目標合格又は推奨の意味ではない。',対象=output,
        目的='全量/固定選択の実損失を公開票、初期気配差、実保有中の逆行/利益返し、返済判断で説明する。',
        留保=['価格時計はCurrentPriceTime代理。物理受信/注文応答の時刻ではない。',
            'MFE/MAEは実保有区間の事後観測。別出口なら取れた利益又は将来入口の資料として使用しない。',
            '保存されないpeer板厚/補充/心理は推定しない。非normal判断の気配はNoneを保持する。',
            '重複する観測タグは排他的な原因比率ではない。同じcaseの複数役割も追加試行に数えない。'],
        金融=0,原input=0,台帳=0,原板=0,NPZ=0,API=0)


def half_full(finance: dict) -> dict:
    """
    機能: 同じpaper親と公開原seqの半量/全量を照合し、費用差と出口/後参加差を区別する。
    引数: finance(dict) は一読した完成親小射影。
    返り値: dict は全対応件数と非比例の具体例。数量比例を新金融に代用しない。
    """
    output={}
    for symbol in SYMBOLS:
        for exit_id in ('GU','TARGET','TRAIL','PARTIAL'):
            half='E01_SCALE_SELECTED_HALF_'+exit_id;full='E01_SCALE_SELECTED_FULL_'+exit_id
            groups=[]
            for cid in (half,full):
                own=[p for p in finance['actual_parent_diagnostics'][cid] if p['symbol']==symbol]
                mapped={(p['session'],p['parent'],p['entry']['source_raw_seq']):p for p in own}
                assert len(mapped)==len(own);groups.append(mapped)
            left,right=groups;common=set(left)&set(right);differ=[]
            for key in sorted(common):
                a,b=left[key],right[key]
                same_entry=(a['entry']['row'],a['entry']['price'])==(b['entry']['row'],b['entry']['price'])
                same_exit=[(e['row'],e['price'],e['reason']) for e in a['exits']]==[(e['row'],e['price'],e['reason']) for e in b['exits']]
                gap=b['net_yen']-2*a['net_yen'];fee_delta=b['fees_yen']-2*a['fees_yen']
                if not same_entry or not same_exit or abs(gap+fee_delta)>1e-6:
                    differ.append(dict(session=key[0],parent=key[1],公開原seq=key[2],同新規=same_entry,同返済行理由=same_exit,
                        半量=timed(a),全量=timed(b),全量net引く半量二倍=gap,注文別料差=fee_delta,
                        場停止を含む=any(e['reason']==143 for p in (a,b) for e in p['exits'])))
            output[symbol+'|'+exit_id]=dict(共通公開親=len(common),半量だけ=len(set(left)-set(right)),全量だけ=len(set(right)-set(left)),
                非比例親数=len(differ),具体例=sorted(differ,key=lambda p:(-abs(p['全量net引く半量二倍']),p['session'],p['parent']))[:5],
                限界='同枚数換算は診断差額だけ。場停止/親判断/保有busyによる後参加差を別実状態の記録で比較する。')
    return output


def prepare() -> None:
    """
    機能: 完了前は正式固定と選定規則だけを読んで診断目的と一読範囲を保存する。
    引数: なし。
    返り値: None。金融結果/公開会計/元入力/台帳の本文は読まない。
    """
    path=STUDY/'engine/金融事前固定.json';payload=path.read_bytes();fixed=json.loads(payload)
    assert fixed['正式freeze'] and len(fixed['configs'])==14
    selection=STUDY/'報告書選定の事前固定_v2.json';selection_payload=selection.read_bytes()
    assert sha(selection_payload)=='145de1fef9b8527a66f74623fd45a77a297789b770ad10ed4d8bf26ecd5679a4'
    write('読取目的の事前固定.json',dict(全合格=True,診断source_SHA256=sources(),金融固定SHA256=sha(payload),
        金融source_SHA256=fixed['source_SHA256'],case_SHA256=fixed['case_SHA256'],sessions=fixed['sessions'],
        選定規則SHA256=sha(selection_payload),選定規則位置=selection.relative_to(ROOT).as_posix(),
        金融結果位置=(STUDY/'engine/finance/結果.json').relative_to(ROOT).as_posix(),
        公開会計位置='アルゴリズム調査/00107_保有容量と一取引利益の再検証/容量別E01の一場平均と全場会計.json',
        予定読取={'完成金融小結果':1,'派生親射影':1,'選定小証跡':1,'公開小会計':0,'原input':0,'台帳':0},
        対象規則='SELECTED_FULL_TARGET/TRAIL及び事前選定v2の商品別一条件。赤字net昇順三場、その場の負net昇順三親。同点は場名/parent昇順。',
        親集計='対象各case/商品全実親の票帯2/3-4/5-9/10+と黒字反証。役割重複は追加試行ではない。',
        根通知参考選択={s:'E01_SCALE_SELECTED_RISK_GU' for s in SYMBOLS},
        最優先='全量目標/追尾最大赤字の公開/初fill気配差と初期spread料、途中逆行、次normal返済悪化を切分ける。半/全量の対応公開親と後参加差も小射影から比較。',
        実行条件='根の金融完了通知後だけ --root-finance-complete。一回失敗後の自動再開始無し。',
        結果読取=0,金融=0,原input=0,台帳=0,API=0))
    print('原因診断の読取目的を固定。金融結果/公開会計読取0。')


def run() -> None:
    """
    機能: 根金融完了授権後だけ小会計二資料各一読を原因診断へ結ぶ。
    引数: なし。CLIで根完了フラグを必須にする。
    返り値: None。開始/False/結果を保存し自動再開始しない。
    """
    assert not (HERE/'開始.json').exists() and not (HERE/'False.json').exists()
    fixed=json.loads((HERE/'読取目的の事前固定.json').read_bytes());source=sources()
    assert source==fixed['診断source_SHA256']
    write('開始.json',dict(授権='根金融完了',診断source_SHA256=source));counts=Counter()
    try:
        payload=(ROOT/fixed['金融結果位置']).read_bytes();counts['finance']+=1
        finance=json.loads(payload);hashes={'finance':sha(payload)}
        projection={k:finance[k] for k in ('全合格','configs','sessions','source開始終端一致','source_SHA256','case_SHA256','actual_parent_diagnostics')}
        projection['results']={cid:{'rows':value['rows']} for cid,value in finance['results'].items()}
        write('目的別の完成親小射影.json',dict(元金融SHA256=hashes['finance'],目的='公開照合/選択補足と半全量差を元result再読0で行う。',finance=projection))
        result=build(projection,None,fixed);result['半量全量の対応親']=half_full(projection)
        assert source==sources()
        result.update(読取計数=dict(counts),計算元SHA256=hashes,診断source_SHA256=source)
        write('全量二出口と選択版の具体損失.json',result)
        print(json.dumps(dict(全合格=True,読取計数=dict(counts),商品別選択=result['商品別選択']),ensure_ascii=False))
    except BaseException:
        write('False.json',dict(全合格=False,原因=traceback.format_exc(),読取計数=dict(counts),自動再開始=False));raise


def attach_selection() -> None:
    """
    機能: 一読派生射影と公開選定小証跡を読み、原金融結果の再読無しで参考選択を照合する。
    引数: なし。
    返り値: None。追加金融/入力/台帳は無し。照合証跡だけ新規保存する。
    """
    fixed=json.loads((HERE/'読取目的の事前固定.json').read_bytes());assert sources()==fixed['診断source_SHA256']
    projection=json.loads((HERE/'目的別の完成親小射影.json').read_bytes())
    path=STUDY/'report_check/小会計確認と選択根拠.json';payload=path.read_bytes();chosen=json.loads(payload)
    assert chosen['selected']==fixed['根通知参考選択'] and chosen['sources']['result']==projection['元金融SHA256']
    write('参考選択の小証跡との追加照合.json',dict(全合格=True,選択=chosen['selected'],選択根拠=chosen['selection'],
        selected_metrics=chosen['selected_metrics'],選択証跡SHA256=sha(payload),元金融SHA256=projection['元金融SHA256'],
        読取計数={'一読派生親射影':1,'選定小証跡':1,'元金融結果':0,'原input':0,'台帳':0},金融=0,API=0))
    print('参考選択小証跡と一読射影が一致。元金融結果再読0。')


def main() -> None:
    """
    機能: 非金融準備と根金融完了後診断を分ける。
    引数: CLI --prepare/--root-finance-complete/--attach-selection(bool)。
    返り値: None。金融再生/原データ/API/公開変更を行わない。
    """
    parser=argparse.ArgumentParser();group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--prepare',action='store_true');group.add_argument('--root-finance-complete',action='store_true')
    group.add_argument('--attach-selection',action='store_true')
    args=parser.parse_args()
    if args.prepare:prepare()
    elif args.root_finance_complete:run()
    else:attach_selection()


if __name__=='__main__':main()
