"""固定代表の同入口・同損切り上限・同保有時間の管理対照だけを、保存結果から診断する。"""

import argparse
import hashlib
import json
from pathlib import Path
import pickle
import socket
import sys

import numpy as np


sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
STUDY=HERE.parent
SYMBOLS=('TOPIX','NK225')
FIELDS=('profit','loss','net','profit_share','money_loss_share','profit_loss_ratio','trades','active_sessions',
        'average_net','average_win','average_loss','win_rate','payoff','fees','spread_drag','legs','adds',
        'risk_excesses','winning_lots','losing_lots','max_trade_loss','max_leg_loss','drawdown',
        'without_best_session','without_best_profit_share','goal80')
REASONS={1:'初期損切り',2:'利益追従',3:'保有時間上限',4:'場内全返済',6:'二市場の反対合意',
         8:'約定後の追加リスク超過',9:'進行失敗と停滞'}


def deny(*args: object,**kwargs: object) -> None:
    """機能: 保存結果の分析から外部への通信を禁止する。

    引数: args(tuple)、kwargs(dict)。返り値: なし(None)。呼出し時は例外。
    """
    raise RuntimeError('固定結果を読み取るだけの診断中に通信してはならない')


def load(path: Path) -> object:
    """機能: 許可後に固定結果又は既存台帳を読み取る。

    引数: path(Path)。返り値: JSON又は保存Python値(object)。新規再生はしない。
    """
    return pickle.loads(path.read_bytes()) if path.suffix=='.pkl' else json.loads(path.read_text(encoding='utf8'))


def digest(path: Path) -> str:
    """機能: 分析対象の指紋を一定メモリーで求める。

    引数: path(Path)。返り値: SHA256(str)。
    """
    value=hashlib.sha256()
    with path.open('rb') as stream:
        while data:=stream.read(4*1024*1024):value.update(data)
    return value.hexdigest()


def amounts(values: list | np.ndarray) -> dict:
    """機能: 全建値又は全組の利益・損失を、相殺前に分けて集計する。

    引数: values(list又はndarray:料金後損益)。返り値: 件数・金額・割合(dict)。
    """
    a=np.asarray(values,dtype=float);profit=float(a[a>0].sum());loss=float(-a[a<0].sum())
    return dict(件数=len(a),利益=profit,損失=loss,収支=profit-loss,
        金額利益割合=profit/(profit+loss) if profit+loss else None,
        平均収支=float(a.mean()) if len(a) else None,
        勝数=int((a>0).sum()),負数=int((a<0).sum()),同値数=int((a==0).sum()))


def campaigns(ledger: dict,sessions: list[str],symbol: str) -> list[dict]:
    """機能: 全返済組を入口判断行で識別し、初回玉・追加玉・出口理由を保存する。

    引数: ledger(dict)、sessions(list[str])、symbol(str)。返り値: 組別明細(list[dict])。
    未来値は使わず、保存された実注文と実返済だけを読み取る。
    """
    output=[]
    for (session,product),record in sorted(ledger.items()):
        if product!=symbol or session not in sessions:continue
        orders=record['orders'];trades=record['trades'];risks=record['risk_events']
        assert len(orders)==0 or np.all(orders[:,0]>orders[:,1])
        assert record['stats'][0]==record['stats'][1]==record['stats'][2]==0
        for close in orders[orders[:,7]==0]:
            cid=close[2];t=trades[trades[:,0]==cid];opened=orders[(orders[:,2]==cid)&(orders[:,7]==1)]
            assert len(t)==len(opened) and len(t)>0
            first=opened[np.argmin(opened[:,9])];a=amounts(t[:,10]);group=float(t[:,10].sum())
            assert abs(group-a['収支'])<1e-6 and abs(t[:,8].sum()-close[8])<1e-6
            assert int(t[:,4].sum())==int(close[4])
            initial=t[t[:,11]==0,10];added=t[t[:,11]>0,10]
            output.append(dict(セッション=session,商品=symbol,組番号=int(cid),入口判断行=int(first[1]),
                入口約定行=int(first[0]),返済判断行=int(close[1]),返済約定行=int(close[0]),
                方向=int(first[3]),返済理由=int(close[6]),返済理由名=REASONS.get(int(close[6]),'不明'),
                初回枚数=int(first[4]),最終枚数=int(close[4]),追加回数=len(opened)-1,
                建値別=a,組収支=group,初回玉=amounts(initial),追加玉=amounts(added),
                組黒字でも負け建値あり=bool(group>0 and np.any(t[:,10]<0)),
                注文料金=float(t[:,7:9].sum()),
                追加リスク確認件数=int(np.count_nonzero(risks[:,1]==cid)) if len(risks) else 0))
    return output


