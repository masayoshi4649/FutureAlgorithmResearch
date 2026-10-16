"""保有時間・利益目標を使わない方向追従を、人工経路と独立期待値で検査する。"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

import numpy as np


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
sys.dont_write_bytecode = True
os.environ['NUMBA_CACHE_DIR'] = str(HERE / 'numba_cache')
spec = importlib.util.spec_from_file_location('wave81_engine_audit', WORK / 'engine.py')
engine = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = engine
spec.loader.exec_module(engine)


def arguments(times, bids, asks=None, own=None, peer=None, **options) -> list:
    """機能: 各原板行に現在の方向状態を与えた人工入力を作る。

    引数: times/bids/asks/own/peer(list|None)、options(dict)。返り値: 引数列(list)。
    方向指標の作り方を分離し、注文の状態遷移のみを検査する。
    """
    times = np.asarray(times, dtype=float)
    bids = np.asarray(bids, dtype=float)
    asks = bids + 1. if asks is None else np.asarray(asks, dtype=float)
    n = len(times)
    own = np.ones(n, dtype=np.int8) if own is None else np.asarray(own, dtype=np.int8)
    peer = own.copy() if peer is None else np.asarray(peer, dtype=np.int8)
    keys = dict(tick=1., start=0., limit=20000., quantity=10, value=1000., fee_unit=41.8,
                latency=5., entry_mode=0, exit_mode=0, solo=0, repair=0)
    keys.update(options)
    return [times, bids, asks, np.ones(n, dtype=bool), np.zeros(n, dtype=bool),
            np.arange(n), times.copy(), own, np.arange(n), np.maximum(np.arange(n)-1, 0),
            bids.copy(), asks.copy(), *[keys[k] for k in ('tick', 'start', 'limit', 'quantity',
            'value', 'fee_unit', 'latency', 'entry_mode')], *([0] * 6), peer,
            np.ones(n, dtype=bool), np.ones(n, dtype=bool),
            *[keys[k] for k in ('exit_mode', 'solo', 'repair')]]


def run(args: list) -> tuple:
    """機能: 人工入力をPython版の方向追従へ渡す。

    引数: args(list)。返り値: 注文・決済・時価・統計・イベント(tuple)。
    """
    return engine.simulate.py_func(*(args + [args[7], args[26], args[27], args[28]] if len(args) == 32 else args))


def clone(args: list) -> list:
    """機能: 原入力を改変しない複製を作る。

    引数: args(list)。返り値: 配列を複製した引数列(list)。
    """
    return [x.copy() if isinstance(x, np.ndarray) else x for x in args]


def near(left, right, label: str) -> None:
    """機能: 独立期待値と計算値を比較する。

    引数: left/right(数値又は配列)、label(str)。返り値: なし(None)。
    """
    np.testing.assert_allclose(left, right, rtol=0, atol=1e-7, err_msg=label)


def same(left: tuple, right: tuple) -> None:
    """機能: 全出力配列が同一であることを確認する。

    引数: left/right(tuple)。返り値: なし(None)。
    """
    for a, b in zip(left, right):
        np.testing.assert_array_equal(a, b)


def main() -> None:
    """機能: 方向・欠測・待機・場内清算・未来不変の人工監査を行う。

    引数: なし。返り値: なし(None)。検査結果をJSONへ保存する。
    """
    checks = []
    paths = []
    prefix_count = 0

    def check(name, action):
        """機能: 検査一件を実行し、失敗も結果として記録する。

        引数: name(str)、action(callable)。返り値: なし(None)。
        """
        try:
            action()
            checks.append(dict(検査=name, 合格=True))
        except Exception as exc:
            checks.append(dict(検査=name, 合格=False, 詳細=str(exc), 型=type(exc).__name__))

    # ----------------------------------------
    # 出口定義を別の論理式で全組合せ照合する。
    matrix_count = 0
    for side in (-1, 1):
        for own in (-1, 0, 1):
            for peer in (-1, 0, 1):
                for vo in (False, True):
                    for vp in (False, True):
                        for mode in (0, 1, 2):
                            for solo in (0, 1):
                                if solo:
                                    expected = 6 if vo and own != side else 0
                                else:
                                    conditions = [vo and vp and not (own == peer == side),
                                                  (vo and own + side == 0) or (vp and peer + side == 0),
                                                  vo and vp and own == peer == -side]
                                    expected = (6 + mode) if conditions[mode] else 0
                                actual = engine.should_exit.py_func(side, own, peer, vo, vp, mode, solo)
                                assert expected == actual, (side, own, peer, vo, vp, mode, solo)
                                matrix_count += 1
    checks.append(dict(検査='出口の方向・有効性・単独条件全組合せ', 合格=True, 組合せ=matrix_count))

    # ----------------------------------------
    # 方向だけを変えて、新規・返済それぞれの遅延と残玉を確認する。
    base = arguments([0, 4, 5, 6, 10, 11, 16], [100, 102, 101, 105, 90, 99, 98],
                     own=[1, 1, 1, 0, 0, 0, 0], peer=[1] * 7)
    paths.append(base)
    baseline = run(base)

    def market():
        """機能: 準備済み方向が開始時刻に直ちに発注され、返済も5秒待つことを確認する。

        引数: なし。返り値: なし(None)。
        """
        near(baseline[0][:, [0, 1, 3, 5, 10, 11, 12]],
             [[2, 0, 1, 102, 0, 5, 5], [5, 3, -1, 99, 6, 11, 11]], '双方5秒')
        near(baseline[1][:, 10], [-30836.], '料金込み決済')
        near(baseline[2][4], -120836., '返済待機中の損失')
        assert list(baseline[3][:3]) == [0, 0, 0]
    check('開始後60秒待機なし・新規返済双方5秒・待機中評価損失', market)

    def mirror():
        """機能: 買いと売りを鏡映した際の対称損益を確認する。

        引数: なし。返り値: なし(None)。
        """
        args = clone(base)
        args[1], args[2] = 300 - base[2], 300 - base[1]
        args[7] *= -1
        args[26] *= -1
        out = run(args)
        near(out[1][:, 10], baseline[1][:, 10], '鏡映決済')
        near(out[2], baseline[2], '鏡映全時価')
    check('ロングとショートの対称性', mirror)

    for movement in (-50, 50):
        args = arguments([0, 5, 1800, 3600, 7200, 14400, 14940, 14945],
                         [100, 100, 100+movement, 100, 100+movement, 100, 100, 100], limit=15000.)
        paths.append(args)

        def long_hold(a=args):
            """機能: 方向が同じなら大きな利益損失と4時間経過でも維持する。

            引数: a(list)。返り値: なし(None)。
            """
            out = run(a)
            near(out[0][:, [0, 6]], [[1, 10], [7, 4]], '場内清算以外で降りない')
            assert out[1][0, 2] == 7 and out[1][0, 1] == 1
        check(f'方向不変なら4時間保持・価格変化{movement:+d}でも固定目標なし', long_hold)

    def unused():
        """機能: 旧目標・停止・保有期限・休止の引数が判断に使われないことを確認する。

        引数: なし。返り値: なし(None)。
        """
        args = clone(base)
        args[20:26] = [0.01, 0.01, 0.01, 1, 100000., 1]
        same(run(args), baseline)
    check('旧固定目標・保有期限・休止の残存なし', unused)

    def reversed_pending():
        """機能: 発注後の反転で新規注文を消さず、約定行で返済を発注する。

        引数: なし。返り値: なし(None)。
        """
        args = arguments([0, 4, 5, 9, 10, 15, 20, 25], [100] * 8,
                         own=[1, -1, -1, -1, -1, -1, 0, 0])
        paths.append(args)
        out = run(args)
        near(out[0][:, [0, 1, 3, 10, 11]],
             [[2, 0, 1, 0, 5], [4, 2, -1, 5, 10], [5, 4, -1, 10, 15], [7, 6, 1, 20, 25]], '待機中反転')
        assert out[4][np.where(out[4][:, 2] == 24)[0][0], 0] == 2
    check('発注済み成行不取消・約定直後の反転返済・現在支持で再入口', reversed_pending)

    def vanished_pending():
        """機能: 中立化した新規待機注文が約定後に返済されることを確認する。

        引数: なし。返り値: なし(None)。
        """
        out = run(arguments([0, 5, 10], [100] * 3, own=[1, 0, 0]))
        near(out[0][:, [0, 1]], [[1, 0], [2, 1]], '消失後の約定と返済')
        assert out[3][0] == 0 and len(out[1]) == 1
    check('新規待機中の支持消失も発注済み成行を消さない', vanished_pending)

    def exit_stays():
        """機能: 返済を送った後に支持が戻っても注文を取消さないことを確認する。

        引数: なし。返り値: なし(None)。
        """
        args = arguments([0, 5, 6, 8, 11], [100] * 5, own=[1, 1, 0, 1, 0])
        out = run(args)
        near(out[0][:, [0, 1]], [[1, 0], [4, 2]], '支持回復後も返済')
    check('返済待機中の支持回復による返済取消なし', exit_stays)

    def latest_reentry():
        """機能: 返済約定時に消えた反対方向へ、古い反転サインで新規しない。

        引数: なし。返り値: なし(None)。
        """
        out = run(arguments([0, 5, 6, 11, 16], [100] * 5, own=[1, 1, -1, 0, 0]))
        assert len(out[0]) == 2 and sum(out[4][:, 2] == 20) == 1
    check('再入口は返済判断時でなく約定後の最新方向で判定', latest_reentry)

    def zero_clock():
        """機能: 遅延0でも発注判断の次原本行でしか約定できないことを確認する。

        引数: なし。返り値: なし(None)。
        """
        out = run(arguments([0, 0, 0, 0], [100] * 4, own=[1, 0, 0, 0], latency=0.))
        near(out[0][:, [0, 1]], [[1, 0], [2, 1]], '同時計順序')
    check('0秒でも同時計の後続原本行で約定', zero_clock)

    def incomplete():
        """機能: 返済待機終端を決済済みとして扱わないことを確認する。

        引数: なし。返り値: なし(None)。
        """
        out = run(arguments([0, 5, 6, 9], [100, 100, 90, 80], own=[1, 1, 0, 0]))
        assert len(out[0]) == 1 and len(out[1]) == 0 and list(out[3][:3]) == [1, 0, 1]
        near(out[2][-1], -210836., '未決済全損失')
    check('未返済残玉・返済待機を明示', incomplete)

    # ----------------------------------------
    # 欠測は中立と区別し、片方反対出口だけは有効側のみでも作動する。
    for mode in (0, 1, 2):
        args = arguments([0, 5, 6, 11, 20], [100] * 5, own=[1, 1, -1, -1, -1],
                         peer=[1, 1, 0, 0, 0], exit_mode=mode)
        args[28][2:] = False
        paths.append(args)

        def missing(a=args, m=mode):
            """機能: 相手欠測が出口の中立と誤認されないことを確認する。

            引数: a(list)、m(int)。返り値: なし(None)。
            """
            out = run(a)
            assert len(out[1]) == (1 if m == 1 else 0)
            assert out[3][0] == (0 if m == 1 else 1)
        check(f'相手無効と自己反対に対する出口X{mode}', missing)

    def invalid_no_entry():
        """機能: 片方の無効方向がある場合に共同入口を許さない。

        引数: なし。返り値: なし(None)。
        """
        args = arguments([0, 5, 10], [100] * 3)
        args[28][:] = False
        assert len(run(args)[4]) == 0
        args[30] = 1
        assert len(run(args)[0]) == 1
    check('無効相手では共同入口不可・単独対照のみ許可', invalid_no_entry)

    # ----------------------------------------
    # 到達上限は待機指値ではなく、その到達での許容判定と再発注である。
    def cap_retry():
        """機能: 上限超過で未約定となり、現在支持があれば別の注文を再発注する。

        引数: なし。返り値: なし(None)。
        """
        args = arguments([0, 5, 10, 11, 16], [100, 103, 103, 103, 103],
                         own=[1, 1, 1, 0, 0], entry_mode=1)
        paths.append(args)
        out = run(args)
        assert out[3][6] == 1 and sum(out[4][:, 2] == 20) == 2
        near(out[0][:, [0, 1, 5]], [[2, 1, 104], [4, 3, 103]], '取消後の現在価格で別注文')
    check('到達価格上限不成立・同原板行で再発注・旧上限へ後戻りなし', cap_retry)

    def cap_no_retry():
        """機能: 到達時に根拠が消えていた上限注文を再発注しない。

        引数: なし。返り値: なし(None)。
        """
        out = run(arguments([0, 5, 10], [100, 103, 100], own=[1, 0, 0], entry_mode=1))
        assert len(out[0]) == 0 and out[3][6] == 1 and sum(out[4][:, 2] == 20) == 1
    check('価格上限不成立後の根拠消失なら再発注なし', cap_no_retry)

    # ----------------------------------------
    # 入口と出口を別の因果状態で判定する改修用の配列を分離確認する。
    def separate_exit():
        """機能: 入口方向を保ったまま、別の出口方向の消失だけで返済する。

        引数: なし。返り値: なし(None)。
        """
        args = arguments([0, 5, 6, 11, 16], [100] * 5)
        args += [np.array([1, 1, 0, 0, 0], dtype=np.int8), args[26].copy(), args[27].copy(), args[28].copy()]
        out = run(args)
        near(out[0][:2, [0, 1, 6]], [[1, 0, 10], [3, 2, 6]], '出口専用配列')
        assert out[3][0] == 1 and out[3][2] == 1
        assert sum(out[4][:, 2] == 20) == 2
        args[31] = 1
        protected = run(args)
        assert len(protected[0]) == 2 and sum(protected[4][:, 2] == 20) == 1
    check('入口と出口の別状態・再準備待ちによる同方向即再入口抑止', separate_exit)

    def event_rearm():
        """機能: 再準備待ちは秒数でなく、有効な方向の消失・再成立で解除される。

        引数: なし。返り値: なし(None)。
        """
        args = arguments([0, 5, 6, 11, 12, 13, 18], [100] * 7,
                         own=[1, 1, 1, 1, 0, 1, 1], repair=1)
        args += [np.array([1, 1, 0, 0, 0, 1, 1], dtype=np.int8), args[26].copy(), args[27].copy(), args[28].copy()]
        out = run(args)
        near(out[0][:, [0, 1]], [[1, 0], [3, 2], [6, 5]], '有効中立の後の再成立')
        args[27][4] = False
        args[28][4] = False
        missing = run(args)
        assert len(missing[0]) == 2 and sum(missing[4][:, 2] == 20) == 1
    check('再準備は有効方向変化のみ・欠測は解除しない', event_rearm)

    # ----------------------------------------
    # セッション終了だけは観測時刻と独立した時計を使う。
    def close_gap():
        """機能: 場内清算予定時刻を過ぎた初有効行で、論理時刻到達済み返済を約定する。

        引数: なし。返り値: なし(None)。
        """
        args = arguments([0, 5, 100, 250], [100] * 4, limit=300.)
        paths.append(args)
        out = run(args)
        near(out[0][-1, [0, 1, 6, 10, 11, 12]], [3, 2, 4, 240, 245, 250], '場内清算論理時計')
    check('観測空白でも場内清算タイマー発火', close_gap)

    def late_entry():
        """機能: 清算時刻後に初めて新規約定した行で、直ちに返済待機を残す。

        引数: なし。返り値: なし(None)。
        """
        out = run(arguments([170, 250], [100, 100], limit=300.))
        assert list(out[3][:3]) == [1, 0, 1], out[3].tolist()
        event = out[4][out[4][:, 2] == 24]
        near(event[:, [0, 3, 6, 7]], [[1, 250, 255, 4]], '新規約定後の清算予定')
    check('清算時刻後に新規約定した同じ行で返済判断', late_entry)

    def no_open_near_close():
        """機能: 清算準備区間に新規発注が増えないことを確認する。

        引数: なし。返り値: なし(None)。
        """
        out = run(arguments([180, 200, 240, 245], [100] * 4, limit=300.))
        assert len(out[4]) == 0
    check('終了120秒前以後の新規禁止', no_open_near_close)

    # ----------------------------------------
    # 全原板のprefixと、未来の方向・価格改変による不変を確認する。
    for number, args in enumerate(paths):
        out = run(args)
        for cut in range(1, len(args[0])):
            shortened = clone(args)
            for k, value in enumerate(shortened):
                if isinstance(value, np.ndarray):
                    shortened[k] = value[:cut].copy()
            short = run(shortened)
            orders = out[0][out[0][:, 0] < cut]
            trades = out[1][out[1][:, 2] < cut]
            events = out[4][(out[4][:, 0] < cut) & (out[4][:, 3] <= args[0][cut-1])]

            def prefix(s=short, o=orders, t=trades, e=events, c=cut, full=out):
                """機能: 原本途中切断以前に出た約定・時価・イベントを照合する。

                引数: s/full(tuple)、o/t/e(ndarray)、c(int)。返り値: なし(None)。
                """
                near(s[0], o, 'prefix注文')
                near(s[1], t, 'prefix決済')
                near(s[2], full[2][:c], 'prefix時価')
                near(s[4], e, 'prefixイベント')
            check(f'人工経路{number}の途中切断{cut}', prefix)
            prefix_count += 1

    def compiled():
        """機能: Python版とnumba版の全配列が一致することを確認する。

        引数: なし。返り値: なし(None)。
        """
        same(engine.simulate(*(base + [base[7], base[26], base[27], base[28]])), baseline)
    check('numba版とPython版の全配列一致', compiled)

    result = dict(用途='実損益を見る前の方向出口・注文状態監査',
                  engine_sha256=hashlib.sha256((WORK/'engine.py').read_bytes()).hexdigest(),
                  出口組合せ=matrix_count, 途中切断=prefix_count, 検査数=len(checks),
                  合格数=sum(x['合格'] for x in checks), 不合格数=sum(not x['合格'] for x in checks), 検査=checks)
    (HERE/'人工方向追従監査.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k != '検査'}, ensure_ascii=False))
    for item in checks:
        if not item['合格']:
            print(json.dumps(item, ensure_ascii=False))
    assert result['不合格数'] == 0


if __name__ == '__main__':
    main()
