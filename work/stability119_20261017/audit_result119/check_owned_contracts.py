"""原本を再読せず、私有保全cacheの原row・正常気配・場末条件を補助照合する。"""

from datetime import datetime, timedelta, timezone
import hashlib
from io import BytesIO
import json
from pathlib import Path

import numpy as np


def main() -> None:
    """
    機能: 私有保全80preparedだけで凍結入力契約と閉場正常2原rowを検査する。
    引数: なし。
    返り値: None。市場原本・measurement cache原本・金融エンジンには接続しない。
    """
    here = Path(__file__).resolve().parent
    assert (here / "集約型停止後の保存会計復元と独立照合の証跡.json").is_file()
    checks = 0
    records = []
    for path in sorted((here / "recovered_owned/prepared").glob("*/*.npz")):
        payload = path.read_bytes()
        with np.load(BytesIO(payload), allow_pickle=False) as saved:
            q = {key[8:]: saved[key].copy() for key in saved.files if key.startswith("quotes__")}
            b = {key[6:]: saved[key].copy() for key in saved.files if key.startswith("bars__")}
        for key in ("row", "seq"):
            assert q[key].dtype == np.int64 and np.all(np.diff(q[key]) > 0)
            checks += 1
        assert np.all(np.diff(q["time"]) >= 0)
        checks += 1
        for key in ("time", "last", "bid", "ask", "bq", "aq"):
            assert np.isfinite(q[key]).all()
            checks += 1
        assert np.all((q["last"] > 0) & (q["bid"] > 0) & (q["bid"] < q["ask"]) & (q["bq"] > 0) & (q["aq"] > 0))
        checks += 1
        assert np.all(np.diff(b["t_s"]) == 60.)
        checks += 1
        valid = b["valid"]
        assert np.isfinite(b["anchor"][valid]).all() and np.all(b["pub_raw_row"][valid] >= 0)
        checks += 1
        assert np.all(b["pub_price_time_s"][valid] >= b["t_s"][valid])
        checks += 1
        assert np.all(np.diff(b["pub_price_time_s"][valid]) >= 0) and np.all(np.diff(b["pub_raw_row"][valid]) >= 0)
        checks += 1
        date, kind = path.stem.rsplit("_", 1)
        day = datetime.fromisoformat(date).replace(tzinfo=timezone(timedelta(hours=9)))
        close = day.replace(hour=15, minute=20) if kind == "Day" else (day + timedelta(days=1)).replace(hour=5, minute=40)
        after = np.flatnonzero(q["time"] >= close.timestamp())
        assert len(after) >= 2 and q["row"][after[1]] > q["row"][after[0]]
        checks += 1
        records.append(dict(symbol=path.parent.name, session=path.stem,
                            SHA256=hashlib.sha256(payload).hexdigest(), 場末後正常原row数=len(after)))
    assert len(records) == 80
    proof = dict(全合格=True, 検査数=checks, 私有保全prepared参照=80, measurement原本再読=0,
                 市場原本読取=0, 金融再生=0, 原row重複と逆行なし=True, 気配正常=True,
                 全80場で閉場後正常2原row=True, records=records,
                 源SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    output = here / "私有保全コピーによる正常原rowと場末二観測保証の補助照合.json"
    assert not output.exists()
    output.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in proof.items() if key != "records"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