def detail(items: list[dict]) -> dict:
    """機能: 実返済だけから出口別損益と追加の成否をまとめる。

    引数: items(list[dict])。返り値: 建値・組・初回/追加・返済理由の診断(dict)。
    """
    reasons={}
    for code in sorted({x['返済理由'] for x in items}):
        chosen=[x for x in items if x['返済理由']==code]
        reasons[str(code)]=dict(理由=REASONS.get(code,'不明'),組=amounts([x['組収支'] for x in chosen]),
            利益=sum(x['建値別']['利益'] for x in chosen),損失=sum(x['建値別']['損失'] for x in chosen),
            注文料金=sum(x['注文料金'] for x in chosen))
    sums={}
    for name in ('初回玉','追加玉'):
        p=sum(x[name]['利益'] for x in items);l=sum(x[name]['損失'] for x in items)
        sums[name]=dict(件数=sum(x[name]['件数'] for x in items),利益=p,損失=l,収支=p-l,
            金額利益割合=p/(p+l) if p+l else None)
    return dict(組=amounts([x['組収支'] for x in items]),建値別利益=sum(x['建値別']['利益'] for x in items),
        建値別損失=sum(x['建値別']['損失'] for x in items),**sums,返済理由別=reasons,
        追加した組数=sum(x['追加回数']>0 for x in items),追加回数=sum(x['追加回数'] for x in items),
        組黒字でも負け建値あり=sum(x['組黒字でも負け建値あり'] for x in items),
        利益追従で赤字の組数=sum(x['返済理由']==2 and x['組収支']<0 for x in items),
        平均最終枚数=sum(x['最終枚数'] for x in items)/len(items) if items else None,
        大きい負けの例=sorted([x for x in items if x['組収支']<0],key=lambda x:x['組収支'])[:3])


def difference(a: dict,b: dict) -> dict:
    """機能: 同商品・同期間の条件差を、損失減額と利益犠牲へ分けて示す。

    引数: a/b(dict:比較先/対照の期間会計)。返り値: 差・削減率・金額割合差(dict)。
    """
    keys=('profit','loss','net','trades','average_net','fees','spread_drag','adds','risk_excesses')
    output={k:(a.get(k)-b.get(k)) if a.get(k) is not None and b.get(k) is not None else None for k in keys}
    output.update(損失削減率=(b['loss']-a['loss'])/b['loss'] if b['loss'] else None,
        利益維持率=a['profit']/b['profit'] if b['profit'] else None,
        金額利益割合差=(a['profit_share']-b['profit_share']) if a['profit_share'] is not None and b['profit_share'] is not None else None,
        取引減少率=(b['trades']-a['trades'])/b['trades'] if b['trades'] else None)
    return output


def paired_entries(a: list[dict],b: list[dict]) -> dict:
    """機能: 同じ入口判断が実行された組と、経路変更による片側だけの組を分ける。

    引数: a/b(list[dict]:A1/A0の組明細)。返り値: 同入口比較と片側追加機会の集計(dict)。
    終了時刻や次の新規機会が変わるため、単純なA1-A0を純粋な追加玉効果と断定しない。
    """
    key=lambda x:(x['セッション'],x['入口判断行'],x['方向'])
    aa={key(x):x for x in a};bb={key(x):x for x in b};assert len(aa)==len(a) and len(bb)==len(b)
    common=sorted(aa.keys()&bb.keys())
    return dict(同入口組数=len(common),
        同入口A1組=amounts([aa[k]['組収支'] for k in common]),同入口A0組=amounts([bb[k]['組収支'] for k in common]),
        同入口でA1収支改善組数=sum(aa[k]['組収支']>bb[k]['組収支'] for k in common),
        同入口で返済判断行が変わった組数=sum(aa[k]['返済判断行']!=bb[k]['返済判断行'] for k in common),
        A1だけの入口=amounts([aa[k]['組収支'] for k in aa.keys()-bb.keys()]),
        A0だけの入口=amounts([bb[k]['組収支'] for k in bb.keys()-aa.keys()]),
        A1の単純2割対照との差=sum(aa[k]['組収支']-.2*bb[k]['組収支'] for k in common),
        二割対照注記='固定A0を一律2割に換算しただけの診断。数量ごとの円未満切捨て、保護線、追加、出口時点の変更を含むため追加玉だけの因果効果ではない。')


