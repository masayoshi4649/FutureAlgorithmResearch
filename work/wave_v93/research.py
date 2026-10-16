"""全31既知場の予定距離・中心返済・失敗後再参加を固定して再生する。"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import pickle
import socket
import sys

import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

import accounting
import catalog
import data
import strategy


def read(path: Path) -> object:
    """
    機能: 凍結仕様又は保存された台帳を読む。
    引数: path(Path)。
    返り値: object。JSON又はpickleの保存内容。
    """
    if path.suffix == '.pkl':
        with path.open('rb') as stream:
            return pickle.load(stream)
    return json.loads(path.read_text(encoding='utf-8'))


def clean(value: object) -> object:
    """
    機能: NumPy値を有限JSONの標準型へ変換する。
    引数: value(object)。
    返り値: object。辞書、列、標準数値へ再帰変換した値。
    """
    if isinstance(value, dict):
        return {str(key): clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(item) for item in value]
    if isinstance(value, np.ndarray):
        return clean(value.tolist())
    if isinstance(value, np.generic):
        return value.item()
    return value


def save(path: Path, value: object) -> None:
    """
    機能: 新しい作業領域内へ会計又は証跡を保存する。
    引数: path(Path)、value(object)。
    返り値: None。生データと過去成果を上書きしない。
    """
    assert path.absolute().is_relative_to(HERE.absolute())
    path.parent.mkdir(parents=True, exist_ok=True)
    assert path.resolve().is_relative_to(HERE.resolve())
    if path.suffix == '.pkl':
        with path.open('wb') as stream:
            pickle.dump(value, stream, protocol=5)
    else:
        path.write_text(json.dumps(clean(value), ensure_ascii=False, indent=2,
                                   allow_nan=False) + '\n', encoding='utf-8')


def deny(*args: object, **kwargs: object) -> None:
    """
    機能: 検証コードの外部接続を禁止する。
    引数: args(tuple)、kwargs(dict)。
    返り値: None。常に例外を出す。
    """
    raise RuntimeError('保存した31セッションの既知入力だけを使用します')


def freeze() -> None:
    """
    機能: 全16条件、理論主、既知期間と全依存を正式損益前に固定する。
    引数: なし。
    返り値: None。監査が未完なら固定しない。
    """
    assert not (HERE / '事前固定.json').exists()
    assert not list((HERE / 'front/results').glob('*.json'))
    assert not list((HERE / 'back/results').glob('*.json'))
    material = data.load_inputs()
    sessions = material['metadata']['sessions']
    assert len(sessions) == 31
    for symbol in catalog.SYMBOLS:
        assert {p.stem for p in (ROOT / 'book' / symbol).glob('*.jsonl')} == set(sessions)
    proofs = list((HERE / 'audit').glob('*.json'))
    good = [path for path in proofs if read(path).get('全合格') is True]
    assert any('人工' in path.name and read(path).get('条件数') == 16 for path in good)
    assert any('接頭' in path.name and read(path).get('条件数') == 16 for path in good)
    assert any('対照' in path.name for path in good)
    for path in good:
        for relative, expected in read(path).get('SHA256', {}).items():
            assert data.digest(ROOT / relative) == expected, (path.name, relative)
    old_fixed = read(HERE.parent / 'wave_v92/事前固定.json')
    for relative, expected in old_fixed['SHA256'].items():
        assert data.digest(ROOT / relative) == expected, relative
    paths = [HERE / name for name in ('catalog.py', 'data.py', 'strategy.py', 'engine.py',
                                      'accounting.py', 'research.py', 'controls.py', 'analysis/assemble.py')]
    paths += list((HERE / 'audit').glob('*.py')) + proofs
    paths += list((HERE / 'theory').glob('*.json')) + material['paths']
    paths += [HERE.parent / 'wave_v92/review/次段N3N4と独立配分の16対照設計.json']
    paths += [HERE / 'review/主C11と16対照の損益前固定理由.json']
    fingerprints = dict(old_fixed['SHA256'])
    fingerprints.update({str(path.relative_to(ROOT)): data.digest(path) for path in sorted(set(paths))})
    save(HERE / '事前固定.json', dict(
        条件=catalog.catalog(), 主=catalog.PRIMARY, 全31=sessions,
        主の選択='C11。回復後の中心利益余地と予定停止リスクを確認し、中心で返済し、極値失敗の実損切り後は双方の旧失敗中心帰還と新準備を要求する論理接続。新損益前に固定し、失う利益・活動不足の反証を残す。固定配分S03は別統合。',
        前16=sessions[:16], 後15=sessions[16:], 旧30=sessions[:-1], 後14=sessions[16:-1],
        追加1=sessions[-1:], 全31既知=True, 新しい未見確認場数=0,
        意味='全31場は既知期間の再探索。条件・主を固定し前16で参考代表を固定してから後15を確認するが、後15も未見データと呼ばない。',
        目的='商品ごとに親別総利益/(総利益+総損失)80%以上、費用後黒字、含み損を含む下落の改善、活動の維持。無取引を勝ち扱いしない。',
        入口='元の双方0.25幅回復確認・LastPrice中心を保持。最初に回復が成立した判断時BBOで、極値停止線までの予定距離0.5/1幅又は中心利益と予定リスクの費用込み比2を単軸確認。不合格なら同エピソードを消費し旧解除と新準備まで再評価しない。次の約定価格を採否へ先取りしない。',
        観測='相手は最新公開格子の厳密過去端点だけ。極値は価格が更新した時だけ更新し同値で形成行を後ろへ移さない。確認は極値形成後の有効源更新を伴う。当時までの価格であり将来の底は使わない。',
        解除='旧anyは共同方向!=0、Cは監視方向がない間は旧any、方向固定後は共同方向が監視側の反対の時だけ解除。±3幅破綻は維持。統合persistentもこの元ガードを維持する。',
        停止='C00旧LastPrice実新規価格から1幅、C01旧清算BBO極値線、C02以降の該当列は両条件OR。判断時の極値線を固定し、同一行の両証拠も記録。約定後の固定線と、判断後の次気配返済であり実最大損失保証ではない。',
        利益目標='入口ゲートC05は元3幅目標を保持。C06/C07だけ新規時に既知中心又は中心0.5幅先を固定し、LastPrice到達で返済判断。停止を優先し同新規観測への遡及返済をしない。',
        再参加='N4は極値線破りの判断証拠と実全返済net負が揃って初めて反発源を休止。上限停止だけの負けは構造破綻と混同しない。自己/双方の旧失敗中心0.25幅帯への新源帰還、又は全窓更新後のraw偽から確認済真を別列で比較。休止解除行は新準備も新規も禁止。',
        相手中心='親固有の自己/相手中心と幅を新規時に固定記録。失敗記録は帰還観測用で注文中心として復活させない。双方帰還は同じ判断行で各帯内、相手最新格子10秒以内・返済時より新源・代理clock>返済clockを要求。',
        新準備='N4専用既知旗は両current/300ER+TV>0、両180bounds源と位置と有限値、共同方向30/300returns有効を要求。rawは両低ER・範囲内・common0の元conjunction。有限common非0は正当偽、欠測やmode0は偽へ代用しない。偽/真とも全窓の最古実sourceclock>実返済clock、偽は両源>返済源、真は後格子・両源>偽源・元mode2を要求。',
        枚数='TOPIXmini片方向10枚、NK225micro20枚。固定配分は8/2と16/4、未使用枠貸出なし。親別損益は源の反対玉と相殺しない。',
        約定='ラージ保存BBOの代理。成行は判断後の次有効買ask/売bid。指値は後続ask<=limit/bid>=limitで有利気配を含める。全量仮定、追加5秒遅延なし、真の受信時刻・小商品板・待ち順位未検証。',
        料金='TOPIXmini片道41.8円/枚、NK225micro11円/枚、各注文合計の端数切捨て。倍率1000/10。全入力行を清算気配と返済手数料で評価し、セッション内全返済。',
        選定='前16で各商品20親・8活動場以上。両黒字かつ平均勝ち/負け>1、次両黒字、次活動充足の順。悪い側金額利益割合、悪い側黒字活動率、割合和、IDの順に参考1つ固定。主は差替えない。',
        判定='全31を後から並べた成績上位は事後診断と明記。完全一致の確認なし対照は独立した発見数に含めない。最大利益日除外、源別方向別、同一新規と後続経路で検証。',
        採用判定=read(HERE / 'review/主C11と16対照の損益前固定理由.json')['採用判定'],
        正式新条件損益前固定=True, SHA256=fingerprints, API取得=0, 実注文=0))
    print('16条件と主C11を固定。31場すべて既知です。', flush=True)


def validate(fixed: dict) -> None:
    """
    機能: 実行前に条件と凍結したすべての依存を照合する。
    引数: fixed(dict)。
    返り値: None。不一致があれば実行を拒絶する。
    """
    assert fixed['条件'] == catalog.catalog()
    for relative, expected in fixed['SHA256'].items():
        assert data.digest(ROOT / relative) == expected, relative


def changes(trace: np.ndarray) -> np.ndarray:
    """
    機能: 未定義値を含む全行状態から変化行と両端を取り出す。
    引数: trace(ndarray[float])。
    返り値: ndarray。行番号とその行の全状態列。
    """
    equal = (trace[1:] == trace[:-1]) | (np.isnan(trace[1:]) & np.isnan(trace[:-1]))
    rows = np.unique(np.r_[0, np.flatnonzero(~equal.all(axis=1)) + 1, len(trace)-1])
    return np.column_stack((rows, trace[rows]))


def ledger(output: dict) -> dict:
    """
    機能: 全注文・会計と予定距離及び失敗後再参加の潜在状態を保存する。
    引数: output(dict、正式執行の結果)。
    返り値: dict。全行を指紋化し、状態は疎形式で独立復元できる。
    """
    names = ('orders', 'trades', 'events', 'stats', 'slots', 'order_columns', 'trade_columns',
             'trace_columns', 'event_columns', 'stat_columns', 'slot_columns', 'reasons', 'event_codes')
    answer = {name: output[name] for name in names}
    answer.update(input_rows=len(output['curve']), trace_changes=changes(output['target_trace']),
                  range_state_changes=changes(output['range_state_trace']),
                  range_state_columns=output['range_state_columns'])
    for name in ('curve', 'source_curve', 'target_trace'):
        answer[name + '_SHA256'] = hashlib.sha256(output[name].tobytes()).hexdigest()
    answer['range_state_SHA256'] = hashlib.sha256(output['range_state_trace'].tobytes()).hexdigest()
    if 'risk_state_trace' in output:
        answer.update(risk_state_changes=changes(output['risk_state_trace']),
                      risk_state_columns=output['risk_state_columns'],
                      risk_state_SHA256=hashlib.sha256(output['risk_state_trace'].tobytes()).hexdigest())
    if 'range_parent_diagnostics' in output:
        answer.update(range_parent_diagnostics=output['range_parent_diagnostics'],
                      range_parent_columns=output['range_parent_columns'])
    answer['source_curve_column_SHA256'] = [hashlib.sha256(output['source_curve'][:, i].tobytes()).hexdigest()
                                            for i in range(2)]
    return answer


def run_one(config: dict, sessions: list[str], base: Path, prepared: dict) -> str:
    """
    機能: 固定した一条件の指定期間を再生し、会計と台帳を新規保存する。
    引数: config(dict)、sessions(list[str])、base(Path)、prepared(dict)。
    返り値: str。完了した条件ID。
    """
    target = base / 'results' / (config['id'] + '.json')
    assert not target.exists()
    rows, records = [], {}
    for key in sorted(key for key in prepared if key[0] in sessions):
        output = strategy.play(config, key, prepared)
        rows.append(accounting.account(key, output))
        records[key] = ledger(output)
    name = '前16' if len(sessions) == 16 else '後15'
    periods = {name: {symbol: accounting.aggregate(rows, symbol, sessions) for symbol in catalog.SYMBOLS}}
    path = base / 'ledgers' / (config['id'] + '.pkl')
    save(path, records)
    save(target, dict(config=config, rows=rows, periods=periods, ledger_SHA256=data.digest(path)))
    return config['id']


def run_config(config: dict, sessions: list[str], base: Path, material: dict) -> str:
    """
    機能: 作業者内で状態を作り、同時に保持する全場配列を並列数以下へ抑える。
    引数: config/material(dict)、sessions(list[str])、base(Path)。
    返り値: str。再生を完了した条件ID。
    """
    return run_one(config, sessions, base, strategy.prepare(material, config))


def score(result: dict) -> tuple:
    """
    機能: 前16の悪い側利益割合と黒字活動率を優先する固定順を作る。
    引数: result(dict)。
    返り値: tuple。昇順で使う採点。
    """
    values = [result['periods']['前16'][symbol] for symbol in catalog.SYMBOLS]
    shares = [value['profit_share'] if value['profit_share'] is not None else -1 for value in values]
    rates = [value['positive_session_rate'] if value['positive_session_rate'] is not None else -1 for value in values]
    return -min(shares), -min(rates), -sum(shares), result['config']['id']


def select() -> None:
    """
    機能: 前16の参考を後15の正式損益前に固定する。
    引数: なし。
    返り値: None。後15も既知であり未知性能と主張しない。
    """
    assert not (HERE / '前16参考代表.json').exists()
    assert not list((HERE / 'back/results').glob('*.json'))
    fixed = read(HERE / '事前固定.json')
    validate(fixed)
    results = [read(HERE / 'front/results' / (config['id'] + '.json')) for config in fixed['条件']]
    active = [result for result in results if all(
        result['periods']['前16'][symbol]['campaigns'] >= 20
        and result['periods']['前16'][symbol]['active_sessions'] >= 8 for symbol in catalog.SYMBOLS)]
    positive = [result for result in active if all(
        result['periods']['前16'][symbol]['net'] > 0 for symbol in catalog.SYMBOLS)]
    good = [result for result in positive if all(
        result['periods']['前16'][symbol]['payoff'] is not None
        and result['periods']['前16'][symbol]['payoff'] > 1 for symbol in catalog.SYMBOLS)]
    pool = good or positive or active or results
    chosen = min(pool, key=score)['config']['id']
    save(HERE / '前16参考代表.json', dict(全合格=True, selected=chosen, primary=catalog.PRIMARY,
         level=0 if good else 1 if positive else 2 if active else 3,
         eligible=[result['config']['id'] for result in pool],
         scores={result['config']['id']: score(result) for result in pool},
         後15正式損益前選定=True, 全31既知=True, 固定SHA256=data.digest(HERE / '事前固定.json'),
         結果SHA256={str(path.relative_to(ROOT)): data.digest(path) for path in
                      sorted((HERE / 'front/results').glob('*.json'))}))
    print(f'前16参考 {chosen} を固定。後15も既知として次に確認します。', flush=True)


def main() -> None:
    """
    機能: 固定、前16、参考選定、後15の順序を守って保存済みデータを実行する。
    引数: コマンド引数の段階と並列数。
    返り値: None。通信と実注文を行わない。
    """
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    for name in ('freeze', 'run-front', 'select', 'run-back'):
        group.add_argument('--' + name, action='store_true')
    parser.add_argument('--workers', type=int, default=3)
    args = parser.parse_args()
    socket.create_connection = deny
    socket.socket.connect = deny
    if args.freeze:
        freeze()
        return
    if args.select:
        select()
        return
    fixed = read(HERE / '事前固定.json')
    validate(fixed)
    if args.run_back:
        chosen = read(HERE / '前16参考代表.json')
        assert chosen['後15正式損益前選定']
        assert chosen['固定SHA256'] == data.digest(HERE / '事前固定.json')
        for relative, expected in chosen['結果SHA256'].items():
            assert data.digest(ROOT / relative) == expected, relative
    sessions = fixed['前16' if args.run_front else '後15']
    base = HERE / ('front' if args.run_front else 'back')
    material = data.load_inputs()
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(run_config, config, sessions, base, material):
                   config['id'] for config in fixed['条件']}
        for future in as_completed(futures):
            print(future.result() + ' 完了', flush=True)


if __name__ == '__main__':
    main()
