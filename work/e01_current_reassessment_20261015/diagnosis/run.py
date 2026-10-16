"""保存結果だけから、全量Native親の方向損益・気配横断・実料を分解する。"""

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_FLOOR
import hashlib
import json
import math
from pathlib import Path
import traceback

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = HERE.parents[2]
INPUT = WORK / 'root_review/公開用の同bytes結果.json'
EXPECTED_SHA = 'ad0df26bb40ae4bc1b37700decec1d1dbabc60efc4419871665b0d23208cb31b'
PLAN = HERE / '中値変化と気配横断及び実料の一読診断計画.json'
PROJECTION = HERE / '全実親の中値気配料と九条件の一読射影.json'
OUTPUT = HERE / '九条件の方向損益と売買コスト及び反応WIDE六例.json'
REPORT = HERE / '二市場の赤字を方向変化と気配横断へ分けた原因.md'
ART = HERE / '全量買売の金額恒等式と保存統合の純人工.json'
VALUE = {'TOPIX': 1000, 'NK225': 10}
CAP = {'TOPIX': 10, 'NK225': 20}
FEE = {'TOPIX': '41.8', 'NK225': '11'}
MAIN = 'E01_CURRENT_VOL_PRICE_RESPONSE_WIDE_TRAIL'


def sha(path: Path) -> str:
    """
    機能: 私有source又は許可済み小資料の指紋を求める。
    引数: path(Path) は対象ファイル。
    返り値: str はSHA256。金融結果の事前hash読取には使わない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sources() -> dict:
    """
    機能: 元の経済17源と診断一源を別々に指紋へ束縛する。
    引数: なし。
    返り値: dict は経済源と診断源。旧JITのimportや書込みは行わない。
    """
    paths = sorted((WORK/'engine').glob('*.py'))
    paths += [WORK/'root_review'/n for n in ('plan.py','finance.py','financial_metrics.py')]
    assert len(paths) == 17
    return {'経済17源': {p.relative_to(ROOT).as_posix(): sha(p) for p in paths},
            '診断源': {Path(__file__).relative_to(ROOT).as_posix(): sha(Path(__file__))}}


def write(path: Path, value: object) -> None:
    """
    機能: 日本語・有限JSONを既存証跡の上書きなしで保存する。
    引数: path(Path)、value(object) は所有域の新保存先と内容。
    返り値: None。非有限数を勝手に零や有限値へ補完しない。
    """
    assert path.parent == HERE and not path.exists()
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def close(a: float, b: float) -> None:
    """
    機能: 円損益や半spread恒等式の許容誤差を検算する。
    引数: a/b(float) は有限の二金額。
    返り値: None。不一致なら診断を停止する。
    """
    assert math.isfinite(a) and math.isfinite(b)
    assert math.isclose(a,b,rel_tol=1e-11,abs_tol=1e-5), (a,b)


def jst(value: float | None) -> str | None:
    """
    機能: 保存価格代理時計だけを日本時刻文字列へ変換する。
    引数: value(float|None) はUTC epoch秒又は未保存。
    返り値: str|None はJST。実受信又は注文応答時計とは呼ばない。
    """
    if value is None:
        return None
    return datetime.fromtimestamp(value, timezone(timedelta(hours=9))).isoformat(timespec='seconds')


def fee(q: int, symbol: str) -> int:
    """
    機能: 各実注文の片道floor料金を独立Decimal算術で求める。
    引数: q(int)、symbol(str) は実約定量と商品。
    返り値: int は円料金。比例近似や二重控除はしない。
    """
    return int((Decimal(q)*Decimal(FEE[symbol])).to_integral_value(rounding=ROUND_FLOOR))


def decompose(parent: dict, symbol: str) -> dict:
    """
    機能: 全量一新規一返済親を中値変化・半spread・実料へ再構成する。
    引数: parent(dict)、symbol(str) は保存一次親診断と商品。
    返り値: dict は円分解。中値は分析用の恒等式で仮想約定モデルではない。
    """
    side = parent['side']
    entry = parent['entry']
    exits = parent['exits']
    assert side in (-1,1) and len(exits) == 1
    exit = exits[0]
    q = entry['quantity']
    assert isinstance(q,int) and q > 0 and q == exit['quantity'] == parent['entry_quantity'] == CAP[symbol]
    e,x = entry['約定'],exit['約定']
    for p in (e,x):
        assert p['normal'] and all(isinstance(p[k],(int,float)) and math.isfinite(p[k]) for k in ('bid','ask','price_time_s'))
        assert 0 < p['bid'] < p['ask']
    assert e['normal_row'] == entry['row'] < x['normal_row'] == exit['row']
    close(entry['price'],e['ask'] if side == 1 else e['bid'])
    close(exit['price'],x['bid'] if side == 1 else x['ask'])
    assert entry['fee_yen'] == exit['fee_yen'] == fee(q,symbol)
    total_fee = entry['fee_yen']+exit['fee_yen']
    assert total_fee == parent['fees_yen']
    mid_e,mid_x = (e['bid']+e['ask'])/2,(x['bid']+x['ask'])/2
    spread_e,spread_x = e['ask']-e['bid'],x['ask']-x['bid']
    mid_gross = side*(mid_x-mid_e)*q*VALUE[symbol]
    crossing = .5*(spread_e+spread_x)*q*VALUE[symbol]
    actual_gross = side*(exit['price']-entry['price'])*q*VALUE[symbol]
    net = actual_gross-total_fee
    close(actual_gross,mid_gross-crossing)
    close(net,parent['net_yen'])
    return dict(mid_direction_yen=mid_gross,crossing_disadvantage_yen=crossing,
                actual_gross_yen=actual_gross,actual_fee_yen=total_fee,actual_net_yen=net,
                entry_mid=mid_e,exit_mid=mid_x,entry_spread=spread_e,exit_spread=spread_x,
                direction_class='中値逆行' if mid_gross < 0 else '中値不変' if mid_gross == 0 else '中値順行',
                net_class='負け' if net < 0 else '零' if net == 0 else '勝ち',
                friction_outweighed_nonnegative_mid=bool(net < 0 and mid_gross >= 0))


def project(data: dict, bound: dict) -> dict:
    """
    機能: 一回読んだ正式結果から必要な親・場会計だけを目的射影へ残す。
    引数: data/bound(dict) は新結果と計画の経済源指紋。
    返り値: dict は全親の恒等式・実観測診断。元台帳本文は開かない。
    """
    assert data['全合格'] and data['source開始終端一致']
    assert data['source_SHA256'] == bound['経済17源']
    assert data['新金融口座'] == 594 and len(data['configs']) == 9 and len(data['sessions']) == 33
    assert len(data['results']) == 9 and len(set(data['sessions'])) == 33
    output = {}
    for config in data['configs']:
        cid=config['id'];case=data['results'][cid]
        assert case['config'] == config and len(case['rows']) == 66
        assert {(r['session'],r['symbol']) for r in case['rows']} == {(s,k) for s in data['sessions'] for k in CAP}
        account_parents={(p['session'],p['symbol'],p['親']):p for p in case['parents']}
        assert len(account_parents)==len(case['parents'])==len(case['parent_diagnostics'])
        parents=[]
        seen=set()
        for p in case['parent_diagnostics']:
            key=p['session'],p['symbol'],p['parent'];a=account_parents[key]
            assert key not in seen;seen.add(key)
            assert a['方向']==p['side'] and a['枚数']==p['entry_quantity'] and a['費用']==p['fees_yen']
            close(a['収支'],p['net_yen'])
            parts=decompose(p,p['symbol']);close(a['粗損益'],parts['actual_gross_yen'])
            parents.append(dict(**p,amounts=parts))
        assert seen == set(account_parents)
        for r in case['rows']:
            pp=[p for p in parents if p['session']==r['session'] and p['symbol']==r['symbol']]
            assert len(pp)==r['親数']
            close(sum(p['net_yen'] for p in pp),r['収支'])
            close(sum(p['fees_yen'] for p in pp),r['費用'])
            close(sum(max(0,p['net_yen']) for p in pp),r['利益'])
            close(-sum(min(0,p['net_yen']) for p in pp),r['損失'])
        output[cid]=dict(config=config,rows=case['rows'],parents=parents)
    return dict(全合格=True,出典SHA256=EXPECTED_SHA,source_SHA256=bound,sessions=data['sessions'],cases=output,
                目的='一実CID/UID全量親の中値方向・気配横断・実料の恒等式と事後原因',
                制約=['中値で約定できる仮説又は別出口の救済利益ではない。',
                      'peerの両BBOと一部支持更新行の時計は未保存。零又は未来点で補完しない。',
                      '事後極値はactual保有期間のみ。入口又は新出口の採否へ戻さない。'])


def totals(parents: list[dict]) -> dict:
    """
    機能: 同じ完結親分母の金額要因と負け分類を相殺前後で合算する。
    引数: parents(list[dict]) は同商品・同条件・同群の射影親。
    返り値: dict は全親又は負け親別の恒等式と分類母数。
    """
    money={name:sum(p['amounts'][name] for p in parents) for name in (
        'mid_direction_yen','crossing_disadvantage_yen','actual_gross_yen','actual_fee_yen','actual_net_yen')}
    close(money['actual_net_yen'],money['mid_direction_yen']-money['crossing_disadvantage_yen']-money['actual_fee_yen'])
    return dict(parent_count=len(parents),**money,
                wins=sum(p['net_yen']>0 for p in parents),losses=sum(p['net_yen']<0 for p in parents),
                mid_reverse_count=sum(p['amounts']['mid_direction_yen']<0 for p in parents),
                nonnegative_mid_but_net_loss=sum(p['amounts']['friction_outweighed_nonnegative_mid'] for p in parents),
                negative_mid_amount=sum(-min(0,p['amounts']['mid_direction_yen']) for p in parents),
                positive_mid_amount=sum(max(0,p['amounts']['mid_direction_yen']) for p in parents),
                never_positive_liquidation_count=sum(p['best_parent_liquidation_yen']<=0 for p in parents),
                once_positive_liquidation_count=sum(p['best_parent_liquidation_yen']>0 for p in parents),
                exits=dict(Counter(str(p['exits'][0]['reason']) for p in parents)))


def example(parent: dict, session_row: dict) -> dict:
    """
    機能: 上位赤字場の最大負け実親を保存済み観測だけで説明する。
    引数: parent/session_row(dict) は選定親と当該場会計。
    返り値: dict は入口・極値・支持・退出の事後診断。peer BBOを推定しない。
    """
    p=parent;known_points={}
    for point in (p['publication'],p['entry']['判断'],p['entry']['約定'],p['exits'][0]['判断'],p['exits'][0]['約定'],
                  p['first_parent_liquidation_argmax'],p['first_parent_liquidation_argmin']):
        point=dict(point,JST=jst(point['price_time_s']));known_points[point['normal_row']]=point
    support=[]
    for e in p['support_events']:
        row,cid,side,old,new,proof,bid,ask,lower,previous=e
        assert int(cid)==p['parent'] and int(side)==p['side'] and proof>p['entry']['row']
        assert new>=old if side==1 else new<=old
        support.append(dict(row=int(row),old_line=old,new_line=new,proof_row=int(proof),proof_bid=bid,proof_ask=ask,
                            opposite_vote_lower_bound=lower,proof_previous_row=int(previous),
                            update_observation=known_points.get(int(row)),proof_observation=known_points.get(int(proof)),
                            missing_clock_if_no_observation=True))
    out={k:p[k] for k in ('session','symbol','parent','side','entry_quantity','net_yen','fees_yen','structure_level','initial_support_line',
         'parent_stop_yen','target_yen','published_price_cap','published_adverse_ticks','holding_price_proxy_seconds','best_parent_liquidation_yen',
         'worst_parent_liquidation_yen','parent_mae_yen','parent_mfe_yen','amounts')}
    out.update(session_net_yen=session_row['収支'],publication=known_points[p['publication']['normal_row']],
               entry=p['entry'],exit=p['exits'][0],best=known_points[p['first_parent_liquidation_argmax']['normal_row']],
               worst=known_points[p['first_parent_liquidation_argmin']['normal_row']],support=support,
               returned_from_best_yen=max(0,p['best_parent_liquidation_yen']-p['net_yen']),
               peer_BBO='未保存。peer row/seq/age/票のみ。',
               原因ラベル='保有後の費用後黒字を返した' if p['best_parent_liquidation_yen']>0 else '保有中に費用後黒字なし')
    return out


def analyze(projection: dict) -> dict:
    """
    機能: 射影だけから九条件・商品別の全親と負け親を分けて原因集計する。
    引数: projection(dict) は保存済み一読射影。
    返り値: dict は集計と③WIDE各商品赤字上位三場の最大負け親。
    """
    aggregated={};examples={}
    for cid,case in projection['cases'].items():
        aggregated[cid]={}
        for symbol in CAP:
            pp=[p for p in case['parents'] if p['symbol']==symbol]
            rr=[r for r in case['rows'] if r['symbol']==symbol]
            assert len(rr)==33
            a=totals(pp);close(a['actual_net_yen'],sum(r['収支'] for r in rr))
            aggregated[cid][symbol]=dict(all_parents=a,negative_parents=totals([p for p in pp if p['net_yen']<0]),
                mean_all33_session_net=a['actual_net_yen']/33,
                session_positive=sum(r['収支']>0 for r in rr),session_negative=sum(r['収支']<0 for r in rr),
                no_trade=sum(r['親数']==0 for r in rr),
                directions={str(side):totals([p for p in pp if p['side']==side]) for side in (1,-1)},
                day_night={tag:totals([p for p in pp if p['session'].endswith('_'+tag)]) for tag in ('Day','Night')})
    case=projection['cases'][MAIN]
    for symbol in CAP:
        negative=sorted((r for r in case['rows'] if r['symbol']==symbol and r['収支']<0),key=lambda r:(r['収支'],r['session']))[:3]
        examples[symbol]=[]
        for row in negative:
            losers=[p for p in case['parents'] if p['session']==row['session'] and p['symbol']==symbol and p['net_yen']<0]
            p=min(losers,key=lambda p:(p['net_yen'],p['parent']))
            examples[symbol].append(example(p,row))
    return dict(全合格=True,出典SHA256=projection['出典SHA256'],projection_SHA256=sha(PROJECTION) if PROJECTION.exists() else None,
                aggregated=aggregated,**{'主③WIDE赤字上位3場の最大負親':examples},
                金額恒等式='実net＝side×(返済mid−入口mid)×q×倍率−(入口spread＋返済spread)/2×q×倍率−実注文料。',
                制約=projection['制約'])


def format_point(point: dict) -> str:
    """
    機能: 保存点を代理JST・原seq・BBOとして短く表示する。
    引数: point(dict) は同一行観測。
    返り値: str は原因説明用。LastとBBO又はpeer情報を混ぜない。
    """
    return f"{jst(point['price_time_s'])} / seq {point['raw_seq']} / BBO {point['bid']:g}–{point['ask']:g} / 局所清算 {point['parent_liquidation_yen']}円"


def markdown(out: dict) -> str:
    """
    機能: 九条件の分母と六例を根へ渡す短い日本語MDへ整形する。
    引数: out(dict) は検算済み原因集計。
    返り値: str は参照リンク付き説明。改善効果は未測として区別する。
    """
    lines=['全9条件の赤字を、方向の逆行と気配横断・実料へ分けた。中値は金額恒等式の分析項であり、中値約定が可能だったことを示さない。',
           '',f"出典は[正式結果の同bytesコピー](../root_review/公開用の同bytes結果.json)（SHA256 `{EXPECTED_SHA}`）。[全親射影](全実親の中値気配料と九条件の一読射影.json)と[検算集計](九条件の方向損益と売買コスト及び反応WIDE六例.json)だけから以下を作成。原結果1読、台帳・cache・原板・API・追加金融は0。",'',
           '|入口・出口|商品|全親 / 負親|全親mid方向円|気配横断円|実料円|実net円|負親のmid逆行 / 非逆行でも負け|','|---|---|---:|---:|---:|---:|---:|---:|']
    for cid,syms in out['aggregated'].items():
        for symbol,z in syms.items():
            a,n=z['all_parents'],z['negative_parents']
            lines.append(f"|{cid.removeprefix('E01_')}|{symbol}|{a['parent_count']} / {n['parent_count']}|{a['mid_direction_yen']:,.0f}|{a['crossing_disadvantage_yen']:,.0f}|{a['actual_fee_yen']:,.0f}|{a['actual_net_yen']:,.0f}|{n['mid_reverse_count']} / {n['nonnegative_mid_but_net_loss']}|")
    lines += ['', '③WIDEの各商品で赤字上位3場を取り、場内で最大損失の完結親を選んだ。同点は場名・親番号順。時刻はすべてCurrentPriceTimeの代理時計。peerの両BBOと未保存の支持更新時刻は補完していない。','']
    for symbol,examples in out['主③WIDE赤字上位3場の最大負親'].items():
        for p in examples:
            a=p['amounts'];pub=p['publication'];side='買い' if p['side']==1 else '売り'
            nvol=None if pub['volume_up'] is None else pub['volume_up']+pub['volume_down']
            lines += [f"**{symbol} {p['session']} 親{p['parent']} {side}{p['entry_quantity']}枚**：場net {p['session_net_yen']:,.0f}円、親net {p['net_yen']:,.0f}円。",'',
                f"公開 {format_point(pub)}。出来高代理{nvol}票、signed釣合い{pub['volume_signed_balance']}。自己価格{pub['own_price_count']}票/{pub['own_price_balance']}、相手価格{pub['peer_price_count']}票/{pub['peer_price_balance']}（peer seq {pub['peer_raw_seq']}、age {pub['peer_price_age_seconds']}秒）。固定FAK許容{p['published_adverse_ticks']}T。",'',
                f"入口 {format_point(p['entry']['約定'])}、実価格{p['entry']['price']:g}。最良 {format_point(p['best'])}。最悪 {format_point(p['worst'])}。",'',
                f"返済判断 {format_point(p['exit']['判断'])}、理由「{p['exit']['reason_label']}」。実返済 {format_point(p['exit']['約定'])}、実価格{p['exit']['price']:g}。保持{p['holding_price_proxy_seconds']:g}代理秒。",'',
                f"中値方向{a['mid_direction_yen']:,.0f} − 横断{a['crossing_disadvantage_yen']:,.0f} − 料{a['actual_fee_yen']:,.0f} ＝ {p['net_yen']:,.0f}円。初期支持線{p['initial_support_line']:g}、親cash stop {p['parent_stop_yen']:,.2f}円、支持更新{len(p['support'])}件。{p['原因ラベル']}。最良清算から最終まで{p['returned_from_best_yen']:,.0f}円を返した（別出口で得られた利益ではない）。",'']
            if p['support']:
                lines += ['支持更新は '+ '、'.join(f"row{v['row']}（proof row{v['proof_row']}） {v['old_line']:g}→{v['new_line']:g}" for v in p['support'])+'。更新行に一致する保存点がなければ、その時刻・原seqは未測。','']
    lines += ['次の修正仮説は、上の負親分類と黒字反証を確認してから別条件へ固定する。中値逆行の負けに気配料だけの修正で十分とは言えず、非逆行の小幅損には追加の横断が影響する。支持更新・追尾の調整は事後MFEをそのまま救済PLへ置き換えず、全後続の実運転で別検証が必要。']
    return '\n'.join(lines)+'\n'


def artificial() -> dict:
    """
    機能: 買売・異幅・方向分類・floor料とJSON統合を金融前に検査する。
    引数: なし。
    返り値: dict は独立整数/Decimal算術に照合した純検査件数。
    """
    checks=0
    for symbol in CAP:
        q=CAP[symbol];m=VALUE[symbol]
        for side in (-1,1):
            for e_width in (1,2,9):
                for x_width in (1,2,29):
                    for movement in (-10,0,1,20):
                        eb,ea=100,100+e_width;xb=100+movement;xa=xb+x_width
                        entry_price=ea if side==1 else eb;exit_price=xb if side==1 else xa
                        ep=dict(normal=True,bid=eb,ask=ea,price_time_s=100,normal_row=1)
                        xp=dict(normal=True,bid=xb,ask=xa,price_time_s=101,normal_row=2)
                        entry=dict(quantity=q,price=entry_price,fee_yen=fee(q,symbol),row=1,約定=ep)
                        exit=dict(quantity=q,price=exit_price,fee_yen=fee(q,symbol),row=2,約定=xp)
                        net=side*(exit_price-entry_price)*q*m-2*fee(q,symbol)
                        p=dict(side=side,entry=entry,exits=[exit],entry_quantity=q,fees_yen=2*fee(q,symbol),net_yen=net)
                        out=decompose(p,symbol)
                        oracle=Decimal(side)*((Decimal(xb)+Decimal(xa)-Decimal(eb)-Decimal(ea))/2)*q*m
                        close(out['mid_direction_yen'],float(oracle));checks+=1
                        assert out['friction_outweighed_nonnegative_mid']==(net<0 and oracle>=0);checks+=1
                        json.loads(json.dumps(out,allow_nan=False));checks+=1
                        bad=json.loads(json.dumps(p));bad['exits'][0]['quantity']-=1
                        try:
                            decompose(bad,symbol)
                        except AssertionError:
                            checks+=1
                        else:
                            raise AssertionError('数量不一致を受理')
    empty=totals([]);assert empty['parent_count']==0 and empty['actual_net_yen']==0
    json.dumps(empty,allow_nan=False);checks+=2
    assert fee(10,'TOPIX')==418 and fee(20,'NK225')==220;checks+=2
    return dict(全合格=True,検査数=checks,実金融読取=0,原入力=0,台帳=0,API=0)


def prepare() -> None:
    """
    機能: 合成検査成功後、一読目的とsource・入力名・不明範囲を先固定する。
    引数: なし。
    返り値: None。実結果本文は読まずstatだけを記録する。
    """
    assert not PLAN.exists() and not ART.exists() and not PROJECTION.exists()
    bound=sources();proof=artificial();proof['source_SHA256']=bound
    write(ART,proof)
    write(PLAN,dict(全合格=True,段階='結果読取前の診断計画と純人工固定',source_SHA256=bound,
        input=dict(path=INPUT.relative_to(ROOT).as_posix(),SHA256=EXPECTED_SHA,stat_bytes=INPUT.stat().st_size,目的読取回数=1),
        読取計数予定=dict(同bytes結果本文=1,射影再利用=1,元金融結果=0,元実台帳=0,cache=0,原板=0,NPZ=0,API=0,新金融=0),
        対象='全9条件・両商品・全完結実親と負親を別集計。全量一新規一返済をassert。',
        実例選定=dict(case=MAIN,条件='商品別場netが負の上位3場、各場の最小親net',同点='場名・親番号昇順'),
        式='net=side*(exitMid-entryMid)*q*mult-.5*(entrySpread+exitSpread)*q*mult-実個別floor料金',
        追加費用二重控除=False,中値約定又は救済PL主張=False,時刻='CurrentPriceTime価格代理時計',
        不足=['peer両BBO未保存','支持更新は配列rowとproofBBOのみ。保存点と行が一致しない場合は時計/seq未保存。',
              'actual保有期間外の価格は未測。future peakは診断のみ。'],
        原金融source変更=False,自動再開始=False,人工=dict(path=ART.name,SHA256=sha(ART))))
    print(json.dumps(dict(準備完了=True,人工検査数=proof['検査数'],planSHA256=sha(PLAN),artSHA256=sha(ART)),ensure_ascii=False))


def run(expected: str) -> None:
    """
    機能: 根授権SHAを検算した同bytes結果を一度だけ射影し、その射影から原因計算する。
    引数: expected(str) は根が通知した確定結果SHA。
    返り値: None。Falseを保全し再読・再金融・自動再開始をしない。
    """
    assert expected==EXPECTED_SHA
    plan=json.loads(PLAN.read_text(encoding='utf-8'))
    bound=sources();assert bound==plan['source_SHA256'] and sha(ART)==plan['人工']['SHA256']
    assert not any(p.exists() for p in (PROJECTION,OUTPUT,REPORT,HERE/'開始.json',HERE/'False.json'))
    counts=dict(同bytes結果本文=0,射影再利用=0,元金融結果=0,元実台帳=0,cache=0,原板=0,NPZ=0,API=0,新金融=0)
    write(HERE/'開始.json',dict(目的='方向変化と気配横断及び実料の別目的一読',計画SHA256=sha(PLAN),source_SHA256=bound))
    try:
        counts['同bytes結果本文']+=1
        raw=INPUT.read_bytes()
        assert len(raw)==plan['input']['stat_bytes'] and hashlib.sha256(raw).hexdigest()==EXPECTED_SHA
        data=json.loads(raw);del raw
        projection=project(data,bound);del data
        write(PROJECTION,projection);del projection
        counts['射影再利用']+=1
        projection=json.loads(PROJECTION.read_text(encoding='utf-8'))
        output=analyze(projection);output['読取計数']=counts
        assert bound==sources()
        output['source開始終端一致']=True;output['計画SHA256']=sha(PLAN)
        write(OUTPUT,output)
        assert not REPORT.exists();REPORT.write_text(markdown(output),encoding='utf-8')
        write(HERE/'完了.json',dict(全合格=True,読取計数=counts,source開始終端一致=True,
              射影SHA256=sha(PROJECTION),結果SHA256=sha(OUTPUT),MD_SHA256=sha(REPORT)))
        print(json.dumps(dict(全合格=True,読取計数=counts,結果SHA256=sha(OUTPUT),MD_SHA256=sha(REPORT)),ensure_ascii=False))
    except BaseException:
        write(HERE/'False.json',dict(全合格=False,読取計数=counts,原因=traceback.format_exc(),自動再開始=False))
        raise


def main() -> None:
    """
    機能: 計画先固定と根授権後一読の二段階だけを受け付ける。
    引数: CLI --prepare(bool) 又は --root-finance-complete(bool)、--expected-result-sha(str)。
    返り値: None。既存成功又はFalseを上書きしない。
    """
    parser=argparse.ArgumentParser()
    parser.add_argument('--prepare',action='store_true')
    parser.add_argument('--root-finance-complete',action='store_true')
    parser.add_argument('--expected-result-sha')
    args=parser.parse_args()
    assert args.prepare != args.root_finance_complete
    if args.prepare:
        prepare()
    else:
        run(args.expected_result_sha)


if __name__=='__main__':
    main()