def condition_identity(c: dict) -> str:
    """機能: 保存条件の識別子を、管理・数量の変種から再構成する。

    引数: c(dict)。返り値: ID(str)。
    """
    return f"{c['entry']}_P{c['policy']}_R{c['stop_bp']}_T{c['trail_bp']}_H{c['hold_minutes']}_A{c['allocation']}"


def findings(representatives: dict) -> list[dict]:
    """機能: 固定代表の目標達成と、数量縮小だけによる損失削減を短く整理する。

    引数: representatives(dict:固定代表別対照診断)。返り値: 商品別の結論列(list[dict])。
    後半や追加結果の順位を作らず、選定済み代表についてだけ同じ基準を適用する。
    """
    output=[]
    for ident,record in representatives.items():
        if record['固定代表'].get('診断専用',False):continue
        for symbol in SYMBOLS:
            row=dict(代表=ident,商品=symbol,代表を選び直した=False,期間別={})
            for period,products in record['期間'].items():
                m=products[symbol]['条件'][ident]['期間指標']
                counts=(20,8) if period=='前16' else (10,5) if period=='後13' else None
                row['期間別'][period]=dict(利益=m['profit'],損失=m['loss'],収支=m['net'],金額利益割合=m['profit_share'],
                    組数=m['trades'],活動場=m['active_sessions'],目標80達成=m['goal80'],
                    件数条件充足=m['trades']>=counts[0] and m['active_sessions']>=counts[1] if counts else None,
                    無取引を成功に含めない=m['trades']>0)
            controls=record['期間']['全29'][symbol];allocation=record['設定']['allocation'];policy=record['設定']['policy']
            if allocation==1 and f'P{policy}' in controls['配分対照']:
                comparison=controls['配分対照'][f'P{policy}'];m=controls['条件'][ident]['期間指標']
                row['小開始の結論']=dict(追加回数=m['adds'],損失削減率=comparison['A1引くA0']['損失削減率'],
                    利益維持率=comparison['A1引くA0']['利益維持率'],金額利益割合差=comparison['A1引くA0']['金額利益割合差'],
                    説明='実追加が0回なので初回数量を減らした効果。金額損失の減少だけを損益比率や予測品質の改善と解釈しない。'
                    if m['adds']==0 else '追加玉の実損益と同入口比較を併記。全経路差を追加玉だけの因果効果とはしない。')
            output.append(row)
    return output


