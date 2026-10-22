"""第二巡で新しく生まれた入口の、価格悪化と勝ち反例を保存分類する。"""

import hashlib

from diagnose_entry130 import HERE, read, save


def main() -> None:
    """
    機能: 全新親を分母に、直前の同方向元親より不利でも勝った例を分離する。
    引数: なし。
    返り値: None。金融再生を行わず、凍結済み診断JSONは変更しない。
    """
    source = HERE / "第二巡の入口見送り後の全親差分.json"
    data = read(source)
    rows = []
    for account in data["accounts"]:
        for pair in account["pairs"]:
            if pair["kind"] != "新しい入口経路の親":
                continue
            new, old = pair["new"], pair["previous_same_side_old"]
            adverse = new["side"] * (new["entry"] - old["entry"]) if old else None
            rows.append(dict(method=account["method"], session=account["session"], symbol=account["symbol"],
                new=new, previous_same_side_old=old, during_old_parent=pair["during_old_parent"],
                adverse_entry_points=adverse,
                previous_failed_activity=bool(old and not old["activity_accepted"])))
    groups = []
    for method in ("W07", "W08"):
        for symbol in ("TOPIX", "NK225"):
            allrows = [r for r in rows if r["method"] == method and r["symbol"] == symbol]
            subset = [r for r in allrows if r["previous_failed_activity"] and r["adverse_entry_points"] > 0.]
            groups.append(dict(method=method, symbol=symbol, all_new_parents=len(allrows),
                adverse_after_failed_old=len(subset), wins=sum(r["new"]["net"] > 0 for r in subset),
                losses=sum(r["new"]["net"] < 0 for r in subset),
                net=sum(r["new"]["net"] for r in subset),
                all_new_net=sum(r["new"]["net"] for r in allrows)))
    save(HERE / "第二巡の遅い参加と勝ち反例の補足.json", dict(financial_replays=0, rows=rows, groups=groups,
        source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        qualification="新方式でのみ発生した親。直前の同方向元親が活動不適格、かつ約定値がその元親より不利。",
        limits="最初の発注資格済み見送り候補又は固定境界の失効は復元していない。第四巡の価格記録基準と同一ではなく、各親が除去されるとは断定しない。旧親は複数の新親の比較対象になる場合がある。"))
    print(groups)


if __name__ == "__main__":
    main()
