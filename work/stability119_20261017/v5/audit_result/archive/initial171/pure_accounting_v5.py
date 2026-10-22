"""保存会計監査を公開APIの小人工へ接続し、市場前に監査式自体を点検する。"""

import hashlib
import json
import os
from pathlib import Path
import sys

import numpy as np


HERE = Path(__file__).resolve().parent
V5 = HERE.parent
os.environ['NUMBA_CACHE_DIR'] = str(HERE / 'private_numba_cache')
sys.dont_write_bytecode = True
sys.path.insert(0, str(V5))
sys.path.insert(0, str(HERE))
import engine_v5 as engine
import audit_result_v5 as subject


def quote(times: list[float], prices: list[float], spread: float) -> dict:
    """
    機能: 会計人工に用いる正常気配を作る。
    引数: times/prices(list[float])、spread(float) は手作り時計と価格。
    返り値: dict は原rowと気配。市場入力を読まない。
    """
    p = np.asarray(prices, float)
    return dict(row=np.arange(len(p), dtype=np.int64) + 1, time=np.asarray(times, float), last=p,
                bid=p - spread / 2., ask=p + spread / 2., bq=np.ones(len(p)), aq=np.ones(len(p)))


def main() -> None:
    """
    機能: 完結・無参加の人工結果を独立な保存会計へ接続する。
    引数: なし。
    返り値: None。市場及び保存結果/cache読取は0、監査源を指紋で拘束する。
    """
    times = np.arange(65, dtype=float) * 60.
    top_close = 1000. * np.exp(np.arange(65) * .0001)
    nk_close = 100. * top_close * np.exp(.0002 * np.sin(np.arange(65) * .71))
    nk = dict(t_s=times, valid=np.ones(65, bool), close=nk_close, pub_price_time_s=times + 60.)
    top = dict(t_s=times, valid=np.ones(65, bool), close=top_close, pub_price_time_s=times + 60.)
    for initial in (101000., 100000.):
        nq = quote([1800., 1801., 1810., 1811., 1870.], [initial, initial, 99990., 99990., 99990.], 2.)
        tq = quote([1800., 1802., 1812., 1870.], [1000.] * 4, .02)
        answer = engine.run_pair(nk, top, nq, tq, dict(method='ratio_mr', lookback=30, entry_end=1900., close_time=2000.))
        saved = dict(answer['summary'], legs=answer['leg_summary'])
        subject.independent_pair(answer, (nq, tq), saved, 2000.)
    subject.write(HERE / '保存会計監査源の公開API人工接続.json', dict(全合格=True, 検査数=subject.audit.CHECKS,
        監査源SHA256=hashlib.sha256(Path(subject.__file__).read_bytes()).hexdigest(),
        人工源SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 市場読取=0, 結果読取=0, cache読取=0,
        留保='監査源だけの人工接続。源人工の再利用は新しい有効性標本ではない。'))
    print(json.dumps(dict(全合格=True, 検査数=subject.audit.CHECKS), ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except BaseException as exc:
        subject.write(HERE / 'pure_False.json', dict(全合格=False, 検査数=subject.audit.CHECKS, 型=type(exc).__name__, 例外=str(exc)))
        raise
