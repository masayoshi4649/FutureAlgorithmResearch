"""可変数量の設計案だけを保存する。金融エンジンも入力射影も実装・実行しない。"""

import hashlib
import json
from pathlib import Path


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]


def run() -> None:
    """
    機能: 二母条件の数量設計と八部品草案を、可用性及び金融結果より前に保存する。
    引数: なし。小 source の指紋だけを保存する。
    返り値: None。大型input33、原板、API、金融、登録へ接続しない。
    """
    paths=('work/wave_v67/replay.py','work/wave_v67/engine_shadow.py','work/wave_v85/strategy.py',
        'work/wave_v87/round12/strategy.py','work/wave_v106/e01_trade_gate/interface.py',
        'work/wave_v106/e01_trade_gate/engine.py','work/wave_v106/e01_trade_gate/daily.py',
        'work/wave_v106/e01_trade_gate/policy.py','work/wave_v106/e01_trade_budget/試行計画.json')
    sources={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths}
    configs=[dict(id='E01_SIZE_W60_'+mode+'_D0_P1_L2_A1',mode=mode,entry_window_seconds=60,
        execution='D0',risk_atr_multiple=1.,base_quantity={'TOPIX':5,'NK225':10},
        profit_goal_yen={'TOPIX':2500,'NK225':1000},loss_budget_yen={'TOPIX':5000,'NK225':2000},
        compare_ids={'L2':'E01_BUDGET_W60_'+mode+'_D0_P1_L2',
                     'L8':'E01_TRADE_W60_'+mode+'_D0_P1L8'}) for mode in ('CONFIRM','VETO')]
    spec=dict(entry=dict(conditions=configs,condition_count=2,母条件='元E01の保存paper新規公開と当時W60 proxy票をそのまま使う。',
        採否='CONFIRMはknownかつ二票以上かつside balance>=.25。VETOはknown二票以上かつside balance<=−.25だけ拒否。',
        数量資格='当該公開行のATRが有限正で、同normal行bid/askが有限正かつask>bid、同原行の正常quote資格がある時だけ数量計算。未知を0価格・未来正常行で補わない。'),
        management=dict(影='元5/10枚paper/feed/vcoreを不変で維持。実数量を影の注文条件や仮想勝敗へ戻さない。',
            数量='公開時に予定損失枠内で最大の整数qを選ぶ。初回も再参加もq<=元base_qty。q0は見送りで、影の全後続を継続。',
            部分返済='原親の初回virtual_qtyをV、公開済み累積virtual返済枚数をC、実初回数量をQとし、累積実返済目標=floor(Q*C/V)。既に予約した数量との差だけ予約する。最終virtual全返済では実残数量を全て処理。',
            順序='旧既知timer取消→前行予約の実返済/新規約定→当行paper公開を保持。すでに同行で約定した実UIDを遡及削除しない。',
            場停止='絶対円の利益又は損失目標へ初到達した当行実清算に基づき、次正常quoteで残UID別に全返済しその場は再開しない。'),
        exit=dict(通常GU='元GUの途中判断・部分返済・全返済・U静観を保持。予定1ATRを実停止線へ置換しない。',
            絶対目標={'TOPIX':{'profit_yen':2500,'loss_yen':5000},'NK225':{'profit_yen':1000,'loss_yen':2000}},
            firsthit='利益目標と損失枠の当時最初の到達を採用。判断後の返済を未来に都合よく取消さず次正常気配で実行。'),
        allocation=dict(base_quantity={'TOPIX':5,'NK225':10},direction_cap={'TOPIX':10,'NK225':20},
            場残損失余力='M=max(0,B+当時fee込み清算収支)。完了利益で再開せず、停止flagが最優先。',
            予定幅='w=1.0*公開時paper ATR。s=当行ask−bid。m=商品円倍率。',
            予定費用込み損失='L(q)=q*(w+s)*m+2*floor(q*f)。fは片道税込41.8円又は11円。',
            整数選択='q=0..base_qtyを列挙しL(q)<=Mを満たす最大整数。q×83.6円や一枚82円の単純比例で料金を置き換えない。',
            一枚許容量='w<=(M−2*floor(f))/m−s。TOPIX一枚往復82円、NK一枚往復22円。'),
        costs=dict(片道税込={'TOPIXmini':41.8,'NK225micro':11},円倍率={'TOPIX':1000,'NK225':10},
            実課金='新規・各部分返済・最終返済の注文別floor(q*f)。実UIDの新規料配分・残UID返済料を含める。',
            予定課金='整数qの新規と全返済を二注文として2*floor(q*f)で審査。後の部分料金floorの合計を実会計で取り直す。'),
        execution=dict(新規='D0。公開時に数量を固定し、当行fill不可、次正常買ask/売bid。約定行の悪化を過去公開へ戻さない。',
            返済='元GU又は場停止の判断後の次正常気配。場末・U静観・取消・busyの優先は既存E01と同じ。',
            注記='ラージTOPIX .5pt/NK10円の観測気配をミニ・micro価格代理へ使用。実商品native quote/queue/部分約定は未確認。'),
        data=dict(範囲='保存済み既知33場。現ナイト価格時計不適合素材は未使用。',
            使用予定='e01_trade_gateの33packetに保存されたpaper feed、normal quotes、当時票。登録後の金融開始時だけ各一読。',
            可用性='size_availability ownerが299公開のATR/同原行BBO/採否を新目的33packet一読で小射影予定。根の準備計画レビュー前は未読。',
            clock='価格時計代理と原seqの因果順。ReceivedAt未保存、真の到着時刻・両市場受信順は不明。'),
        implementation=dict(状態='金融本体未実装・JIT未作成・正式source未固定。8部品の数式と実装接口の草案だけ。',
            予定='新所有域へ元E01 executionをコピーし、公開数量と累積virtual割合による実返済だけを変える。旧登録source/cacheは書かない。',
            必須人工=['sizingオフ又は全base数量の時、旧注文/UID/費用/全curveがexact。',
                '買売反射、未知BBO/ATR、整数料金境界、q0見送り後の全影継続。',
                'Q1/2/3とvirtual5/10の複数partial、累積floor、最終残全返済、予約遅延で二重返済なし。',
                '当行既fill保持、busy、U/期限優先、次正常返済、未完接頭と未来書換え不変。',
                '実数量別floor料金とfee清算、絶対円goalはq減量後も不変。'],
            source_references=sources))
    plan=dict(id='106_E01公開時の費用込み予定リスクで初回も数量を選ぶ_草案',purpose='新部品仮説の非金融設計',
        完成範囲='8部品草案のみ。正式登録可能な実装・金融事前固定の完成証跡ではない。',spec=spec,
        予定条件数=2,KNOWN追加=0,
        原停止係数=dict(出口paper='.75ATR: wave_v67/replay.py settings()がmodified stop_atr=.75。',
            通常準備影='元PARAMS基準stop_atr=1.0。通常準備影と出口paperを混同しない。',
            新予定尺度='1.0ATRは保守的な数量審査の仮定。実GU停止までの距離又は損失上限そのものではない。'),
        予想される用途='固定5/10の初回と再参加の円リスクを、当時の揺れ幅・気配差・費用へ合わせて下げる。小さい残余力で同量へ再挑戦しない。',
        結果前の反証=['TOPIX公開ATRが一枚許容量を超えればq0になりやすい。活動消失を成功としない。',
            '2:1の場損失枠対利益目標は、最大赤字<=平均黒字を自動的に達成しない。',
            '数量減少で同じ円利益目標までに必要な値幅が増え、元GUがそれ以前に撤回・利確する可能性がある。',
            '予定ATR幅から外れた次quoteギャップ、spread悪化、原paperstop基準と実建値の差により枠を超える場合がある。',
            '元partialが小数量では0枚になる経路変化、別の後参加、停止時刻変更を保存損益比例で求めることはできない。'],
        299可用性の測定='既299 witnessは公開ATRと当行両BBOを欠く。初期支持価格と現在逆板priceをspreadに代用しない。root別ownerの新小射影完成まで未測定。',
        新入力読取=0,新金融=0,原板=0,原NPZ=0,API=0,登録=0,新JIT=0,元source変更=0,
        source_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    out=HERE/'費用込み予定リスク数量の8部品と失敗予測_未実施.json';assert not out.exists()
    saved=(json.dumps(plan,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf-8');out.write_bytes(saved)
    print(hashlib.sha256(saved).hexdigest(),flush=True)


if __name__=='__main__':run()
