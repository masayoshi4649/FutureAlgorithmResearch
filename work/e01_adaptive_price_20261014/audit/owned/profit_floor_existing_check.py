"""旧00106の容量利用と利益の経済的な大きさを、公開小会計だけから再評価する。"""

from collections import Counter
from decimal import Decimal,ROUND_FLOOR
from pathlib import Path
import hashlib
import json
import math
import traceback

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
PUBLIC=ROOT/'アルゴリズム調査/00106_支持の強さで注文価格を切り替えるE01/支持強度別価格制限と銘柄別固定会計.json'
PREVIOUS=HERE/'八適応条件528会計と旧24引用及び全実親両寄与の独立監査.json'
READS={}


def read_once(path: Path) -> dict:
    """
    機能: 公開小会計と既独立証跡を、この新目的で各一読する。
    引数: path(Path) は PUBLIC 又は PREVIOUS の小 JSON。
    返り値: dict は保存内容。旧金融結果・入力・台帳・API を開かない。
    """
    assert path in (PUBLIC,PREVIOUS) and path not in READS
    raw=path.read_bytes();READS[path]=hashlib.sha256(raw).hexdigest()
    return json.loads(raw.decode('utf-8-sig'))


def fee(quantity: int, symbol: str) -> int:
    """
    機能: 片道注文料を料金有理数から整数円切捨てで算術する。
    引数: quantity(int) は実枚数、symbol(str) は TOPIX 又は NK225。
    返り値: int は実片道料。将来約定の料金以外の滑りを補完しない。
    """
    return quantity*209//5 if symbol=='TOPIX' else quantity*11