def main() -> None:
    """機能: 前半固定代表の管理十対照を、選定後の保存結果だけで独立分析する。

    引数: CLI --include-extra(bool:追加確認完了後だけ)。返り値: なし(None)。
    rootの実行許可後だけ起動する。結果読取・対照診断を行い、新条件や新試験を作らない。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--include-extra',action='store_true');args=parser.parse_args()
    socket.socket.connect=deny;socket.create_connection=deny
    chosen=load(STUDY/'前半選定.json');fixed=load(STUDY/'事前固定.json')
    assert chosen['前16だけで選択']
    if args.include_extra:assert (STUDY/'未見確認完了.json').exists(),'追加場は実行完了通知後だけ読む'
    paths=[STUDY/'前半選定.json',STUDY/'事前固定.json'];representatives={}
    groups=list(chosen['代表'])
    # ----------------------------------------
    # J代表が旧出口を選んだ時だけ、既存492内の固定R20/H30十対照を別の診断として読む。
    # 代表の差替えや未見の追加再生は行わない。rootから完了後に明示依頼された切分けである。
    for representative in chosen['代表']:
        if representative['family']=='J' and '_P0_' in representative['id']:
            entry=representative['id'].split('_')[0]
            codes=[f'{entry}_P{p}_R20_T{20 if p==2 else 40}_H30_A{a}' for p in range(1,6) for a in (0,1)]
            groups.append(dict(id=codes[0],family='J',eligible=None,controls=codes,診断専用=True,
                説明='選定代表とは別に、既存固定492条件内のJ入口R20/H30十対照を診断。前半後半で再選定せず未見には新適用しない。'))
    for representative in groups:
        ident=representative['id'];seed=load(STUDY/'results'/(ident+'.json'))['config']
        control_ids=representative['controls'];periods={x:fixed[x] for x in ('前16','後13','全29')}
        with_extra=args.include_extra and not representative.get('診断専用',False)
        if with_extra:periods['追加1']=fixed['追加1']
        entries={}
        for control in control_ids:
            base=STUDY;result_path=base/'results'/(control+'.json');ledger_path=base/'ledgers'/(control+'.pkl')
            result=load(result_path);ledger=load(ledger_path);paths.extend((result_path,ledger_path))
            assert digest(ledger_path)==result['ledger_SHA256']
            assert all(result['config'][x]==seed[x] for x in ('entry','stop_bp','hold_minutes','cooldown'))
            if with_extra:
                extra=STUDY/'unseen';rp=extra/'results'/(control+'.json');lp=extra/'ledgers'/(control+'.pkl')
                addition=load(rp);more=load(lp);paths.extend((rp,lp));assert digest(lp)==addition['ledger_SHA256']
                assert not set(ledger)&set(more);ledger.update(more)
                result['periods'].update(addition['periods']);result['rows']+=addition['rows']
            entries[control]=dict(result=result,ledger=ledger)
        group={}
        for period,sessions in periods.items():
            products={}
            for symbol in SYMBOLS:
                controls={};items={}
                for control,value in entries.items():
                    a=value['result']['periods'][period][symbol];item=campaigns(value['ledger'],sessions,symbol);d=detail(item)
                    assert len(item)==a['trades'] and abs(d['建値別利益']-a['profit'])<1e-6 and abs(d['建値別損失']-a['loss'])<1e-6
                    assert abs(d['組']['収支']-a['net'])<1e-6
                    controls[control]=dict(期間指標={k:a.get(k) for k in FIELDS},実返済診断=d);items[control]=item
                allocations={};management={}
                for policy in range(1,6):
                    candidate=dict(seed,policy=policy,trail_bp=seed['stop_bp'] if policy==2 else 2*seed['stop_bp'])
                    aid=condition_identity(dict(candidate,allocation=1));bid=condition_identity(dict(candidate,allocation=0))
                    if aid in controls and bid in controls:
                        allocations[f'P{policy}']=dict(A1=aid,A0=bid,
                            A1引くA0=difference(entries[aid]['result']['periods'][period][symbol],entries[bid]['result']['periods'][period][symbol]),
                            同じ入口の比較=paired_entries(items[aid],items[bid]))
                    for allocation in (0,1):
                        cid=condition_identity(dict(candidate,allocation=allocation))
                        base_id=condition_identity(dict(seed,policy=1,trail_bp=2*seed['stop_bp'],allocation=allocation))
                        if cid in controls and base_id in controls:
                            management[f'P{policy}_A{allocation}']=dict(比較先=cid,P1対照=base_id,
                                差=difference(entries[cid]['result']['periods'][period][symbol],entries[base_id]['result']['periods'][period][symbol]))
                products[symbol]=dict(条件=controls,配分対照=allocations,管理対照=management)
            group[period]=products
        representatives[ident]=dict(固定代表=representative,設定=seed,期間=group)
    proof=dict(前半代表選定を変更=False,新条件追加=False,新損益再生=False,API取得=0,実注文=0,
        追加1場読取=args.include_extra,目標='建値別金額利益/(利益+損失)>=80%。組の勝率とは別。',
        比較の限界=[
            'P1からP5は同入口・同損切り幅上限・同保有時間・同再新規待機時間。実返済時点が変わり次の入口機会も変わる。',
            'P2は早期建値保護だけでなく追従幅もP1の半分。保護だけの単独効果には分解できない。',
            'P4は直前高安の幅検査による入口棄却を含み、実際の初期損切り幅も固定Rより小さいことがある。純粋な出口変更ではない。',
            'A1は有利追加・全玉リスク検査・保護線の数量依存で実経路が変わる。負け金額縮小だけで予測確度改善と断定しない。',
            '初回玉と追加玉の実現損益を別集計し、組黒字の内側にある追加建値の負けも金額損失へ残す。',
            '利益追従という返済理由は判断線の位置に由来する。予約線での約定保証ではなく、次有効行の気配と料金で赤字になる場合がある。'],
        主要結論=findings(representatives),代表=representatives,SHA256={str(p.relative_to(STUDY)):digest(p) for p in sorted(set(paths))},
        分析器SHA256=digest(Path(__file__)))
    target=HERE/'改善機構の対照分析.json'
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')
    print('固定代表の管理・配分対照を保存しました',flush=True)


if __name__=='__main__':
    main()
