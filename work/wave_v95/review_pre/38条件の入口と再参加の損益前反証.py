"""損益を参照せず、独立した四源規則と実装の純判定を人工系列で反証する。"""

import ast
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
STAGE = HERE.parent
ROOT = STAGE.parents[1]
CHANNELS = ((0, 1, 2), (5, 6, 7), (10, 11, 12), (14, 15, 16))


def sha(path: Path) -> str:
    """
    機能: 読み取った損益前コードの指紋を求める。
    引数: path(Path)はコードの位置。
    返り値: strはSHA256。ファイルを変更しない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def functions(path: Path, names: tuple[str, ...]) -> dict:
    """
    機能: 必要な純関数だけをASTから読取り、売買や旧領域キャッシュを起動しない。
    引数: path(Path)、names(tuple[str,...])は読取関数名。
    返り値: dictはNumPyだけを使う関数環境。デコレータを外し人工検査に限定する。
    """
    parsed = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    nodes = []
    for node in parsed.body:
        if isinstance(node, ast.FunctionDef) and node.name in names:
            node.decorator_list = []
            nodes.append(node)
    assert {node.name for node in nodes} == set(names)
    env = {'np': np, 'SYMBOLS': ('TOPIX', 'NK225')}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), env)
    return env


def catalog() -> list[dict]:
    """
    機能: 損益を含まない条件カタログだけを読む。
    引数: なし。
    返り値: list[dict]は固定前の38条件。旧コードへの書込みを行わない。
    """
    path = STAGE / 'catalog.py'
    spec = importlib.util.spec_from_file_location('反証用95条件読取', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.catalog()


def pair(symbol: str, side: int, steps: float = 0, newer: bool = False) -> np.ndarray:
    """
    機能: 商品呼値に合う独立LP二源と旧BBO二源の人工観測を作る。
    引数: symbol(str)、side(int)、steps(float)、newer(bool)。
    返り値: ndarray[float64]は22列の人工観測。異なる源番号と時計を意図的に使う。
    """
    ticks = (.5, 10.) if symbol == 'TOPIX' else (10., .5)
    prices = (4000., 68000.) if symbol == 'TOPIX' else (68000., 4000.)
    out = np.ones(22, dtype=float)
    for j in range(2):
        offset, lp_offset = j * 5, 10 + j * 4
        increment = 2 if newer else 0
        clock = (102. + j * .25) if newer else (100. if j == 0 else 99.)
        out[offset:offset + 5] = [10 + j * 100 + increment, 40 + j * 100 + increment,
            clock, prices[j] + side * steps * ticks[j], prices[j] + ticks[j] + side * steps * ticks[j]]
        out[lp_offset:lp_offset + 4] = [20 + j * 100 + increment, 41 + j * 100 + increment,
            clock + (.1 if newer else 0.), prices[j] + side * steps * ticks[j]]
    return out


def reference_status(observed: np.ndarray, anchor: np.ndarray, exit_time: float,
                     side: int, ticks: tuple[float, float]) -> tuple[bool, bool, bool]:
    """
    機能: 実装を呼ばず、四源の同時正常性と時計及び位置の規則を列挙する。
    引数: observed/anchor(ndarray)、exit_time(float)、side(int)、ticks(tuple[float,float])。
    返り値: tuple[bool,bool,bool]は新源、両気配、両LPの各資格。
    """
    good = True
    for row in (observed, anchor):
        good &= bool(np.isfinite(row[:18]).all() and np.all(row[18:] == 1))
        for index, sequence, clock in CHANNELS:
            good &= bool(row[index] >= 0)
        for j in (0, 1):
            offset, lp_offset = j * 5, 10 + j * 4
            good &= bool(0 < row[offset + 3] < row[offset + 4] and row[lp_offset + 3] > 0)
    fresh = good and all(observed[index] > anchor[index] and observed[sequence] > anchor[sequence]
        and observed[clock] > exit_time and observed[clock] > anchor[clock]
        for index, sequence, clock in CHANNELS)
    quotes = fresh and all(side * (observed[j * 5 + k] - anchor[j * 5 + k]) >= ticks[j] - 1e-8
        for j in (0, 1) for k in (3, 4))
    prices = fresh and all(side * (observed[10 + j * 4 + 3] - anchor[10 + j * 4 + 3]) >= ticks[j] - 1e-8
        for j in (0, 1))
    return bool(fresh), bool(quotes), bool(prices)


def gate_accept(kind: int, active: bool, previous_side: int, candidate_side: int,
                status: tuple[bool, bool, bool], sustained: bool = False) -> bool:
    """
    機能: 反対候補だけに制限を掛ける独立した政策述語を返す。
    引数: kind/previous_side/candidate_side(int)、active/sustained(bool)、status(tuple[bool,...])。
    返り値: boolは政策だけの受理。既存の入口・執行資格は別に必要である。
    """
    if kind == 0 or not active or candidate_side != -previous_side:
        return True
    return kind == 2 and status[1] or kind == 3 and status[1] and status[2] or kind == 4 and sustained


def trigger(net: float, reason: int, stop_only: bool) -> bool:
    """
    機能: 直前の実完了親だけで損失記憶を再評価する。
    引数: net(float)、reason(int)、stop_only(bool)。
    返り値: bool。対象外の直近完了親でも以前の記憶を解除する。
    """
    return net < 0 and (not stop_only or reason in (1, 2))


def add_case(cases: list[dict], name: str, symbol: str, side: int, observed: np.ndarray,
             anchor: np.ndarray, expected: tuple[bool, bool, bool], implementation: dict) -> None:
    """
    機能: 独立期待値、純実装、政策5段の受理を一緒に検算する。
    引数: cases(list[dict])、name/symbol(str)、side(int)、observed/anchor(ndarray)、expected(tuple)、implementation(dict)。
    返り値: None。人工結果だけをcasesへ追加し、実価格や実損益を使わない。
    """
    ticks = (.5, 10.) if symbol == 'TOPIX' else (10., .5)
    reference = reference_status(observed, anchor, 100., side, ticks)
    actual = tuple(bool(value) for value in implementation['loss_gate_status'](observed, anchor, 100., side, *ticks))
    assert reference == expected, (name, symbol, side, reference, expected)
    assert actual == reference, (name, symbol, side, actual, reference)
    same_direction = [gate_accept(kind, True, -side, -side, actual) for kind in range(5)]
    assert all(same_direction)
    cases.append({'人工': name, '商品': symbol, '方向': side, '四源正常更新': actual[0],
        '両買売気配進行': actual[1], '両LP進行': actual[2], '同方向は全政策で受理': True,
        '反対受理_R0からR4': [bool(gate_accept(kind, True, -side, side, actual)) for kind in range(5)]})


def test_gates(implementation: dict) -> list[dict]:
    """
    機能: 時計、値、数量資格の正負例を両商品・上下反射で検査する。
    引数: implementation(dict)は抽出済み純実装。
    返り値: list[dict]は全人工比較結果。
    """
    cases = []
    for symbol in ('TOPIX', 'NK225'):
        for side in (-1, 1):
            anchor = pair(symbol, side)
            good = pair(symbol, side, 1, True)
            add_case(cases, '四源が非同期でも全て返済時計より後なら合格', symbol, side, good, anchor,
                     (True, True, True), implementation)
            for index, sequence, clock in CHANNELS:
                changed = good.copy()
                changed[clock] = 100.
                add_case(cases, f'源{index}同時計の新seqを拒否', symbol, side, changed, anchor,
                         (False, False, False), implementation)
                changed = good.copy()
                changed[sequence] = anchor[sequence]
                add_case(cases, f'源{index}原seq再利用を拒否', symbol, side, changed, anchor,
                         (False, False, False), implementation)
                changed = good.copy()
                changed[index] = anchor[index]
                add_case(cases, f'源{index}源index再利用を拒否', symbol, side, changed, anchor,
                         (False, False, False), implementation)
            for field in (18, 19, 20, 21):
                changed = good.copy()
                changed[field] = 0
                add_case(cases, f'資格{field}不明をLPで救済しない', symbol, side, changed, anchor,
                         (False, False, False), implementation)
            for field in (7, 13, 17):
                changed = good.copy()
                changed[field] = np.nan
                add_case(cases, f'値又は時計{field}のNaNを拒否', symbol, side, changed, anchor,
                         (False, False, False), implementation)
            changed = good.copy()
            changed[13], changed[17] = anchor[13], anchor[17]
            add_case(cases, '新LPは同値のまま_気配のみ進行_R2だけ合格', symbol, side, changed, anchor,
                     (True, True, False), implementation)
            changed = good.copy()
            changed[17] = anchor[17]
            add_case(cases, '片方LPだけ進行_R3を拒否', symbol, side, changed, anchor,
                     (True, True, False), implementation)
            for field in (3, 4, 8, 9):
                changed = good.copy()
                changed[field] = anchor[field]
                local_anchor = anchor.copy()
                j = 0 if field < 5 else 1
                offset = j * 5
                if changed[offset + 3] >= changed[offset + 4]:
                    local_tick = (.5, 10.)[j] if symbol == 'TOPIX' else (10., .5)[j]
                    local_anchor[offset + 4] += local_tick
                    changed[offset + 4] += local_tick
                add_case(cases, f'気配{field}一方だけ残るspread変化を拒否', symbol, side, changed, local_anchor,
                         (True, False, True), implementation)
            changed = good.copy()
            changed[3] = changed[4]
            add_case(cases, '最良気配同値の不正を拒否', symbol, side, changed, anchor,
                     (False, False, False), implementation)
            changed = good.copy()
            changed[10] = -1
            add_case(cases, '自己LP源不明を拒否', symbol, side, changed, anchor,
                     (False, False, False), implementation)
            invalid_anchor = anchor.copy()
            invalid_anchor[20] = 0
            assert not implementation['loss_pair_valid'](invalid_anchor)
            fallback = good.copy()
            add_case(cases, '最初のpostexit正常pairは基準のみ_同じ行は不合格', symbol, side,
                     good, fallback, (False, False, False), implementation)
            after_fallback = pair(symbol, side, 2, True)
            for index, sequence, clock in CHANNELS:
                after_fallback[index] += 2
                after_fallback[sequence] += 2
                after_fallback[clock] += 5
            add_case(cases, 'fallback後に四源更新と更なる進行なら合格', symbol, side,
                     after_fallback, fallback, (True, True, True), implementation)
    return cases


def test_memory_and_pulses(strategy: dict) -> dict:
    """
    機能: 実完了親の料金後損失と、拒否候補の消費及び再準備を人工で検査する。
    引数: strategy(dict)は抽出済み発火関数。
    返り値: dictは反証例と再現可能な人工計数。
    """
    memory = []
    for stop_only in (False, True):
        for net, reason, expected in ((-1., 1, True), (-1., 2, True), (-1., 3, not stop_only),
                                      (-1., 4, not stop_only), (0., 1, False), (1., 1, False)):
            assert trigger(net, reason, stop_only) == expected
            memory.append({'停止限定': stop_only, '実net': net, '実理由': reason, '記憶': expected})
    assert trigger(-668., 3, False) and not trigger(-668., 3, True)
    assert trigger(-668., 1, True)
    clock = np.arange(0., 930., 15.)
    state = np.zeros(len(clock), dtype=np.int8)
    state[0] = state[1] = 1
    state[clock >= 615.] = -1
    actual = strategy['event_pulses'](clock, state, np.ones(len(clock), bool))
    assert np.flatnonzero(actual).tolist() == [0, 41]
    rejected_first = actual.copy()
    rejected_first[0] = 0
    assert rejected_first[1] == 0
    invalid_neutral = np.ones(len(clock), bool)
    invalid_neutral[(clock >= 30.) & (clock < 615.)] = False
    no_rearm = strategy['event_pulses'](clock, state, invalid_neutral)
    assert np.flatnonzero(no_rearm).tolist() == [0]
    narrow = np.arange(0., 660., 15.)
    narrow_state = np.ones(len(narrow), dtype=np.int8)
    narrow_state[(narrow >= 525.) & (narrow <= 585.)] = 0
    narrow_pulse = strategy['event_pulses'](narrow, narrow_state, np.ones(len(narrow), bool))
    assert np.flatnonzero(narrow_pulse).tolist() == [0, 40]
    floating_old = (5001.5 / 5000. - 1.) * 10000.
    floating_new = (5001.5 - 5000.) / 5000. * 10000.
    assert floating_old < 3. and floating_new < 3. and floating_old != floating_new
    return {'実完了netと停止限定': memory, 'gross0の料金だけ赤字はN及びstopならSで発動': True,
        'stop負の次にnonstop負ならS解除_N更新': True,
        '返済予約では状態不変_人工政策': '予約時−1でも実約定net+1なら記憶False。実完了前は前の記憶を維持する。',
        '拒否後同じpulseは復活なし': True, '未知中立を60秒再準備へ使用しない': True,
        '発火600秒等号は受理': True,
        '同値LPとMIDでも浮動演算差': {'旧式bp': floating_old, '新式bp': floating_new,
            'この例は両式とも3bp未満': True,
            '結果前修正': '候補P2/P3には旧75式ratio_ret_bpを別列で保持しnull全列一致にする。J2許可は旧77と同型の差/old式を維持する。'}}


def persistence_counterexample() -> dict:
    """
    機能: 位置維持と新しい時計の有無、未来の真反転を逃す反例を構成する。
    引数: なし。
    返り値: dictは損益計算を伴わない数理反証。
    """
    start = pair('TOPIX', 1, 1, True)
    repeated_clock = start.copy()
    for index, sequence, clock in CHANNELS:
        repeated_clock[index] += 1
        repeated_clock[sequence] += 1
    index_advanced = all(repeated_clock[index] > start[index] for index, _, _ in CHANNELS)
    clock_advanced = all(repeated_clock[clock] > start[clock] for _, _, clock in CHANNELS)
    assert index_advanced and not clock_advanced
    fresh_flat = repeated_clock.copy()
    for _, _, clock in CHANNELS:
        fresh_flat[clock] += 10.
    assert all(fresh_flat[clock] > start[clock] for _, _, clock in CHANNELS)
    assert fresh_flat[13] == start[13] and fresh_flat[17] == start[17]
    return {'同clock新seqのみの追加更新反例': {'経過格子秒': 10, '四index更新': index_advanced,
            '四clock更新': clock_advanced, '結果前修正': 'rootが各四源のindex及びrawseq更新に加え、持続開始時の各源clockより厳密に新しいことを採用。'},
        '新時計で同じ1tick位置を10秒維持': {'持続成立': True, '開始後価格の上昇幅tick': 0,
            '結論': 'R4は基準を超えた位置の維持を確認する。連続的な価格傾斜・将来順行・板消費を保証しない。'},
        '真反転を逃す反例': '失敗親後、反対方向へ1tick進み8秒で更に大きく進むpathはR3なら入口資格を得てもR4の10秒前に波が終わる。R1は反対方向を全て捨てる。',
        '拒否pulseを復活させない影響': '当該15秒候補がgate不成立なら、その後10秒確認が成立しても同じ候補は返却しない。次の600秒間隔と有効中立60秒の候補まで無活動になり得る。',
        '両市場不同期': '自己進行がTrueの後に消失し、後で相手だけTrueになっても同一判断行で共同成立したとはしない。'}


def theoretical_limits() -> list[str]:
    """
    機能: 新研究の因果的許容範囲と、利益の証明に使えない事項を整理する。
    引数: なし。
    返り値: list[str]は正式損益前の反証。
    """
    return [
        '上がる価格は需給の価格結果であり、その後も同じ方向へ進む原因の直接観測ではない。正常LP・両BBO進行の改善は条件付き期待値の正符号を保証しない。',
        '買い後の売りや売り後の買いは会計上の返済需要を作るが、参加者の在庫・期限・別市場ヘッジが不明なので、その時計と価格を決定しない。',
        'P0→P1は同じ旧候補へLP許可を適用、P1→P2は旧validのもとLPで候補再構成、P2→P3は価格観測資格を独立させる。P3候補とR3再参加は別の作用。',
        'R2/R3は直前の失敗親を反転仮説の誤りと決め付けず、新たな両市場証拠を要求する。急な真反転は拒否され、遅い偽反転は受理され得る。',
        '前の損失がトレーリングの返済気配又は料金のためでもNは発動する。Sは管理理由依存であり、経済損失が同じでも期限理由なら発動しない。',
        '損失後の同方向が旧94で両区間黒字、反対方向がNKで両区間赤字だったという既知分類は仮説であり、反対制限の統合損益は再参加経路が変わるため単純な親除外と一致しない。',
        '各時計はCurrentPriceTime代理であり真受信時計ではない。原seq順・厳密過去参照と同clock源再利用の拒否は監査可能だが実運用の注文伝播・滑りを証明しない。',
        '旧OFI又はQが未知でも正常LPがあれば価格窓は使える。ただし執行資格・数量・十分な逆OFIの不存在を買い支持へ変えることは禁止する。',
        '最終約定LPは同じ最良気配の買い側・売り側で約定するだけでも動く。自己15秒両気配支持はこの単純な往復を抑えるが、相手LP方向だけでは相手両気配の進行を保証しない。損失後R2/R3の両市場両気配はこの差を明示的に確認する。',
        'P2からP3へ有効資格が増えると、初回発火と再準備の消費時刻も変わる。候補集合は単なる追加ではなく、同一判断と新固有・旧固有経路を別々に照合する必要がある。',
        '片方の入口資格又は値を過去に保持したTrueと、後で他方だけTrueを足し合わせない。四源は同じ公開格子の資格と現在の値を同時に比較する。',
        '4/8枚は10/20上限内のリスク縮小対照であり、親の価格利益率・料金後利益割合が改善するとは限らない。共通上限による安定性指標と同実数量の親比較を維持する。',
        'R1・R4の活動不足による赤字金額削減を毎セッション収益改善と同一視しない。無取引を勝ちに含めず、活動場と両商品別の料金後黒字・最大赤字・RMSを併記する。',
        '31場は全て既知。前16/後15分離は選定手順の一貫性を検査するが、これまで閲覧済みデータの未知将来検証にはならない。条件38と主P3_R3_Nは損益前に固定し後付け差替えをしない。',
    ]


def main() -> None:
    """
    機能: 損益前コードだけを読み、人工反証を新担当領域へ保存する。
    引数: なし。
    返り値: None。正式売買・正式損益・APIは実行も閲覧もしない。
    """
    HERE.mkdir(parents=True, exist_ok=True)
    paths = [STAGE / 'catalog.py', STAGE / 'data.py', STAGE / 'prepare_prices.py',
             STAGE / 'strategy.py', STAGE / 'engine.py', Path(__file__)]
    before = {str(path.relative_to(ROOT)): sha(path) for path in paths}
    values = catalog()
    assert len(values) == 38 and len({row['id'] for row in values}) == 38
    assert 'P3_R3_N' in {row['id'] for row in values}
    engine = functions(STAGE / 'engine.py', ('loss_pair_valid', 'loss_gate_status'))
    strategy = functions(STAGE / 'strategy.py', ('event_pulses',))
    gates = test_gates(engine)
    memory = test_memory_and_pulses(strategy)
    persist = persistence_counterexample()
    after = {str(path.relative_to(ROOT)): sha(path) for path in paths}
    assert before == after, '検査中に入力コードが変化しました。最新実装で再検査してください。'
    value = {'段階': '95正式損益前の理論と独立純判定人工。正式戦略成績の監査ではない。',
        '条件数': len(values), '主': 'P3_R3_N', '独立純判定人工数': len(gates),
        '全商品上下反射': True, '人工全合格': True, '人工': gates,
        '完了親と発火の反証': memory, '持続及び失った真反転': persist,
        '理論的限界': theoretical_limits(), '損益前コードSHA256': before,
        '実装監査で別途必要': ['全P0旧J8の候補・注文・親・時価一致',
            'N/S実約定とfallback及びR4のエンジン内状態を全38人工で照合',
            '候補300/15秒、許可5秒、実原行の別源及び全prefix未来毒入れ',
            'root全正式driverの隔離人工fixtureによる終端保存と再読取'],
        '正式95損益実行': 0, '正式95損益閲覧': 0, 'API取得': 0, '実注文': 0}
    out = HERE / '38条件の入口と四源再参加の損益前反証.json'
    out.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    assert json.loads(out.read_text(encoding='utf-8'))['人工全合格']
    print(f'四源純判定人工{len(gates)}件及び料金・記憶・発火・持続反証を保存。正式損益0。', flush=True)


if __name__ == '__main__':
    main()
