"""初期診断の四列既知条件と、実装kind5の三十秒二列条件の差を保存する。"""

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent


def main() -> None:
    """
    機能: kind5の実装条件で保存D11親を再分類し、初期診断との差だけを明示する。
    引数: なし。
    返り値: None。金融再生も完成会計の変更も行わない。
    """
    source = HERE / "第二巡D11の残存赤字と短期支持条件の取捨.json"
    data = json.loads(source.read_text(encoding="utf-8"))
    products = []
    for symbol in ("TOPIX", "NK225"):
        rows = [r for r in data["all_parents"] if r["symbol"] == symbol]
        earlier_rejected, final_rejected, differences = [], [], []
        for parent in rows:
            market, direction = parent["source_market"], parent["direction"]
            short_known = market[11] == 1 and all(market[c] is not None for c in (4, 6))
            direction_allowed = all(market[c] is not None and direction * market[c] >= -.05 for c in (4, 6))
            earlier = parent["known"] and direction_allowed
            final = short_known and direction_allowed
            if not earlier:
                earlier_rejected.append(parent)
            if not final:
                final_rejected.append(parent)
            if earlier != final:
                differences.append(dict(parent=parent, initial_allowed=earlier, final_allowed=final))
        products.append(dict(
            symbol=symbol, initial_rejected_count=len(earlier_rejected),
            initial_rejected_net=sum(r["net"] for r in earlier_rejected),
            actual_kind5_rejected_count=len(final_rejected),
            actual_kind5_rejected_wins=sum(r["net"] > 0 for r in final_rejected),
            actual_kind5_rejected_losses=sum(r["net"] < 0 for r in final_rejected),
            actual_kind5_rejected_net=sum(r["net"] for r in final_rejected),
            differences=differences,
        ))
    target = HERE / "第三巡kind5実定義と初期分類の差.json"
    assert not target.exists()
    target.write_text(json.dumps(dict(
        passed=True, products=products,
        rule="current_known=1、自己30秒と相手30秒だけ有限、双方の方向付き差>=−0.05ATR。120秒列の欠測は追加拒否しない。",
        source=dict(path=str(source), sha256=hashlib.sha256(source.read_bytes()).hexdigest()),
        adapter_source_sha256=hashlib.sha256((HERE.parent / "adapter3.py").read_bytes()).hexdigest(),
        producer_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        financial_replays=0, original_market_reads=0, API=0,
        caution="保存親の実条件別分類。第三巡の全経路会計とは区別する。",
    ), ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(products, ensure_ascii=False))


if __name__ == "__main__":
    main()
