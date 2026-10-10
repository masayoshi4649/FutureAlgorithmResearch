"""全6720波と、H019の運用・対照・固定診断104表示枠を結果前に固定する。"""

from datetime import datetime
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import conditional_design as design

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SLOTS = {'A0': '固定A0', 'MIN': '常時MIN', 'POLICY': '自動選択運用',
         'SELECTED': '選択方式の全期間固定・診断'}


def source_method(slot: str, session: str, selected_mode: str) -> str:
    """機能: 表示枠と期間だけから参照する保存条件を決める。

    引数: slot/session/selected_mode (str)。返り値: 元条件ID (str)。損益は参照しない。
    """
    assert slot in SLOTS and session in design.SESSIONS
    assert selected_mode in ('A0', 'MIN', *(f'B{i:02d}' for i in range(12)))
    mode = slot if slot in ('A0', 'MIN') else selected_mode
    if slot == 'POLICY' and session in design.SESSIONS[:6]:
        mode = 'A0'
    return f'H019__{mode}__V000'


def prepare() -> dict:
    """機能: 全波・表示枠・独立計算・重複計数の規則を成績未読で固定する。

    引数: なし。返り値: 固定規則 (dict)。既存との差は停止する。
    """
    paths = [Path(__file__), HERE / 'conditional_design.py', HERE / 'engine_conditional.py',
             HERE.parent / 'wave_v34/wave_order_audit.py', HERE.parent / 'wave_v23/chart.js']
    value = {'全条件': design.catalog(), '全指定波': design.waves(), '全条件数': 840,
        '全指定波数': 6720, '比較境界数': 13440, '図示枠': SLOTS, '全図示数': 104,
        '主図示数': 78, '補足図示数': 26, '固有再生数': {'選択B系': 78, '選択A0又はMIN': 52},
        '期間': list(design.SESSIONS), '初期6': list(design.SESSIONS[:6]), '後半7': list(design.SESSIONS[6:]),
        '対象選択': '初期6だけで凍結されたselected_exit_mode_idを機械的に使用。結果を見て図の対象を選ばない。',
        '運用参照': 'POLICYは初期6固定A0・後7選択方式。SELECTEDは全13固定の診断であり運用と呼ばない。',
        '重複': '表示は常に104枠。元条件ID・セッション・銘柄で一意な52又は78だけ再生する。収支偶然一致による省略はしない。',
        '指定波': '全840×4波×2銘柄を全注文からの現金・在庫・実現損益で独立計算。13440境界と保有分/枚数分・全区間注文を検算。影損益は加えない。',
        '波の限界': '全4波は初期6内。POLICYの8波は既存A0からの派生参照で6720へ二重加算しない。後7の波証明ではない。',
        '再生照合': '主再生完了後に固有対象のみ10結果指紋・全約定/準備/進行イベント・損益と枚数・control14・全組返済差を保存値へ照合。',
        '影': '同じ入口の固定A0通常。実At・悪化・損益から独立して再生成。影fresh準備行だけ実準備を許可。',
        '足': '保存済み確定5分足OHLC。全新規/返済は原本の約定行と価格で間引かず表示。',
        '線': '5分時計以下の最後の原本行をasof参照。固定追跡候補・最終有効線・初期予算線・A0/Atを描き、異なる組やフラットを接続しない。破線は表示補助。',
        '短縮': '悪化方向・追加候補が固定より狭い行・既設線まで実際に進めたイベントを区別。全進行イベントと根拠参照行を明細へ保存する。',
        '注記': '短い冒頭と注文確認主体。凡例・次行執行・仮想と実の準備明細は折畳み。選択固定診断は明記。',
        '独立検査': '注文からの会計と別式の候補/累積線/初期予算を確認。全104枠操作、画像による暗色可読性、ローカルリンクを検査。',
        '新探索': False, 'API取得数': 0, '現在保存物使用': False,
        '参照SHA256': {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}}
    assert len(value['全条件']) == 840
    for selected in ('A0', 'MIN', 'B00'):
        references = {(source_method(slot, session, selected), session, symbol)
                      for slot in SLOTS for session in design.SESSIONS for symbol in ('TOPIX', 'NK225')}
        assert len(references) == (78 if selected.startswith('B') else 52)
    path = HERE / 'chart_wave_fixed.json'
    if path.exists():
        old = json.loads(path.read_text(encoding='utf-8'))
        assert {key: item for key, item in old.items() if key != '固定日時'} == value
        return old
    value['固定日時'] = datetime.now(ZoneInfo('Asia/Tokyo')).isoformat()
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    return value


if __name__ == '__main__':
    prepare()
    print('全6720波・13440境界と104表示枠、固有52/78再生を結果前固定。')
