"""実市場を読まず、00128の特徴公開時計と未来非参照を独立に検査する。"""

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / "features128.py"


def fixture():
    """
    機能: 正の人工価格を持つ二商品入力を作る。
    引数: なし。
    返り値: dictは同じ価格時計の人工packet。
    """
    times = np.arange(0., 4201., 10.)
    return dict(inputs={
        ("人工_Night", "TOPIX"): dict(time_s=times.copy(), last=1000.+times/100.,
                                         start=0.),
        ("人工_Night", "NK225"): dict(time_s=times.copy(), last=2000.+times/50.,
                                         start=0.),
    })


def clipped(packet, cut):
    """
    機能: 指定時計の前だけを残した人工入力を作る。
    引数: packet(dict)は人工入力、cut(float)は除外開始時計。
    返り値: dictはコピーされた接頭入力。
    """
    value = copy.deepcopy(packet)
    for ready in value["inputs"].values():
        count = np.searchsorted(ready["time_s"], cut, side="left")
        ready["time_s"] = ready["time_s"][:count]
        ready["last"] = ready["last"][:count]
    return value


def main():
    """
    機能: スナップショットの純人工確認を行い結果を所有領域へ保存する。
    引数: CLI第1引数(str)は証跡の接尾語。省略時は初回。
    返り値: None。失敗も証跡へ残し、金融処理や原本読取は行わない。
    """
    suffix = sys.argv[1] if len(sys.argv) > 1 else "初回"
    raw = SOURCE.read_bytes()
    snap = HERE / f"features128_{suffix}.py"
    assert not snap.exists()
    snap.write_bytes(raw)
    spec = importlib.util.spec_from_file_location(f"features128_audit_{suffix}", snap)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    checks = []

    def check(name, action):
        """
        機能: 一件の人工反例を評価して成功又は例外を保存する。
        引数: name(str)は確認名、action(callable)は例外で失敗を示す関数。
        返り値: None。checksへ追記する。
        """
        try:
            action()
            checks.append(dict(確認=name, 合格=True))
        except Exception as exc:
            checks.append(dict(確認=name, 合格=False, 内容=f"{type(exc).__name__}: {exc}"))

    packet = fixture()
    keys = list(packet["inputs"])
    full = module.build(packet)

    def release():
        """
        機能: 線形入力の手計算値と自己・相手の遅延公開を確認する。
        引数: なし。
        返り値: None。
        """
        values = full[keys[0]]
        times = packet["inputs"][keys[0]]["time_s"]
        at = np.flatnonzero(times == 1380.)[0]
        # 自己は終端1320直前1310、相手は終端1260直前1250。
        expected = [1011.9, 1007.4, np.std(np.arange(1001.7, 1013.2, .6)),
                    1013.1, 1001.1, 1., 3., 12., 1000., 1320.,
                    6., 24., 1., 25., 1260.]
        np.testing.assert_allclose(values[at], expected, rtol=0, atol=1e-10)
        assert not np.isfinite(values[times < 1380.]).all(axis=1).any()
        mask = np.isfinite(values[:, 9]) & np.isfinite(values[:, 14])
        assert np.all(values[mask, 9]+60. <= times[mask])
        assert np.all(values[mask, 14]+120. <= times[mask])

    check("手計算値と公開遅延", release)
    for cut in (1880., 3030.):
        def prefix(cut=cut):
            """
            機能: 将来尾を切ったとき既知特徴が不変であることを確認する。
            引数: cut(float)は人工切断時計。
            返り値: None。
            """
            part = module.build(clipped(packet, cut))
            for key in keys:
                np.testing.assert_array_equal(part[key], full[key][:len(part[key])])
        check(f"接頭切断{cut}", prefix)

        def poison(cut=cut):
            """
            機能: 将来価格を極端に変えても過去特徴が変わらないことを確認する。
            引数: cut(float)は価格変更開始時計。
            返り値: None。
            """
            changed = copy.deepcopy(packet)
            for ready in changed["inputs"].values():
                ready["last"][ready["time_s"] >= cut] *= 10.
            values = module.build(changed)
            for key in keys:
                count = np.searchsorted(packet["inputs"][key]["time_s"], cut, side="left")
                np.testing.assert_array_equal(values[key][:count], full[key][:count])
        check(f"未来価格改変{cut}", poison)

    def reflection():
        """
        機能: 価格鏡映で価格列・差分列が対称になることを確認する。
        引数: なし。
        返り値: None。
        """
        other = copy.deepcopy(packet)
        for key, ready in other["inputs"].items():
            ready["last"] = 2.*ready["last"][0] - ready["last"]
        values = module.build(other)
        for key in keys:
            expected = full[key].copy()
            pivot = packet["inputs"][key]["last"][0]
            expected[:, [0, 1, 8]] = 2.*pivot-expected[:, [0, 1, 8]]
            expected[:, 3] = 2.*pivot-full[key][:, 4]
            expected[:, 4] = 2.*pivot-full[key][:, 3]
            expected[:, [6, 7, 10, 11, 13]] *= -1.
            np.testing.assert_allclose(values[key], expected, rtol=0, atol=1e-10)
    check("鏡映売買対称", reflection)

    def same_clock():
        """
        機能: 一分境界と同時計の毒値が境界前終値へ混入しないことを確認する。
        引数: なし。
        返り値: None。
        """
        other = copy.deepcopy(packet)
        for ready in other["inputs"].values():
            at = np.flatnonzero(ready["time_s"] == 1260.)[0]
            ready["last"][at] = 900000.
        values = module.build(other)
        # 毒値は終端1260には含まれない。公開1380時点の相手特徴も不変。
        at = np.flatnonzero(packet["inputs"][keys[0]]["time_s"] == 1380.)[0]
        np.testing.assert_array_equal(values[keys[0]][at, 10:], full[keys[0]][at, 10:])
    check("境界同時計の毒値拒否", same_clock)

    def missing():
        """
        機能: 長い価格欠測を0変動の有効資料として利用しないことを確認する。
        引数: なし。
        返り値: None。
        """
        other = copy.deepcopy(packet)
        ready = other["inputs"][keys[1]]
        ready["last"][(ready["time_s"] >= 1800.) & (ready["time_s"] <= 2200.)] = np.nan
        value = module.build(other)[keys[0]]
        own_time = other["inputs"][keys[0]]["time_s"]
        assert not np.isfinite(value[(own_time >= 2040.) & (own_time <= 2300.), 10:]).all(axis=1).any()
    check("長い欠測は未知", missing)

    def stale():
        """
        機能: 相手更新が途絶えた後に最後の資料が永久有効にならないことを確認する。
        引数: なし。
        返り値: None。
        """
        other = copy.deepcopy(packet)
        ready = other["inputs"][keys[1]]
        ready["time_s"] = ready["time_s"][ready["time_s"] <= 2520.]
        ready["last"] = ready["last"][:len(ready["time_s"])]
        value = module.build(other)[keys[0]]
        own_time = other["inputs"][keys[0]]["time_s"]
        assert not np.isfinite(value[own_time > 2800., 10:]).all(axis=1).any(), "相手終了後280秒超でも有効な特徴が残る"
    check("相手早期終了後の資料鮮度", stale)

    def all_unknown():
        """
        機能: 全価格不明の相手がある場合に未知特徴を返すことを確認する。
        引数: なし。
        返り値: None。
        """
        other = copy.deepcopy(packet)
        other["inputs"][keys[1]]["last"][:] = np.nan
        value = module.build(other)
        for rows in value.values():
            assert not np.isfinite(rows).all(axis=1).any()
    check("全価格未知", all_unknown)

    result = dict(全合格=all(v["合格"] for v in checks), 確認数=len(checks), 確認=checks,
                  数値源=str(SOURCE), 数値源SHA256=hashlib.sha256(raw).hexdigest(),
                  新金融=0, 市場素材読取=0, 原本読取=0)
    target = HERE / f"特徴の独立人工監査_{suffix}.json"
    assert not target.exists()
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
