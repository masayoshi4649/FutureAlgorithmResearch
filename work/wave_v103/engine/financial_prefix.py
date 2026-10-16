"""正式金融の固定4先頭親で、過去注文・時価・由来を接頭だけ独立に再確認する。"""

import argparse
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path
import pickle
import sys
import time
import traceback

import numpy as np

import adapter


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WAVE = HERE.parent
PLAN = HERE / '実金融の先頭4親の接頭検査前固定.json'
PROOF = HERE / '実金融の先頭4親と接頭不変.json'
CASE_ORDER = (('U_C1R1', 'TOPIX'), ('U_C1R1', 'NK225'), ('C_VOLUME', 'TOPIX'), ('C_VOLUME', 'NK225'))


def digest(path: Path) -> str:
    """
    機能: 小さい直接資料又は今回参照台帳の内容指紋を求める。
    引数: path(Path)は新資料。
    返り値: strはSHA256。巨大原本を再hashしない。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read(path: Path) -> dict:
    """
    機能: 固定設計又は完了済み金融証跡をUTF-8で読む。
    引数: path(Path)。
    返り値: dict。選定に損益の優劣を用いない。
    """
    return json.loads(path.read_text(encoding='utf-8-sig'))


def save(path: Path, value: dict) -> None:
    """
    機能: 所有engine内へ新しい接頭証跡を保存する。
    引数: path(Path)、value(dict)。
    返り値: None。既存の証跡を上書きしない。
    """
    assert path.resolve().is_relative_to(HERE.resolve()) and not path.exists()
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def account_prefix(account: dict, pulse_id: str, normal_length: int) -> dict:
    """
    機能: 同一raw原行までの活動とnormal対応を切断し、未来候補を保存しない。
    引数: account(dict)、pulse_id(str)、normal_length(int)。
    返り値: dict。根のfinance.play.connectが同じ原行対応として検証できる接頭口座。
    """
    source = account['source']
    mapping = source['execution_to_raw_index']
    assert 0 < normal_length <= len(mapping)
    raw_length = int(mapping[normal_length - 1]) + 1
    past_source = {name: value[:normal_length] if name == 'execution_to_raw_index' else value[:raw_length]
                   for name, value in source.items()}
    normal = {name: value[:normal_length] if isinstance(value, np.ndarray) else value
              for name, value in account['normal_record'].items()}
    original = account['pulses'][pulse_id]
    pulse = dict(original, event=original['event'][:raw_length], normal_event=original['normal_event'][:normal_length],
        decisions=[row for row in original['decisions'] if row['row'] < raw_length],
        normal_decisions=[row for row in original['normal_decisions'] if row['normal_row'] < normal_length])
    if 'peer_rows' in original:
        pulse['peer_rows'] = original['peer_rows'][:raw_length]
    item = dict(account['item'], raw_rows=raw_length, normal_execution_rows=normal_length)
    return dict(item=item, source=past_source, normal_record=normal, pulses={pulse_id: pulse})


def prepared_prefix(value: dict, normal_length: int) -> dict:
    """
    機能: 旧recordと信号の原行/格子を当時既知の範囲へ切断する。
    引数: value(dict)は根で一度prepareされた値、normal_length(int)。
    返り値: dict。未来の場末まであるrecordや未来格子を接頭へ返さない。
    """
    record, signal = value['record'], value['signal']
    size, grid_size = len(record['time_s']), len(signal['grid'])
    assert 0 < normal_length <= size
    stamp = float(np.max(record['time_s'][:normal_length]))
    grid_length = int(np.searchsorted(signal['grid'], stamp, side='right'))
    past_record = {name: data[:normal_length] if isinstance(data, np.ndarray) and data.ndim and len(data) == size else data
                   for name, data in record.items()}

    def trim(data: object) -> object:
        """
        機能: own原行又は判断格子の軸を保存し、その他の値は参照で保つ。
        引数: data(object)は旧信号の子値。
        返り値: object。信号copyの接頭であり、元素材を変更しない。
        """
        if isinstance(data, np.ndarray) and data.ndim:
            if len(data) == size:
                return data[:normal_length]
            if len(data) == grid_size:
                return data[:grid_length]
            return data
        if isinstance(data, dict):
            return {name: trim(child) for name, child in data.items()}
        return data

    return dict(value, record=past_record, signal=trim(signal))


def compare(full: dict, past: dict, length: int, parent: int) -> dict:
    """
    機能: 接頭内の物理注文・完結親・全玉時価・保有・当時lineageを正式台帳と比較する。
    引数: full/past(dict)は正式台帳と接頭出力、length/parent(int)。
    返り値: dict。照合件数と未返済状態。接頭損益で新条件を採択しない。
    """
    expected_orders = full['orders'][full['orders'][:, 0] < length]
    expected_trades = full['trades'][full['trades'][:, 3] < length]
    np.testing.assert_array_equal(past['orders'], expected_orders)
    np.testing.assert_array_equal(past['trades'], expected_trades)
    for name in ('curve', 'source_curve', 'target_trace'):
        np.testing.assert_array_equal(past[name], full[name][:length], err_msg=name)
    expected_lineage = [row for row in full['raw_entry_diagnostics'] if row['fill_normal_row'] < length]
    assert past['raw_entry_diagnostics'] == expected_lineage
    entered = past['orders'][(past['orders'][:, 2] == parent) & (past['orders'][:, 7] == 1)]
    exited = past['orders'][(past['orders'][:, 2] == parent) & (past['orders'][:, 7] == 0)]
    assert len(entered) == 1 and len(exited) == 0
    assert np.sum(past['target_trace'][-1, :2]) > 0, '接頭端点を未来の場末へ返済しました'
    return dict(一致注文数=len(expected_orders), 一致完結親数=len(expected_trades), 一致lineage数=len(expected_lineage),
                一致時価原行数=length, 全時価2源及び6列保有一致=True,
                対象親未返済=True, 端点保有枚数=int(np.sum(past['target_trace'][-1, :2])), 未来場末清算=0)


def choose(terminal: dict) -> tuple[list[dict], dict]:
    """
    機能: 固定4条件の各商品先頭実親を、正式session順と実入口原行順で選ぶ。
    引数: terminal(dict)は完了した全32結果。
    返り値: tuple[list[dict],dict]。計画4件と参照台帳。利益/損失や都合の良い場で選び直さない。
    """
    selections, ledgers = [], {}
    for case_id, symbol in CASE_ORDER:
        spec = terminal['results'][case_id]
        case_path = ROOT / spec['path']
        assert digest(case_path) == spec['SHA256']
        case = read(case_path)
        active = {(row['session'], row['symbol']): row['campaigns'] > 0 for row in case['rows']}
        session = next((session for session in terminal['sessions'] if active[session, symbol]), None)
        assert session is not None, (case_id, symbol, '先頭実親がありません')
        ledger = case['ledgers'][session + '|' + symbol]
        payload = (ROOT / ledger['path']).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == ledger['SHA256']
        full = pickle.loads(gzip.decompress(payload))
        assert full['configured_quantity'] == 1 and full['pulse_id'] == case_id
        trade = min(full['trades'], key=lambda row: (int(row[2]), int(row[0])))
        parent, first_fill = int(trade[0]), int(trade[2])
        exits = full['orders'][(full['orders'][:, 2] == parent) & (full['orders'][:, 7] == 0)]
        assert len(exits) == 1
        decision, exit_fill = int(exits[0, 1]), int(exits[0, 0])
        assert exit_fill > first_fill
        lengths = [decision if decision >= first_fill + 1 else first_fill + 1]
        assert all(length <= exit_fill for length in lengths)
        selection = dict(手法=case_id, 商品=symbol, 場=session, 先頭親=parent, 初回実fill原行=first_fill,
            返済判断原行=decision, 返済fill原行=exit_fill, 接頭保持行数=lengths,
            出口直前境界成立=decision >= first_fill + 1, 結果位置=spec['path'], 結果SHA256=spec['SHA256'],
            台帳位置=ledger['path'], 台帳SHA256=ledger['SHA256'])
        selections.append(selection)
        ledgers[case_id, symbol] = full
    return selections, ledgers


def execute() -> None:
    """
    機能: 根が許可した正式4先頭親の金融接頭だけを一回確認する。
    引数: なし。CLIのroot許可引数を通して呼ぶ。
    返り値: None。正式全32再実行、反事実条件の新損益、原本/APIは実行しない。
    """
    assert not PROOF.exists() and not PLAN.exists()
    design = read(HERE / '仮説整合出口の金融未読固定.json')
    assert design['金融結果読取前'] and design['新金融結果参照'] == 0
    assert digest(ROOT / design['草案位置']) == design['草案SHA256']
    terminal_path = WAVE / '金融全32の結果.json'
    assert terminal_path.exists(), '根の全32終端がまだありません。再開始や観測pollはしません'
    terminal = read(terminal_path)
    assert terminal['全合格'] and terminal['条件数'] == 19 and terminal['開始終端source一致']
    for relative, wanted in terminal['source_SHA256'].items():
        assert digest(ROOT / relative) == wanted, relative
    selections, full_ledgers = choose(terminal)
    refs = [Path(__file__), HERE / 'finance_adapter.py', HERE / 'adapter.py', WAVE / 'research.py', WAVE / 'base.py',
            WAVE / 'activity/data.py', WAVE / 'activity/全32の状態可用性と発火.json',
            terminal_path, WAVE / '金融事前固定.json', HERE / '次の仮説整合出口の検討.json',
            HERE / '仮説整合出口の金融未読固定.json', ROOT / 'work/wave_v102/engine.py', ROOT / 'work/wave_v102/strategy.py']
    beginning = {path.relative_to(ROOT).as_posix(): digest(path) for path in refs}
    save(PLAN, dict(状態='正式結果参照あり・全再生の前ではなく指定接頭実行の前に固定', 対象=selections,
        選定='指定U_C1R1/C_VOLUME各商品、正式場順で活動する最初場の入口原行順先頭親。金額を使った選定なし。',
        設計未読固定SHA256=digest(HERE / '仮説整合出口の金融未読固定.json'), SHA256=beginning,
        全32再実行=0, 新counterfactual損益=0, 原本API取得=0))
    print(json.dumps(dict(固定先頭親=[{key: row[key] for key in ('手法', '商品', '場', '先頭親', '接頭保持行数')} for row in selections]), ensure_ascii=False), flush=True)
    base = adapter.module('103実金融接頭の一回開始素材', WAVE / 'base.py')
    material = base.load()
    strategy = adapter.module('103実金融接頭の一回旧準備', ROOT / 'work/wave_v102/strategy.py')
    prepared = strategy.prepare(material, adapter.reference_config())
    base.immutable(prepared)
    cache = adapter.module('103実金融接頭の活動cache', WAVE / 'activity/data.py')
    sessions = list(dict.fromkeys(row['場'] for row in selections))
    activities = {session: cache.load_session(session, verify=True) for session in sessions}
    finance = adapter.module('103実金融接頭の金融接口', HERE / 'finance_adapter.py')
    checks = []
    for selection in selections:
        case_id, symbol, session = selection['手法'], selection['商品'], selection['場']
        full = full_ledgers[case_id, symbol]
        account, value = activities[session]['accounts'][symbol], prepared[session, symbol]
        for length in selection['接頭保持行数']:
            past_account, past_value = account_prefix(account, case_id, length), prepared_prefix(value, length)
            output = finance.play(past_value, past_account, case_id, quantity=1, finish=False)
            checked = compare(full, output, length, selection['先頭親'])
            checked.update(手法=case_id, 商品=symbol, 場=session, 親=selection['先頭親'], 保持normal原行数=length,
                           保持raw原行数=len(past_account['source']['raw_seq']))
            checks.append(checked)
            print(json.dumps(dict(接頭合格=True, 手法=case_id, 商品=symbol, 場=session, 保持normal原行数=length, 未来場末清算=0), ensure_ascii=False), flush=True)
    ending = {path.relative_to(ROOT).as_posix(): digest(path) for path in refs}
    assert beginning == ending
    proof = dict(全合格=True, 金融参照あり=True, 対象先頭親数=4, 金融接頭再生数=len(checks), 対象=selections, 検査=checks,
        検査件数=dict(先頭実親=4, 金融接頭=len(checks), 全curve及び2源時価及び6列保有=len(checks), 当時lineage=len(checks), 未来場末清算なし=len(checks)),
        開始終端source一致=True, 開始SHA256=beginning, SHA256=ending, 計画SHA256=digest(PLAN),
        未読草案SHA256=design['草案SHA256'], base読取回数=1, 旧prepare回数=1,
        activity各対象場読取回数={session: 1 for session in sessions}, 正式全32再実行=0,
        新counterfactual損益=0, 原本読取=0, API取得=0, 実注文=0,
        限界='正式結果を参照した指定4先頭親だけの接頭検査。新入口の成果・未知データ性能の証明ではない。未返済親の将来net/cohort完結情報は接頭比較へ使わず、当時の全玉時価と過去物理注文を比較した。')
    save(PROOF, proof)
    print(json.dumps(dict(全合格=True, 先頭実親=4, 金融接頭=len(checks), 証跡SHA256=digest(PROOF)), ensure_ascii=False), flush=True)


def main() -> None:
    """
    機能: 根の正式終端確認後の許可された接頭検査だけを実行する。
    引数: CLI --root-four-financial-prefix-authorized(bool)。
    返り値: None。実行許可のない無引数では金融結果を開かない。
    """
    parser = argparse.ArgumentParser(description='全32再実行をしない指定4先頭親の金融接頭検査')
    parser.add_argument('--root-four-financial-prefix-authorized', action='store_true', required=True)
    parser.parse_args()
    execute()


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        folder = HERE / ('実金融接頭False_' + time.strftime('%Y%m%d_%H%M%S'))
        folder.mkdir(exist_ok=False)
        sources = {}
        for name in ('financial_prefix.py', 'finance_adapter.py', 'adapter.py'):
            content = (HERE / name).read_bytes()
            (folder / name).write_bytes(content)
            sources[name] = hashlib.sha256(content).hexdigest()
        if PLAN.exists():
            (folder / PLAN.name).write_bytes(PLAN.read_bytes())
        save(folder / 'False.json', dict(全合格=False, 金融参照あり=True, 例外=str(error), traceback=traceback.format_exc(),
            原sourceSHA256=sources, 正式全32再実行=0, 新counterfactual損益=0))
        raise
