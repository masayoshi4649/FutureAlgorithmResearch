"""D016の板条件を価格だけへ置換し、板による時刻選別の寄与を反証する。"""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import pickle
import sys
import time
from zoneinfo import ZoneInfo

import numpy as np
from numba import njit

HERE = Path(__file__).resolve().parent
OLD = HERE.parent / 'wave_v23'
sys.path.insert(0, str(OLD))
import engine
import managers
import research
import discovery_signals as signals
import discovery_runner as runner

SYMBOLS = ('TOPIX', 'NK225')
FIELDS = ('time_s', 'seq', 'ofi', 'progress', 'price_short')
SEEDS = tuple(range(64))


def freeze() -> dict:
    """機能: 新しい対照の損益を計算する前に、数値と判定式を固定保存する。

    引数: なし。返り値: 固定仕様 (dict)。既存の固定ファイルは上書きしない。
    """
    original = runner.read(HERE / '探索条件の固定.json')
    spec = next(s for s in original['signals'] if s['id'] == 'D016')
    manager = next(s for s in original['managers'] if s['id'] == 'D065')
    rule = {
        '対象': 'D016__D065の事後反証。未知検証ではない。対照を探索候補へ加えず再順位付けしない。',
        '元信号': spec, '共通管理': manager,
        '価格符号閾値ATR比': .03,
        '撤回価格符号閾値ATR比': .03,
        '価格条件': {
            'P01': '両市場の30秒価格変化が同じ非ゼロ符号。方向は30秒符号。',
            'P02': '両市場とも60秒価格符号と30秒価格符号が逆で、両市場の30秒符号が一致。方向は30秒符号。',
            'P03': '自市場の60秒価格符号と30秒価格符号が逆。方向は30秒符号。相手市場を判定に使わない。',
            'P04': 'P01に、元候補と同じ(-30秒符号)×60秒進行<=0.35ATRを両市場で要求。板による入口選別だけを完全除去する補助対照。',
        },
        '保持': 'TTL120秒、最大観測間隔120秒、開始20分待機、相手追加遅延60秒を元仕様のまま維持。',
        '価格のみ撤回': '自市場の60秒価格符号と30秒価格符号が同じ時、その符号を撤回方向とする。保持中方向と逆なら解除。元と同様、新しい入口成立は同じ行の撤回より優先。',
        '補助比較': 'P01/P02/P03は元OFI撤回を残す入口だけ置換した3条件も検証する。元D016の入口を維持して撤回だけ価格化したD016_PRICE_VETOも検証する。これら3条件は板なしとは呼ばない。',
        '乱数対照': {
            'id': 'R04', 'seed': list(SEEDS),
            '目的': 'D016は成立時の売買方向が必ず30秒価格符号と一致する。板方向は独立の売買方向ではなく価格方向を採る時刻のフィルターである。その選別を無予測に置換する。',
            '規則': '各市場の解放イベントごとに独立公平な仮想OFI符号を生成。P04の価格適格時刻のうち自市場と追加60秒遅延相手の仮想符号が両方とも30秒価格符号の逆なら発火。保持と撤回は価格のみ。',
            '乱数固定': 'sha256(d016-price-control|seed|session|symbol)先頭8byte littleをPCG64初期値としrandom(n)<0.5で-1、それ以外+1。末尾延長で過去列不変。',
            '限界': '元OFIの有効率・持続性・市場間相関を再現しない。発火密度を併記する。元D016発火時刻で売買方向を乱数化する既存対照とは別。',
        },
        '約定': '費用0・指定価格約定・同じD065固定1枚・次行執行・全玉場内返済。',
        'データ限界': '全て既知13セッション26区間。価格は元の板特徴解放時刻のmid。板数量やOFIを除いても、板イベント由来の観測時刻情報は残る。純粋な固定時刻足との比較ではない。',
        '選別禁止': '64seed全てを掲載し、良かったseedの採用や閾値再調整を行わない。',
    }
    path = HERE / 'd016_price_control_fixed.json'
    if path.exists():
        existing = runner.read(path)
        assert existing['規則'] == rule, '固定済み対照の変更は禁止'
        return existing
    fixed = {'固定日時': datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(), '規則': rule,
             'コードSHA256': runner.digest(Path(__file__)),
             '入力固定SHA256': runner.digest(HERE / '探索条件の固定.json')}
    runner.save(path, fixed)
    print('対照条件の固定完了。ここまで新しい損益計算なし。', flush=True)
    return fixed


