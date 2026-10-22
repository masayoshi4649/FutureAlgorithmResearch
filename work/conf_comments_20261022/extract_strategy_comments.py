"""設定コメント確認用に、戦略の全上書きキーと既定値を原コードから抽出する。"""

from pathlib import Path
import json
import re


def scalar(value: str) -> int | float | bool:
    """機能: Go の数値・真偽値を読む。

    引数: value(str) はリテラル。
    返り値: int | float | bool は同値の値。
    """
    value = value.strip()
    if value in {"true", "false"}:
        return value == "true"
    number = float(value)
    return int(number) if number.is_integer() else number


def main() -> None:
    """機能: 63 キーの定義・既定値・制約を JSON とテキストへ保存する。

    引数: なし。
    返り値: None。原コードは変更しない。
    """
    output = Path(__file__).resolve().parent
    root = output.parent.parent
    types_path = root / "App/SessionTrader/internal/strategy/types.go"
    features_path = root / "App/SessionTrader/internal/e01/features.go"
    text = types_path.read_text(encoding="utf-8")
    features = features_path.read_text(encoding="utf-8")
    sources = {"features": features, "day": text, "night": text, "extra": text}
    classes = {"features": "FeatureConfig", "day": "DayParameters", "night": "NightParameters", "extra": "ExtraParameters"}
    paths = {"features": features_path, "day": types_path, "night": types_path, "extra": types_path}
    fields = {}
    defaults = {}
    default_lines = {}
    field_offsets = {}
    for group, cls in classes.items():
        source = sources[group]
        block = re.search(r"type " + cls + r" struct \{(.*?)\n\}", source, re.S)
        fields[group] = re.findall(r'\s*(\w+)\s+(int|float64|bool)\s+`[^`]*toml:"([^"]+)"', block.group(1))
        field_offsets[group] = block.start(1)
        if group == "features":
            match = re.search(r"return FeatureConfig\{([^}]+)\}", source)
            values = dict(re.findall(r"(\w+):\s*([^,}]+)", match.group(1)))
            defaults[group] = {field: scalar(values[field]) for field, _, _ in fields[group]}
        else:
            match = re.search(r"\b" + group.capitalize() + r":\s*" + cls + r"\{([^}]+)\}", source)
            values = match.group(1).split(",")
            assert len(values) == len(fields[group])
            defaults[group] = {field[0]: scalar(value) for field, value in zip(fields[group], values)}
        default_lines[group] = source.count("\n", 0, match.start()) + 1

    # ----------------------------------------
    # 説明は利用箇所を直接読み、無効化とゼロ幅を区別する。
    notes = {
        "features.atr_period": "5分足 TR を平滑化する期間。係数は1/期間。整数1以上。",
        "features.atr_min_bars": "ATRを公開するまでに必要な当場5分確定足数。整数1以上。ATR自体の最低幅はラージ2tick。",
        "features.ema_fast": "1分足終値の短期EMA期間。整数1以上。",
        "features.ema_slow": "1分足終値の長期EMA期間。整数で短期期間以上。指定本数未満は方向未確定。",
        "features.slope_bars": "長期EMAの傾きを比べる過去1分足本数。整数1以上。",
        "features.gap_atr": "短期EMAと長期EMAの差を方向成立とみなすATR倍率。0でも同値では成立しない。",
        "features.slope_atr": "現在と指定本数前の長期EMA差を方向成立とみなすATR倍率。",
        "features.candle_delay_seconds": "1分足・5分足の終了から指標名目公開までの追加秒数。実受信が遅ければ実受信まで待つ。0は追加待機なし。",
        "features.peer_delay_seconds": "相手市場のEMA方向へ加える公開待機秒数。夜間独自履歴の固定60秒追加待機には作用しない。",
        "features.warmup_seconds": "場開始から二市場共通方向を許可するまでの秒数。日中注文器のwarmupも別に満たす。",
        "features.support_atr": "30秒中値変化が主方向を支持するとみなすATR倍率。厳密な超過判定。",
        "features.support_expiry_seconds": "直近の短期支持が有効な秒数。0は無効化でなく支持の寿命0。",
        "features.adverse_long_atr": "120秒中値変化を逆行候補とするATR倍率。最低ラージ2tick。",
        "features.adverse_short_atr": "30秒中値変化を逆行候補とするATR倍率。最低ラージ1tick。120秒側と同方向成立が必要。",
        "day.warmup_seconds": "場開始から日中の追跡新規を準備できるまでの秒数。特徴量の準備・方向確定も別途必要。0以上。",
        "day.cooldown_seconds": "内部E01の通常・早期返済モデルそれぞれの全返済後、新規準備を再許可する待機秒数。0以上。",
        "day.pending_seconds": "内部の追跡新規条件の有効秒数。取消・失効後は新しい方向判断で再準備。正数。実注文期限とは別。",
        "day.entry_cutoff_seconds": "ForceCloseより何秒前から日中主担当の新規準備・発火を止めるか。0以上。",
        "day.max_hold_seconds": "内部E01の新規から経過すると返済条件を作る秒数。正数。0で制限解除は不可。",
        "day.entry_atr": "追跡安値/高値から新規成立方向へ戻すATR倍率。新規準備時ATR基準。正数。",
        "day.normal_risk_atr": "内部E01の通常モデルで、初期枚数×初期ATRに対する組全体の損失許容倍率。正数。",
        "day.tight_risk_atr": "内部E01の早期返済モデルに用いる組損失幅のATR倍率。正数。",
        "day.trail_arm_atr": "内部E01で極値の順行幅がこのATR倍率以上になれば追跡床を開始。正数。",
        "day.normal_trail_atr": "内部E01通常モデルの極値から戻す追跡幅のATR倍率。正数。",
        "day.tight_arm_atr": "早期返済モデルが狭い追跡幅へ切り替える順行ATR倍率。trail_arm条件も必要。正数。",
        "day.tight_trail_atr": "早期返済モデルが切替後に用いる追跡戻り幅のATR倍率。正数。",
        "day.split_atr": "内部E01の初回部分利確水準の初期ATR倍率。2枚以上なら一度だけ概ね半分。正数。",
        "day.risk_floor": "現在ATRが縮んだとき実玉の組損切り許容幅も縮める際の下限比率。0より大きく1以下。1ならこの縮小なし。",
        "day.weak_support": "新規時に両市場の方向付き30秒変化へ要求する下限。各市場ATR単位。負数なら軽微な逆行を許す。有限なら負数も可。",
        "day.quote_spread_atr": "新規時に許す売買気配差の初期ATR倍率。0は新規不成立になり得る。",
        "day.quote_distance_atr": "新規側の気配価格が現在値より不利に離れる幅の初期ATR倍率。絶対距離ではない。",
        "day.withdrawal_atr": "約定後最初の正常観測を基点として両市場とも逆行したとするATR倍率。0は微小逆行を対象。",
        "day.persistence_seconds": "上記両市場逆行が続いたとき撤退する秒数。TOPIX120/NK22560。0は成立観測で撤退。",
        "day.maximum_gap_seconds": "正常な自己観測の間隔がこの秒数を超えれば逆行継続時計をリセット。通信の強制返済猶予とは別。",
        "night.retest": "0=進行確認型、1=突破→戻り→再反発の確認型。0/1のみ。TOPIX既定0、NK225既定1。",
        "night.stop_r": "夜間主担当の初期損切り幅。R=max(新規準備時ATR,minimum_ticks×ラージ呼値)。正数。",
        "night.trail_start_r": "返済側気配での最大含み益がRの何倍なら追跡床を作るか。0なら新規直後から候補。",
        "night.trail_width_r": "最大含み益から戻す追跡幅のR倍率。0は幅0であり追跡無効ではない。",
        "night.cooldown_seconds": "夜間主担当の実玉が全部返済された後の再新規待機秒数。0で追加待機なし。",
        "night.quiet_seconds": "米国現物開始の前後それぞれに置く主担当静観秒数。主担当の新規を止め残玉返済。追加担当は対象外。0は空区間。",
        "night.post_open_prepare_seconds": "米国現物開始から夜間主担当の新規準備を始めるまでの秒数。静観後からの秒数ではない。",
        "night.minimum_ticks": "夜間主担当Rの下限となるラージ呼値の数。0ならATRだけが下限。小数可。",
        "night.efficiency": "20分間の始終差絶対値÷各1分差絶対値の合計が、突破準備に必要な下限。0以上、1超も設定上通るが成立しない。",
        "night.quote_spread_r": "夜間の突破準備・発注に許す気配差のR倍率。",
        "night.quote_distance_r": "夜間判断価格から売/買各気配までの最大距離のR倍率。確認型は現在値、再試験型は中値を使う。",
        "night.arm_lifetime_seconds": "突破の準備から新規成立を待てる秒数。0は原則次時刻に寿命切れ。",
        "night.confirm_seconds": "突破準備から発注まで最低限待つ秒数。0でも別の観測で確認する。",
        "night.boundary_break_r": "突破境界の逆方向へRの何倍動けば準備取消/保有撤退候補となるか。保有撤退は相手20分逆方向も必要。",
        "night.bounce_r": "再試験型で戻り極値から再反発を必要とするR倍率。確認型では不使用。",
        "night.progress_r": "確認型で突破境界から順行進行を必要とするR倍率。再試験型では不使用。",
        "night.retest_progress_r": "再試験型の第1段階で突破境界から必要とする順行R倍率。",
        "night.retest_return_r": "再試験型の第2段階で突破境界からの順行距離がこのR倍率以下へ戻る必要がある。",
        "night.long_support_r": "確認型の新規時に両市場それぞれの120秒変化へ要求する方向付きATR倍率。厳密な超過判定。入口Rではなく各市場ATR単位。",
        "night.long_opposition_r": "再試験型で両市場120秒変化がともにこの倍率を超えて逆行なら拒否。各市場ATR単位。両方既知のときだけ使用。",
        "extra.style": "0=両市場5分/20分変化の符号票、1=両市場の当場始値比の符号票を優先。どちらも同票時の補助判定あり。整数0/1。",
        "extra.stop_r": "未参加補完玉の初期損切りR倍率。正数。Rは新規時ATR・20分高低幅×係数・最低tick幅の最大。",
        "extra.trail_start_r": "未参加補完玉の追跡開始R倍率。TOPIX夜1.25/NK225夜0.75/昼1。0は追跡無効でない。",
        "extra.trail_width_r": "未参加補完玉の最大含み益から戻すR倍率。TOPIX夜0.75/その他0.5。0は幅0。",
        "extra.minimum_ticks": "未参加補完玉Rの下限となるラージ呼値の数。0なら他の幅だけ、小数可。",
        "extra.band_fraction": "公開済み21個の1分末観測から作る20分高低幅に掛けるR下限係数。0なら当該下限なし。",
        "extra.quote_spread_r": "未参加補完の新規時に許す売買気配差のR倍率。",
        "extra.entry_cutoff_seconds": "ForceClose前に補完担当の新規を止める秒数。schedule.extra_cutoff_secondsを上書き。Day/Night主担当には不使用。0以上。",
        "extra.budget_ticks": "補完枚数を縮めるリスク予算のラージtick数。q=max(1,min(上限,切捨て(上限×予算tick幅/R)))。0は予算縮小なし。NK225夜のみ既定12。",
    }
    rows = []
    for group, members in fields.items():
        for field, kind, tag in members:
            key = f"{group}.{tag}"
            default = defaults[group][field]
            values = {f"{ref}/{session}": default for ref in ["TOPIX", "NK225"] for session in ["Day", "Night"]}
            if key == "day.persistence_seconds":
                values.update({"NK225/Day": 60, "NK225/Night": 60})
            if key == "night.retest":
                values.update({"NK225/Day": True, "NK225/Night": True})
            if key == "extra.style":
                values["TOPIX/Night"] = 0
            if key == "extra.trail_start_r":
                values.update({"TOPIX/Night": 1.25, "NK225/Night": .75})
            if key == "extra.trail_width_r":
                values["TOPIX/Night"] = .75
            if key == "extra.budget_ticks":
                values["NK225/Night"] = 12
            if key == "extra.entry_cutoff_seconds":
                values = {k: "schedule.extra_cutoff_seconds（既定600）" for k in values}
            source = sources[group]
            declaration = re.search(r"^\s*" + field + r"\s+(?:int|float64|bool)\s+`", source[field_offsets[group]:], re.M)
            line = source.count("\n", 0, field_offsets[group] + declaration.start()) + 1
            while source.splitlines()[line - 1].strip() == "":
                line += 1
            relative = paths[group].relative_to(root).as_posix()
            rows.append({"キー": key, "型": kind, "既定値": values, "説明と制約": notes[key], "定義": f"{relative}:{line}", "既定値定義": f"{relative}:{default_lines[group]}"})
    assert len(rows) == len(notes) == 63
    metadata = {"用途": "読取レビュー。アプリ本体変更なし。全63キーをコード定義から抽出。", "共通制約": "キーは引用符付き部門.変数。有限数値のみ。boolはtrue/falseではなく数値0/1。整数項目は小数不可。値は宣言された部門全体へ適用され、銘柄/昼夜の個別既定差を上書きする。", "係数の基本範囲": "原則0以上。day.weak_supportのみ負数可。day内部E01の幅・pending・max_holdは正数、day.risk_floorは0超1以下、night.stop_r/extra.stop_rは正数。期間整数は1以上。", "注意": "night欄は夜主担当、day欄は昼主担当だけで使用。featuresの一部は日中E01向けで、夜間独自履歴の窓・公開待機は別の固定仕様。extraは追加ピラミッドでなく未参加時の補完。", "一覧": rows}
    (output / "戦略上書き63キーと既定値.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [metadata["用途"], metadata["共通制約"], metadata["係数の基本範囲"], metadata["注意"], ""]
    for row in rows:
        lines.extend([row["キー"], "  既定: " + " / ".join(f"{key}={value}" for key, value in row["既定値"].items()), "  " + row["説明と制約"], "  定義: " + row["定義"] + " / 既定: " + row["既定値定義"], ""])
    (output / "戦略上書き63キーと既定値.txt").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"件数": len(rows), "保存先": str(output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
