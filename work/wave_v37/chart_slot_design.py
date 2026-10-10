"""数量調整の図と、元枠ごとの空き区間診断を結果前に固定する。"""

from pathlib import Path
import json
import hashlib

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = ROOT/'アルゴリズム調査/00032_悪化時の部分減量と回復後の数量復元'
METHODS = {
    'H019__B06_RB06_F50_N1__V000': '主案：悪化で減量・新しい肯定で復元',
    'H019__A0__V000': '元のA0',
    'H019__B06_NONE_F50__V000': '悪化で減量・復元なし',
    'H019__B06_T120_F50_N1__V000': '悪化で減量・120秒後に復元',
    'H019__CORE50__V000': '最初から固定コアだけ保有',
    'H019__SMALL50__V000': '小数量・元利確時に半数返済',
}


def rules() -> dict:
    """機能: 表示対象と分解の非重複な意味を結果前に定める。

    引数: なし。返り値: 検査仕様(dict)。
    """
    return dict(図対象=METHODS, 図示数=156, セッション数=13, 銘柄数=2,
        診断対象=list(METHODS), 対応基準='H019__A0__V000',
        図='原本確定5分足＋全注文。初回/減量/復元/元返済/予算返済を理由番号で区別。',
        方向表示='entry複写の管理方向帯は使わない。数量操作はadjustment_eventsとsourceに限定。',
        時刻='数量の5分標本は当該時計以前の最後の原本行。足と注文の未来asofはしない。',
        枠差='元組IDと元枠番号で対応。各空き区間の-d*(終了又は復元約定価格-空き開始約定価格)を円換算。',
        分類=['初回から不保有', '悪化減量', '早期予算終了'],
        非重複='減量ですでに空いた枠は実予算終了で再度空いたと数えず、元の空き区間を継続。',
        復元後='復元玉の全返済脚損益を別表。枠差の式へ加えると二重計上になるため加算しない。',
        照合='全元枠・全実枠、全初回・全復元・全返済の脚会計を独立再計算し、空き区間和=実収支-元A0収支を各組/区間/銘柄で確認。',
        限界='保存経路の会計分解。予算停止がなければ後で復元した等の別方針の反実仮想は計算しない。',
        生データ変更=False, API取得=0, 保存ライブ=False, 成績による対象選別=False)


def prepare() -> dict:
    """機能: 全実装が揃った時だけ対象・検算器の指紋を固定する。

    引数: なし。返り値: 固定記録(dict)。売買結果は読まない。
    """
    files = ['chart_slot_design.py', 'slot_difference.py', 'chart_report.py', 'chart_data_audit.py', 'chart.js']
    hashes = {name: hashlib.sha256((HERE/name).read_bytes()).hexdigest() for name in files}
    value = dict(規則=rules(), 実装SHA256=hashes, 新損益読取=False)
    path = HERE/'chart_slot_fixed.json'
    if path.exists():
        assert json.loads(path.read_text(encoding='utf-8')) == value
    else:
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    return value


if __name__ == '__main__':
    prepare()