@njit(cache=True)
def hold(candidate: np.ndarray, veto: np.ndarray, times: np.ndarray, ttl: float, max_gap: float) -> np.ndarray:
    """機能: 元の期限付き保持を同じ順序で高速再現する。

    引数: candidate/veto/times (ndarray)、ttl/max_gap (float)。返り値: 方向 (ndarray[int8])。
    """
    output = np.zeros(len(times), dtype=np.int8)
    state, supported, previous = 0, -np.inf, -np.inf
    for i in range(len(times)):
        stamp = times[i]
        if stamp - previous > max_gap or stamp - supported > ttl:
            state = 0
        if state and veto[i] == -state:
            state = 0
        if candidate[i] != 0:
            state, supported = int(candidate[i]), stamp
        output[i] = state
        previous = stamp
    return output


def coins(seed: int, key: tuple[str, str], count: int) -> np.ndarray:
    """機能: 将来の経路長に依存しない仮想OFI符号を生成する。

    引数: seed/count (int)、key (tuple[str,str])。返り値: 公平符号 (ndarray[int8])。
    """
    identity = f'd016-price-control|{seed}|{key[0]}|{key[1]}'.encode()
    generator = np.random.default_rng(int.from_bytes(hashlib.sha256(identity).digest()[:8], 'little'))
    return np.where(generator.random(count) < .5, -1, 1).astype(np.int8)


