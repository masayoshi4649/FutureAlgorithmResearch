"""第一巡の固定採点器を依存として使い、板分位24条件だけを別研究として評価する。"""

from pathlib import Path
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "search"))
import engine161 as base
from rules161r2 import candidates, load_thresholds, signal

WARNING = "第二巡の追加開発。後半13場は第一巡の結果が既に観測された既知資料であり、独立未見・再認証とは呼ばない。今回の候補選択自体は固定30/10だけを使う。"
ORIGINAL_WRITE = base.write_json
THRESHOLDS = None


def empty_models(scenes, data_root, access_log):
    """第二巡は学習器を追加せず空のモデルを返す。

    引数: scenes(list)、data_root(Path)、access_log(list)。返り値: dict。
    """
    return {}


def evaluate_candidate(data, candidate, phase, models):
    """第二巡の固定板条件を第一巡と同じ間引き・先着で採点する。

    引数: data/candidate/models(dict)、phase(str)。返り値: list[dict]。
    """
    if not np.any(data["feature"]["phase"].astype(str) == phase):
        return []
    long_signal = signal(data["f"], candidate, 1, phase, THRESHOLDS)
    short_signal = signal(data["f"], candidate, -1, phase, THRESHOLDS)
    return base.collect_events(data, long_signal, short_signal, candidate["id"], phase)


def write_development(path, value):
    """互換ファイル名の全結果へ既知追加開発の留保を必ず書く。

    引数: path(Path)、value(dict)。返り値: None。
    凍結選択では追加メタデータ込みの内容指紋を再計算する。
    """
    value["metadata"] = WARNING
    value["confirmation_is_known_development"] = True
    if Path(path).name == "selection_frozen161.json":
        value["content_sha256"] = base.canonical_digest({key: item for key, item in value.items() if key != "content_sha256"})
    if Path(path).name == "locked_test161.json":
        value["warning"] = WARNING
    ORIGINAL_WRITE(path, value)


def configure():
    """別プロセス内の依存関数だけを第二巡の固定候補へ接続する。

    引数: なし。返り値: None。第一巡ファイルは変更しない。
    """
    global THRESHOLDS
    THRESHOLDS = load_thresholds()
    base.candidates = candidates
    base.train_models = empty_models
    base.evaluate_candidate = evaluate_candidate
    base.write_json = write_development


def main():
    """第一巡と同じCLIと登録受領検査で別研究を起動する。

    引数: CLI(stage/receipt/manifest/spec/data/out/freeze)。返り値: None。
    """
    configure()
    base.main()


if __name__ == "__main__":
    main()