def main() -> None:
    """
    機能: 最大容量との換算、実枚数分布、全場/黒字/全取引平均と旧価格固定の事後数量算術を求める。
    引数: なし。TOPIX平均全完結親net10万円を最新目標として固定する。
    返り値: None。再評価の自所有証跡を保存し、新バックテストとは呼ばない。
    """
    target=HERE/'旧00106の実容量使用と一取引10万円床の独立算術.json'
    failed=HERE/'旧00106経済床の独立算術False.json'
    assert not target.exists() and not failed.exists()
    try:
        public,previous=read_once(PUBLIC),read_once(PREVIOUS)
        assert public['全合格'] and previous['全合格'] and len(public['sessions'])==33
        assert previous['正式結果SHA256']=='13f534a10b081db94944d723171214a2132829b66b70f177e0d3055b27116944'
        assert previous['検査']['実親小射影']==508 and previous['検査']['実親小注文']==1016
        # 先行独立監査では各親に新規1・返済1以上を要求して合計1016だったため、今回対象も一括全返済1である。
        selected=public['pair']['selected'];symbols={};condition_means={}
        for cid,case in public['cases'].items():
            full=case['metrics']['TOPIX']['full']
            count=full['campaigns'];value=full['net']/count if count else None
            condition_means[cid]=dict(親数=count,費用後収支=full['net'],全親平均net円=value,
                平均10万円達成=value is not None and value>=100000)
        for symbol,cid in selected.items():
            capacity,mult,large=(10,1000,10000) if symbol=='TOPIX' else (20,10,1000)
            case=public['cases'][cid]
            rows=[r for r in case['rows'] if r['symbol']==symbol]
            diagnosis={(d['session'],d['symbol']):d for d in case['fak_diagnosis']}
            qcounts=Counter();observations=[];sum_q=0;net=0;fees=0;active=0;positive=[];hypothesis=[]
            for row in rows:
                own=diagnosis[row['session'],symbol];first=own['first_actual'];q=0 if first is None else first['quantity']
                assert row['campaigns'] in (0,1)
                assert (first is not None)==(row['campaigns']==1)
                if q:
                    assert type(q) is int and 0<q<=(5 if symbol=='TOPIX' else 10)
                    assert own['実政策新規数']==1
                    assert row['winning_lots']+row['losing_lots']==q
                    assert row['fees']==2*fee(q,symbol)
                    qcounts[q]+=1;sum_q+=q;active+=1
                else:
                    assert row['net']==row['fees']==row['winning_lots']==row['losing_lots']==0
                if row['net']>0:positive.append(row['net'])
                net+=row['net'];fees+=row['fees']
                equivalent=row['net']/(capacity*mult)
                observation=dict(session=row['session'],net_yen=row['net'],fee_yen=row['fees'],actual_entry_quantity=q,
                    entry_capacity_fraction=q/capacity,capacity_net_price_points=equivalent,
                    realized_net_price_points_per_actual_lot=row['net']/(q*mult) if q else None)
                if q:
                    actual=own['first_actual'];gross=row['net']+row['fees']
                    signed_price_points=gross/(q*mult)
                    unchanged_price_net=signed_price_points*capacity*mult-2*fee(capacity,symbol)
                    initial_reserved_risk=capacity*(actual['published_ATR']+actual['published_spread'])*mult+2*fee(capacity,symbol)
                    hypothesis.append(dict(session=row['session'],旧価格固定の実現方向値幅=signed_price_points,
                        固定全量=capacity,同価格一括返済の往復料=2*fee(capacity,symbol),事後価格固定net円=unchanged_price_net,
                        旧公開時の全量1ATR予約円=initial_reserved_risk,
                        旧5000又は2000円予約内=initial_reserved_risk<=(5000 if symbol=='TOPIX' else 2000),
                        判定='旧新規/返済価格を固定した事後価格模型。新規受理/出口/後参加を再生した新バックテストではない。'))
                observations.append(observation)
            full=case['metrics'][symbol]['full']
            assert math.isclose(net,full['net']) and active==full['campaigns']==full['active']
            assert active==len(positive) and full['negative']==0
            symbols[symbol]=dict(selected_id=cid,全場=33,黒字場=len(positive),無取引場=33-active,
                収支円=net,総料金円=fees,全33平均収支円=net/33,
                黒字平均収支円=net/len(positive) if positive else None,
                全完結親平均net円=net/active if active else None,
                片方向容量=capacity,価格1単位の一枚円倍率=mult,容量1価格単位円=capacity*mult,
                全33合計の容量換算価格単位=net/(capacity*mult),
                全33平均の容量換算価格単位=net/(33*capacity*mult),
                黒字平均の容量換算価格単位=net/(len(positive)*capacity*mult) if positive else None,
                一枚ラージ相当価格単位合計=net/large,
                新規枚数分布={str(q):n for q,n in sorted(qcounts.items())},総実新規枚数=sum_q,
                活動親の平均実新規枚数=sum_q/active if active else None,
                活動親の平均容量使用率=sum_q/(active*capacity) if active else None,
                全33の場最大枚数使用率平均=sum_q/(33*capacity),
                最大実同時枚数=max(qcounts) if qcounts else 0,
                最大実枚数使用率=max(qcounts)/capacity if qcounts else 0,
                使用率の定義='対象は各活動場の実親1・初回新規1・追加玉なし。時間加重保有率ではない。',
                各場=observations,旧価格固定の全量事後模型=hypothesis,
                旧価格固定全量net合計=math.fsum(h['事後価格固定net円'] for h in hypothesis),
                旧価格固定全量net平均=math.fsum(h['事後価格固定net円'] for h in hypothesis)/active if active else None)
        top=symbols['TOPIX'];assert top['収支円']==8260 and top['黒字場']==8
        full_fee=2*fee(10,'TOPIX');required=(100000+full_fee)/(10*1000)
        assert full_fee==836 and required==10.0836
        assert not any(v['平均10万円達成'] for v in condition_means.values())
        # 正ATRなら、観測最小spread .5だけで容量10の予約が旧場枠5000を超える。
        min_reserve_atr0=10*.5*1000+full_fee
        assert min_reserve_atr0==5836 and min_reserve_atr0>5000
        max_minimum=0
        for q in range(1,11):
            if q*.5*1000+2*fee(q,'TOPIX')<=5000:max_minimum=q
        assert max_minimum==8
        output=dict(全合格=True,評価訂正='旧金額割合/赤字率/補填力は形式達成。経済的利益床を含めると現選択と公開32条件は未達。',
            新目標=dict(TOPIX全完結親平均net円以上=100000,損失親も分母に含む=True,NK円額床未指定=True,
                同時保有上限TOPIXmini=10,手数料後=True),
            商品別容量と平均=symbols,公開32条件のTOPIX全親平均=condition_means,
            容量10で必要な平均実現方向値幅pt=required,全量一括往復料金円=full_fee,
            公開ラージ最小spreadのみの10mini最低予約円=min_reserve_atr0,
            ATR零を仮定しても旧5000円枠で可能な最大整数枚数=max_minimum,
            原因=['現qの選択上限自体が影初回5miniで、保有上限10miniまで使用する実装ではない。',
                '旧B5000円と予約1ATR+spread+feeは10miniを受理できない。spread .5ptだけでも5836円、正ATRならさらに必要。',
                'P1は初受理実q×.5pt×1000円の純目標で場停止。小q1なら500円目標となり、小幅利確1回で場を終える。',
                '0.5pt（1観測呼値）尺度の利確を容量利用で補うだけでは、容量10でも平均100000円に必要な10.0836ptの値幅を取れていない。'],
            確定部分=['10mini容量の1pt=10000円。現8260円は全33合計.826pt、全33平均250.303円、8完結親平均1032.5円。',
                '旧実価格と一括返済を固定した全量料金算術は可能。ただしその経路へ新数量を渡すと制御と受理条件が変わる。'],
            再比較要件=['親定義を固定し、手数料後の全完結親平均を用いる。勝ち親だけの平均や親分割で10万円床を満たさない。',
                '数量上限/影5との関係、公開予約1ATR枠、初受理場目標、場損失枠を独立に固定してから新全feedを再生する。',
                'mini10で約10.0836pt平均を狙う出口と、その間の最大清算逆行/損失/保有時間/週場制限を検証する。',
                '既存三基準、上位3除外、前後半、全33平均・活動・容量換算を併記し、少数巨大勝ちによる平均だけで選ばない。',
                'FAK公開価格条件・実料金・次正常返済・mini板到達未測の模型留保を維持する。'],
            留保=['全量事後模型は新バックテストではない。単純×10と異なり注文料floorを再算術したが、q選択や出口を再生していない。',
                '大きいqでは料・初期spread損・保有逆行も増える。既存5000円予約/停止のまま全量を約定したと仮定するのは整合しない。',
                '時間加重容量使用率、必要証拠金、真のmini板消費・部分FAK・市場 impact は今回未測。',
                '平均10.0836ptは全親の平均net10万円に対応する値幅で、全取引を必ずこの値幅で利確する保証ではない。'],
            小資料一読SHA256={p.relative_to(ROOT).as_posix():h for p,h in READS.items()},
            独立sourceSHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            旧金融result再読=0,入力=0,台帳=0,原板=0,NPZ=0,API=0,新金融=0,旧源又は共有変更=0)
        target.write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
        print(json.dumps(dict(全合格=True,TOPIX実q分布=top['新規枚数分布'],TOPIX平均全親net=top['全完結親平均net円'],
            TOPIX旧価格固定全量平均=top['旧価格固定全量net平均'],必要平均値幅=required,SHA256=hashlib.sha256(target.read_bytes()).hexdigest()),ensure_ascii=False))
    except Exception:
        failed.write_text(json.dumps(dict(全合格=False,原因=traceback.format_exc(),小資料読取SHA256={p.relative_to(ROOT).as_posix():h for p,h in READS.items()},
            新金融=0,旧結果再読=0,入力=0,台帳=0,API=0,自動再実行=False),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        raise


if __name__=='__main__':main()
