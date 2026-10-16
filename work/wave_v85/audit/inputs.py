"""原E01の保存素材と追加原本の対応を、再生器を使わず独立確認する。"""

from datetime import datetime
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]


def read(path):
    """
    機能: UTF-8の固定記録を読む。
    引数: path (Path)。
    返り値: dict の保存内容。
    """
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path):
    """
    機能: 対象ファイルを変更せず指紋化する。
    引数: path (Path)。
    返り値: str のSHA256。
    """
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for part in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            value.update(part)
    return value.hexdigest()


def raw_check(key, ready, folder, expected_hash):
    """
    機能: 追加原本全文の指紋と、独立選択した9点の価格・気配・時計を照合する。
    引数: key (tuple[str,str])、ready (dict)、folder (Path)、expected_hash (str)。
    返り値: dict の原本照合記録。
    """
    n = len(ready["seq"])
    selected = np.unique(np.rint(np.linspace(0, n - 1, 9)).astype(int))
    target = {int(ready["seq"][i]): int(i) for i in selected}
    samples = []
    value = hashlib.sha256()
    path = ROOT / "book" / key[1] / (key[0] + ".jsonl")
    with np.load(folder / "features" / f"約定系列_{key[1]}_{key[0]}.npz") as tape:
        for name in ("seq", "time_s", "last"):
            np.testing.assert_array_equal(tape[name], ready[name])
        with path.open("rb") as stream:
            for line_number, line in enumerate(stream):
                value.update(line)
                if line_number not in target:
                    continue
                i = target[line_number]
                raw = json.loads(line)
                stamp = datetime.fromisoformat(raw["CurrentPriceTime"]).timestamp()
                assert stamp == ready["time_s"][i]
                assert raw["CurrentPrice"] == ready["last"][i]
                assert raw["Buy1"]["Price"] == tape["bid"][i]
                assert raw["Sell1"]["Price"] == tape["ask"][i]
                samples.append(dict(入力行=i, 原本行=line_number, 時刻=stamp,
                                    現在値=raw["CurrentPrice"], 買気配=raw["Buy1"]["Price"],
                                    売気配=raw["Sell1"]["Price"]))
    assert value.hexdigest() == expected_hash and len(samples) == len(selected)
    return dict(セッション=key[0], 銘柄=key[1], 指紋一致=True, 原本抜取=samples,
                全価格対応配列一致=True, 原本SHA256=value.hexdigest())


def main():
    """
    機能: 旧28場を旧指紋と照合し、新2場を原本へ独立対応させる。
    引数: なし。
    返り値: None。会計・市場情報取得・旧成果書込みは行わない。
    """
    fixed = read(WORK / "prepared/入力準備の完了.json")
    old = read(ROOT / "work/wave_v67/入力指紋.json")
    prior_hash = {str(Path("work/wave_v67") / name): digest for name, digest in old.items()}
    original83 = read(ROOT / "work/wave_v83/prepared/価格入力の照合.json")
    raw_hash = {(r["session"], r["symbol"]): r["原本SHA256"] for r in original83["各口座"]}
    accounts, extra, fingerprints = [], [], {}
    old_count = 0
    seen = set()
    for pair in fixed["入力対応"]:
        paths = {kind: ROOT / name for kind, name in pair.items()}
        for kind, path in paths.items():
            name = str(path.relative_to(ROOT))
            fingerprints[name] = sha(path)
            expected = fixed["使用入力SHA256"].get(name, fixed["使用入力SHA256"].get(name.replace("\\", "/")))
            assert fingerprints[name] == expected
            if path.is_relative_to(ROOT / "work/wave_v67"):
                assert fingerprints[name] == prior_hash[name]
                old_count += 1
        with paths["inputs"].open("rb") as stream:
            inputs = pickle.load(stream)
        with paths["signals"].open("rb") as stream:
            signals = pickle.load(stream)
        assert set(signals) == {"entry", "B00", "B01"}
        for key, ready in inputs.items():
            assert key not in seen
            seen.add(key)
            n = len(ready["seq"])
            assert np.all(np.diff(ready["seq"]) > 0)
            assert np.all(np.diff(ready["time_s"]) >= 0)
            assert ready["time_s"][-1] > ready["limit"]
            assert len(ready["last"]) == len(ready["atr"]) == n
            assert np.all(np.isfinite(ready["last"])) and np.all(ready["last"] > 0)
            direction = signals["entry"][key]
            assert direction.shape == (n,) and np.isin(direction, (-1, 0, 1)).all()
            for code in ("B00", "B01"):
                signal = signals[code][key]
                source = signal["source_row"]
                assert source.shape == (n,) and (source >= -1).all()
                assert np.all(source <= np.arange(n))
                assert np.isin(signal["direction"], (-1, 0, 1)).all()
            if key[0] in ("2026-10-09_Day", "2026-10-09_Night"):
                extra.append(raw_check(key, ready, paths["inputs"].parent, raw_hash[key]))
            accounts.append(dict(セッション=key[0], 銘柄=key[1], 行数=n, 元信号未来参照なし=True,
                同時計隣接数=int(np.sum(np.diff(ready["time_s"]) == 0))))
    assert len(seen) == 60 and len(extra) == 4 and old_count == len(prior_hash)
    assert sorted({k[0] for k in seen}) == fixed["全30"]
    result = dict(全合格=True, 口座数=len(seen), 旧入力指紋一致数=old_count,
        全価格行数=sum(r["行数"] for r in accounts), 追加原本一致数=len(extra), 原本抜取数=36,
        口座別=accounts, 追加原本=extra, 入力SHA256=fingerprints, コードSHA256=sha(Path(__file__)),
        限界="信号生成の未来切断は準備担当の別検査。ここは原本対応・旧素材同一性・保存元行の独立照合。CurrentPriceTimeは実受信時計を証明しない。",
        売買損益参照=False, API取得=0, 旧書込=0)
    (HERE / "原E01入力の独立照合.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("全合格", "口座数", "旧入力指紋一致数", "全価格行数", "追加原本一致数", "原本抜取数")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
