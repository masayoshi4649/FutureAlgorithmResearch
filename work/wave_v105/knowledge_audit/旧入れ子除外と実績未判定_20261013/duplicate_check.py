"""手法名や成績を除き、明示された実行仕様の重複を純Pythonで比較する。"""

import hashlib
import json
import math


PARTS = ("entry", "management", "exit", "allocation", "costs", "execution", "data", "implementation")
LABELS = dict(zip(PARTS, ("入口", "途中判断", "出口", "枚数と配分", "費用", "約定", "データ", "実装版")))
UNKNOWN_MARKERS = {"unknown", "null", "none", "未登録", "不明", "未定", "未取得", "unknown/null"}
METADATA_KEYS = {"id", "ID", "name", "名前", "手法名", "説明", "description", "結果", "result", "results"}


# ----------------------------------------
def _without_metadata(value: object) -> object:
    """
    機能: ID・名称・説明・結果を位置にかかわらず指紋対象から除く。
    引数: value(object)は提案又は過去仕様。
    返り値: objectは経済条件だけの新構造。入力自体は変更しない。
    """
    if isinstance(value, dict):
        return {key: _without_metadata(child) for key, child in value.items() if key not in METADATA_KEYS}
    if isinstance(value, list):
        return [_without_metadata(child) for child in value]
    return value


# ----------------------------------------
def _issues(value: object, path: str) -> list[str]:
    """
    機能: 構造データの欠落、不明値、非JSON値を位置付きで調べる。
    引数: value(object)は仕様の一部分、path(str)は日本語表示用の位置。
    返り値: list[str]は不完全な箇所。空ならこの部品の明示値を正規化できる。
    """
    if value is None:
        return [f"{path}: nullは未確定です"]
    if isinstance(value, bool):
        return []
    if isinstance(value, int):
        return []
    if isinstance(value, float):
        return [] if math.isfinite(value) else [f"{path}: NaN又は無限大を拒否しました"]
    if isinstance(value, str):
        if not value.strip() or value.strip().casefold() in UNKNOWN_MARKERS:
            return [f"{path}: 空文字又は未登録の不明値です"]
        return []
    if isinstance(value, dict):
        if not value:
            return [f"{path}: 空の構造データです"]
        result = []
        for key, child in value.items():
            if not isinstance(key, str) or not key.strip():
                result.append(f"{path}: 辞書のキーは空でない文字列が必要です")
                continue
            result.extend(_issues(child, f"{path}.{key}"))
        return result
    if isinstance(value, list):
        if not value:
            return [f"{path}: 空の構造データです"]
        return [issue for index, child in enumerate(value) for issue in _issues(child, f"{path}[{index}]")]
    return [f"{path}: JSONの構造データではありません（{type(value).__name__}）"]


# ----------------------------------------
def canonical(value: object) -> str:
    """
    機能: 辞書順に依存せず、配列順とJSON型を保持した正規文字列を作る。
    引数: value(object)は確定したJSON構造データ。
    返り値: strはUTF-8指紋の入力。boolと数値、整数と小数は別表記を保つ。
    """
    issues = _issues(value, "仕様")
    if issues:
        raise ValueError(" / ".join(issues))
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


# ----------------------------------------
def _spec(value: object) -> tuple[dict | None, list[str]]:
    """
    機能: proposal又はtrialから8部品だけの完全な仕様を取り出す。
    引数: value(object)はspecを持つ記録、又は8部品そのもの。
    返り値: tuple[dict | None,list[str]]は採用仕様と欠落理由。名前や結果は採用しない。
    """
    if not isinstance(value, dict):
        return None, ["記録は辞書である必要があります"]
    source = value.get("spec") if "spec" in value else value
    if not isinstance(source, dict):
        return None, ["specは8部品の辞書である必要があります"]
    source = _without_metadata(source)
    missing = [LABELS[key] for key in PARTS if key not in source]
    issues = ["必須部品がありません: " + "、".join(missing)] if missing else []
    extra = sorted(str(key) for key in source if key not in PARTS)
    if extra:
        issues.append("spec内の未分類項目は8部品へ配置してください: " + "、".join(extra))
    for key in PARTS:
        if key not in source:
            continue
        part = source[key]
        if not isinstance(part, (dict, list)):
            issues.append(f"{LABELS[key]}: 非空の辞書又は配列が必要です")
        issues.extend(_issues(part, LABELS[key]))
    return ({key: source[key] for key in PARTS}, []) if not issues else (None, issues)


# ----------------------------------------
def _digest(value: object) -> str:
    """
    機能: 正規JSONのUTF-8バイト列のSHA256を計算する。
    引数: value(object)は確定したJSON構造データ。
    返り値: strは64桁の指紋。名前や結果の取り込みは呼出元で防ぐ。
    """
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def _fingerprints(spec: dict) -> dict:
    """
    機能: 完全仕様と各部品の正規JSONをSHA256へ変換する。
    引数: spec(dict)は8部品の確定仕様。
    返り値: dictは全体指紋と部品指紋。仕様データを変更しない。
    """
    return {"全体": _digest(spec), "部品": {key: _digest(spec[key]) for key in PARTS}}


