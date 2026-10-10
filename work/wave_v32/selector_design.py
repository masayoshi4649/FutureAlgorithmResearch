"""二つの入口を一つの口座で選ぶ主6方式と、反証142条件を損益前に固定する。"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import pickle
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parent


def digest(path: Path) -> str:
    """機能: 参照資料を分割して読み指紋を計算する。

    引数: path (Path)。返り値: SHA256 (str)。
    """
    value = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(8 * 1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def catalog() -> list[dict]:
    """機能: 主6と反証142を一意な固定IDで列挙する。

    引数: なし。返り値: 148条件 (list[dict])。損益を読まず、順位を作らない。
    """
    common = dict(role='primary', variation='baseline', manager_id='D273', initial_request=1,
                  er_window=30, er_trend_threshold=.35, er_range_threshold=.20,
                  decision_minutes=30, confirmations=2, minute_release_seconds=120,
                  common_market_delay_seconds=60, history_window=6, score_gap=.25,
                  score_clip=3., delay_seconds=0, fill_model='specified', random_seed=None)
    definitions = [
        ('S000', 'T固定：中期方向の入口', 'fixed', 1, 0),
        ('S001', 'R固定：価格だけの短期反転入口', 'fixed', 2, 0),
        ('S002', 'A：両市場の効率比でT/Rを選択', 'A', None, 0),
        ('S003', 'B：過去6完了区間の相対成績でT/Rを選択', 'B', None, 0),
        ('S004', 'A要求で取消し、実入口は常にT', 'A', None, 1),
        ('S005', 'A要求で取消し、実入口は常にR', 'A', None, 2),
    ]
    primary = [dict(common, id=identifier, name=name, base_selector=identifier,
                    selector_kind=kind, fixed_request=request, source_override=override,
                    entry_source={0: 'selected', 1: 'always_T', 2: 'always_R'}[override])
               for identifier, name, kind, request, override in definitions]
    output = deepcopy(primary)
    indexed = {row['id']: row for row in primary}

    def add(base: str, suffix: str, variation: str, label: str, **changes) -> None:
        """機能: 主仕様の一軸だけを変更した反証専用条件を加える。

        引数: base/suffix/variation/label (str)、changes (dict)。返り値: なし (None)。
        """
        output.append(dict(indexed[base], id=base + '__' + suffix, role='adversarial',
                           variation=variation, name=indexed[base]['name'] + '／' + label, **changes))

    # ----------------------------------------
    # 近傍は別々に変更し、同時に複数の軸を最適化しない。
    for window in (24, 36):
        add('S002', f'N{window:03}', 'er_window', f'ER窓{window}本', er_window=window)
    for window in (5, 7):
        add('S003', f'N{window:03}', 'history_window', f'過去{window}完了区間', history_window=window)
    for gap in (.20, .30):
        add('S003', f'G{round(gap * 100):03}', 'score_gap', f'切替差{gap:.2f}', score_gap=gap)
    for base in ('S002', 'S003'):
        for seconds in (1, 5, 15):
            add(base, f'D{seconds:03}', 'lag', f'入口と要求を{seconds}秒遅延', delay_seconds=seconds)
        add(base, 'O000', 'observed', '全約定を条件成立時の観測価格へ変更', fill_model='observed')
        for seed in range(64):
            add(base, f'Q{seed:03}', 'random_request', f'要求IDだけ公平乱数seed{seed}', random_seed=seed)
    output.sort(key=lambda row: row['id'])
    assert len(output) == len({row['id'] for row in output}) == 148
    assert sum(row['role'] == 'primary' for row in output) == 6
    return output


def rules() -> dict:
    """機能: 評価尺度と判定・解釈を結果前の固定値で定義する。

    引数: なし。返り値: 判定規則と対照仕様 (dict)。
    """
    return {
        '主比較ID': ['S000', 'S001', 'S002', 'S003', 'S004', 'S005'],
        '採用目安の対象': ['S002', 'S003'],
        '全条件数': 148, '主比較数': 6, '反証数': 142,
        '反証内訳': {'A窓': 2, 'B窓と差の単独変更': 4, '両入口と要求の遅延': 6,
                     '全約定観測価格': 2, '要求IDだけの乱数': 128},
        '全既知セッション数': 13, '初期化セッション数': 6, '主評価セッション数': 7,
        '評価区間': 'すべての148条件で時系列の第7〜13セッションを同じ主評価とする。全13は別の再現集計。',
        'B近傍7窓': '最初7完了区間まではT。第7区間も共通主評価に残し、評価開始をずらさない。',
        '市場単位': 'TOPIXミニとNK225マイクロを別々に判定。円額を合算して優劣や採否を決めない。',
        '契約倍率': {'TOPIX': 1000., 'NK225': 10.},
        '初回枚数': {'TOPIX': 5, 'NK225': 10}, '片方向保有上限': {'TOPIX': 10, 'NK225': 20},
        '共通管理': 'D273。新規0.25ATR追跡、初期全体1ATR損失基準、2ATRで整数半分利確、1.5ATRから3ATR追跡、最長360分、全返済後5分休止。追加・両建て・ドテンなし。場内全返済。',
        'T': '旧v27 H019の固定入口。旧保存方向と全配列指紋を照合する。',
        'R': 'v25 d016_price_control.build(mode=P02,veto_mode=price)の価格だけの入口と価格だけの撤回。旧OFI撤回を残したP02_OLD_VETOとは別。管理をD273へ統一して再生する。',
        'Rの限界': '価格は解放済み板mid。板数量・OFIは選択方向に使わないが、板イベント由来の観測時刻は残る。レンジ専用手法やミーンリバージョンの一般解とは呼ばない。',
        'A': {
            'ER式': 'abs(close[-1]-close[-window-1])/sum(abs(diff(last window+1 closes)))。分母0は0。',
            '足解放': '確定1分足の足始+120秒、さらに両市場共通60秒後。判断時計以前の最後の公開足をasof参照。',
            '時計': 'session.start+1800*k、k=1,2,...。両市場limitの小さい方未満。時刻延長で過去判断を変えない。',
            '要求候補': '両ER>=.35ならT、両ER<=.20ならR、中間/不一致/欠測なら候補なし。',
            '連続確認': '両市場とも前時計より新しい公開足が必要。同じ候補2回で更新。新足なし・欠測・中間/不一致は確認回数を0へ戻し現在要求を維持。',
            '初期': '毎セッションT。必要window+1本がない間もT。',
            '最初に切替可能な分': {'24': 60, '30': 90, '36': 90},
        },
        'B': {
            '判断': '各セッション開始時だけ。双方の当該セッションを丸ごと学習外にする。セッション中の損失で選び直さない。',
            '影口座': '過去の両市場×両枝4口座がcomplete=True、全玉返済済み、completed_at<=次開始であること。完了時刻は原本終端。実選択の片枝だけを学習しない。',
            '尺度R': '各過去sessionでstart+1200秒以上かつlimit未満の最初の有限正ATR×固定枚数×小型倍率。T/R共通、取引の有無に依存しない。両市場のどちらかが欠測なら区間全体を学習から外す。',
            'スコア': '各枝・各銘柄の直近window適格完了区間のnet_yen/Rを[-3,+3]へ制限した平均。両銘柄平均の小さい方を枝スコアとする。報告損益は切り詰めない。',
            '切替': '別枝score>現枝score+gapのときだけ切替。同点又は小差は現枝維持。初期と適格学習不足はT。',
        },
        '要求と所有': '要求IDは両市場共通、適用は各銘柄のフラット時だけ。保有中は注文元の建玉所有IDと共通出口を保持し、最新要求だけを残す。',
        '取消': '同方向のID変更でも旧未約定を取り消す。行iで取消判断→次行先頭で失効/確認→新IDで準備→さらに次行以降約定。旧注文がなければ不要な取消待ちは作らない。',
        '行内優先': '前行から有効な約定を先に処理し、現在行の選択で遡って取り消さない。切替で含み損・建値・ATR・追跡端点・損失・5分休止を初期化しない。',
        '取消対照': 'S004/S005はA要求をそのまま使い仮の所有IDも追跡。実入口だけT又はRへ固定し、Aの実約定時刻をコピーしない。',
        '遅延反証': 'T/R両入口と要求IDをそれぞれ同セッション内の1/5/15秒前以下の最後の原本行へasof遅延。履歴不足は入口0・要求T。価格、ATR、損益、管理時計は遅延しない。',
        '観測価格反証': '新規・損切り・追跡・部分利確を含め全約定を条件成立時の現在観測価格pで実行。旧観測派生の部分利確指定値維持とは異なる。注文判断から次行以降という順序は維持。',
        '乱数': {
            'seed': list(range(64)), '要求以外': 'T/R入口と全管理は維持。両市場へ同じ要求IDを渡す。',
            'A': "sha256('v32-selector-A|{seed}|{session}|{k}')先頭8byte little整数のbit0。0=T、1=R。同30分時計で2回確認、毎session初T。ER有効率・実際の切替回数・占有率は使わない。",
            'B': "最初6完了sessionはT、以後sha256('v32-selector-B|{seed}|{session}')先頭8byte little整数のbit0で同様に要求。",
            '集計': '各主A/Bと64seedの全順位・中央値・分位点・両銘柄で主以上の件数を報告。正式p値としない。最良seedを採用しない。',
        },
        '一次目安': {'両銘柄各収支': '>0', 'PF最低': 1.1, '1枚平均利益損失比最低': 1.1,
                      '稼働セッション最低': 4, '最大1勝ち組除外後収支': '>=0', '最大1黒字セッション除外後収支': '>=0'},
        '尺度定義': {
            '利益損失': '全返済脚の正損益合計/負損益の絶対額合計。利益玉だけでなく全損失玉を含む。',
            'PF': 'gross_profit_yen/gross_loss_yen。',
            '1枚平均利益損失比': '(gross_profit_yen/profit_units)/(gross_loss_yen/loss_units)。同値決済は別掲。',
            '分母0': '保存Noneは推測して無限大へ置換せず未確認扱い。一次目安を通過させない。',
            '稼働': 'そのsessionに実際の新規約定が1件以上。要求・未約定注文だけでは数えない。',
            '最大1勝ち組': '同じ建玉群の初回新規から全返済までを1組として部分利確を合算。最大の正組損益だけを全収支から除く。',
            '最大1黒字区間': '評価7内の最大正セッション収支だけを除く。組除外と区間除外は別々に計算し、同時二重除外しない。',
            'DD': '評価7を時系列につなげた全原本行の実現+含み損益曲線から求める最大下落。評価開始残高0、全玉場内返済。セッションDD最大の単純代用は禁止。',
            '枚数': '勝ち/負け/同値決済枚数を別々に合計。差は勝ち−負け決済枚数で保有残ではない。',
        },
        'T固定への工学目標': {'各銘柄収支': '候補net>=0.75*T固定net', '各銘柄DD': '候補DD<=0.80*T固定DD',
                               '位置づけ': '選択追加の改良目標。ユーザー要求の必要条件や全体の解なし判定へ読み替えない。'},
        '選択が動いた証拠': '後半7の各銘柄でT由来とR由来の新規約定がそれぞれ1件以上、実適用IDの変更が1回以上。Bは直前適用からのセッション間変更を含む。要求変更のみや取消のみは枝発火としない。',
        '比較による棄却': {
            '対照': ['S001', 'S004', 'S005'],
            'Pareto支配': 'いずれか1対照が両銘柄とも候補以上のnetかつ候補以下のDDで、4値のうち少なくとも1値が厳密改善。対照ごとに判定する。',
            '全4値同一': '支配とは別に同等と表示し、この比較による追加価値未確認とする。',
            '限界': 'S004/S005はA取消対照。Bへの支配や同等は追加価値未確認であり、Bの予測力がないことの証明ではない。',
        },
        '反証と判定の接続': '142変形全件を主との差・同じ一次目安の維持で報告する。反証合格率等の新たな集計閾値は追加しない。悪化を隠さず成立条件の限界を明示し、変形を新候補へ昇格しない。',
        '判定単位': 'S002/S003を別々に判定。合格した主候補の一覧だけを保存し、一位選抜・日別の良い方接続・さらに選ぶ選択器は作らない。',
        '指定波': '旧4波×両銘柄は全13の目的適合参考。多くが初期6内のため主評価7の利益証拠へ混ぜず、新しい採用ゲートにも追加しない。',
        '完全性': '全148×13×2=3848入力、主評価148×7×2=2072入力、全主6と全反証142、A/B各64seedの重複なしを必須にする。完備は収益採用とは別。',
        '禁止': '旧コードと原本の変更、現在API追加取得、保存ライブの読取り/再生、反証最良の採用、結果後閾値調整。',
        '既知と未知': '全13は既読、T/Rは既知成績から選んだ部品。今回の逐次選択を真の未見OOSや統計的確証とは呼ばない。',
    }


def freeze() -> dict:
    """機能: 全対象・時系列評価区間・参照元を新損益前に固定する。

    引数: なし。返り値: 固定仕様 (dict)。既存固定があれば完全一致を要求する。
    """
    with (WORK / 'wave_v23/inputs.pkl').open('rb') as source:
        inputs = pickle.load(source)
    assert len(inputs) == 26
    sessions = sorted({key[0] for key in inputs}, key=lambda session: min(r['start'] for k, r in inputs.items() if k[0] == session))
    assert len(sessions) == 13 and set(inputs) == {(s, symbol) for s in sessions for symbol in ('TOPIX', 'NK225')}
    files = [Path(__file__), HERE / 'selection_fixed.md', WORK / 'wave_v23/inputs.pkl',
             WORK / 'wave_v23/features_depth.pkl', WORK / 'wave_v27/hierarchy_signals.py',
             WORK / 'wave_v27/hierarchy_design_fixed.json', WORK / 'wave_v27/directions/H019.npz',
             WORK / 'wave_v25/d016_price_control.py', WORK / 'wave_v25/d016_price_control_fixed.json',
             WORK / 'wave_v25/discovery_signals.py', WORK / 'wave_v25/探索条件の固定.json',
             WORK / 'wave_v28/engine_context.py', WORK / 'wave_v28/次反復の選択設計案.md',
             WORK / 'wave_v30/context_split_design.py', WORK / 'wave_v30/管理設計の固定.json',
             WORK / 'wave_v31/次反復の選択器レビュー.md']
    value = {'規則': rules(), '条件': catalog(), 'セッション順': sessions, '初期化6': sessions[:6],
             '主評価7': sessions[6:], '全入力キー': [list(key) for key in sorted(inputs)],
             'API取得数': 0, '現在データ使用': False, '新損益参照前': True,
             'SHA256': {path.relative_to(WORK).as_posix(): digest(path) for path in files},
             '実装の結合': '後続runner/signals/engineと配列の実装指紋は起動manifestで別途固定し、この判定規則を変更しない。'}
    path = HERE / 'selection_fixed.json'
    if path.exists():
        old = json.loads(path.read_text(encoding='utf-8'))
        assert {k: v for k, v in old.items() if k != '固定日時'} == value
        return old
    value['固定日時'] = datetime.now(ZoneInfo('Asia/Tokyo')).isoformat()
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    return value


if __name__ == '__main__':
    fixed = freeze()
    print('主6＋反証142＝', len(fixed['条件']), '条件を新損益前に固定。主評価は共通後半7区間。', flush=True)
