"""全96の指定波と、H019固定/現在ATRの52図を結果前に固定する。"""

from datetime import datetime
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import design

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def prepare() -> dict:
    """機能: 成績を読まず、全波と図示対象・原本asof描画・照合方法を固定する。

    引数: なし。返り値: 固定内容 (dict)。既存の同一資料は再利用する。
    """
    conditions = design.catalog()
    paths = [Path(__file__), HERE / 'design.py', HERE / 'engine_dynamic_atr.py', HERE / 'input_audit.py',
             HERE.parent / 'wave_v30/episode_audit.py', HERE.parent / 'wave_v23/chart.js']
    record = {
        '全条件': conditions, '全指定波': design.waves(), '全条件数': 96, '全指定波数': 768, '比較境界数': 1536,
        '図示対象': ['H019__A0__V000', 'H019__AT__V000'], '図示数': 52,
        '選び方': '機構を変更したH019と旧H019の同一入口対照。損益順位で対象を差し替えない。',
        '指定波の独立計算': '全注文の累積現金・買い保有・売り保有を作り、開始/終了以前の最終原本行の価格で時価評価。実現損益は全返済の元価格差から積算。正逆保有分・枚数分も注文からの在庫を時間積分。全96を選別しない。',
        '波の限界': '4指定波は全て初期6セッションに含まれ、共通後半7の成績・未知検証とは数えない。正ネット20分は目的適合の目安。',
        '図の再生': '主再生終了後に固定2条件×26だけを同じエンジンで詳細再生し、全orders/trades/cycles/statsとcurveSHAを主保存値に照合する。',
        '描画足': '保存済みの確定5分足OHLCを価格の背景にする。売買マーカーは全原本約定時刻・約定値で描く。',
        '指標の描画時刻': 'セッション開始から5分刻みの時計（場末を含む）でtime<=時計の最後の原本行をasof参照。将来原本行や次足を使わない。A0/At/損切り/追跡線はその行の判断後の値で、更新価格注文は次原本行から有効。',
        '間引きの限界': '5分内の線更新や返済を全て線で復元するものではない。フラットのサンプルではA0/At/価格線を切断し、異なる組を結ばない。正確な返済は全マーカーと台帳で確認する。',
        '表示する指標': ['組番号', 'A0', '保持At', '実追跡幅に使うATR', '次行有効損切り線', '次行有効追跡線', '保有方向', '参照原本行'],
        '新探索': False, 'API取得数': 0, '現在保存物使用': False,
        '参照SHA256': {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
    }
    path = HERE / 'chart_wave_fixed.json'
    if path.exists():
        old = json.loads(path.read_text(encoding='utf-8'))
        assert {key: value for key, value in old.items() if key != '固定日時'} == record
        return old
    record['固定日時'] = datetime.now(ZoneInfo('Asia/Tokyo')).isoformat()
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    return record


if __name__ == '__main__':
    prepare()
    print('全768波とH019対照52図の対象・原本asof時刻を固定。成績読取・再生なし。')