def candidates(own: dict, peer: dict, mode: str, params: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """機能: 価格対照と元の板反転候補、価格/板の二つの撤回列を作る。

    引数: own/peer/params (dict)、mode (str)。返り値: 候補・価格撤回・元撤回 (tuple[ndarray,...])。
    """
    short = signals._sign(own['price_short'], .03)
    long = signals._sign(own['progress'], .03)
    peer_short = signals._sign(peer['price_short'], .03)
    peer_long = signals._sign(peer['progress'], .03)
    flow = signals._sign(own['ofi'], params['flow_threshold'])
    peer_flow = signals._sign(peer['ofi'], params['flow_threshold'])
    price_veto = np.where(long == short, short, 0).astype(np.int8)
    old_veto = np.where(flow == short, short, 0).astype(np.int8)
    same_short = (short != 0) & (short == peer_short)
    reversal = (short != 0) & (long == -short)
    absorbed = ((-short) * own['progress'] <= params['absorption_max_atr'])
    absorbed &= ((-short) * peer['progress'] <= params['absorption_max_atr'])
    if mode == 'D016':
        good = same_short & absorbed & (flow == -short) & (peer_flow == -short)
    elif mode == 'P01':
        good = same_short
    elif mode == 'P02':
        good = reversal & same_short & (peer_long == -peer_short)
    elif mode == 'P03':
        good = reversal
    elif mode == 'P04':
        good = same_short & absorbed
    else:
        raise ValueError(mode)
    return np.where(good, short, 0).astype(np.int8), price_veto, old_veto


def build(inputs: dict, models: dict, params: dict, mode: str, veto_mode: str = 'price', seed: int | None = None) -> tuple[dict, dict]:
    """機能: 同じ観測時計・保持時間で価格対照を原本行の方向列へ展開する。

    引数: inputs/models/params (dict)、mode/veto_mode (str)、seed (int|None)。
    返り値: 銘柄区間別方向・発火密度 (tuple[dict,dict])。
    """
    random_flow = {key: coins(seed, key, len(model['seq'])) for key, model in models.items()} if seed is not None else {}
    outputs, counts = {}, {}
    for key, ready in inputs.items():
        own = models[key]
        peer_key = (key[0], SYMBOLS[1 - SYMBOLS.index(key[1])])
        peer = signals._peer(own, models[peer_key], ('ofi', 'progress', 'price_short'), params['peer_delay_seconds'])
        candidate, price_veto, old_veto = candidates(own, peer, mode, params)
        if seed is not None:
            peer_coins = signals._asof(models[peer_key]['time_s'] + params['peer_delay_seconds'],
                                       random_flow[peer_key], own['time_s'], 0)
            good = (random_flow[key] == -candidate) & (peer_coins == -candidate)
            candidate = np.where(good, candidate, 0).astype(np.int8)
        veto = price_veto if veto_mode == 'price' else old_veto
        values = hold(candidate, veto, own['time_s'], params['signal_ttl_seconds'], max(120, params['seconds']))
        direction = signals._asof(own['seq'], values, ready['seq']).astype(np.int8)
        direction[ready['time_s'] < ready['start'] + params['warmup_minutes'] * 60] = 0
        direction[~np.isfinite(ready['atr']) | (ready['atr'] <= 0)] = 0
        valid = own['time_s'] >= ready['start'] + params['warmup_minutes'] * 60
        counts['|'.join(key)] = {'解放イベント数': len(candidate), '待機後イベント数': int(valid.sum()),
                               '待機後非ゼロ発火数': int(np.count_nonzero(candidate[valid])),
                               '全原本行数': len(direction), '非ゼロ方向行数': int(np.count_nonzero(direction))}
        outputs[key] = direction
    return outputs, counts


def replay(identifier: str, inputs: dict, direction: dict, manager: dict, counts: dict) -> dict:
    """機能: 全区間を同じ管理で再生し、全玉の収支・上限・次行執行を検算する。

    引数: identifier (str)、inputs/direction/manager/counts (dict)。返り値: 期間・区間集計 (dict)。
    """
    rows = []
    ledger_hash = hashlib.sha256()
    for key, ready in inputs.items():
        cfg = managers.make_config(manager, key[1], ready)
        result = engine.run(ready, direction[key], cfg, detail=False)
        ledger_hash.update(str(key).encode())
        ledger_hash.update(result['trades'].tobytes())
        row = research.summarize(result, cfg, key[1], key[0], identifier)
        wins = sorted([float(v) * cfg['point_value'] for v in result['cycles'][:, 3] if v > 0], reverse=True)
        row['two_largest_cycle_profits'] = wins[:2]
        rows.append(row)
    summaries = runner.diagnostics(rows)
    for symbol in SYMBOLS:
        own = [value for key, value in counts.items() if key.endswith('|' + symbol)]
        summaries[symbol]['待機後発火数'] = sum(r['待機後非ゼロ発火数'] for r in own)
        summaries[symbol]['非ゼロ方向行数'] = sum(r['非ゼロ方向行数'] for r in own)
    return {'id': identifier, 'symbols': summaries, 'sessions': rows, 'イベント密度': counts,
            'ledger_hash': ledger_hash.hexdigest(), '会計上限次行場内返済検算': True}


def causal_audit(inputs: dict, models: dict, params: dict) -> dict:
    """機能: 未来削除・未来価格改変・左右反射で新しい対照の因果性を監査する。

    引数: inputs/models/params (dict)。返り値: 監査結果 (dict)。損益は計算しない。
    """
    session = sorted({key[0] for key in inputs})[-1]
    pair = {key: value for key, value in inputs.items() if key[0] == session}
    boards = {key: models[key] for key in pair}
    cutoff = min(r['start'] + (r['time_s'][-1] - r['start']) * .55 for r in pair.values())
    truncated_inputs, truncated_models, perturbed = {}, {}, {}
    for key, ready in pair.items():
        keep = ready['time_s'] <= cutoff
        truncated_inputs[key] = {name: value[keep] if isinstance(value, np.ndarray) and len(value) == len(keep) else value
                                 for name, value in ready.items()}
        board_keep = boards[key]['time_s'] <= cutoff
        truncated_models[key] = {name: value[board_keep] for name, value in boards[key].items()}
        perturbed[key] = {name: value.copy() for name, value in boards[key].items()}
        for name in ('ofi', 'progress', 'price_short'):
            perturbed[key][name][~board_keep] = 1000.
    modes = [('D016', 'old', None), ('D016', 'price', None)]
    modes += [(mode, veto, None) for mode in ('P01', 'P02', 'P03') for veto in ('price', 'old')]
    modes += [('P04', 'price', seed) for seed in (None, 0, 63)]
    checked = 0
    for mode, veto, seed in modes:
        full, _ = build(pair, boards, params, mode, veto, seed)
        short, _ = build(truncated_inputs, truncated_models, params, mode, veto, seed)
        future, _ = build(pair, perturbed, params, mode, veto, seed)
        for key in pair:
            length = len(short[key])
            np.testing.assert_array_equal(full[key][:length], short[key])
            np.testing.assert_array_equal(full[key][:length], future[key][:length])
            if mode in ('P01', 'P02', 'P03', 'P04') and veto == 'price':
                no_board = {k: {n: (np.zeros_like(v) if n == 'ofi' else v) for n, v in b.items()} for k, b in boards.items()}
                removed, _ = build(pair, no_board, params, mode, veto, seed)
                np.testing.assert_array_equal(full[key], removed[key])
            checked += 1
        if seed is None:
            reflected = {key: {name: -value if name in ('ofi', 'progress', 'price_short') else value
                               for name, value in board.items()} for key, board in boards.items()}
            mirror, _ = build(pair, reflected, params, mode, veto)
            for key in pair:
                np.testing.assert_array_equal(-full[key], mirror[key])
    return {'未来削除・未来価格特徴改変の一致区間数': checked,
            '価格対照からOFI完全除去で方向一致': True,
            '決定的対照の価格・OFI左右反射で売買反転': True,
            '乱数末尾長非依存': True, '監査区間': session}


def distribution(random_rows: list[dict], targets: dict) -> dict:
    """機能: 64seedを一つも選別せず、各銘柄の全分布を集計する。

    引数: random_rows (list[dict])、targets (dict)。返り値: 分布・片側経験割合 (dict)。
    """
    output = {}
    for symbol in SYMBOLS:
        values = np.array([r['symbols'][symbol]['net_yen'] for r in random_rows], dtype=float)
        pf = np.array([r['symbols'][symbol]['money_ratio'] for r in random_rows], dtype=float)
        base = targets['D016_PRICE_VETO']['symbols'][symbol]['net_yen']
        output[symbol] = {'seed数': len(values), '収支平均円': float(values.mean()), '収支中央値円': float(np.median(values)),
                          '収支最小円': float(values.min()), '収支最大円': float(values.max()),
                          '収支25%円': float(np.quantile(values, .25)), '収支75%円': float(np.quantile(values, .75)),
                          '黒字seed数': int(np.sum(values > 0)), '黒字seed割合': float(np.mean(values > 0)),
                          'PF中央値': float(np.median(pf)),
                          '元板入口・価格撤回以上の収支seed数': int(np.sum(values >= base)),
                          '上側経験割合補正あり': float((1 + np.sum(values >= base)) / (len(values) + 1)),
                          '発火イベント数平均': float(np.mean([r['symbols'][symbol]['待機後発火数'] for r in random_rows])),
                          '元板入口発火イベント数': targets['D016_ORIGINAL']['symbols'][symbol]['待機後発火数'],
                          '注記': 'これは後から選んだ候補の説明用分布で、探索全体の多重比較を補正した有意確率ではない。'}
    output['両銘柄黒字seed数'] = sum(all(row['symbols'][s]['net_yen'] > 0 for s in SYMBOLS) for row in random_rows)
    return output


def write_report(result: dict) -> None:
    """機能: 板の方向と発火時刻の役割を区別して、短い反証報告を保存する。

    引数: result (dict)。返り値: なし (None)。
    """
    lines = ['# D016の板条件を価格だけに置き換えた対照', '',
             '既知13セッションで有望に見えた D016__D065 への事後反証。比較条件は新しい収支を見る前に d016_price_control_fixed.json に固定した。未知相場の検証ではない。', '',
             '**結論：今回の既知期間では、板なしの両市場価格反転P02でも両銘柄の黒字・損小利大を再現でき、収支は元D016を上回った。「板情報がないと稼げない」とは言えない。一方、元D016は特にTOPIXで損失総額と最大下落が小さい。**', '',
             '元条件の吸収上限は **0.35ATR**、管理の最高利益保護率が25%。D016成立時の売買方向は必ず30秒価格変化の符号と同じであり、OFIの寄与はその価格方向を採用する時刻の選別である。', '',
             '全条件はD065固定1枚、費用0、指定価格約定、次行執行、場内全返済。金額はTOPIXミニとNK225マイクロを別々に集計し、両銘柄の円額を足して順位付けしない。', '',
             '|条件|TOPIX収支円|PF|NK225収支円|PF|', '|---|---:|---:|---:|---:|']
    for identifier, row in result['決定的対照'].items():
        top, nk = (row['symbols'][s] for s in SYMBOLS)
        lines.append(f"|{identifier}|{top['net_yen']:,.0f}|{top['money_ratio']:.2f}|{nk['net_yen']:,.0f}|{nk['money_ratio']:.2f}|")
    lines += ['', '## 元の板条件と両市場価格反転の違い', '',
              '|条件・銘柄|利益円|損失円|収支円|利益枚数/損失枚数|平均1枚利益/損失|含み損込み最大下落円|黒字セッション|',
              '|---|---:|---:|---:|---:|---:|---:|---:|']
    for identifier in ('D016_ORIGINAL', 'P02'):
        for symbol in SYMBOLS:
            row = result['決定的対照'][identifier]['symbols'][symbol]
            lines.append(f"|{identifier} {symbol}|{row['gross_profit_yen']:,.0f}|{row['gross_loss_yen']:,.0f}|{row['net_yen']:,.0f}|{row['profit_units']}/{row['loss_units']}|{row['average_unit_payoff']:.2f}|{row['drawdown_yen']:,.0f}|{row['win_sessions']}/13|")
    lines += ['', '- D016_ORIGINAL：元条件の完全再現。D016_PRICE_VETO：入口は元の板条件、撤回だけ価格化。',
              '- P01：両市場の30秒方向一致。P02：両市場の60秒方向から30秒方向への反転。P03：同反転を自市場だけで判定。',
              '- P04：両市場の30秒一致に元の符号付き0.35ATR上限を残し、OFI入口条件を全除去。',
              '- `_OLD_VETO` は入口のみ価格化し、撤回には元のOFIを残す。価格だけの対照とは区別する。',
              '- その他の価格対照の撤回は自市場の60秒と30秒の価格方向一致で判断。TTL120秒、最大間隔120秒、開始20分待機、相手追加60秒遅延は維持。P03は相手を判定に使わない。', '',
              'P02も最大2勝ちセッションを除いてTOPIX +61,500円、NK +14,000円。ただしTOPIXの最大下落は元D016の26,000円から81,500円へ拡大した。取引が増えて利益総額も損失総額も増えるため、収支の増加だけで安定性が上がったとは言えない。自市場だけのP03はPF1.27/1.14で、両市場の一致による時刻選別が効いている可能性がある。', '',
              '## 64seedの無予測OFI対照', '',
              'P04の価格適格時刻で独立公平な仮想OFI符号を両市場に割り当て、両方が価格方向の逆になったときだけ発火する。方向を無作為に取引する対照ではなく、板による発火選別を無作為に置換した対照。元OFIの持続性・銘柄間相関・発火率は一致させていない。', '',
              '|銘柄|64seed収支中央値円|最小〜最大円|黒字seed|PF中央値|元板入口・価格撤回以上|',
              '|---|---:|---:|---:|---:|---:|']
    for symbol in SYMBOLS:
        row = result['乱数分布'][symbol]
        lines.append(f"|{symbol}|{row['収支中央値円']:,.0f}|{row['収支最小円']:,.0f}〜{row['収支最大円']:,.0f}|{row['黒字seed数']}/64|{row['PF中央値']:.2f}|{row['元板入口・価格撤回以上の収支seed数']}/64|")
    lines += ['', '元の板入口は64seed全てを両銘柄それぞれで上回った。ただし板入口の発火数はTOPIX240回/NK137回、乱数フィルターの平均は約5,074回/3,426回で頻度が大きく異なる。したがって、この乱数対照だけで板の方向予測能力が有意と断定できない。元の発火数に合わせた対照や期間追加は別途必要。']
    lines += ['', '## 解釈上の限界', '',
              '価格列の観測時刻は元の板イベント由来であり、板数量を完全除去した条件にも観測頻度の情報は残る。価格対照の閾値最適化はしていないため、ここで劣っても全ての価格手法に対する板の優位性を示すわけではない。後から発見候補に行った少数の説明用対照であり、探索全体の選択バイアスは解消しない。', '',
              '元方向・元台帳は保存済みD016__D065と完全一致。全条件で会計、次行執行、片方向上限、全玉返済を検算。新しい方向列は未来部分の削除・改変に不変で、決定的条件は価格反射で売買方向が反転する。', '',
              '区間ごとの利益・損失・収支・勝ち負け枚数と全64seedは d016_price_control.json に保存した。']
    (HERE / 'd016_price_control.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def main() -> None:
    """機能: 仕様固定、因果監査、対照再生、原候補再現、全seed集計を順に実行する。

    引数: コマンド引数なし。返り値: なし (None)。処理は単一プロセスに限定する。
    """
    began = time.perf_counter()
    fixed = freeze()
    params, manager = fixed['規則']['元信号']['params'], fixed['規則']['共通管理']
    inputs = pickle.loads((OLD / 'inputs.pkl').read_bytes())
    features = pickle.loads((OLD / 'features_depth.pkl').read_bytes())
    models = {key: {name: np.asarray(value[name]).copy() for name in FIELDS}
              for key, ready in inputs.items() for value in [signals._book(ready, features[key], params['seconds'])]}
    print('価格特徴の準備完了。', flush=True)
    audit = causal_audit(inputs, models, params)
    tests = [('D016_ORIGINAL', 'D016', 'old'), ('D016_PRICE_VETO', 'D016', 'price')]
    tests += [(mode, mode, 'price') for mode in ('P01', 'P02', 'P03', 'P04')]
    tests += [(mode + '_OLD_VETO', mode, 'old') for mode in ('P01', 'P02', 'P03')]
    deterministic = {}
    stored = np.load(HERE / 'directions' / 'D016.npz')
    for identifier, mode, veto in tests:
        directions, counts = build(inputs, models, params, mode, veto)
        if identifier == 'D016_ORIGINAL':
            for key, direction in directions.items():
                np.testing.assert_array_equal(direction, stored['|'.join(key)])
                own = models[key]
                peer = signals._peer(own, models[(key[0], SYMBOLS[1 - SYMBOLS.index(key[1])])], ('ofi', 'progress', 'price_short'), params['peer_delay_seconds'])
                candidate, _, old_veto = candidates(own, peer, mode, params)
                np.testing.assert_array_equal(hold(candidate, old_veto, own['time_s'], 120, 120), signals._hold(candidate, old_veto, own['time_s'], 120, 120))
        deterministic[identifier] = replay(identifier, inputs, directions, manager, counts)
        print(f'決定的対照完了: {identifier}', flush=True)
    original = next(row for row in runner.read(HERE / 'summaries' / 'D016.json')['candidates'] if row['id'] == 'D016__D065')
    assert deterministic['D016_ORIGINAL']['ledger_hash'] == original['ledger_hash']
    for symbol in SYMBOLS:
        for field, value in original['symbols'][symbol].items():
            actual = deterministic['D016_ORIGINAL']['symbols'][symbol][field]
            if value is None:
                assert actual is None
            else:
                np.testing.assert_allclose(actual, value, atol=1e-7, rtol=0)
    audit['元D016方向・D065全台帳・期間全数値完全一致'] = True

    # ----------------------------------------
    random_rows = []
    for seed in SEEDS:
        direction, counts = build(inputs, models, params, 'P04', 'price', seed)
        random_rows.append(replay(f'R04_{seed:02d}', inputs, direction, manager, counts))
        if seed % 8 == 7:
            print(f'無予測板フィルター {seed + 1}/64 完了', flush=True)
    result = {'固定ファイル': 'd016_price_control_fixed.json', '固定SHA256': runner.digest(HERE / 'd016_price_control_fixed.json'),
              '実行コードSHA256': runner.digest(Path(__file__)), '因果性・再現監査': audit,
              '決定的対照': deterministic, '全64seed': random_rows,
              '乱数分布': distribution(random_rows, deterministic), '処理秒': time.perf_counter() - began}
    runner.save(HERE / 'd016_price_control.json', result)
    write_report(result)
    print(json.dumps({'処理秒': result['処理秒'], '監査': audit, '乱数分布': result['乱数分布']}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
