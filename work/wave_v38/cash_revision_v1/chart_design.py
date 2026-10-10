"""結果を見ずに指定した六方式の注文図・照合範囲を固定する。"""

from pathlib import Path
import hashlib
import json
import adaptive_assessment as assessment
import adaptive_design as adaptive

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
OUT=ROOT/'アルゴリズム調査/00033_復元方式の自動選択と改善8条件の反証'
BASE='H019__A0__R1__V000'
PRIMARY=assessment.PRIMARY
METHODS={
    BASE:'元A0・追加実損益R退出あり',
    PRIMARY:'主案・悪化状態で復元方法を自動選択',
    assessment.SIGNAL:'固定：新しいB01肯定で復元',
    assessment.CLOCK:'固定：120秒後のB01公開で復元',
    assessment.REVERSE:'逆分岐：主案と逆の復元方法を選択',
    PRIMARY.replace('__R1__','__R0__'):'主案・追加実損益R退出なし',
}
DESCRIPTIONS={
    BASE:'初回TOPIX5枚・NK22510枚。元A0の価格条件・時間条件で返済し、数量調整は行いません。',
    PRIMARY:'B06の逆方向で減量。減量約定時の有効なB01が保有逆方向なら新しいB01肯定による復元、それ以外は120秒後の新しいB01公開による復元を選びます。',
    assessment.SIGNAL:'B06の逆方向で減量。常に、減量後に公開された新しいB01肯定で復元を予約します。',
    assessment.CLOCK:'B06の逆方向で減量。常に、減量から120秒以降に公開された有効なB01で復元を予約します。肯定方向は要求しません。',
    assessment.REVERSE:'減量約定時の有効なB01が保有逆方向なら120秒時計、それ以外は新しいB01肯定による復元を選びます。',
    PRIMARY.replace('__R1__','__R0__'):'主案と同じ復元選択で、実の実現＋含み損による追加R退出だけを無効にします。元A0の返済条件は有効です。',
}
TARGETS=[(PRIMARY,'TOPIX','2026-09-22_Night'),
         (assessment.CLOCK,'NK225','2026-09-24_Day'),
         (assessment.REVERSE,'TOPIX','2026-09-29_Day')]


def rules() -> dict:
    """機能: 六方式と表示・根拠照合の規則を返す。

    引数: なし。返り値: 事前指定の表示仕様(dict)。
    """
    assert len(METHODS)==6 and set(METHODS)<={s['id'] for s in adaptive.catalog()}
    return dict(図対象=METHODS,方式説明=DESCRIPTIONS,図示数=156,セッション数=13,銘柄数=2,
        固定描画例=TARGETS,成績による対象選別=False,
        価格='原本closedの5分足OHLC。売買の未来価格は標本化しない。',
        数量='各5分時計以下の最終原本行を参照。実と影A0の買売合計枚数を示す。',
        注文='全注文・全返済を省略しない。初回、減量、復元、元返済、追加R返済を区別する。',
        分岐='減量約定時の選択イベントを独立した紫色の判断帯と表で表示。約定マーカーと区別し、固定方式に架空の選択イベントを作らない。',
        根拠='sourceはready配列公開行。分岐の有効性・方向・分類・方式・公開時刻と、調整予約／取消／約定を別表にする。',
        照合='再生全配列指紋と保存台帳、全注文・返済・分岐・操作根拠・原本足・独立注文積算asof・損益／枚数集計を全156で一致確認。',
        実行条件='V000だけ。指定価格・費用0・伝達追加遅延0・次有効行。Rは厳密な金額損失保証ではない。',
        既知データ=True,API取得数=0,現在保存物使用=False)


def prepare() -> dict:
    """機能: 対象と表示実装を保存し、既存の固定と違えば拒否する。

    引数: なし。返り値: 固定記録(dict)。売買結果は読まない。
    """
    files=('chart_design.py','chart_report.py','chart_data_audit.py','chart.js','chart_visual_check.py')
    value=dict(規則=rules(),実装SHA256={n:hashlib.sha256((HERE/n).read_bytes()).hexdigest() for n in files},
               結果参照前の表示対象固定=True)
    path=HERE/'chart_fixed.json'
    encoded=json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)
    if path.exists():assert json.loads(path.read_text(encoding='utf-8'))==json.loads(encoded)
    else:path.write_text(encoded,encoding='utf-8')
    return value
