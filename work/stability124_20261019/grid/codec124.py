"""118の因果公開足と、採用現在値行の正常BBOを同じ入力読取から作る。"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OBSERVATION_TICK = {"TOPIX": 0.5, "NK225": 10.0}
UPSTREAM = HERE / "codec_source.py"


# ----------------------------------------


def import_upstream() -> object:
    """
    機能: 118の不変入力源を固有名で読み、既存の読取・公開契約を再利用する。
    引数: なし。
    返り値: object は118入力モジュール。市場ファイルを読まず、sys.pathも変更しない。
    """
    spec = importlib.util.spec_from_file_location("_stability124_input118_source", UPSTREAM)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SOURCE = import_upstream()


def prepare(arrays: dict, info: dict, symbol: str) -> dict:
    """
    機能: 同じ原配列から因果公開足と採用現在値行の正常最良気配を作る。
    引数: arrays(dict[str,ndarray]) は118原列、info(dict) は場の固定目録、symbol(str) はTOPIX又はNK225。
    返り値: dict はbars・quotes・diagnostics・最終採用現在値とその時計。読取も書込も行わない。
    """
    assert symbol in OBSERVATION_TICK
    assert info["symbol"] == symbol
    expected = SOURCE.bounds(info["session"])
    supplied = tuple(float(value) for value in info.get("bounds", expected))
    assert supplied == expected
    made = SOURCE.prepare_session(arrays, *supplied, tick=OBSERVATION_TICK[symbol])
    price_rows = made["prices"]["raw_row_index"]
    reasons = SOURCE.book_reasons(arrays)
    selected = price_rows[reasons[price_rows] == 0]
    quotes = {
        "row": selected.astype(np.int64, copy=True),
        "seq": arrays["raw_seq"][selected].astype(np.int64, copy=True),
        "time": arrays["price_time_s"][selected].astype(np.float64, copy=True),
        "last": arrays["last"][selected].astype(np.float64, copy=True),
        "bid": arrays["bid"][selected].astype(np.float64, copy=True),
        "ask": arrays["ask"][selected].astype(np.float64, copy=True),
        "bq": arrays["bid_qty"][selected].astype(np.float64, copy=True),
        "aq": arrays["ask_qty"][selected].astype(np.float64, copy=True),
    }
    n = len(selected)
    assert all(value.shape == (n,) for value in quotes.values())
    assert np.all(np.diff(quotes["row"]) > 0)
    assert np.all(np.diff(quotes["seq"]) > 0)
    assert np.all(np.diff(quotes["time"]) >= 0)
    assert all(np.isfinite(quotes[key]).all() for key in ("time", "last", "bid", "ask", "bq", "aq"))
    assert np.all((quotes["bid"] > 0) & (quotes["bid"] < quotes["ask"]))
    assert np.all((quotes["bq"] > 0) & (quotes["aq"] > 0))
    diagnostics = dict(made["diagnostics"])
    diagnostics.update(
        accepted_price_rows=len(price_rows),
        accepted_quote_rows=n,
        accepted_price_rows_without_valid_quote=len(price_rows) - n,
        same_clock_quote_rows=int(np.count_nonzero(np.diff(quotes["time"]) == 0)),
        execution_contract="採用現在値行かつ118 book_reasons==0。判断原rowより厳密に後の正常BBOを執行担当が選ぶ。",
        observation_product=symbol,
        observation_tick=OBSERVATION_TICK[symbol],
        receiving_clock_available=False,
    )
    observed_prices = made["prices"]
    last_observed_price = float(observed_prices["last"][-1]) if len(price_rows) else float("nan")
    last_observed_time = float(observed_prices["price_time_s"][-1]) if len(price_rows) else float("nan")
    return dict(bars=made["bars"], quotes=quotes, diagnostics=diagnostics,
                last_observed_price=last_observed_price, last_observed_time=last_observed_time)


def load(info: dict, symbol: str) -> dict:
    """
    機能: 旧44列NPZ又は新JSONLを一回読み、同じ原配列から足と正常BBOを作る。
    引数: info(dict) はpath・kind・session・symbol・固定サイズ等、symbol(str) はTOPIX又はNK225。
    返り値: dict はbars・quotes・diagnostics・read_metadata・最終採用現在値と時計。原入力更新と再読を行わない。
    """
    assert symbol in OBSERVATION_TICK and info["symbol"] == symbol
    assert info["kind"] in ("old_npz", "jsonl")
    if info["kind"] == "old_npz":
        expected_digest = info.get("sha256", info.get("SHA256"))
        assert isinstance(expected_digest, str) and len(expected_digest) == 64
        assert "bytes" in info
        arrays = SOURCE.read_old(info)
        metadata = dict(
            path=info["path"], bytes=int(info["bytes"]), sha256=expected_digest,
            rows=len(arrays["raw_seq"]), reads=1,
        )
    else:
        arrays = SOURCE.read_jsonl(info)
        metadata = arrays.pop("_read_metadata")
        assert metadata["reads"] == 1
    made = prepare(arrays, info, symbol)
    metadata.update(kind=info["kind"], session=info["session"], symbol=symbol)
    made["read_metadata"] = metadata
    return made
