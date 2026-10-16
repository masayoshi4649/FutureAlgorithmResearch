"""同一E01ルールの両商品差を、保存小会計と既369集計及び登録仕様だけで敵対監査する。"""

from collections import Counter
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from pathlib import Path
import hashlib
import json
import math
import sys


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
REVIEW=ROOT/'work/wave_v106/price_review'
sys.dont_write_bytecode=True
sys.path.insert(0,str(REVIEW))
from risk_sizing_finance_small import goal, near

CID='E01_ANCHOR_W60_CONFIRM_D0_P1_L2_A1'
TRIAL='106_E01予定リスク数量の初回受理目標アンカーP1P2四対照'
PATHS=(ROOT/'work/wave_v106/e01_size_goal_anchor/finance/結果.json',
       ROOT/'work/wave_v106/new_goal/初回受理損失四条件追加後の65基準と全候補判定.json',
       ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/data/trials.json')
READS={}


def read_once(path: Path) -> dict:
    """
    機能: 事前に指定した三つの保存JSONだけを新目的で各一読する。
    引数: path(Path)は旧goal小金融結果・369小集計・登録のいずれか。
    返り値: dictは保存値。同読取bytesのSHAを記録し原板等へ進まない。
    """
    assert path in PATHS and path not in READS
    saved=path.read_bytes();READS[path.relative_to(ROOT).as_posix()]=hashlib.sha256(saved).hexdigest()
    return json.loads(saved.decode('utf-8-sig'))


def fee(quantity: int, symbol: str) -> int:
    """
    機能: 実注文一つの片道税込料を独立に整数円切捨てする。
    引数: quantity(int)、symbol(str)は枚数と商品。
    返り値: intは注文料。実注文・金融は作らない。
    """
    unit=Decimal('41.8') if symbol=='TOPIX' else Decimal('11')
    return int((unit*quantity).to_integral_value(rounding=ROUND_FLOOR))


def economics(symbol: str, q: int) -> dict:
    """
    機能: 同一式の利益・固定損失・料・一呼値spreadを価格単位へ換算する。
    引数: symbol(str)、q(int)は商品と最初に受理した枚数。
    返り値: dictは式の算術例。spread一呼値は仮定で全実取引の実測ではない。
    """
    full=5 if symbol=='TOPIX' else 10;tick=Decimal('.5') if symbol=='TOPIX' else Decimal('10')
    value=Decimal(1000 if symbol=='TOPIX' else 10);tick_value=tick*value
    profit=q*tick_value;loss=2*full*tick_value;cost=2*fee(q,symbol)
    initial=q*tick_value+cost
    adverse=(loss-initial)/(q*value);favorable=(profit+initial)/(q*value)
    return dict(初回受理q=q,通常全量=full,q全量比=q/full,観測呼値=float(tick),一枚一呼値円=float(tick_value),
        利益目標円=float(profit),固定損失停止円=float(loss),名目損失利益比=float(loss/profit),
        利益幅呼値=1.,名目損失幅呼値=float(loss/(q*tick_value)),往復注文料=cost,
        一呼値spread時の初期清算円=-float(initial),
        初期返済気配から損失線へ逆行幅=float(adverse),初期返済気配から利益線へ順行幅=float(favorable),
        逆行呼値切上げ=int((adverse/tick).to_integral_value(rounding=ROUND_CEILING)),
        順行呼値切上げ=int((favorable/tick).to_integral_value(rounding=ROUND_CEILING)))


# ----------------------------------------
def main() -> None:
    """
    機能: 全33場・先頭受理q・同一コードの実効差・既試行再利用・事後選択リスクを整理する。
    引数: なし。新金融計画の授権まで正式金融を行わない。
    返り値: Noneは自所有JSONと簡潔な日本語MD。共有資料と凍結源を変更しない。
    """
    HERE.mkdir(parents=True,exist_ok=True)
    scope=HERE/'保存小会計三資料の読取目的固定.json'
    target=HERE/'同一E01の両商品差と再利用及び事後選択の敵対監査.json'
    assert not scope.exists() and not target.exists()
    scope.write_text(json.dumps(dict(対象条件=CID,目的='同一式の呼値・手数料・初回q/fullを原因仮説として整理。新規勝率探索ではない。',
        新目的一読=[p.relative_to(ROOT).as_posix() for p in PATHS],ATR実測='小金融境界に無ければ未測定のまま。原板・台帳へ進まない。',
        原板=0,NPZ=0,packet=0,ledger=0,金融=0,API=0),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    data,latest,registry=(read_once(p) for p in PATHS)
    assert READS[PATHS[0].relative_to(ROOT).as_posix()]=='8959ab1bf2f532e5358c458fc81590b8f88964233b231cb78d48293afd07d0f7'
    assert data['全合格'] and data['source開始終端一致'] and latest['全合格']
    assert latest['summary']['eligible_ids']==369 and latest['summary']['both_full_pass']==latest['summary']['both_robust_pass']==[]
    config=next(c for c in data['configs'] if c['id']==CID)
    saved=data['results'][CID];assert len(saved['rows'])==66 and len(data['sessions'])==33
    trial=next(t for t in registry['trials'] if t['id']==TRIAL)
    assert trial['status']=='検証済み' and config in trial['spec']['entry']['conditions']
    assert trial['completed_result']['path']==PATHS[0].relative_to(ROOT).as_posix()
    assert trial['completed_result']['sha256']==READS[PATHS[0].relative_to(ROOT).as_posix()]
    assert config['profit_ticks']==1 and config['loss_ticks']==2 and config['risk_atr_multiple']==1
    assert config['quantity']=={'TOPIX':5,'NK225':10} and config['cap']=={'TOPIX':10,'NK225':20}
    stats={};qdist={};firsts={};all_rows={};rows_checked=0
    for symbol in ('TOPIX','NK225'):
        rows=[r for r in saved['rows'] if r['symbol']==symbol];assert len(rows)==33
        assert [r['session'] for r in rows]==data['sessions']
        for row in rows:
            assert row['全会計合格'];near(row['利益']-row['損失'],row['収支']);rows_checked+=1
        full=goal(rows);positives=sorted([r for r in rows if r['収支']>0],key=lambda r:r['収支'],reverse=True)[:3]
        removed={r['session'] for r in positives};tail=goal([r for r in rows if r['session'] not in removed])
        fees=sum(r['費用'] for r in rows)
        stats[symbol]=dict(全33=full,上位3除外=tail,除外場=sorted(removed),前16=goal(rows[:16]),後17=goal(rows[16:]),
            支払手数料=fees,手数料前価格差収支=full['収支']+fees,
            定義='手数料前価格差収支は実bid/ask模型の価格差合計。気配差を消した収支ではない。')
        for old,new in (('利益','利益'),('損失','損失'),('収支','収支'),('利益割合','金額利益割合')):near(saved['symbols'][symbol][old],full[new])
        all_rows[symbol]=rows
        boundaries=[b for b in data['初回受理と費用後目標境界'][CID] if b['symbol']==symbol]
        assert len(boundaries)==33
        entries=[b for b in boundaries if b['anchor']['成立']]
        counts=Counter(b['anchor']['数量'] for b in entries)
        qdist[symbol]=dict(受理場=len(entries),未受理場=33-len(entries),初受理q分布={str(q):n for q,n in sorted(counts.items())},
            初回q全量比分布={str(q/(5 if symbol=='TOPIX' else 10)):n for q,n in sorted(counts.items())},
            公開ATR保存=False,初期BBO差保存=False,
            限界='先頭受理の分布だけ。場途中の全qや未受理理由別母数はこの小境界に保存されていない。')
        firsts[symbol]=[dict(session=b['session'],q=b['anchor']['数量'],全量=b['anchor']['通常全量'],
            受理行=b['anchor']['受理行'],紙上親=b['anchor']['紙上親'],利益目標=b['目標円'],固定損失=b['損失予算円']) for b in entries]
        for entry in firsts[symbol]:
            expected=economics(symbol,entry['q']);assert entry['利益目標']==expected['利益目標円'] and entry['固定損失']==expected['固定損失停止円']
    # 同一両商品ルールの追加例は既369へ保存済み。計算し直して新証拠とは呼ばない。
    reuse=[]
    for cid,candidate in latest['新候補'].items():
        assert cid.startswith('E01_LOSS_ANCHOR_W60_')
        reuse.append(dict(id=cid,変更='初回受理q/fullへ損失停止線も比例。数量選択予算とGUは不変。',
            保存済み=True,新金融再実行予定=False,
            TOPIX収支=sum(r['net'] for r in candidate['rows'] if r['symbol']=='TOPIX'),
            NK225収支=sum(r['net'] for r in candidate['rows'] if r['symbol']=='NK225')))
    assert len(reuse)==4 and all(r['TOPIX収支']<0 and r['NK225収支']<0 for r in reuse)
    plans=dict(入口=trial['spec']['entry'],途中=trial['spec']['management'],出口=trial['spec']['exit'],
        数量=trial['spec']['allocation'],費用=trial['spec']['costs'],執行=trial['spec']['execution'])
    calculations={symbol:[economics(symbol,q) for q in range(1,(5 if symbol=='TOPIX' else 10)+1)] for symbol in ('TOPIX','NK225')}
    fee_tick={symbol=dict(未丸め往復一枚料=83.6 if symbol=='TOPIX' else 22.,一枚一呼値円=500 if symbol=='TOPIX' else 100,
        未丸め往復料対一呼値=(83.6/500 if symbol=='TOPIX' else 22/100),
        単独一枚実往復料=2*fee(1,symbol)) for symbol in ('TOPIX','NK225')}
    hypotheses=[dict(法則='利確だけq比例・損失B固定は、同じコードでもq/fullにより実効損失幅が変わる。',
        根拠='利益=1観測呼値×初受理q。損失=2呼値×通常全量。従ってL/P=2full/q。',
        確認済み=True,因果の限界='この相違だけでNK/TOP成績差の全原因とは言えない。価格経路・当時ATRの分布を別測定する必要がある。'),
        dict(法則='同じ60代理秒の2票基準は、同じ独立証拠量又は同じ方向精度を保証しない。',
        根拠='公表更新票は真の攻撃注文でも独立tickでもなく、商品別更新頻度・実値幅が未揃い。',
        確認済み='仕様上の限界。銘柄別の原因率は未測定。'),
        dict(法則='費用/呼値ではNK側が高い。費用だけでTOPの不振を説明する仮説は矛盾する。',
        根拠='未丸め往復料/1呼値はTOP16.72%、NK22%。それでもこの保存条件はNK側の金額比が高い。',
        確認済み=True,因果の限界='実注文q・気配差・部分返済料が異なるため実総費用の寄与はこれだけでは説明できない。'),
        dict(法則='一銘柄の最良候補選択は同一汎用アルゴリズムの成功ではない。',
        根拠='NK CONFIRM_P1の全33は金額65/赤字20を満たすが第三基準は不合格。上位3除外後は金額65も不足。TOP同条件は全体赤字。',
        確認済み=True,因果の限界='既知内の探索結果であり、銘柄別条件選択や新調整を未知成功とは呼べない。')]
    assert stats['NK225']['全33']['基準']['金額65'] and stats['NK225']['全33']['基準']['赤字20']
    assert not stats['NK225']['全33']['基準']['平均黒字補填'] and not stats['NK225']['上位3除外']['基準']['金額65']
    assert stats['TOPIX']['全33']['収支']<0
    output=dict(全合格=True,評価='保存値と式の監査合格。原因の確定又は新アルゴリズムの有効性合格ではない。',
        条件=CID,比較範囲='同じ一条件・商品別全33場。商品間の円額単純順位を評価基準にしない。',
        source_SHA256=READS,独立source_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        照合行数=rows_checked,商品別=stats,初回受理数量=qdist,初回受理行と固定線=firsts,
        保存全場=all_rows,制度上の単位=fee_tick,全qの算術例=calculations,登録部品=plans,原因仮説=hypotheses,
        再利用できる既試行=reuse,既369範囲=latest['summary'],
        次段の必要観測=['公開ATR/観測呼値・初期気配差/呼値・q/fullの対応を既小射影で確認する。',
            '同じ入口の方向別・共通親の費用後最大逆行/順行と先着停止を、診断前に対象を固定して比較する。',
            '銘柄別の事後閾値選択を避け、両商品共通の規格化か状態条件変更を一つずつ対照する。'],
        未確定=['価格経路の違いと入口精度の違いをこの3小資料だけでは分離できない。',
            '当時ATR・BBO差・全数量eventsは小金融境界に無い。分布を推測で埋めない。',
            '両市場が同方向かの効果、補充、板厚み、真の攻撃方向は今回未測定。'],
        事後選択='同じ既知33の369ID探索。銘柄別最良選択を一つの事前ルール又は未知成功と扱わない。',
        新金融監査状態='preparedのみ。根の新正式計画・終端0までは金融監査を開始しない。',
        原板=0,NPZ=0,packet=0,ledger=0,金融=0,API=0,凍結source及び共有docs変更=0)
    target.write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    top,nk=stats['TOPIX']['全33'],stats['NK225']['全33']
    text=f'''# 同じE01条件が日経とTOPIXで違う結果になる点の敵対監査

対象は `{CID}`。この同一ルールは両商品で有用と確定していません。

| 商品 | 全33収支 | 金額利益割合 | 黒字/赤字/無取引 | 平均黒字net | 最大赤字 | 上位3黒字除外後 |
| --- | ---: | ---: | --- | ---: | ---: | ---: |
| TOPIXミニ | {top['収支']:,.0f}円 | {top['金額利益割合']:.1%} | {top['黒字']}/{top['赤字']}/{top['無取引']} | {top['平均黒字']:,.1f}円 | {top['最大赤字']:,.0f}円 | {stats['TOPIX']['上位3除外']['収支']:,.0f}円 |
| 日経マイクロ | {nk['収支']:,.0f}円 | {nk['金額利益割合']:.1%} | {nk['黒字']}/{nk['赤字']}/{nk['無取引']} | {nk['平均黒字']:,.1f}円 | {nk['最大赤字']:,.0f}円 | {stats['NK225']['上位3除外']['収支']:,.0f}円 |

先に確かめられた構造差は、利確だけ初回qに比例し、損失停止額を通常全量のまま残すことです。利益は1観測呼値×q、損失は2観測呼値×通常全量なので、損失/利益は `2×通常全量/q`。初回1枚ならTOPIXは10倍、日経は20倍の損失線です。同じコードでも実効的な価格の許容幅は同じではありません。

初受理qの分布はTOPIX `{qdist['TOPIX']['初受理q分布']}`、日経 `{qdist['NK225']['初受理q分布']}`。公開ATRを1呼値で割った実分布はこの小金融資料に無いので、まだ原因として断定しません。

料/呼値は日経の方が高い（未丸め往復料はTOPIX16.72%、日経22%）。費用だけでTOPIXが負けるとの説明には無理があります。更新票の密度、入口後の価格経路、q/fullと許容幅の組合せを分ける必要があります。

損失線もq比例にする4対照はすでに保存済みで、両商品とも赤字でした。同じ試行を再生せず、この失敗を再利用します。日経の今回の好成績も、最大赤字を平均黒字一場で補う基準には届かず、上位3黒字除外後の金額比も65%未満です。銘柄別の都合の良い条件選択を汎用性又は未知成功とは呼べません。

次段は、当時ATR/呼値・気配差/呼値・q/fullを既小射影で確認し、元の入口の価格応答を同じ原行で比較します。価格幅の規格化と入口構造の変更を混ぜず、同じ33場での対照を一つずつ固定します。

根拠：[保存値と全場・式の監査](同一E01の両商品差と再利用及び事後選択の敵対監査.json)。原板・NPZ・packet・台帳・金融・APIは0。新正式計画待ちで、修正の効果は未測定です。
'''
    (HERE/'同じE01条件が両商品で違う理由の監査メモ.md').write_text(text,encoding='utf-8')
    print(json.dumps(dict(全合格=True,条件=CID,両商品=dict(TOPIX=top,NK225=nk),初回q=qdist,
        SHA256=hashlib.sha256(target.read_bytes()).hexdigest()),ensure_ascii=False))


if __name__=='__main__':main()
