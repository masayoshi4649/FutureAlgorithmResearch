"""原板活動の因果計算と全42保存素材の接続を独立に検査する。"""

from copy import deepcopy
from datetime import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import pickle
import sys
import time

import numpy as np


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
sys.path.insert(0, str(WORK))


def read(path):
    """
    機能: 保存JSONを読む。
    引数: path(Path)は対象。
    返り値: dict又はlist。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha(path):
    """
    機能: 入力や出典の内容指紋を求める。
    引数: path(Path)は対象。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture(times=None):
    """
    機能: 正出来高の買い代理が明瞭な架空原行を作る。
    引数: times(ndarray|None)は架空時計。
    返り値: listは時計・現在値・出来高・両気配・原連番・正常旗。
    """
    times = np.arange(101, dtype=float) if times is None else np.array(times, float)
    n = len(times)
    bid = 100.+np.arange(n)*.125
    ask = bid+1.
    return [times, ask.copy(), 100.+np.arange(n, dtype=float), bid, ask,
            np.arange(n, dtype=np.int64), np.ones(n, bool)]


def scalar(args, i):
    """
    機能: 当該行までだけを走査し、累計配列を使わず一窓の活動を計算する。
    引数: args(list)は入力、i(int)は判断原行。
    返り値: tupleは活動4列・始端番号・内訳5列。
    """
    times, last, volume, bid, ask, seq, quote_valid = args
    eligible = [j for j in range(i) if times[j] < times[i]-30.]
    a = eligible[-1] if eligible else -1
    output = np.array([np.nan, np.nan, np.nan, 0.])
    detail = np.full(5, np.nan)
    if a < 0:
        return output, a, detail

    def known(j):
        """
        機能: 一行の必要観測が有効かを独立判定する。
        引数: j(int)は行。
        返り値: boolは観測資格。
        """
        return bool(quote_valid[j] and np.isfinite(
            [times[j], last[j], volume[j], bid[j], ask[j]]
        ).all() and volume[j] >= 0 and 0 < bid[j] < ask[j])

    buy, sell, other, positive, bad = 0., 0., 0., 0., 0
    for j in range(a+1, i+1):
        edge = known(j) and known(j-1) and seq[j] == seq[j-1]+1
        edge = edge and times[j] >= times[j-1] and volume[j] >= volume[j-1]
        if not edge:
            bad += 1
            continue
        change = volume[j]-volume[j-1]
        positive += change
        if change > 0:
            if last[j] >= ask[j-1]:
                buy += change
            elif last[j] <= bid[j-1]:
                sell += change
            else:
                other += change
    age = times[i]-30.-times[a]
    detail[:] = buy, sell, other, bad, age
    if known(i) and known(a) and bad == 0 and age <= 30:
        output[:] = ((bid[i]+ask[i])-(bid[a]+ask[a]))/2., positive, buy-sell, 1.
    return output, a, detail


def compare_scalar(args, output, positions=None):
    """
    機能: 指定行の全特徴・始端・内訳を独立窓計算と照合する。
    引数: args(list)、output(tuple)、positions(iterable|None)。
    返り値: intは照合行数。
    """
    positions = range(len(args[0])) if positions is None else positions
    count = 0
    for i in positions:
        expected = scalar(args, int(i))
        np.testing.assert_allclose(output[0][i], expected[0], rtol=0, atol=1e-10, equal_nan=True)
        assert output[1][i] == expected[1]
        np.testing.assert_allclose(output[2][i], expected[2], rtol=0, atol=1e-10, equal_nan=True)
        if output[0][i, 3] == 1:
            assert output[0][i, 1] == sum(output[2][i, :3])
            assert abs(output[0][i, 2]) <= output[0][i, 1]
            assert output[1][i] < i
        count += 1
    return count


