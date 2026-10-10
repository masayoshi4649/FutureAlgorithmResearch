"""五反復の全探索を母集団とする開始日共通符号対照を、候補選抜と分けて記述する。"""

from __future__ import annotations

import argparse
from datetime import datetime
import gzip
import hashlib
import itertools
import json
from pathlib import Path
import pickle
from zoneinfo import ZoneInfo

import numpy as np


HERE = Path(__file__).resolve().parent
PHASE_COUNTS = {"wave_v25": 36668, "wave_v26": 19776, "wave_v27": 19776, "wave_v28": 27648, "wave_v29": 4800}
SYMBOLS = ("TOPIX", "NK225")
RULES = {
    "対象": list(PHASE_COUNTS), "期待条件数": PHASE_COUNTS, "全条件数": 108668,
    "単位": "各セッションのnet_rを開始日ごとに加算。両銘柄は合算しない。",
    "統計量": "銘柄ごとに日別Rの合計÷日別R二乗和の平方根。二銘柄の小さい方をその手法の値とする。全日ゼロは0。",
    "対照": "7開始日について±1の全128組合せ。ある開始日の符号は、全手法と両銘柄の損益に共通に掛ける。",
    "探索効果": "各符号組合せで、全108,668条件中の最大値を求める。上位だけや合格だけへ母集団を絞らない。台帳同一条件も削除しない。",
    "実行条件": "v29全探索完了、研究候補の固定.json作成後だけ読む。候補が0件でも同じ対照を計算する。",
    "比較対象": "v26/v27の現在照合候補の固定.jsonとv28/v29の研究候補の固定.json。旧比較は自身の反復にない場合v25へ解決。P02等が全探索母集団にない場合は母集団外として記録し、成績を捏造しない。",
    "同順位": "反復v25→v29、各固定信号カタログ順、固定管理カタログ順の先頭を最大値の代表名にする。最大値の数式は同じ。",
    "数値実装": "各銘柄の日別Rを最初に最大絶対値で割り、その後L2長で割る。正の倍率による正規化なので従来の二乗和平方根方式と数学的に同値。巨大有限値の二乗overflowと微小値のunderflowを避ける。",
    "入力ガード": "条件ID集合・重複・26入力のsession/symbol集合・日集合・R有限性を検証。日内加算後も有限性を検証。不足・余分・重複・非有限値を拒否する。",
    "選抜禁止": "この診断の首位へ主候補を変更しない。採否条件へ追加せず、閾値の緩和・再最適化に用いない。",
    "解釈": "少ない開始日と多数探索に対する記述的な対照。日ごとの独立・符号対称性は実証されていない。実価格の再生でも正式な有意確率でもない。",
    "限界": "前四反復と一回の現在照合を知って第五反復を設計した事実は消えない。過去の全作業を網羅せず、今回v25〜v29の五反復に限る。",
    "禁止": "価格取得、売買再生、現在スナップショット読取、旧v27コードと固定JSONの変更。",
}


def read(path: Path):
    """機能: 通常または圧縮されたUTF-8のJSONを読む。

    引数: path (Path)。返り値: JSONの内容 (dict|list)。
    """
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as stream:
        return json.load(stream)


def save(path: Path, value) -> None:
    """機能: 新しい作業領域にだけJSONを保存する。

    引数: path (Path)、value (dict|list)。返り値: なし (None)。
    """
    with path.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)


