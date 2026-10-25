"""保有中の追跡ATRだけを更新する、24主条件と72診断を結果前に固定する。"""

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
SESSIONS = tuple(f'{day}_{period}' for day in ('2026-09-21', '2026-09-22', '2026-09-23',
                 '2026-09-24', '2026-09-25', '2026-09-28', '2026-09-29')
                 for period in ('Day', 'Night') if (day, period) != ('2026-09-29', 'Night'))


def digest(path: Path) -> str:
    """機能: ファイルを改変せずSHA256を計算する。

    引数: path (Path)。返り値: 16進指紋 (str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def old_design() -> dict:
    """機能: 旧結果前仕様だけを読み、今回の入口と固定管理の原型を得る。

    引数: なし。返り値: 旧探索仕様 (dict)。損益や現在データは読まない。
    """
    return json.loads((HERE.parent / 'wave_v27/探索条件の固定.json').read_text(encoding='utf-8'))


def signals() -> list[dict]:
    """機能: 短期価格と相手方向を確認する12入口を機構だけで指定する。

    引数: なし。返り値: 旧仕様をそのまま複製した12入口 (list[dict])。
    """
    original = {row['id']: row for row in old_design()['signals']}
    result = [deepcopy(original[name]) for name in SIGNAL_IDS]
    assert all(s['params']['entry_kind'] == 'short_price' and s['params']['peer_confirm'] is True for s in result)
    return result


def manager() -> dict:
    """機能: 旧D273の全管理値を原型のまま返す。

    引数: なし。返り値: 固定管理仕様 (dict)。追加の最適化を行わない。
    """
    return deepcopy(next(s for s in old_design()['managers'] if s['id'] == 'D273'))


def variants() -> list[dict]:
    """機能: 原型と三つの単独変更を列挙する。

    引数: なし。返り値: 4診断仕様 (list[dict])。
    """
    return [
        {'id': 'V000', 'name': '主条件', 'entry_delay_seconds': 0, 'trail_atr_delay_seconds': 0, 'observed_fill': False},
        {'id': 'V015', 'name': '入口方向だけ15秒遅延', 'entry_delay_seconds': 15, 'trail_atr_delay_seconds': 0, 'observed_fill': False},
        {'id': 'O000', 'name': '全約定を観測価格へ変更', 'entry_delay_seconds': 0, 'trail_atr_delay_seconds': 0, 'observed_fill': True},
        {'id': 'L300', 'name': '追跡用ATRだけ5分過去参照', 'entry_delay_seconds': 0, 'trail_atr_delay_seconds': 300, 'observed_fill': False},
    ]


def waves() -> list[dict]:
    """機能: 既存の指定4波を時刻・方向ごと変更せず取得する。

    引数: なし。返り値: 固定区間4件 (list[dict])。
    """
    return json.loads((HERE.parent / 'wave_v32/episode_audit_fixed.json').read_text(encoding='utf-8'))['対象']


def catalog() -> list[dict]:
    """機能: 12入口×固定/現在ATR×4変形の全96条件を生成する。

    引数: なし。返り値: 主24・診断72の全条件 (list[dict])。
    """
    output = []
    for signal in signals():
        for mode_id, mode, dynamic in (('A0', 'initial', 0), ('AT', 'current', 1)):
            for variant in variants():
                name = f"{signal['id']}__{mode_id}__{variant['id']}"
                output.append({'id': name, 'signal_id': signal['id'], 'manager_id': 'D273',
                    'name': signal['name'] + '／' + ('初回ATR固定' if dynamic == 0 else '現在ATRへ追跡幅更新') + '／' + variant['name'],
                    'atr_mode_id': mode_id, 'atr_mode': mode, 'dynamic_trail_atr': dynamic,
                    'variant_id': variant['id'], 'role': 'primary' if variant['id'] == 'V000' else 'diagnostic',
                    'entry_delay_seconds': variant['entry_delay_seconds'], 'trail_atr_delay_seconds': variant['trail_atr_delay_seconds'],
                    'observed_fill': variant['observed_fill'],
                    'reference_id': f"{signal['id']}__A0__{variant['id']}",
                    'base_id': f"{signal['id']}__{mode_id}__V000",
                    'adoption_target': signal['id'] == 'H019' and dynamic == 1 and variant['id'] == 'V000'})
    assert len(output) == len({s['id'] for s in output}) == 96
    assert sum(s['role'] == 'primary' for s in output) == 24
    assert sum(s['adoption_target'] for s in output) == 1
    return output


def rules() -> dict:
    """機能: 比較範囲・因果仕様・採否と有用性の意味を結果前に定義する。

    引数: なし。返り値: 判定と解釈の固定規則 (dict)。
    """
    return {
        '目的': '利益の返却を抑える効果と、継続波の途中撤退・再参入増加の交換を切り分ける。',
        '全条件数': 96, '主条件数': 24, '診断条件数': 72, '対象入口': list(SIGNAL_IDS),
        '採用比較': {'旧案': 'H019__A0__V000', '変更案': 'H019__AT__V000'},
        '他11入口': '結果を見る前に機構で指定した対応比較。収支上位の入口へ差し替えず、全12の差と改善/悪化/同値件数を保存する。',
        '主評価7': list(SESSIONS[6:]), '初期6': list(SESSIONS[:6]), '全既知13': list(SESSIONS),
        '評価の限界': '全13は既読。共通後半7も真に未見の検証ではない。新しい96市場や独立96仮説とは扱わない。',
        '尺度': 'TOPIXミニとNK225マイクロを個別比較。円額合算で順位付けしない。',
        '倍率': {'TOPIX': 1000., 'NK225': 10.}, '初回枚数': {'TOPIX': 5, 'NK225': 10},
        '片方向上限': {'TOPIX': 10, 'NK225': 20}, '費用': 0.,
        '原本価格': 'ラージの観測価格・呼値格子を保持して小口倍率へ換算する仮定。実小口板の約定再現とは別。',
        '共通管理': 'D273のまま。新規0.25ATR追跡・有効300秒、初回全体1ATR損失基準、2ATRで整数半分利確、1.5ATRから3ATR追跡、最長360分、全返済後5分休止、場内全返済。追加・両建て・ドテンなし。',
        '初回ATR_A0': '既存D273が新規に固定したATR。初期損失予算、1.5ATR追跡始動、2ATR部分利確、入口・枚数・初回Rを変更しない。',
        '現在ATR_At': 'ready.atrの当該原本行までに公開済みの値を追跡幅3×Atだけへ使用。新しいATR算式や将来足を追加しない。',
        '追跡床': '買いは既存床と高値−3Atの大きい方、売りは小さい方。At増大で確定済み保護価格を緩めない。現在行で更新した注文は次行以降から有効。',
        '欠測': '追跡用ATRは有限正値のみ。欠測時は直前の有効値、まだなければ当組A0。追跡用ATRの下限は2呼値で、3倍の追跡幅は最低6呼値。A0方式は追跡用At入力を使用しない。',
        '入口15秒': '同一セッション内のtime<=現在−15秒の最後の入口をasof参照。過去がなければ0。価格・ATR・管理時計は遅らせない。',
        '観測価格約定': '新規・損切り・追跡・部分利確・場末等の全約定を成立行の現在観測価格pにする。旧診断の利確指定値維持とは異なる。',
        'ATR5分': '追跡へ渡すAtだけtime<=現在−300秒の最後の値へ置換。A0、入口、初期予算、始動、部分利確は不変。参照なしは欠測規則へ。A0のL300とV000は理由を含む全台帳・曲線・集計の同一を必須とする。',
        '比較前必須': ['全96×26の会計・原本指紋・先読み防止・上限・場内返済',
                     'A0主12は旧同入口D273と全台帳一致', 'A0のATR5分診断12はA0主と全台帳一致'],
        '候補基礎': {
            '対象': 'H019変更案の全13と共通7を別々に、両銘柄で判定。',
            '両期間': {'収支': '>0', '総利益損失比': '>1', '勝ち1枚平均と負け1枚平均の比': '>1'},
            '主7のみ': {'稼働セッション': '>=4', '最大1勝ち組除外収支': '>=0', '最大1黒字セッション除外収支': '>=0'},
            '比の未定義': '損失ゼロ等で有限比を算出できない場合は未確認。無取引やNoneを合格にしない。',
            '除外': '全て独立した検査。部分返済脚を別の勝ち組として分離せず、完全返済までの組で判定する。'},
        '収支DDの関係': {
            '同時改善': '両期間×両銘柄の全4組で収支が旧案以上・含み込みDDが旧案以下、8比較値のどこか一つ以上が厳密改善。',
            '同値': '全8比較値が同じ。改良が生じたと呼ばない。',
            'リスク収益交換': '全4組でDD非増かつどこか減少するが、一つ以上の収支が減少。数値と減少率を示し、無価値とも無条件改良とも呼ばない。',
            '収益リスク交換': '全4組で収支非減かつどこか増加するが、一つ以上のDDが増加。',
            '旧案が支配': '全4組で旧案の収支以上・DD以下が成立し、どこか厳密差がある。',
            '混在': '上記以外。銘柄や期間の良い側だけで共通改良と呼ばない。'},
        '指定波': '既存4波×両銘柄の固定時刻と20分目安を保持。全96を計測し、H019変更案が旧案で達成した波を失えば波維持は不成立。全8が初期6内の目的診断で、主評価7の未見証拠ではない。',
        '指定波区間': waves(),
        '主条件の採用目安': 'H019変更案に限り、比較前必須・候補基礎・収支DD同時改善・指定波維持を全て満たす。満たさなければ旧案A0を維持し、交換関係があればその用途を説明する。75%収支/80%DDの比率条件は使わない。',
        '返却の主定義': '各完全返済組の時価損益（当組実現＋含み、組開始0を含む）の最高値peak>=0から最終組収支finalを引いた正部max(peak−final,0)。負け組も含むので名称は「組ピークから返済までの悪化」。',
        '利益が出た組の返却': 'peak>0の組だけの同じ差を補足として別集計。利益が出た組だけの改善で全口座採否を決めない。',
        '返却の単位': '円と初回予定R両方。R=初回枚数×A0×point_value（初期stop=1）。組数・R合計・円合計・1組平均・中央値を併記。R合計だけで取引回数変化を隠さない。',
        '返却と波切断': '返却が減っても収支減、波の正方向保有減、新規増、損失増なら交換として記述。全12対応の平均/中央値/改善悪化同値件数も全件保存する。返却減を単独採用ゲートにしない。',
        '診断の扱い': '72条件を全て比較。同変形のA0/At差と自方式の主条件差を保存。主と同じ基礎/関係/波判定を診断表示するが追加合格率閾値は設けない。悪化と順位逆転は留保に記す。診断最良の採用昇格や閾値再調整は行わない。',
        '解釈': '機構の改善確認と未知相場の収益保証は別。任意の改良目標未達をアルゴリズム全体の無価値としない。',
        '禁止': '新規API・保存ライブの読取/再生・旧原本/旧コード変更・結果を見た追加条件・後付け入口選抜。',
        '数値比較': '円額は絶対許容差1e-6のみ。統計的同等幅として使わず演算丸め差だけを許容する。',
    }


def freeze() -> dict:
    """機能: 新損益を読む前に96条件・判定・元仕様と方向の指紋を保存する。

    引数: なし。返り値: 固定記録 (dict)。既存固定との不一致は拒否する。
    """
    sources = [Path(__file__), HERE.parent / 'wave_v27/探索条件の固定.json',
               HERE.parent / 'wave_v23/inputs.pkl', HERE.parent / 'wave_v28/engine_context.py',
               HERE.parent / 'wave_v32/episode_audit_fixed.json']
    sources += [HERE.parent / 'wave_v27/directions' / (name + '.npz') for name in SIGNAL_IDS]
    value = {'固定日時': datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(), '規則': rules(),
             'signals': signals(), 'manager': manager(), 'variants': variants(), 'conditions': catalog(),
             'API取得数': 0, '現在保存物使用': False, '新PnL参照': False,
             '参照SHA256': {p.relative_to(ROOT).as_posix(): digest(p) for p in sources}}
    path = HERE / 'design_fixed.json'
    if path.exists():
        old = json.loads(path.read_text(encoding='utf-8'))
        assert {k: v for k, v in old.items() if k != '固定日時'} == {k: v for k, v in value.items() if k != '固定日時'}, '固定仕様の変更'
        return old
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    return value


if __name__ == '__main__':
    print('結果前の固定:', len(freeze()['conditions']), '条件')
