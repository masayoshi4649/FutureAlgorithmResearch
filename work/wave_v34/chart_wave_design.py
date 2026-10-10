"""全192の指定波とH019の固定・動的通常・動的制御の78図を結果前に固定する。"""

from datetime import datetime
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import scheduler_design as design

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def prepare() -> dict:
    """機能: 新成績を読まず全波・図示対象・準備イベント表示と照合方法を固定する。

    引数: なし。返り値: 固定内容 (dict)。既存記録との差は停止する。
    """
    paths = [Path(__file__), HERE / 'scheduler_design.py', HERE / 'engine_scheduler.py',
             HERE.parent / 'wave_v33/input_audit.py', HERE.parent / 'wave_v30/episode_audit.py',
             HERE.parent / 'wave_v23/chart.js']
    value = {
        '全条件': design.catalog(), '全指定波': design.waves(), '全条件数': 192,
        '全指定波数': 1536, '比較境界数': 3072,
        '図示対象': ['H019__A0__NORMAL__V000', 'H019__AT__NORMAL__V000', 'H019__AT__SHADOW__V000'],
        '図示数': 78,
        '選び方': 'H019の旧固定、現在ATR通常、現在ATR準備制御を事前固定。A0制御は同値対照のため重複図を省く。成績で変更しない。',
        '指定波の独立計算': '全192の全注文から累積現金と買売在庫を再構成し、4波×2銘柄の境界時価・実現・含み損益、正逆保有分・枚数分、全区間新規/返済を検算する。影の損益は実収支に加えない。',
        '波の限界': '4波は全て初期6セッションに含まれる目的適合の参考。共通後半7の未知検証と扱わない。正ネット20分は目安。',
        '図の再生': '主再生後に固定3方式×26のみ同じ注文器で影と実を詳細再生し、全6結果指紋・準備/起点台帳・全金額と枚数を保存結果へ照合する。',
        '仮想の再生': '同じ入口方向と指定約定モデルの独立A0通常。追跡Atや実側状態を渡さない。SHADOW方式だけ仮想fresh準備rowを実の許可へ変換する。',
        '描画足': '保存された確定5分足OHLCを背景とし、全新規/返済は原本約定時刻と価格で表示する。',
        '準備イベント表示': '仮想と実の新設準備を2本の時刻帯で表示する。紫のひし形=仮想fresh準備、水色丸=仮想と準備payloadが一致する実準備、橙四角=通常運転の非共有実準備。実約定は価格図の売買三角/返済×とし、準備を約定と呼ばない。',
        '準備明細': '全準備の原本row/同値時刻/ローカルID/方向/初期水準/A0/期限/数量と、実約定への起点リンクを表示・照合する。同方向でも新設IDを区別し、追跡更新はfreshへ数えない。',
        '指標の描画時刻': '開始から5分時計（場末含む）以下の最終原本行をasof参照する。A0/At/初期予算由来損切り/追跡線は判断後で次行発効。フラットは欠値にし、異なる組を結ばない。',
        '間引きの限界': '線の点間の破線は表示補助。5分内の全更新を補間したものではない。準備と約定は間引かず全件を明細へ載せる。',
        '活動量の限界': '影fresh件数と実新設/新規約定を分ける。非許可原本行数を機会損失件数と呼ばない。通常運転の非共有準備は失敗や禁止違反ではない。',
        '新探索': False, 'API取得数': 0, '現在保存物使用': False,
        '参照SHA256': {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}}
    path = HERE / 'chart_wave_fixed.json'
    if path.exists():
        old = json.loads(path.read_text(encoding='utf-8'))
        assert {key: row for key, row in old.items() if key != '固定日時'} == value
        return old
    value['固定日時'] = datetime.now(ZoneInfo('Asia/Tokyo')).isoformat()
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    return value


if __name__ == '__main__':
    prepare()
    print('全1536波/3072境界とH019対照78図を結果前固定。新成績読取なし。')
