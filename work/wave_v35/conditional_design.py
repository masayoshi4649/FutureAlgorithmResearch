"""入口機会を固定した条件付き追跡短縮と、過去6区間だけの選択を固定する。"""

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
    """機能: 読取専用でファイルの指紋を求める。

    引数: path (Path)。返り値: SHA256 (str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def previous() -> dict:
    """機能: 前回の設計だけを読み、損益は読まない。

    引数: なし。返り値: 前回事前設計 (dict)。
    """
    return json.loads((HERE.parent / 'wave_v34/scheduler_design_fixed.json').read_text(encoding='utf-8'))


def signals() -> list[dict]:
    """機能: 成績による選抜なしで同じ12入口を返す。

    引数: なし。返り値: 入口仕様 (list[dict])。
    """
    result = deepcopy(previous()['signals'])
    assert [r['id'] for r in result] == list(SIGNAL_IDS)
    return result


def manager() -> dict:
    """機能: 枚数・初期R・部分返済などを変えないD273を返す。

    引数: なし。返り値: 管理仕様 (dict)。
    """
    return deepcopy(previous()['manager'])


def waves() -> list[dict]:
    """機能: ユーザー指定4波の同じ時刻と方向を返す。

    引数: なし。返り値: 波仕様 (list[dict])。
    """
    return deepcopy(previous()['規則']['指定波区間'])


def condition_specs() -> list[dict]:
    """機能: 独立担当が定めた6機序×2窓の悪化方向仕様を受け取る。

    引数: なし。返り値: B00〜B11仕様 (list[dict])。
    """
    import deterioration_signals
    result = deepcopy(deterioration_signals.catalog())
    assert [r['id'] for r in result] == [f'B{i:02d}' for i in range(12)]
    return result


def exit_modes() -> list[dict]:
    """機能: 固定・常時短縮・12悪化条件の14方式を列挙する。

    引数: なし。返り値: 返済方式 (list[dict])。
    """
    result = [{'id': 'A0', 'name': '固定A0の3倍幅', 'width_mode': 0, 'condition_id': None},
              {'id': 'MIN', 'name': '常時min(A0,At)の3倍幅', 'width_mode': 1, 'condition_id': None}]
    result += [{'id': spec['id'], 'name': spec.get('name', spec['id']) + 'で短縮',
                'width_mode': 2, 'condition_id': spec['id']} for spec in condition_specs()]
    return result


def variants() -> list[dict]:
    """機能: 原型と入口時計・約定モデル・方向無関係の診断を返す。

    引数: なし。返り値: 全5変形 (list[dict])。
    """
    return [{'id': name, 'name': label, 'entry_clock_scale': scale, 'condition_clock_scale': 1.,
             'observed_fill': observed, 'random_seed': seed}
            for name, label, scale, observed, seed in (
                ('V000', '主条件', 1., False, None), ('C080', '入口の時間尺度0.8倍', .8, False, None),
                ('C120', '入口の時間尺度1.2倍', 1.2, False, None),
                ('O000', '全約定を成立行の観測価格', 1., True, None),
                ('R000', '活動時刻を保ち方向だけ30分ごと符号乱数化', 1., False, 0))]


def catalog() -> list[dict]:
    """機能: 12入口×14返済×5変形の840条件を選別せず作る。

    引数: なし。返り値: 主168・診断672条件 (list[dict])。
    """
    result = []
    for signal in signals():
        for mode in exit_modes():
            for variant in variants():
                name = f"{signal['id']}__{mode['id']}__{variant['id']}"
                result.append({'id': name, 'signal_id': signal['id'], 'manager_id': 'D273',
                    'name': signal['name'] + '／' + mode['name'] + '／' + variant['name'],
                    'exit_mode_id': mode['id'], 'width_mode': mode['width_mode'],
                    'condition_id': mode['condition_id'], 'variant_id': variant['id'],
                    'role': 'primary' if variant['id'] == 'V000' else 'diagnostic',
                    **{k: v for k, v in variant.items() if k not in ('id', 'name')},
                    'reference_id': f"{signal['id']}__A0__{variant['id']}",
                    'always_reference_id': f"{signal['id']}__MIN__{variant['id']}",
                    'base_id': f"{signal['id']}__{mode['id']}__V000",
                    'adoption_scope': signal['id'] == 'H019' and variant['id'] == 'V000'})
    assert len(result) == len({r['id'] for r in result}) == 840
    assert sum(r['role'] == 'primary' for r in result) == 168
    assert sum(r['adoption_scope'] for r in result) == 14
    return result


def rules() -> dict:
    """機能: 選択・対照・採用目安・解釈上の制限を結果前に定義する。

    引数: なし。返り値: 事前規則 (dict)。
    """
    return {'目的': '全新規機会を一致させ、板・価格・両市場の悪化確認で追跡を短縮する退出差を分離する。',
        '全条件数': 840, '主条件数': 168, '診断条件数': 672,
        '運用入口': 'H019固定。他11は選択根拠と対応対照。入口最良への変更なし。',
        '全既知13': list(SESSIONS), '選択用6': list(SESSIONS[:6]), '主評価7': list(SESSIONS[6:]),
        '期間の意味': '全13既知であり、後7も真の未見ではない。今回の計算は初期6完了→選択固定→後7の二段階に分ける。',
        '仮想入口': '各変形と同じ入口・約定モデルの固定A0独立影。影の新準備行だけ実準備可能。実損益で影を変更しない。',
        '全入口一致': '各実口座の全準備・全新規約定は同変形の固定影と完全一致を必須とする。実の全返済時刻は対応する影の返済時刻以前。同じ新規全組で退出差を比較できる。',
        '固定追跡候補': '全方式で固定3A0の保護候補を毎行更新。悪化時の3min(A0,At)候補を追加し、一度保護した床は緩めない。悪化0への復帰でも確保済みの価格線は解除しない。',
        '変更しないもの': '初回5/10枚、新規0.25A0追跡、初期全体1A0損失予算、1.5A0始動、2A0整数半分返済、360分保有、5分休止、場内全返済はD273共通。',
        '悪化': 'Bの過去だけから作ったsigned方向が保有と逆の行。中立・欠測・未公開では不発。参加と方向と実際の短縮回数を区別する。',
        '尺度': 'TOPIXミニ1pt1000円・NK225マイクロ1pt10円。円額は銘柄間合算せず、初回予定R基準のnet_rを選択の共通尺度へ使う。',
        '費用': 0., '原本価格': '原本ラージの価格格子を小型倍率換算。小型板の実約定再現ではない。',
        '選択入力': 'V000の168方式×初期6×2銘柄だけ。後7、欠落、重複、未完了、選択時刻後の完了記録を拒否。',
        '運用選択': '最初6は固定A0で運用しつつ候補を仮想運転。6終了後に14方式から1つ選び、後7は同方式を両銘柄に固定。セッションごとの後付け切替はしない。',
        '適格': '各銘柄別の12入口対応差で、net_r差中央値>=0かつ最大DD円差中央値<=0。丸め許容R1e-10/円1e-6。固定A0はゼロで必ず選択肢に残す。',
        '順位': '弱い銘柄のnet_r差中央値が大→両銘柄の中央値の平均が大→固定A0優先→方式ID昇順。順位Rは小数12桁で固定。同じ入口の枚数と初回Rは一致。',
        '損小利大の判定': '選択の適格と分離して、運用policyの全13/後7を両銘柄別に黒字・総利益損失比1超・勝ち負け1枚平均比1超。後7は4区間稼働・最大1勝ち組除外と最大1黒字区間除外を別々に非負。未定義比率は未確認。',
        '採用目安': '選ばれた非A0方式のみ対象。実装全件完備、候補基礎、H019の運用policyと固定A0の全13/後7×両銘柄で収支非減/DD非増かつ1つ以上改善、選択固定条件の旧指定波達成維持。75/80条件や未来利益保証は要求しない。',
        '常時短縮対照': '常時MINとの同時改善/交換/同値/支配/混在を別記。BがMINに支配されるなら確認条件の追加価値は支持されない。未選択MINへの事後差替えは禁止。',
        '指定波区間': waves(), '指定波': '全4波は選択用6内。policyの初期A0による波維持と、選択固定条件自身の8波診断を分ける。後7の波証明とはしない。',
        '入口時計': 'C080/C120はv27 hierarchy_signals.neighbor_specsのclock変形だけを入口へ適用し影も同入口。B窓・公開遅延・相手60秒は変更しない。A0/MINのCを原型同値とはしない。',
        '観測約定': 'O000は影と実の全新規・全返済を成立行価格pで約定する。',
        '方向乱数': 'R000は原Bの0/非0時刻を保持し、session開始から30分ブロックの符号±1を掛ける。全H・全B・両市場に同じseed/session/block符号を用い、初期/後半で同じ生成法。未来参照なし。',
        '乱数式': "sha256('v35|{seed}|{session}|{block}').digest()先頭8byte little整数bit0。0なら+1、1なら-1。block=floor((time_s-session_start)/1800)。",
        '追加乱数': '選択がB系のときH019選択方式V000入力へseed0〜63と単純符号反転を追加。seed0はR000再利用。他63と反転は診断のみ。最良seed採用・正式p・新採否閾値なし。',
        '乱数留保': '原信号の活動時刻だけは同一。保有逆方向になる時間、実短縮回数、保護幅は完全一致しないので件数・保有中逆方向時間を併記。選択工程全体の乱数化ではない。',
        '条件除去': '固定A0/MINを全条件の対照とし、同じ120/600窓で価格のみ・板のみ・両市場合意等の機序差を全対応で示す。部品単独差でない組合せは純粋な寄与と断定しない。',
        '未実施留保': 'B窓自体±20%、新手法の入口15秒遅延・追跡ATR5分遅延は今回未検査。旧v34結果を新方式の頑健性確認として継承しない。',
        '判定禁止': '最良入口・診断・seedへの差替え、初期6へ選択条件を遡って運用成績と呼ぶこと、未知利益の断定。',
        '原本等': 'book/candle/旧コードは読取のみ。現在API・保存ライブの読取/再生は行わない。'}


def freeze() -> dict:
    """機能: 840条件・選択式・対照・旧設計への指紋を固定する。

    引数: なし。返り値: 事前固定記録 (dict)。
    """
    paths = [Path(__file__), HERE / 'deterioration_signals.py', HERE / 'deterioration_design_fixed.json',
             HERE.parent / 'wave_v34/scheduler_design_fixed.json']
    payload = {'固定日時': datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(), '規則': rules(),
        'signals': signals(), 'condition_specs': condition_specs(), 'exit_modes': exit_modes(),
        'manager': manager(), 'variants': variants(), 'conditions': catalog(),
        '参照SHA256': {p.relative_to(ROOT).as_posix(): digest(p) for p in paths},
        '新PnL参照': False, 'API取得数': 0, '現在保存物使用': False}
    path = HERE / 'conditional_design_fixed.json'
    if path.exists():
        old = json.loads(path.read_text(encoding='utf-8'))
        assert {k: v for k, v in payload.items() if k != '固定日時'} == {k: v for k, v in old.items() if k != '固定日時'}
        return old
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return payload


if __name__ == '__main__':
    print('条件付き追跡の固定:', len(freeze()['conditions']))
