"""所有者・参加・指定波・図示の対象と計測法を結果を見る前に固定する。"""

from datetime import datetime
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def digest(path: Path) -> str:
    """機能: 固定対象ファイルの指紋を計算する。

    引数: path (Path)。返り値: SHA256 (str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare() -> dict:
    """機能: 主成績を読まず全148と主6図示および会計境界の計測仕様を保存する。

    引数: なし。返り値: 固定仕様 (dict)。再実行時は同一内容のみ認める。
    """
    fixed = json.loads((HERE / '探索条件の固定.json').read_text(encoding='utf-8'))
    from selector_design import catalog
    conditions = catalog()
    assert conditions == fixed['conditions'] and len(conditions) == 148
    waves = [
        dict(id='W01', session='2026-09-21_Day', start='2026-09-21T10:45:00+09:00', end='2026-09-21T15:35:00+09:00', side=1, name='9/21デイ後半の上昇'),
        dict(id='W02', session='2026-09-22_Day', start='2026-09-22T09:20:00+09:00', end='2026-09-22T11:45:00+09:00', side=-1, name='9/22デイ前半の下落'),
        dict(id='W03', session='2026-09-23_Day', start='2026-09-23T09:05:00+09:00', end='2026-09-23T11:15:00+09:00', side=-1, name='9/23デイ前半の下落'),
        dict(id='W04', session='2026-09-22_Night', start='2026-09-23T00:40:00+09:00', end='2026-09-23T03:20:00+09:00', side=1, name='9/22ナイト深夜の上昇'),
    ]
    assert {row['session'] for row in waves} <= set(fixed['初期6セッション'])
    rules = {
        '対象': [row['id'] for row in conditions], '条件': conditions,
        '全条件数': 148, '全入力数': 3848, '指定波件数': 1184, '図示件数': 156,
        '図示対象': ['S000', 'S001', 'S002', 'S003', 'S004', 'S005'],
        '指定波': waves, '初期6セッション': fixed['初期6セッション'], '主評価7セッション': fixed['共通評価7セッション'],
        '波の位置付け': '4指定波は全て初期6区間に含まれ、主評価7区間の成績ではない。目的適合の参考であり選抜・未知検証・有意性に使わない。',
        '選別': '全148条件を失敗・赤字・無約定を含め計測し、図示だけは結果によらず主6方式へ固定。',
        '所有監査': '新規の前行未約定から所有者と実入口源を再構成し、部分返済を経て完全返済まで不変。全返済後は0。取消要求の次原本行先頭で確認し旧注文消去、その行再準備から更に次行約定。要求変更に先立つ既存約定は保持。',
        '参加時間': '原本行後の状態を次行まで保持し、セッション開始から返済判断時刻までに切り取る。同時刻の寄与0。最終観測以降の時間を延長しない。',
        '追加参加項目': ['actual_entry_source_minutes', 'position_owner_minutes', 'pending_owner_minutes', 'long_unit_minutes', 'short_unit_minutes', 'held_minutes', 'flat_minutes'],
        '主集計照合': 'request/applied時間、実入口枝別新規/利益/損失/収支/返済枚数、全eventcount、最初最後appliedを独立に再計算。主集計のlong/short枚数分は全観測範囲、診断の場内枚数分は別キー。',
        '境界': '同銘柄の前区間最終applied→次区間最初appliedの差を次区間へ帰属。主評価集計には第6→第7の境界を含める。場初の第0行適用変更は区間内変更として別途数える。',
        '波計測': '旧4波の開始/終了以前の最終原本行で現金+純保有×観測値を評価。全注文から両境界を独立再構成。正方向ネット保有20分は目安。',
        '図': '主6×26の全返済を確定5分足へ描画。要求ID・適用ID・実入口源の状態帯を併記。全新規・全返済・枚数・理由・収支を保存台帳と照合する。',
        'API取得数': 0, '現在保存物使用': False, '新条件探索': False,
        '探索固定SHA256': digest(HERE / '探索条件の固定.json'),
        '参照SHA256': {path.relative_to(ROOT).as_posix(): digest(path) for path in [
            Path(__file__), HERE / 'engine_selector.py', HERE / 'selector_design.py', HERE / 'selection_fixed.json',
            HERE.parent / 'wave_v30/episode_audit.py', HERE.parent / 'wave_v23/chart.js']},
    }
    destination = HERE / 'selection_participation_fixed.json'
    if destination.exists():
        old = json.loads(destination.read_text(encoding='utf-8'))
        assert {key: value for key, value in old.items() if key != '固定日時'} == rules
        return old
    rules['固定日時'] = datetime.now(ZoneInfo('Asia/Tokyo')).isoformat()
    destination.write_text(json.dumps(rules, ensure_ascii=False, indent=2), encoding='utf-8')
    return rules


if __name__ == '__main__':
    prepare()
    print('成績を読まず、全148所有参加・波1184・主6図156の計測仕様を固定。')