def digest(path: Path) -> str:
    """機能: 読取仕様とコードの指紋を計算する。

    引数: path (Path)。返り値: SHA256 (str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze() -> dict:
    """機能: 新結果を読む前に数式・母集団・解釈と実装を固定する。

    引数: なし。返り値: 固定済み仕様 (dict)。
    """
    old_files = (HERE.parent / "wave_v28" / "all_search_control.py", HERE.parent / "wave_v28" / "探索全体対照の固定.json")
    record = dict(固定日時=datetime.now(ZoneInfo("Asia/Tokyo")).isoformat(), 第五反復の新損益未読=True,
                  規則=RULES, コードSHA256=digest(Path(__file__)), 旧資料SHA256={str(path): digest(path) for path in old_files},
                  新実装="母集団を五反復へ拡張。数式と全日共通符号は維持し、v29研究候補固定の存在を実行条件とする。")
    path = HERE / "探索全体対照の固定.json"
    if path.exists():
        old = read(path)
        assert {key: value for key, value in old.items() if key != "固定日時"} == {key: value for key, value in record.items() if key != "固定日時"}, "事前固定後の対照規則/実装変更"
        return old
    save(path, record)
    return record


def normalized_r(values: np.ndarray) -> np.ndarray:
    """機能: 日別Rを最大絶対値で先に縮尺し、overflowなしにL2正規化する。

    引数: values (ndarray[float]) は手法×2銘柄×7開始日。返り値: 同じ形の正規化値 (ndarray)。
    """
    values = np.asarray(values, float)
    if values.ndim != 3 or values.shape[0] < 1 or values.shape[1:] != (2, 7) or not np.isfinite(values).all():
        raise ValueError("R行列の形または有限性が不正")
    magnitude = np.max(np.abs(values), axis=2, keepdims=True)
    scaled = np.divide(values, magnitude, out=np.zeros_like(values), where=magnitude > 0)
    length = np.sqrt(np.sum(scaled * scaled, axis=2, keepdims=True))
    normalized = np.divide(scaled, length, out=np.zeros_like(values), where=length > 0)
    assert np.isfinite(normalized).all()
    return normalized


def daily_matrix(rows: list[dict], identifier: str, input_keys: set[tuple], dates: list[str]) -> np.ndarray:
    """機能: 26入力の欠落/重複/ID混入を拒否し、日別Rへ集約する。

    引数: rows (list[dict])、identifier (str)、input_keys (set[tuple])、dates (list[str])。
    返り値: 銘柄×開始日のR行列 (ndarray)。
    """
    assert len(rows) == len(input_keys) == 26, "セッション行数の不足又は重複"
    assert {(row["session"], row["symbol"]) for row in rows} == input_keys, "入力キー集合の欠落又は混入"
    assert sorted({row["session"][:10] for row in rows}) == dates, "開始日集合の不一致"
    assert all(row["id"] == identifier for row in rows), "候補内に別IDの行が混入"
    assert all(isinstance(row["net_r"], (int, float)) and not isinstance(row["net_r"], bool) and np.isfinite(row["net_r"]) for row in rows), "非有限又は非数値のRを拒否"
    matrix = np.zeros((2, len(dates)), float)
    try:
        with np.errstate(over="raise", invalid="raise"):
            for row in rows:
                matrix[SYMBOLS.index(row["symbol"]), dates.index(row["session"][:10])] += row["net_r"]
    except FloatingPointError as error:
        raise ValueError("日内R加算の非有限化を拒否") from error
    assert np.isfinite(matrix).all(), "日別Rが非有限"
    return matrix


def candidate_results(results: list[dict], signal_id: str, manager_ids: list[str]) -> list[dict]:
    """機能: 一信号の全管理IDを照合し、固定カタログ順に整える。

    引数: results (list[dict])、signal_id (str)、manager_ids (list[str])。返り値: 検証済み結果 (list[dict])。
    """
    expected = [signal_id + "__" + identifier for identifier in manager_ids]
    assert len(results) == len(expected) and len(expected) == len(set(expected)), "条件数又は管理IDが不正"
    assert {result["id"] for result in results} == set(expected), "全条件ID集合が不一致"
    lookup = {result["id"]: result for result in results}
    assert len(lookup) == len(results), "条件ID重複"
    return [lookup[identifier] for identifier in expected]


def collect() -> tuple[list[str], np.ndarray, list[str], dict]:
    """機能: 全探索と研究候補選定の完了後にだけ、全108668条件の日別Rを読む。

    引数: なし。返り値: ID・R行列・日・参照指紋 (tuple[list,ndarray,list,dict])。
    """
    selected_path = HERE / "研究候補の固定.json"
    assert selected_path.exists(), "研究候補の選定前には実行しない"
    selected = read(selected_path)
    assert selected["候補再選択禁止"] is True and selected["現在データ使用"] is False
    input_keys = set(pickle.loads((HERE.parent / "wave_v23" / "inputs.pkl").read_bytes()))
    dates = sorted({key[0][:10] for key in input_keys})
    assert len(input_keys) == 26 and len(dates) == 7 and {key[1] for key in input_keys} == set(SYMBOLS)
    identifiers, matrices, fingerprints = [], [], {str(selected_path): digest(selected_path)}
    for phase, expected_count in PHASE_COUNTS.items():
        directory = HERE.parent / phase
        fixed_path, completed_path = directory / "探索条件の固定.json", directory / "反証前の候補固定.json"
        assert completed_path.exists() and (directory / "全条件の期間集計.json.gz").exists(), f"全探索未完了: {phase}"
        fixed, completed = read(fixed_path), read(completed_path)
        assert completed["全条件数"] == fixed["全組合せ数"] == expected_count
        signal_ids, manager_ids = ([item["id"] for item in fixed[key]] for key in ("signals", "managers"))
        assert len(signal_ids) == len(set(signal_ids)) and len(manager_ids) == len(set(manager_ids))
        assert len(signal_ids) * len(manager_ids) == expected_count
        fingerprints[str(fixed_path)], fingerprints[str(completed_path)] = digest(fixed_path), digest(completed_path)
        count = 0
        for signal_id in signal_ids:
            path = directory / "sessions" / f"{signal_id}.json.gz"
            results = candidate_results(read(path), signal_id, manager_ids)
            for result in results:
                matrices.append(daily_matrix(result["rows"], result["id"], input_keys, dates))
                identifiers.append(phase + "/" + result["id"])
                count += 1
        assert count == expected_count
        print(f"{phase}の全{count:,}条件を読込み", flush=True)
    assert len(identifiers) == len(set(identifiers)) == sum(PHASE_COUNTS.values()) == RULES['全条件数']
    values = np.asarray(matrices)
    assert np.isfinite(values).all()
    return identifiers, values, dates, fingerprints


def all_sign_scores(normalized: np.ndarray) -> tuple[np.ndarray, list[dict]]:
    """機能: 全128符号を全手法・両銘柄へ共通適用して、毎回全探索の最大を選ぶ。

    引数: normalized (ndarray)。返り値: 元統計量と符号ごとの最大値/行番号 (tuple[ndarray,list[dict]])。
    """
    original = normalized.sum(axis=2).min(axis=1)
    cases = []
    for signs in itertools.product((-1, 1), repeat=7):
        scores = np.einsum("ijk,k->ij", normalized, np.asarray(signs, float)).min(axis=1)
        winner = int(np.argmax(scores))
        cases.append(dict(符号=list(signs), 全探索最大値=float(scores[winner]), 最大値の行=winner))
    assert len(cases) == 128
    return original, cases


def fixed_candidate_comparisons(names: list[str], original: np.ndarray, maxima: np.ndarray) -> tuple[dict, list[dict], dict]:
    """機能: 既に選抜済みの候補だけを対照へ載せ、母集団外の旧比較を明示する。

    引数: names (list[str])、original/maxima (ndarray)。返り値: 比較・母集団外・資料指紋 (tuple[dict,list,dict])。
    """
    indices = {name: index for index, name in enumerate(names)}
    selected, missing, fingerprints = {}, [], {}
    for phase, filename in (("wave_v26", "現在照合候補の固定.json"), ("wave_v27", "現在照合候補の固定.json"), ("wave_v28", "研究候補の固定.json"), ("wave_v29", "研究候補の固定.json")):
        path = HERE.parent / phase / filename
        assert path.exists(), f"固定候補ファイルがない: {phase}"
        source = read(path)
        assert source["候補再選択禁止"] is True
        candidates = source["候補"]
        assert len(candidates) == len({candidate["id"] for candidate in candidates}), "固定候補の重複"
        fingerprints[str(path)] = digest(path)
        for candidate in candidates:
            identifier = candidate["id"]
            name = phase + "/" + identifier
            if name not in indices and "wave_v25/" + identifier in indices:
                name = "wave_v25/" + identifier
            if name not in indices:
                assert phase not in ("wave_v28", "wave_v29"), "研究候補が全探索母集団にない"
                missing.append(dict(選択元=phase, 手法ID=identifier, 理由="P02等の補助比較は全組合せ探索母集団に存在しない。統計量を捏造せず母集団外として記録。"))
                continue
            value = float(original[indices[name]])
            if name not in selected:
                selected[name] = dict(元の統計量=value, 探索最大値がこれ以上の符号組合せ数=int(np.sum(maxima >= value - 1e-12)), 選択元=[])
            selected[name]["選択元"].append(phase)
    return selected, missing, fingerprints


def synthetic_checks() -> dict:
    """機能: 新しい相場結果を読まず、数式同値・極端値・不正入力拒否を検査する。

    引数: なし。返り値: 合成検査の合否と件数 (dict)。
    """
    generator = np.random.default_rng(20260929)
    values = generator.normal(size=(17, 2, 7))
    direct = values / np.sqrt(np.sum(values * values, axis=2, keepdims=True))
    stable = normalized_r(values)
    np.testing.assert_allclose(stable, direct, atol=1e-15, rtol=1e-15)
    original, cases = all_sign_scores(stable)
    for case in cases:
        direct_scores = (direct * np.array(case["符号"])[None, None, :]).sum(axis=2).min(axis=1)
        np.testing.assert_allclose(case["全探索最大値"], direct_scores.max(), atol=1e-14, rtol=0)
    np.testing.assert_allclose(original, direct.sum(axis=2).min(axis=1), atol=1e-14, rtol=0)
    np.testing.assert_allclose(normalized_r(values * np.array([1e250, 1e-250])[None, :, None]), stable, atol=1e-14, rtol=0)
    extremes = np.zeros((3, 2, 7))
    extremes[0, :, :3] = np.array([1, -1, 1]) * 1e300
    extremes[1, :, :3] = np.array([1, -1, 1]) * 1e-300
    result = normalized_r(extremes)
    np.testing.assert_allclose(result[:2, :, :3], np.broadcast_to(np.array([1, -1, 1]) / np.sqrt(3), (2, 2, 3)), atol=1e-15, rtol=0)
    assert np.all(result[2] == 0)
    rejected = 0
    for invalid in (np.full((1, 2, 7), np.nan), np.full((1, 2, 7), np.inf), np.zeros((0, 2, 7)), np.zeros((1, 1, 7))):
        try:
            normalized_r(invalid)
        except ValueError:
            rejected += 1
        else:
            raise AssertionError("不正R行列を受理")
    dates = ["2026-09-21", "2026-09-22", "2026-09-23", "2026-09-24", "2026-09-25", "2026-09-28", "2026-09-29"]
    sessions = [day + "_Day" for day in dates] + [day + "_Night" for day in dates[:-1]]
    keys = {(session, symbol) for session in sessions for symbol in SYMBOLS}
    rows = [dict(id="監査__管理", session=session, symbol=symbol, net_r=1.) for session, symbol in sorted(keys)]
    matrix = daily_matrix(rows, "監査__管理", keys, dates)
    np.testing.assert_array_equal(matrix, np.tile([2., 2., 2., 2., 2., 2., 1.], (2, 1)))
    bad_rows = [rows[:-1], rows[:-1] + [rows[0]], [dict(row, id="別候補") if index == 0 else row for index, row in enumerate(rows)],
                [dict(row, net_r=np.inf) if index == 0 else row for index, row in enumerate(rows)]]
    for invalid in bad_rows:
        try:
            daily_matrix(invalid, "監査__管理", keys, dates)
        except (ValueError, AssertionError):
            rejected += 1
        else:
            raise AssertionError("不正セッションを受理")
    for results in ([dict(id="H__A"), dict(id="H__A")], [dict(id="H__A")], [dict(id="H__A"), dict(id="別__B")]):
        try:
            candidate_results(results, "H", ["A", "B"])
        except AssertionError:
            rejected += 1
        else:
            raise AssertionError("不正条件IDを受理")
    assert [row["id"] for row in candidate_results([dict(id="H__B"), dict(id="H__A")], "H", ["A", "B"])] == ["H__A", "H__B"]
    return dict(通常値の旧数式同値=True, 全128共通符号一致=True, 正倍率不変=True, 巨大微小ゼロの正規化=True,
                不正入力拒否件数=rejected, 全セッション日集約一致=True, 新相場結果読取=False)


def evaluate() -> dict:
    """機能: 全探索最大値の対照を計算するが、研究候補や採用条件を変更しない。

    引数: なし。返り値: 記述対照の結果 (dict)。
    """
    fixed = freeze()
    names, values, dates, references = collect()
    original, cases = all_sign_scores(normalized_r(values))
    for case in cases:
        case["最大値の手法"] = names[case.pop("最大値の行")]
    maxima = np.array([case["全探索最大値"] for case in cases])
    winner = int(np.argmax(original))
    selected, missing, selected_hashes = fixed_candidate_comparisons(names, original, maxima)
    output = dict(固定=fixed, 全条件数=len(names), 反復別条件数=PHASE_COUNTS, 開始日=dates, 符号組合せ数=len(cases),
                  元データ最大値=float(original[winner]), 元データ最大値の手法=names[winner],
                  探索最大値が元最大値以上の組合せ数=int(np.sum(maxima >= original[winner] - 1e-12)),
                  探索最大値の百分位=np.percentile(maxima, [0, 5, 50, 95, 100]).tolist(), 固定候補=selected,
                  母集団にない固定比較=missing, 全符号対照=cases, 正式な有意確率ではない=True,
                  候補採用判定に使用=False, 参照資料SHA256={**references, **selected_hashes})
    save(HERE / "探索全体対照の結果.json", output)
    return output


def main() -> None:
    """機能: 結果前の規則固定と合成検査、又は全探索・選抜後の一回計算を行う。

    引数: --prepare (bool)。返り値: なし (None)。価格取得と現在データの機能は持たない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare", action="store_true")
    args = parser.parse_args()
    if args.prepare:
        checks = synthetic_checks()
        frozen = freeze()
        save(HERE / "全探索対照の合成検査.json", dict(検査=checks, コードSHA256=frozen["コードSHA256"]))
        print("五反復108,668条件の共通128符号対照を固定。合成検査通過、新結果未読。", flush=True)
        return
    result = evaluate()
    print(json.dumps({key: value for key, value in result.items() if key in ("全条件数", "符号組合せ数", "探索最大値が元最大値以上の組合せ数", "正式な有意確率ではない")}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