# ----------------------------------------
def _difference(left: object, right: object, path: str) -> list[dict]:
    """
    機能: 型を含む値の違いを、日本語の部品位置と変更前後で記録する。
    引数: left/right(object)は比較仕様、path(str)は日本語の位置。
    返り値: list[dict]は条件差の詳細。配列は順序のある一部品として比較する。
    """
    if canonical(left) == canonical(right):
        return []
    if isinstance(left, dict) and isinstance(right, dict):
        result = []
        for key in sorted(set(left) | set(right)):
            current = f"{path}.{key}"
            if key not in left:
                result.append({"位置": current, "変更": "新規項目", "過去": "項目なし", "提案": right[key]})
            elif key not in right:
                result.append({"位置": current, "変更": "項目削除", "過去": left[key], "提案": "項目なし"})
            else:
                result.extend(_difference(left[key], right[key], current))
        return result
    return [{"位置": path, "変更": "型又は値の差", "過去": left, "提案": right}]


# ----------------------------------------
def analyze(proposal: dict, trials: list[dict]) -> dict:
    """
    機能: 8部品の実行仕様で、再利用・新データ・実装差・条件差を判定する。
    引数: proposal(dict)は提案spec、trials(list[dict])は既存の試行記録。
    返り値: dictは日本語の判定と指紋・部品差。不完全な過去は重複なしの証明にしない。
    """
    if not isinstance(trials, list):
        raise TypeError("trialsは既存試行の配列である必要があります")
    proposed, issues = _spec(proposal)
    result = {"仕様版": 1, "提案完全": proposed is not None, "提案不完全理由": issues,
        "判定": "提案仕様が不完全です", "比較": [], "完全同一": [], "不完全な過去試行": [],
        "比較可能件数": 0, "再利用可能": False, "重複なしの証明": False,
        "限界": "入力に登録された明示仕様の比較です。未記載ルール、未登録試行、結果の正しさは検証しません。"}
    result.update(proposal_complete=result["提案完全"], matches=[], incomplete_history=result["不完全な過去試行"])
    if proposed is None:
        return result
    fingerprints = _fingerprints(proposed)
    result["提案指紋"] = fingerprints
    for index, trial in enumerate(trials):
        old, reasons = _spec(trial)
        ref = {"番号": index, "ID": str(trial.get("id", trial.get("ID", f"既存{index}")))} if isinstance(trial, dict) else {"番号": index}
        if old is None:
            result["不完全な過去試行"].append({"記録": ref, "理由": reasons, "扱い": "未照合。重複していない根拠には使いません"})
            continue
        old_fingerprints = _fingerprints(old)
        changed = [key for key in PARTS if fingerprints["部品"][key] != old_fingerprints["部品"][key]]
        if not changed:
            category, action = "完全同一", "既存結果を再利用する"
            result["完全同一"].append(ref)
        elif changed == ["data"]:
            category, action = "新データ", "同条件で新しい又は変更されたデータの範囲を検証する"
        elif changed == ["implementation"]:
            category, action = "実装差", "実装変更の理由と経済同値又は修正の必要性を説明する"
        elif set(changed) <= {"data", "implementation"}:
            category, action = "データ及び実装差", "新データと実装修正の範囲を分けて説明する"
        else:
            category, action = "条件差", "変えたルール部品と理由を登録する"
        differences = [detail for key in changed for detail in _difference(old[key], proposed[key], LABELS[key])]
        result["比較"].append({"記録": ref, "判定": category, "推奨": action,
            "過去指紋": old_fingerprints, "変更部品": [LABELS[key] for key in changed], "部品差": differences})
        result["matches"].append({"id": ref.get("ID", f"既存{index}"),
            "kind": "実装差" if category == "データ及び実装差" else category,
            "index": index, "詳細分類": category, "推奨": action,
            "過去指紋": old_fingerprints, "変更部品": [LABELS[key] for key in changed], "部品差": differences})
    result["比較可能件数"] = len(result["比較"])
    result["再利用可能"] = bool(result["完全同一"])
    if result["再利用可能"]:
        result["判定"] = "完全同一の登録試行があり、既存結果を再利用できます"
    elif result["不完全な過去試行"]:
        result["判定"] = "比較可能な試行に完全同一はありませんが、不完全な過去試行があり未照合です"
    elif not trials:
        result["判定"] = "登録試行がありません。過去の未登録試行との重複は未確認です"
    else:
        result["判定"] = "入力の完全な登録試行の範囲では完全同一はありません"
    result["note"] = result["判定"] + "。" + result["限界"]
    return result
