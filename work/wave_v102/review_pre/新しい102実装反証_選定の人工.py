"""前16選定の独立検算器を私有人工だけで反証する。正式frontは読まない。"""

from copy import deepcopy
from datetime import date, timedelta
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile

import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
CODE = WORK / 'review/selection.py'


def digest(path: Path) -> str:
    """
    機能: 人工検査コードと独立選定器の指紋を計算する。
    引数: path (Path) は実在する保存コード。
    返り値: str はSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def module(path: Path) -> object:
    """
    機能: 正式mainを実行せず独立選定器の純関数だけを読込む。
    引数: path (Path) は選定器のコード。
    返り値: object は読込済みモジュール。台帳・正式入力の読取は行わない。
    """
    spec = importlib.util.spec_from_file_location('102選定の人工だけの読取', path)
    answer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(answer)
    return answer


def summary(selection: object, ident: str, sessions: list[str], quantity: int | None,
            active_count: int = 8, mixed_cohorts: bool = False) -> dict:
    """
    機能: 小QのRMS・親内相殺・活動不足を切り分ける私有候補会計を作成する。
    引数: selection (object)、ident (str)、sessions (list[str])、quantity (int | None)、active_count (int)、mixed_cohorts (bool)。
    返り値: dict は独立summary。市場予測又は合法な新規判断の成績とは呼ばない。
    """
    rows = []
    prices = {(session, symbol): 4000. if symbol == 'TOPIX' else 70000.
              for session in sessions for symbol in selection.SYMBOLS}
    config = dict(id=ident, trend_budget=8, range_budget=0, trend_initial_quantity=quantity,
                  trend_growth_mode=int(mixed_cohorts))
    for index, session in enumerate(sessions):
        for symbol in selection.SYMBOLS:
            actual_quantity = (8 if symbol == 'TOPIX' else 16) if quantity is None else quantity
            parent_quantity = actual_quantity * (2 if mixed_cohorts else 1)
            active = index < active_count
            signed = (100. if index < 6 else -30.) * actual_quantity
            parents = [(signed, signed, 0, parent_quantity)] * 3 if active else []
            groups = []
            for item in parents:
                if mixed_cohorts:
                    groups.extend([(item[1] + 200 * actual_quantity, item[1] + 200 * actual_quantity, 0, actual_quantity),
                                   (-200 * actual_quantity, -200 * actual_quantity, 0, actual_quantity)])
                else:
                    groups.append(item)
            row = dict(session=session, symbol=symbol, **selection.totals(parents),
                       cohorts=selection.totals(groups, cohort=True),
                       actual_peak_quantity=parent_quantity if active else 0)
            assert row['lots'] == row['cohorts']['lots']
            assert row['net'] == row['cohorts']['net']
            rows.append(row)
    return selection.summarize(config, rows, sessions, prices)


def ledger(selection: object, symbol: str, side: int) -> dict:
    """
    機能: 複数注文料と親黒字・後段建玉群赤字の相殺を持つ合法枚数の私有約定台帳を作る。
    引数: selection (object)、symbol (str)、side (int) は買い1又は売り-1。
    返り値: dict は注文17列・親16列・建玉群25列の人工台帳。新売買エンジンは実行しない。
    """
    columns = ['parent_id', 'cohort_id', 'source', 'side', 'quantity', 'decision_row', 'decision_seq',
               'decision_time', 'entry_row', 'entry_seq', 'entry_time', 'entry_price', 'entry_fee', 'order_uid',
               'exit_row', 'exit_seq', 'exit_time', 'exit_price', 'exit_fee_share', 'gross', 'net',
               'risk_budget', 'initial_quantity', 'entry_kind', 'parent_final_quantity']
    quantities = [1, 1, 2, 4]
    base, multiplier, factor = (4000., 1000., .5) if symbol == 'TOPIX' else (70000., 10., 10.)
    entry_prices = [base + side * factor * offset for offset in (1, 5, 13, 21)]
    exit_price = base + side * factor * 15
    entry_fees = [selection.fee(quantity, symbol) for quantity in quantities]
    close_fee = selection.fee(8, symbol)
    shares = [close_fee * quantity // 8 for quantity in quantities]
    priority = sorted(range(4), key=lambda i: (-(close_fee * quantities[i] % 8), i))
    for index in priority[:close_fee - sum(shares)]:
        shares[index] += 1
    orders = np.zeros((5, 17), dtype=float)
    groups = np.zeros((4, 25), dtype=float)
    for index, (quantity, price) in enumerate(zip(quantities, entry_prices)):
        row, uid = index * 2 + 2, index + 10
        orders[index, :10] = [row, row - 1, 1, 0, side, quantity, price, 1, 0, entry_fees[index]]
        orders[index, 16] = uid
        gross = side * quantity * (exit_price - price) * multiplier
        groups[index] = [1, index, 0, side, quantity, row - 1, row - 1 + 100, row - 1., row, row + 100,
                         row * 1., price, entry_fees[index], uid, 10, 110, 10., exit_price, shares[index],
                         gross, gross - entry_fees[index] - shares[index], 0, 1, int(index > 0), 8]
    orders[-1, :10] = [10, 9, 1, 0, -side, 8, exit_price, 0, 1, close_fee]
    orders[-1, 16] = 20
    gross = sum(row[19] for row in groups)
    trade = np.array([[1, 0, 2, 10, side, 8, sum(q * p for q, p in zip(quantities, entry_prices)) / 8,
                       exit_price, sum(entry_fees), close_fee, gross,
                       gross - sum(entry_fees) - close_fee, 0, 1, 0, 1]], dtype=float)
    return dict(orders=orders, trades=trade, growth_cohorts=groups, growth_cohort_columns=columns)


def main() -> None:
    """
    機能: 3候補の選定集合・小Q比較・実累計料・不正back段階・未許可mainを人工で反証する。
    引数: なし。
    返り値: None。新しい人工証跡を保存する。正式前16/後15の金融結果は読まない。
    """
    before = digest(CODE)
    selection = module(CODE)
    sessions = [str(date(2026, 9, 21) + timedelta(days=index)) + '_Day' for index in range(16)]
    small = summary(selection, 'Z_SMALL_Q', sessions, 1)
    full = summary(selection, 'FULL_Q', sessions, None)
    masked = summary(selection, 'A_PARENT80_ONLY', sessions, 1, mixed_cohorts=True)
    insufficient = summary(selection, 'B_INSUFFICIENT_ACTIVITY', sessions, 1, active_count=7)
    chosen = selection.choose([masked, insufficient, small])
    assert chosen['selected'] == 'Z_SMALL_Q' and chosen['level'] == 0
    assert chosen['eligible'] == ['Z_SMALL_Q']
    for symbol in selection.SYMBOLS:
        stable_small, stable_full = small['stability'][symbol], full['stability'][symbol]
        assert stable_small['positive_session_rate'] == stable_full['positive_session_rate'] == .75
        scale = 8 if symbol == 'TOPIX' else 16
        assert stable_full['downside_rms_units'] == scale * stable_small['downside_rms_units']
        assert stable_small['session_count'] == 16 and stable_small['active_sessions'] == 8
        assert small['periods'][symbol]['profit_share'] > .8
        assert masked['periods'][symbol]['profit_share'] > .8
        assert masked['periods'][symbol]['cohorts']['profit_share'] < .8
        assert masked['periods'][symbol]['cohorts']['payoff'] > 1
        assert insufficient['periods'][symbol]['campaigns'] == 21
        assert insufficient['periods'][symbol]['active_sessions'] == 7
        # ----------------------------------------
        # 集合内の最終割合順位は親/建玉群の悪い側。親だけを見る誤接続を拒否する。
        assert selection.ranking(masked)[4] > selection.ranking(small)[4]
    assert selection.choose([masked])['level'] == 1
    assert selection.choose([insufficient])['level'] == 5
    # ----------------------------------------
    # 料金は新規4注文の累計。TOPIXでは最終8枚を一注文とした料334円とは異なる332円。
    account_cases = []
    for symbol in selection.SYMBOLS:
        for side in (-1, 1):
            stored = ledger(selection, symbol, side)
            account = selection.account(stored, symbol)
            assert account['campaigns'] == 1 and account['cohorts']['cohorts'] == 4
            assert account['profit'] > 0 and account['cohorts']['loss'] > 0
            assert account['lots'] == account['cohorts']['lots'] == 8
            if symbol == 'TOPIX':
                assert stored['trades'][0, 8] == 332 != selection.fee(8, symbol)
                wrong = deepcopy(stored)
                wrong['trades'][0, 8] = selection.fee(8, symbol)
                try:
                    selection.account(wrong, symbol)
                    raise RuntimeError('累計建料の誤置換を拒否できません')
                except AssertionError:
                    pass
            account_cases.append(dict(商品=symbol, 方向=side, 親利益=account['profit'],
                                      建玉群利益=account['cohorts']['profit'], 建玉群損失=account['cohorts']['loss'],
                                      累計新規料=float(stored['trades'][0, 8])))
    # ----------------------------------------
    # 実workを変更せず一時人工stageだけで後15の存在を拒否させる。
    guard_cases = []
    with tempfile.TemporaryDirectory(prefix='102独立選定人工_') as directory:
        base = Path(directory)
        fixed = dict(条件=[dict(id='ARTIFICIAL_%02d' % index) for index in range(20)], 前16=sessions)
        for kind, suffix in (('results', '.json'), ('ledgers', '.pkl')):
            target = base / 'front' / kind
            target.mkdir(parents=True)
            for config in fixed['条件']:
                (target / (config['id'] + suffix)).write_bytes('人工:内容はguardで読みません'.encode('utf-8'))
        (base / '前16参考代表.json').write_text('{}', encoding='utf-8')
        selection.guard(base, fixed)
        guard_cases.append('全20前16・根select・back未作成だけ通過')
        for suffix in ('.json', '.pkl'):
            invalid = base / 'back' / ('不正後15' + suffix)
            invalid.parent.mkdir(exist_ok=True)
            invalid.write_bytes('後15:内容は拒否時にも読みません'.encode('utf-8'))
            try:
                selection.guard(base, fixed)
                raise RuntimeError('後15段階を拒否できません')
            except AssertionError:
                guard_cases.append('後15' + suffix + '存在を内容読取前に拒否')
            invalid.unlink()
    refusal = subprocess.run([sys.executable, '-X', 'utf8', '-B', str(CODE)],
                             capture_output=True, text=True, encoding='utf-8')
    assert refusal.returncode != 0 and '前16/select完了の明示通知前は金融結果を読みません' in refusal.stderr
    assert before == digest(CODE)
    proof = dict(全合格=True, 種類='102前16選定独立検算器の正式損益前人工反証',
                 人工候補数=3, 人工代表=chosen['selected'], 集合段階=chosen['level'], 候補集合=chosen['eligible'],
                 小Q比較='同じ活動8/16・黒字6/8。Q1のRMSは旧全量TOPIX8/日経16の1/8又は1/16だが確度改善とは認定しない。',
                 親相殺だけ80の候補='親80以上/建玉群80未満はtarget集合から除外。損小利大等を満たせば下位robust集合。',
                 不足活動='21親でも活動7場の候補は活動集合から除外。',
                 人工約定会計=account_cases, 段階guard=guard_cases,
                 未許可CLI拒否=True, 根score及びselect呼出=0,
                 scope='純選定3候補/数量比較1対照/私有約定4会計/人工stage3境界。新売買エンジンは実行しない。',
                 正式前16損益閲覧=0, 正式後15損益閲覧=0, 新売買実行=0, API取得=0, 実注文=0,
                 SHA256={str(CODE.relative_to(ROOT)): digest(CODE),
                         str(Path(__file__).relative_to(ROOT)): digest(Path(__file__))})
    path = HERE / '新しい102実装反証_選定の人工.json'
    path.write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print('102独立選定器の3候補・小Q・累計料・建玉群80及び前後段階の人工反証が合格。正式損益0。', flush=True)


if __name__ == '__main__':
    main()
