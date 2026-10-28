"""固定した研究153の原板観測定義と最短準備時計を、入力目録を変更せず保存する。"""

from datetime import datetime, timedelta
import json

from audit_inputs153 import HERE, ROOT, JST, fingerprint, read_json


def main() -> None:
    """原板の時刻資格と研究実装へ渡す時計上の制約を整理する。

    引数: なし。
    返り値: None。入力目録・原資料・金融会計は変更しない。
    """
    manifest_path = HERE / "入力目録153.json"
    manifest = read_json(manifest_path)
    pairs = [(60, 30), (180, 30), (300, 60), (600, 60)]
    clocks = []
    for scene in manifest["sessions"]:
        for symbol, qualification in scene["qualification"].items():
            first = qualification["first_usable_at"]
            earliest = []
            if first:
                start = datetime.fromisoformat(first)
                earliest = [{"window_seconds": window, "difference_seconds": difference,
                             "minimum_full_known_seconds": window+difference,
                             "theoretical_earliest": (start+timedelta(seconds=window+difference)).isoformat()}
                            for window, difference in pairs]
            clocks.append({"session": scene["session"], "symbol": symbol, "partial": scene["partial"],
                           "first_normal_quote": first, "earliest_slope_if_no_unknown_gap": earliest,
                           "actual_first_signal_time_measured": False})
    result = {
        "purpose": "金融再生前に固定する原板観測・資料資格。入口条件の採否や収益性は測っていない。",
        "input_manifest": fingerprint(manifest_path),
        "main": {"complete_sessions": 51, "Day": 26, "Night": 25, "symbols": ["NK225", "TOPIX"]},
        "partial": {"session": "2026-10-26_Night", "cutoff_exclusive": "2026-10-26T21:13:52+09:00", "known_not_holdout": True},
        "raw_reader": {
            "reference": "work/preus149/engine_go/main.go の loadBoards（Scene互換）",
            "clock": "CurrentPriceTime。タイムゾーンが明示された価格時計。独立の受信時計は原データにない。",
            "inclusion": "セッション開始以上・終了以下、途中cutoff排他。価格時計不明・逆行・現在値非正の行を除外する149読取基準を再利用可能。",
            "normal_quote": "Buy1がbid、Sell1がask。両価格と数量が有限の正値かつask>bid。異常BBO行は読取段階で消さず未知区間へ切り替える。",
            "tie_order": "同一市場の原行順を維持。同時計多行を平均化・1行へ潰す処理はしない。今回の両商品判断は独立。",
            "volume_clock": "TradingVolumeTime=nullは約定時計欠測であり、正常板の否定には使わない。",
            "received_model_limit": "Received=CurrentPriceTimeは研究上の模型であり実測受信時刻ではない。通信遅延・同価格時計内の実際の経過秒は今回の資料から復元できない。"},
        "time_weighted_sma": {
            "window_and_slope_difference_seconds": pairs,
            "normal_quote_hold_seconds": 120,
            "price": "正常BBO中値=(bid+ask)/2",
            "weight": "前回正常中値を次の観測時計まで区間積分。同時計の更新は経過0秒の重み。前回観測から120秒を越えて保持しない。",
            "invalid": "不正板が観測された時点から未知。正常板へ復帰しても未知区間を埋め戻さない。",
            "readiness": "W秒SMAとD秒前SMAの双方に必要なW+D秒が既知の場合だけ傾きを算出する。将来の最初の有効時刻から遡って値を埋めない。",
            "earliest_times": "以下は未知区間がなかった場合の理論下限。実際の初回判断時刻は金融再生器で別途記録する。"},
        "candles_reference_only": {
            "trading_feature_input": False,
            "timestamp_means": "足開始。closed=trueのみ完成した足として扱う。",
            "minimum_publish_time": "1分足はtime+60秒、5分足はtime+300秒より前には利用しない。",
            "legacy_publish_delay": "145/149はさらに60秒の名目公開遅延。今回は指標入力から外すため売買判定に用いない。",
            "gap": "無生成の分足区間が多数ある。約定や価格時計が進まなかった可能性もあり、通信断と断定しない。前値で架空のOHLCを追加しない。"},
        "closing": {"decision": "各セッション終了10分前に全返済判断", "fill": "判断後の次の正常BBO。終端前6分以内に正常気配がある51場を完了資格とした。",
                    "partial": "既知途中は末尾で強制精算しない。未決済含みを別表示し、51完了場の合計から除外。"},
        "clocks": clocks,
        "API_calls": 0, "financial_replays": 0,
    }
    path = HERE / "原板観測定義153.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print("DEFINITION_SHA256", fingerprint(path)["sha256"])
    print("MANIFEST_UNCHANGED", result["input_manifest"]["sha256"] == fingerprint(manifest_path)["sha256"])


if __name__ == "__main__":
    main()
