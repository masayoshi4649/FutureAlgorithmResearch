"""固定ATRの仮想建玉が新規準備した行だけ参加する192条件を結果前に固定する。"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SIGNAL_IDS = tuple(f'H{i:03d}' for i in (3, 11, 19, 27, 35, 43, 51, 59, 67, 75, 83, 91))
SESSIONS = tuple(f'{day}_{phase}' for day in ('2026-09-21', '2026-09-22', '2026-09-23', '2026-09-24',
                 '2026-09-25', '2026-09-28', '2026-09-29') for phase in ('Day', 'Night')
                 if (day, phase) != ('2026-09-29', 'Night'))


def digest(path: Path) -> str:
    """機能: ファイルを改変せずSHA256を計算する。

    引数: path (Path)。返り値: 指紋 (str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def previous() -> dict:
    """機能: 前回の結果前設計だけを読み、同じ入口・ATR・管理・評価期間を使う。

    引数: なし。返り値: 前回仕様 (dict)。損益資料は読まない。
    """
    return json.loads((HERE.parent / 'wave_v33/design_fixed.json').read_text(encoding='utf-8'))


def signals() -> list[dict]:
    """機能: 同じ12入口を選別せず返す。

    引数: なし。返り値: 12入口 (list[dict])。
    """
    result = deepcopy(previous()['signals'])
    assert [r['id'] for r in result] == list(SIGNAL_IDS)
    return result


def manager() -> dict:
    """機能: 新規枚数・初回R・返済条件が不変のD273を返す。

    引数: なし。返り値: 共通管理 (dict)。
    """
    return deepcopy(previous()['manager'])


def variants() -> list[dict]:
    """機能: 原型・入口15秒・全観測約定・追跡ATR5分の4変形を返す。

    引数: なし。返り値: 4変形 (list[dict])。
    """
    return deepcopy(previous()['variants'])


def waves() -> list[dict]:
    """機能: 指定4波の時刻と方向を変更せず返す。

    引数: なし。返り値: 固定4波 (list[dict])。
    """
    return deepcopy(previous()['規則']['指定波区間'])


def catalog() -> list[dict]:
    """機能: 12入口×2ATR方式×2準備制御×4変形の192を列挙する。

    引数: なし。返り値: 主48・診断144の全条件 (list[dict])。
    """
    result = []
    for signal in signals():
        for atr_id, mode, dynamic in (('A0', 'initial', 0), ('AT', 'current', 1)):
            for gate_id, gated in (('NORMAL', False), ('SHADOW', True)):
                for variant in variants():
                    name = f"{signal['id']}__{atr_id}__{gate_id}__{variant['id']}"
                    result.append({'id': name, 'signal_id': signal['id'], 'manager_id': 'D273',
                        'name': signal['name'] + '／' + ('初回ATR固定' if dynamic == 0 else '現在ATR追跡')
                                + '／' + ('仮想の新規準備時だけ参加' if gated else '通常の再エントリー') + '／' + variant['name'],
                        'atr_mode_id': atr_id, 'atr_mode': mode, 'dynamic_trail_atr': dynamic,
                        'gate_id': gate_id, 'gated': gated, 'variant_id': variant['id'],
                        'role': 'primary' if variant['id'] == 'V000' else 'diagnostic',
                        'entry_delay_seconds': variant['entry_delay_seconds'],
                        'trail_atr_delay_seconds': variant['trail_atr_delay_seconds'], 'observed_fill': variant['observed_fill'],
                        'reference_id': f"{signal['id']}__A0__NORMAL__{variant['id']}",
                        'dynamic_reference_id': f"{signal['id']}__AT__NORMAL__{variant['id']}",
                        'base_id': f"{signal['id']}__{atr_id}__{gate_id}__V000",
                        'predecessor_id': f"{signal['id']}__{atr_id}__{variant['id']}",
                        'adoption_target': signal['id'] == 'H019' and dynamic == 1 and gated and variant['id'] == 'V000'})
    assert len(result) == len({r['id'] for r in result}) == 192
    assert sum(r['role'] == 'primary' for r in result) == 48
    assert sum(r['adoption_target'] for r in result) == 1
    return result


def rules() -> dict:
    """機能: 仮想準備の定義・同値対照・採用と機構効果を固定する。

    引数: なし。返り値: 結果前の比較規則 (dict)。
    """
    base = deepcopy(previous()['規則'])
    base.update({
        '目的': '現在ATRで早く退出した後の過剰な再入場を抑える効果と、次の波へ入れない損失を同一入口で切り分ける。',
        '全条件数': 192, '主条件数': 48, '診断条件数': 144,
        '採用比較': {'旧案': 'H019__A0__NORMAL__V000', '変更案': 'H019__AT__SHADOW__V000'},
        '機構効果比較': {'通常動的ATR': 'H019__AT__NORMAL__V000', '変更案': 'H019__AT__SHADOW__V000'},
        '仮想建玉': '各H・各診断に対して独立運転する固定ATR A0通常口座。実の保有・退出・損益・休止で状態を変えない。セッション開始ごとに実と影をともに初期化する。',
        '仮想入力': '実と同じ入口方向・価格・入口ATR・診断約定モデル。V015は影も15秒入口、O000は影も全観測価格約定。L300は影A0なので追跡At変更を使わない。影に未来値や実口座の損益を渡さない。',
        '許可イベント': '影で新しいpending注文を実際に準備した原本行だけ許可。追跡中の価格更新、影の約定行、影保有中、影が単にflatの行は新規参加許可にしない。取消後に新しく準備すれば別の許可イベントとなる。',
        '実の準備': '実が未保有・休止終了・通常新規条件を満たす同じ許可行にだけ新pendingを準備する。保有中/休止中の影許可は見送り、後で復活させない。影準備行を見て作る実注文は通常どおり次行以降に有効。',
        '既存pending': '実側の既設pendingは通常どおり価格追跡・期限・方向取消を続ける。許可が翌行0になっただけで取消しない。途中参加や影の元価格へ遡った約定をしない。',
        '同一行順序': '影は当該原本行まで処理してその行の新準備イベントを出す。実はその行までの同じ情報とイベントで準備し、未来行の許可を参照しない。',
        '比較前必須': ['全192×26の因果・会計・上限・場内返済・原本指紋',
                     'NORMAL全96は前回v33の同条件と全台帳一致',
                     'A0 SHADOW全48は同変形A0 NORMALと理由・台帳・曲線まで一致',
                     'A0のL300全24は同gateのV000と旧5結果と準備イベント一致。未使用At表示列は別扱い',
                     '実側の退出や損益を変えても影イベントは不変、prefixと未来変更で過去許可不変'],
        '主条件の採用目安': 'H019 AT SHADOWに限定。実装監査・前回同じ候補基礎・旧A0 NORMALとの両期間×両銘柄の収支/DD同時改善・旧案の指定波維持を全て満たす。At NORMALとの関係は機構効果として別判定し、新たな数値閾値を追加しない。',
        '機構の有用性': 'At SHADOW対At NORMALを別に、同時改善/交換/同値/旧案支配/混在で分類。旧A0との目標と混ぜず、改善した指標・悪化した指標の両方を示す。A0 SHADOWの恒等性は実装確認であり新たな利益の根拠ではない。',
        '活動量': '影の新準備件数、実の新準備と約定件数、実保有中/休止中に見送った影イベントを分離する。gate=0の原本行数を失った取引機会数とは呼ばない。新規減少だけを安全性向上としない。',
        '損小利大の評価': '利益玉だけを切り出さず全玉の利益/損失/収支、勝ち/負け/同値決済枚数、平均枚損益、最大勝ち組/セッション除外、含み込みDD、正方向波保有を照合する。利益返却の定義は前回と同じ。',
        '反例': '実が先に損切りした後も影が保有していると、方向が再び進んでも許可が来ず利益を失う。実が影より長く保有している間の影準備は見送られる。影に追随すれば常に安全になるわけではない。',
        '診断の扱い': '144診断を選別せず、旧A0通常・同変形At通常・同一方式主条件との差を全件表示する。診断最良や別入口へ採用対象を変えず、悪化を留保として残す。追加通過率閾値はない。',
        '禁止': '新規API・保存ライブ読取/再生・旧原本/旧コード変更・結果を見た追加条件・後付け入口選抜。',
    })
    return base


def freeze() -> dict:
    """機能: 損益の前に192条件・判定・元設計を固定する。

    引数: なし。返り値: 固定記録 (dict)。
    """
    files = [Path(__file__), HERE.parent / 'wave_v33/design_fixed.json', HERE.parent / 'wave_v33/assessment.py',
             HERE.parent / 'wave_v33/engine_dynamic_atr.py', HERE.parent / 'wave_v23/inputs.pkl']
    files += [HERE.parent / 'wave_v30/directions' / (name + '.npz') for name in SIGNAL_IDS]
    value = {'固定日時': datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(), '規則': rules(), 'signals': signals(),
             'manager': manager(), 'variants': variants(), 'conditions': catalog(),
             '参照SHA256': {p.relative_to(ROOT).as_posix(): digest(p) for p in files},
             '新PnL参照': False, 'API取得数': 0, '現在保存物使用': False}
    path = HERE / 'scheduler_design_fixed.json'
    if path.exists():
        old = json.loads(path.read_text(encoding='utf-8'))
        assert {k: v for k, v in old.items() if k != '固定日時'} == {k: v for k, v in value.items() if k != '固定日時'}
        return old
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    return value


if __name__ == '__main__':
    print('仮想準備の事前固定:', len(freeze()['conditions']), '条件')
