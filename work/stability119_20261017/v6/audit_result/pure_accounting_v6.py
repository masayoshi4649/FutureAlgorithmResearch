"""新十四口座監査のUID/部分返済/別丸めと未清算拒否を小人工で確認する。"""

import hashlib
import importlib.util
from pathlib import Path

import numpy as np

import audit_result_v6 as subject


HERE = Path(__file__).resolve().parent
V6 = HERE.parent


def main() -> None:
    """
    機能: 五枚二UIDの部分/全返済を独立会計と手計算へ照合する。
    引数: なし。実市場・実結果・cacheは読まない。
    返り値: None。監査算術だけの人工証跡を新規保存する。
    """
    path = V6 / 'engine/daily.py'
    spec = importlib.util.spec_from_file_location('private_v6_pure_accounting_reference', path)
    daily = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(daily)
    for symbol in ('TOPIX', 'NK225'):
        for side in (1, -1):
            quotes = dict(seq=np.arange(7, dtype=np.int64), time_s=np.asarray([0., 1., 1., 2., 3., 4., 5.]),
                          bid=np.full(7, 99.5), ask=np.full(7, 100.5), quote_valid=np.ones(7, bool))
            quotes['quote_valid'][4] = False
            quotes['bid'][4] = quotes['ask'][4] = 0.
            entry, close = (100.5, 99.5) if side == 1 else (99.5, 100.5)
            orders = np.asarray([[1., 0., 1., side, 2., entry, 0., 1.],
                                 [2., 1., 1., side, 3., entry, 0., 1.],
                                 [3., 2., 1., -side, 4., close, 1., 0.],
                                 [5., 4., 1., -side, 1., close, 1., 0.]])
            uids, targets = np.asarray([10, 11, -1, -1], np.int64), np.asarray([-1, -1, -1, 11], np.int64)
            ledger = daily.reconstruct(('人工', symbol), orders, uids, quotes, targets)
            account = dict(symbol=symbol, record=dict(price=np.full(7, 100.), seq=quotes['seq'], time_s=quotes['time_s']), quotes=quotes)
            summary = subject.reconstruct(account, ledger)
            expected = -5416. if symbol == 'TOPIX' else -160.
            subject.audit.near(summary['収支'], expected, '二UID部分全返済の手計算')
            subject.audit.near(ledger['reserved_exit_fees'][2], 208. if symbol == 'TOPIX' else 55., '二UID残料は合算後丸めと区別')
            subject.audit.near(ledger['reserved_exit_fees'][3], 41. if symbol == 'TOPIX' else 11., '部分返済後の残UID料')
            incomplete = daily.reconstruct(('人工', symbol), orders[:2], uids[:2], quotes, targets[:2], finish=False)
            rejected = False
            try:
                subject.reconstruct(account, incomplete)
            except AssertionError:
                rejected = True
            subject.audit.check(rejected, '未清算の新口座を完結成功にしない')
    subject.write(HERE / '二UID部分返済と注文別料及び全原行時価の監査源純人工.json', dict(全合格=True,
        検査数=subject.audit.CHECKS, 監査源SHA256=hashlib.sha256(Path(subject.__file__).read_bytes()).hexdigest(),
        人工源SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 市場読取=0, 結果読取=0, cache読取=0,
        留保='監査算術の小人工。旧又は新セッションの金融効果を測定しない。'))
    print(subject.audit.CHECKS)


if __name__ == '__main__':
    try:
        main()
    except BaseException as exc:
        subject.write(HERE / 'pure_False.json', dict(全合格=False, 検査数=subject.audit.CHECKS, 型=type(exc).__name__, 例外=str(exc)))
        raise
