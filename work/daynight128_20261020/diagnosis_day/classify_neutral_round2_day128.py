"""短期の停止と逆行を分けた追加仮説を、既存親の分類として保存する。"""

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent


def main() -> None:
    """
    機能: 既存D11親の両市場三十秒変化を、中立許容条件で分類する。
    引数: なし。
    返り値: None。条件変更後の売買は再生せず、分類結果だけ保存する。
    """
    source = HERE / "第二巡D11の残存赤字と短期支持条件の取捨.json"
    data = json.loads(source.read_text(encoding="utf-8"))
    classifications = []
    for symbol in ("TOPIX", "NK225"):
        parents = [r for r in data["all_parents"] if r["symbol"] == symbol]
        rejected = []
        for parent in parents:
            market, direction = parent["source_market"], parent["direction"]
            allowed = parent["known"] and all(
                market[c] is not None and direction * market[c] >= -.05 for c in (4, 6))
            if not allowed:
                rejected.append(parent)
        classifications.append(dict(
            symbol=symbol, condition="二市場が既知で、両方の方向付き30秒差が−0.05ATR以上。ゼロ変化は許す。",
            rejected_parents=rejected, count=len(rejected),
            wins=sum(r["net"] > 0 for r in rejected), losses=sum(r["net"] < 0 for r in rejected),
            saved_parent_net=sum(r["net"] for r in rejected),
            caution="保存親の条件分類であり、新たな運転の改善収支ではない。",
        ))
    target = HERE / "第二巡D11で中立と逆行を分けた保存親分類.json"
    assert not target.exists()
    target.write_text(json.dumps(dict(
        passed=True, classifications=classifications,
        source=dict(path=str(source), sha256=hashlib.sha256(source.read_bytes()).hexdigest()),
        producer_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        financial_replays=0, original_market_reads=0, API=0,
    ), ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
