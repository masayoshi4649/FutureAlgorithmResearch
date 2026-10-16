"""順行後の逆行保険について、極値・支持公開・次観測注文の因果順を検査する。"""

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[2]


def module(name, path):
    """
    機能: 他の作業を変更せず監査用名で読み込む。
    引数: name(str)、path(Path)。
    返り値: module。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def save(name, value):
    """
    機能: 今回の監査領域へ有限値の証拠を保存する。
    引数: name(str)、value(dict)。
    返り値: None。
    """
    path = (HERE / name).resolve()
    assert path.is_relative_to(HERE)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def hashes():
    """
    機能: 条件・売買・支持準備の変更を検知する。
    引数: なし。
    返り値: dict[str,str]。
    """
    return {name: hashlib.sha256((WORK / name).read_bytes()).hexdigest()
            for name in ('catalog.py', 'strategy.py', 'engine.py', 'build_engine.py', 'prepare.py')}


def load():
    """
    機能: 新戦略と条件を読み、監査先へキャッシュを向ける。
    引数: なし。
    返り値: tuple[module,dict,module]。
    """
    strategy = module('監査87逆行保険戦略', WORK / 'strategy.py')
    catalog = module('監査87逆行保険条件', WORK / 'catalog.py')
    prior = module('監査87逆行保険基本道具', WORK.parent / 'round7/audit/checks.py')
    import numba
    numba.config.CACHE_DIR = str(HERE / 'cache')
    os.environ['NUMBA_CACHE_DIR'] = str(HERE / 'cache')
    strategy.base.integration.reference.initialize()
    return strategy, {c['id']: c for c in catalog.catalog()}, prior


def run(strategy, ready, core, observed, prepare=.5, pullback=.5, confirm=0, own=None, peer=None,
        own_valid=None, peer_valid=None, own_release=None, peer_release=None):
    """
    機能: 人工支持配列と現在までの元注文だけで一度再生する。
    引数: strategy(module)、ready(dict)、core(ndarray)、observed(bool)、幅(float)、confirm(int)、支持配列(list|None)。
    返り値: tupleの保険結果。既定支持は元方向と反対である。
    """
    n = len(ready['last'])
    direction = core[0, 3]
    seq = np.arange(n, dtype=np.int64) * 10
    a = np.full(n, -direction * .1) if own is None else np.asarray(own, float) * direction
    b = np.full(n, -direction * .1) if peer is None else np.asarray(peer, float) * direction
    av = np.ones(n, bool) if own_valid is None else np.asarray(own_valid, bool)
    bv = np.ones(n, bool) if peer_valid is None else np.asarray(peer_valid, bool)
    ar = seq.copy() if own_release is None else np.asarray(own_release, np.int64)
    br = ready['time_s'] - 1 if peer_release is None else np.asarray(peer_release, float)
    frozen = core.copy()
    result = strategy.engine.simulate(ready['time_s'], ready['last'], core, ready['quiet'], ready['quiet'],
        ready['end'], 0., ready['tick'], -1, 0., .25, .5, .25, observed, prepare, pullback, confirm,
        seq, a, av, b, bv, ar, br)
    np.testing.assert_array_equal(core, frozen)
    assert all(0 <= o[1] < o[0] < n for o in result[0])
    for e in result[5]:
        row, cid, pending, gate, extreme, extreme_row, line = e
        assert pending < row and gate < row and extreme_row < row
        if confirm:
            i = int(gate)
            assert av[i] and bv[i] and ar[i] <= seq[i] and br[i] < ready['time_s'][i]
            assert -direction * a[i] > .05 and -direction * b[i] > .05
    return result


def synthetic(strategy, prior):
    """
    機能: 準備閾値・極値・支持の境界、遡及取消と指定線遡及約定を反証する。
    引数: strategy/prior(module)。
    返り値: None。人工経路の利益は実相場の優位とは扱わない。
    """
    before = hashes()
    checks = []
    for symbol in ('TOPIX', 'NK225'):
        for reflected in (False, True):
            for observed in (False, True):
                common = dict(symbol=symbol, reflected=reflected)
                for prepare in (0., .25, .5):
                    for pullback in (.25, .5):
                        peak = 100 + prepare * 4
                        level = peak - pullback * 4
                        prices = [100, 100, peak - .5 if prepare else 100, peak, level, level, level]
                        r, c = prior.material(prices, [(1, 1, 1, 100), (5, 0, 1, level)], **common)
                        out = run(strategy, r, c, observed, prepare, pullback)
                        assert out[0][0, 0] == 4
                        prepared = out[3][out[3][:, 2] == 8]
                        assert len(prepared) == 1 and prepared[0, 0] == (1 if prepare == 0 else 3)
                        checks.append(dict(検査='準備閾値ちょうど到達と逆行幅', 商品=symbol, 反射=reflected, 観測=observed, 準備=prepare, 逆行=pullback))
                # ----------------------------------------
                # 順行極値を更新した後は、その行までの高値からのみ戻りを判定する。
                r, c = prior.material([100, 100, 102, 104, 102, 102, 102], [(1, 1, 1, 100), (5, 0, 1, 102)], **common)
                out = run(strategy, r, c, observed)
                assert out[0][0, 0] == 4 and out[0][0, 1] == 3
                assert out[5][0, 5] == 3 and out[5][0, 4] == r['last'][3]
                checks.append(dict(検査='過去極値更新後の線だけを次観測へ公開', 商品=symbol, 反射=reflected, 観測=observed))
                # ----------------------------------------
                # 支持は厳密閾値・双方一致。古い反対値は新しい中立で失効する。
                r, c = prior.material([100, 100, 102, 101, 100, 99, 99], [(1, 1, 1, 100), (5, 0, 1, 99)], **common)
                for label, values in (
                    ('厳密0.05は不足', dict(own=[-.05] * 7)),
                    ('片方中立では不可', dict(peer=[0.] * 7)),
                    ('片方順方向では不可', dict(peer=[.1] * 7)),
                    ('無効支持では不可', dict(own_valid=[False] * 7)),
                    ('新しい中立が旧支持を消す', dict(own=[-.1, -.1, -.1, 0., 0., 0., 0.])),
                    ('相手同時計は未公開', dict(peer_release=r['time_s'].tolist())),
                    ('自己未来元行は未公開', dict(own_release=(np.arange(7) * 10 + 1).tolist()))):
                    out = run(strategy, r, c, observed, confirm=1, **values)
                    assert not len(out[0]), label
                    checks.append(dict(検査=label, 商品=symbol, 反射=reflected, 観測=observed))
                out = run(strategy, r, c, observed, confirm=1, peer_release=(r['time_s'] - 10000).tolist(), own_release=[0] * 7)
                assert out[0][0, 0] == 4
                checks.append(dict(検査='独自の秒鮮度上限を追加しない', 商品=symbol, 反射=reflected, 観測=observed))
                r, c = prior.material([100, 100, 102, 99, 98, 98, 98], [(1, 1, 1, 100), (5, 0, 1, 98)], **common)
                out = run(strategy, r, c, observed, confirm=1, own=[0., 0., 0., -.1, -.1, -.1, -.1])
                assert out[0][0, 0] == 4 and out[0][0, 5] == r['last'][4]
                checks.append(dict(検査='線通過後の初支持は指定でも次観測成行', 商品=symbol, 反射=reflected, 観測=observed))
                out = run(strategy, r, c, observed, confirm=1, own=[-.1, -.1, -.1, 0., 0., 0., 0.])
                assert out[0][0, 0] == 3 and out[5][0, 3] == 2
                checks.append(dict(検査='当行支持消失で前行注文を遡及取消しない', 商品=symbol, 反射=reflected, 観測=observed))
                r, c = prior.material([100, 100, 102, 101, 100, 99, 99, 99], [(1, 1, 1, 100), (6, 0, 1, 99)], **common)
                out = run(strategy, r, c, observed, confirm=1, own=[-.1, -.1, -.1, 0., -.1, -.1, -.1, -.1])
                assert out[0][0, 0] == 5 and out[0][0, 5] == r['last'][5]
                assert np.count_nonzero(out[0][:, 7]) == 1
                assert np.any((out[3][:, 2] == 5) & (out[3][:, 9] == 86))
                checks.append(dict(検査='支持取消は一回を消費せず再公開する', 商品=symbol, 反射=reflected, 観測=observed))
                # ----------------------------------------
                # 新規と元終了が同じ観測でも、保険返済は次の有効原本行。
                r, c = prior.material([100, 100, 102, 100, np.nan, 100, 100], [(1, 1, 1, 100), (3, 0, 1, 100)], **common)
                out = run(strategy, r, c, observed)
                assert out[0][:, 0].tolist() == [3, 5] and out[0][-1, 1] == 3 and out[0][-1, 6] == 83
                checks.append(dict(検査='元終了同観測の保険新規は次有効観測返済', 商品=symbol, 反射=reflected, 観測=observed))
                r, c = prior.material([100, 100, 102, 100, 100, 100], [(1, 1, 1, 100), (3, 0, 1, 100)], **common,
                                      times=[0, 1, 2, 3, 3, 4])
                out = run(strategy, r, c, observed)
                assert out[0][:, 0].tolist() == [3, 4]
                checks.append(dict(検査='同じ代理時計でも次原本行を区別', 商品=symbol, 反射=reflected, 観測=observed))
                r, c = prior.material([100, 100, 102, 100, 100, 100], [(1, 1, 1, 100), (4, 0, 1, 100)], **common,
                                      quiet=[False, False, False, True, True, False])
                out = run(strategy, r, c, observed)
                assert not len(out[0])
                checks.append(dict(検査='静観は待機保険を取消し発注しない', 商品=symbol, 反射=reflected, 観測=observed))
                r, c = prior.material([100, 100, 102, 100, 100, 100], [(1, 1, 1, 100), (4, 0, 1, 100)], **common, end=4.)
                out = run(strategy, r, c, observed)
                assert out[0][-1, 0] == 4 and out[0][-1, 6] == 85
                checks.append(dict(検査='保険自身の場末予定で清算', 商品=symbol, 反射=reflected, 観測=observed))
    assert before == hashes()
    save('逆行保険の準備支持と発動順序の人工境界.json', dict(全合格=True, 検査数=len(checks), 検査=checks, コードSHA256=before))


def main():
    """
    機能: 最終実装に対して人工境界検査を実行する。
    引数: なし。
    返り値: None。
    """
    strategy, configs, prior = load()
    synthetic(strategy, prior)


if __name__ == '__main__':
    main()