def main():
    """
    機能: 純人工・JIT・全保存行の対応・原板限定読取を検査する。
    引数: なし。
    返り値: None。特徴だけを扱い、注文・金融再生は行わない。
    """
    source = WORK/"activity130.py"
    manifest_path = WORK/"原板活動の非金融準備.json"
    manifest = read(manifest_path)
    initial_hash = sha(source)
    assert manifest["source"]["sha256"] == initial_hash
    spec = importlib.util.spec_from_file_location("原板活動130独立", source)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    calculate = module.calculate.py_func
    tests = []

    def check(name, action):
        """
        機能: 検査を例外込みで記録する。
        引数: name(str)、action(callable)は検査内容。
        返り値: None。
        """
        try:
            detail = action()
            tests.append(dict(確認=name, 合格=True, 詳細=detail))
        except Exception as error:
            tests.append(dict(確認=name, 合格=False, 詳細=f"{type(error).__name__}: {error}"))

    def basic():
        """
        機能: 厳密前始端の量と価格差を手計算で確認する。
        引数: なし。
        返り値: dictは確定した例。
        """
        args = fixture()
        result = calculate(*args)
        compare_scalar(args, result)
        np.testing.assert_array_equal(result[0][31], [3.875, 31., 31., 1.])
        assert result[1][31] == 0
        assert result[0][30, 3] == 0
        for a, b in zip(result, module.calculate(*args)):
            np.testing.assert_array_equal(a, b)
        return dict(判断行=31, 始端=0, 買い代理量=31, 中値差=3.875)
    check("厳密前始端と独立全行計算及びJIT", basic)

    for label, value in (("売り", -10.), ("曖昧", .5), ("買い", 10.)):
        def direction(label=label, value=value):
            """
            機能: 当行の現在値と前行の気配による分類を確認する。
            引数: label(str)、value(float)は分類値。
            返り値: None。
            """
            args = fixture()
            args[1] = args[3]+value
            result = calculate(*args)
            compare_scalar(args, result)
            assert result[0][31, 2] == {"売り": -31., "曖昧": 0., "買い": 31.}[label]
        check(f"出来高方向の{label}分類", direction)

    def previous_quote():
        """
        機能: 気配が大きく移動しても当行気配で出来高分類をやり直さない。
        引数: なし。
        返り値: None。
        """
        args = fixture()
        args[3][31:] += 20.
        args[4][31:] += 20.
        args[1][31] = args[4][30]
        args[2][31:] += 9.
        result = calculate(*args)
        compare_scalar(args, result)
        assert args[1][31] < args[3][31] and result[2][31, 0] == 40.
        assert result[2][31, 1] == 0.
    check("当行気配ではなく直前askとの一致で買い代理", previous_quote)

    for column in (1, 2, 3, 4, 6):
        def missing(column=column):
            """
            機能: 必要情報の欠測が窓内にある間は未知とし、窓から出た後だけ回復する。
            引数: column(int)は欠測入力列。
            返り値: None。
            """
            args = fixture()
            args[column][20] = False if column == 6 else np.nan
            result = calculate(*args)
            compare_scalar(args, result)
            assert result[0][31, 3] == 0
            assert result[0][52, 3] == 1
        check(f"必要列{column}の欠測と回復", missing)

    for kind in ("出来高減少", "出来高負", "原行飛び", "原行重複", "交差気配", "同値気配", "出来高ゼロ"):
        def broken(kind=kind):
            """
            機能: 不連続・気配不正を未知とし、正常な出来高ゼロと区別する。
            引数: kind(str)は変化内容。
            返り値: None。
            """
            args = fixture()
            if kind == "出来高減少":
                args[2][20:] -= 30.
            elif kind == "出来高負":
                args[2][20] = -1.
            elif kind == "原行飛び":
                args[5][20:] += 2
            elif kind == "原行重複":
                args[5][20] -= 1
            elif kind in ("交差気配", "同値気配"):
                args[4][20] = args[3][20]-(1. if kind == "交差気配" else 0.)
            else:
                args[2][:] = 10.
            result = calculate(*args)
            compare_scalar(args, result)
            if kind == "出来高ゼロ":
                assert list(result[0][31, 1:]) == [0., 0., 1.]
            else:
                assert result[0][31, 3] == 0 and result[0][52, 3] == 1
        check(f"{kind}の区別", broken)

    def age():
        """
        機能: 始端の古さ30秒境界を包含し、超過を未知にする。
        引数: なし。
        返り値: None。
        """
        for times, expected in (([0., 60.], 1.), ([0., 60.000001], 0.)):
            args = fixture(times)
            out = calculate(*args)
            compare_scalar(args, out)
            assert out[0][-1, 3] == expected
    check("始端古さ30秒の包含境界", age)

    for invalid in (np.nan, np.inf, -1.):
        def invalid_clock(invalid=invalid):
            """
            機能: 検索前提を満たさない時計を明示的に拒否する。
            引数: invalid(float)は非有限又は逆行時計。
            返り値: None。
            """
            args = fixture()
            args[0][50] = invalid
            try:
                calculate(*args)
            except ValueError:
                return
            raise AssertionError("不正時計を拒否しなかった")
        check(f"有限単調時計の事前条件_{invalid}", invalid_clock)

    def mirrored():
        """
        機能: 価格を上下反転すると活動量は不変、方向と価格差だけ反転する。
        引数: なし。
        返り値: None。
        """
        args = fixture()
        reflected = deepcopy(args)
        reflected[1], reflected[3], reflected[4] = 500.-args[1], 500.-args[4], 500.-args[3]
        original, mirror = calculate(*args), calculate(*reflected)
        compare_scalar(reflected, mirror)
        np.testing.assert_array_equal(original[0][:, [1, 3]], mirror[0][:, [1, 3]])
        np.testing.assert_allclose(original[0][:, [0, 2]], -mirror[0][:, [0, 2]], equal_nan=True)
        np.testing.assert_array_equal(original[2][:, 0], mirror[2][:, 1])
    check("上下鏡像で価格と符号だけ反転", mirrored)

    for repeated in (False, True):
        def prefixes(repeated=repeated):
            """
            機能: 全ての有効接頭辞と後続同時計の毒化に対して過去特徴の不変を確認する。
            引数: repeated(bool)は一つの価格時計に複数原行を含むか。
            返り値: dictは検査した切断数。
            """
            args = fixture(np.repeat(np.arange(45, dtype=float), 3) if repeated else None)
            full = calculate(*args)
            count = 0
            for end in range(1, len(args[0])+1):
                shortened = [a[:end] for a in args]
                for wanted, actual in zip(full, calculate(*shortened)):
                    np.testing.assert_array_equal(wanted[:end], actual)
                if end < len(args[0]):
                    changed = deepcopy(args)
                    for column in (1, 2, 3, 4):
                        changed[column][end:] += 10000.
                    changed[5][end:] += 1000
                    for wanted, actual in zip(full, calculate(*changed)):
                        np.testing.assert_array_equal(wanted[:end], actual[:end])
                count += 1
            compare_scalar(args, full)
            return dict(全接頭辞=count, 同時計=repeated)
        check(f"接頭辞と未来値及び同時計後行を不使用_{repeated}", prefixes)

    # ----------------------------------------
    # 保存特徴の全原行対応と、選んだ窓の独立計算を確認する。
    packets, packet_hashes = {}, {}
    input_checks, raw_samples, scalar_count, total_rows = [], [], 0, 0
    for ref in manifest["inputs"]:
        packet_path = ROOT/ref["packet"]["path"]
        if str(packet_path) not in packets:
            packet_hashes[str(packet_path)] = sha(packet_path)
            assert packet_hashes[str(packet_path)] == ref["packet"]["sha256"]
            packets[str(packet_path)] = pickle.loads(packet_path.read_bytes())
        packet = packets[str(packet_path)]
        key = (ref["session"], ref["symbol"])
        ready, quote = packet["inputs"][key], packet["quotes"][key]
        raw_path = WORK/"activity_raw"/f'{ref["symbol"]}_{ref["session"]}.npz'
        with np.load(raw_path) as raw_file:
            raw = {k: raw_file[k] for k in raw_file.files}
        prepared_path = ROOT/ref["output"]["path"]
        assert sha(prepared_path) == ref["output"]["sha256"]
        with np.load(prepared_path) as prepared:
            for field in ("time_s", "seq"):
                np.testing.assert_array_equal(prepared[field], ready[field])
                np.testing.assert_array_equal(prepared[field], quote[field])
            np.testing.assert_array_equal(raw["last"], ready["last"])
            np.testing.assert_array_equal(raw["bid"], quote["bid"])
            np.testing.assert_array_equal(raw["ask"], quote["ask"])
            assert np.isfinite(ready["time_s"]).all()
            assert (np.diff(ready["time_s"]) >= 0).all()
            assert (np.diff(ready["seq"]) > 0).all()
            values = (prepared["activity"], prepared["anchor_row"], prepared["details"])
        n = len(ready["time_s"])
        assert n == ref["rows"] == len(values[0])
        assert int((values[0][:, 3] == 1).sum()) == ref["known"]
        source_path = ROOT/ref["source"]["path"]
        assert source_path.stat().st_size == ref["source"]["bytes"]
        assert source_path.stat().st_mtime_ns == ref["source"]["mtime_ns"]
        gaps = np.flatnonzero(np.diff(ready["seq"]) != 1)+1
        good_rows = np.flatnonzero(values[0][:, 3] == 1)
        points = {0, n-1, n//4, n//2, 3*n//4}
        if len(good_rows):
            points.update([int(good_rows[0]), int(good_rows[len(good_rows)//2])])
        if len(gaps):
            points.update([int(gaps[0]), min(n-1, int(gaps[0])+1)])
        inputs = [ready["time_s"], raw["last"], raw["volume"], raw["bid"], raw["ask"],
                  ready["seq"], quote["quote_valid"]]
        scalar_count += compare_scalar(inputs, values, sorted(points))
        sample_indices = {0}
        if len(good_rows):
            sample_indices.add(int(good_rows[0]))
        if len(gaps) and ready["seq"][gaps[0]] < 30000:
            sample_indices.add(int(gaps[0]))
        seq_to_index = {int(ready["seq"][i]): i for i in sample_indices}
        with source_path.open("rb") as handle:
            for seq, line in enumerate(handle):
                if seq in seq_to_index:
                    i = seq_to_index[seq]
                    obj = json.loads(line)
                    expected = [obj.get("CurrentPrice"), obj.get("TradingVolume"),
                                (obj.get("Buy1") or {}).get("Price"),
                                (obj.get("Sell1") or {}).get("Price")]
                    expected = [float(v) if isinstance(v, (int, float)) else np.nan for v in expected]
                    np.testing.assert_array_equal([raw[k][i] for k in ("last", "volume", "bid", "ask")],
                                                  expected)
                    assert datetime.fromisoformat(obj["CurrentPriceTime"]).timestamp() == ready["time_s"][i]
                    raw_samples.append(dict(session=ref["session"], symbol=ref["symbol"],
                                            packet_row=i, raw_seq=seq))
                if seq >= max(seq_to_index):
                    break
        input_checks.append(dict(session=ref["session"], symbol=ref["symbol"], rows=n,
                                 source=ref["source"], packet=ref["packet"], output=ref["output"],
                                 raw_cache_sha256=sha(raw_path), scalar_rows=sorted(points)))
        total_rows += n
        if len(input_checks) % 8 == 0:
            print("非金融素材照合", len(input_checks), "/42", flush=True)
    assert len(input_checks) == 42 and len({(r["session"], r["symbol"]) for r in input_checks}) == 42
    assert sha(source) == initial_hash
    passed = all(t["合格"] for t in tests)
    destination = HERE/f"原板活動の独立人工と全42素材接続_{time.time_ns()}.json"
    destination.write_text(json.dumps(dict(
        passed=passed, tests=tests, inputs=input_checks, mapped_rows=total_rows,
        independent_scalar_rows=scalar_count, raw_samples=raw_samples,
        sources={str(source.relative_to(ROOT)): initial_hash,
                 str(manifest_path.relative_to(ROOT)): sha(manifest_path),
                 str(Path(__file__).relative_to(ROOT)): sha(Path(__file__))},
        financial_replays=0, api_calls=0,
        limitations=[
            "公表増分の代理分類であり、真の攻撃側・約定消費・取消・補充を識別したものではない",
            "単調有限の保存価格時計が事前条件。実受信時刻や二市場共通受信先後は不明",
            "全原行の配列接続は確認。特徴の独立窓再計算と原板JSON直接照合は記載した限定行",
            "入口候補の採否と準備取消の新数値核・実損益は未検査",
        ],
    ), ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(dict(passed=passed, cases=len(tests), inputs=len(input_checks), rows=total_rows,
                          scalar_rows=scalar_count, raw_samples=len(raw_samples), path=str(destination),
                          failures=[t for t in tests if not t["合格"]]), ensure_ascii=False))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
