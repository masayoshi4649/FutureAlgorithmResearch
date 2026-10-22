"""原版Ｅ０１の入口と通常影を維持する、結果を見る前の十六条件。"""

from copy import deepcopy


def catalog():
    """
    機能: 原版対照・単機構九条件・統合六条件を返す。
    引数: なし。
    返り値: list[dict[str, object]]。金融計算や入力読取りは行わない。
    """
    base = {
        "mask": 0,
        "time_mode": "none",
        "changes": {},
        "reentry_mode": "shadow",
        "cooldown_seconds": 300.0,
        "fee_per_side": 0.0,
        "protect_start_atr": 0.0,
        "protect_keep_fraction": 0.5,
        "protect_require_opposition": True,
        "protect_window_seconds": 30.0,
        "protect_long_window_seconds": 120.0,
        "protect_short_opposition_atr": 0.05,
        "protect_long_opposition_atr": 0.1,
        "protect_only_raise_during_opposition": True,
        "rearm_mode": "none",
        "rearm_window_seconds": 30.0,
        "rearm_progress_atr": 0.0,
        "rearm_support_atr": 0.05,
        "session_loss_r": 0.0,
        "peer_freshness_seconds": 15.0,
        "increase_positions": False,
        "restore_positions": False,
        "force_first_entry": False,
    }
    candidates = []

    # ----------------------------------------
    # 単独機構は必ず原版へ一つだけ加え、出口と入口の効果を分ける。
    definitions = [
        ("E01", "原版Ｅ０１", {}, "原版"),
        ("P01", "二市場逆行時に一リスク以上の利益を保全", {"protect_start_atr": 1.0}, "条件付き利益保全"),
        ("P02", "二市場逆行時に一・五リスク以上の利益を保全", {"protect_start_atr": 1.5}, "条件付き利益保全"),
        ("P03", "二市場逆行時に二リスク以上の利益を保全", {"protect_start_atr": 2.0}, "条件付き利益保全"),
        ("A01", "損失後は両市場の新しい四分の一幅進行で再参加", {"rearm_mode": "loss_anchor", "rearm_progress_atr": 0.25}, "損失後の根拠更新"),
        ("A02", "損失後は両市場の新しい半幅進行で再参加", {"rearm_mode": "loss_anchor", "rearm_progress_atr": 0.5}, "損失後の根拠更新"),
        ("A03", "損失後は両市場の新しい四分の三幅進行で再参加", {"rearm_mode": "loss_anchor", "rearm_progress_atr": 0.75}, "損失後の根拠更新"),
        ("L01", "場の清算損が初回一・五リスクなら終了", {"session_loss_r": 1.5}, "場の損失予算"),
        ("L02", "場の清算損が初回二・二五リスクなら終了", {"session_loss_r": 2.25}, "場の損失予算"),
        ("L03", "場の清算損が初回三リスクなら終了", {"session_loss_r": 3.0}, "場の損失予算"),
        ("I01", "利益保全と損失後の根拠更新", {"protect_start_atr": 1.0, "rearm_mode": "loss_anchor", "rearm_progress_atr": 0.25}, "二機構統合"),
        ("I02", "利益保全と場の損失予算", {"protect_start_atr": 1.0, "session_loss_r": 2.25}, "二機構統合"),
        ("I03", "損失後の根拠更新と場の損失予算", {"rearm_mode": "loss_anchor", "rearm_progress_atr": 0.25, "session_loss_r": 2.25}, "二機構統合"),
        ("I04", "三機構の標準統合", {"protect_start_atr": 1.0, "rearm_mode": "loss_anchor", "rearm_progress_atr": 0.25, "session_loss_r": 2.25}, "三機構統合"),
        ("I05", "三機構の広い予算と深い確認", {"protect_start_atr": 1.5, "rearm_mode": "loss_anchor", "rearm_progress_atr": 0.5, "session_loss_r": 3.0}, "三機構統合"),
        ("I06", "三機構の遅い保全と狭い場予算", {"protect_start_atr": 2.0, "rearm_mode": "loss_anchor", "rearm_progress_atr": 0.75, "session_loss_r": 1.5}, "三機構統合"),
    ]
    for identifier, label, changes, mechanism in definitions:
        item = deepcopy(base)
        item.update(changes)
        item.update(id=identifier, name=label, mechanism=mechanism)
        candidates.append(item)
    assert len(candidates) == 16
    assert len({item["id"] for item in candidates}) == 16
    return candidates


def specification():
    """
    機能: 条件の単位・時計・順序と反証の要点を返す。
    引数: なし。
    返り値: dict[str, object]。実装承認前の固定仕様案。
    """
    return {
        "状態": "親の実装採用と金融前固定に供する仕様案。金融実行は零。",
        "対象": "全四十一既知場。原版Ｅ０１、少額Ｅ０１ではない。",
        "通常入口": "原版の維持方向一致と短期支持、四分の一初回ＡＴＲ追跡新規。開始条件の再要求は加えない。",
        "通常途中出口": "元の半量利確、悪化半減、出口影四分の三ＡＴＲ、段階追尾、三百六十分期限、場末を維持。",
        "数量": "初回ＴＯＰＩＸミニ五枚・日経マイクロ十枚、片方向上限十枚・二十枚。追加・復元なし。",
        "費用": "手数料零。価格モデルは親の共通金融固定に従い、気配差・次観測悪化を隠さない。",
        "組リスク": "初回受理数量×初回準備時ＡＴＲ×商品円倍率を一リスクとし、その組内では固定。四分の三損失枠そのものを一リスクとは呼ばない。",
        "場リスク": "その場で最初に成立した実組の一リスクを場終了まで固定。後から小さいＡＴＲへ差替えない。",
        "利益保全": "実現済み部分返済と残玉清算を足す実組損益の既知最高値が閾値に達し、かつ新規後に更新された両市場で三十秒Last方向差がマイナス〇・〇五ＡＴＲ未満、百二十秒Last差がマイナス〇・一ＡＴＲ未満の時だけ、利益床を既知最高益の半分へ上げる。以前の床を下げない。両市場反対が消えた時は床を維持し、新しい最高益だけでは床を上げない。",
        "利益床の実行": "当行で作った床を過去へ遡及しない。既に床を割っていれば次の有効観測で返済予約する。未割れなら次観測以降に監視する。床価格での返済保証はない。",
        "損失アンカー": "実組が全返済して損益負になった方向だけを再参加制限。全返済行より後の自己原資料と、全返済時計より後かつ自己より厳密過去の相手原資料が初めて揃った時の各Lastと各公表ＡＴＲを固定する。",
        "再参加解除": "同方向について、通常影終了と五分休止を満たし、両Lastが各固定アンカーから指定ＡＴＲ以上順行し、両市場でアンカー後に収まる三十秒窓のLast方向差が〇・〇五ＡＴＲを超えた時、次観測から制限解除。その後にも元の追跡準備を必要とする。逆方向の権利は独立。",
        "場予算": "既実現と全残玉の清算額を足した場全体損益が、固定場リスク×指定倍の負値以下なら次有効観測へ全返済し、その場の未実行新規を取消す。実損失の上限保証ではない。",
        "相手時計": "相手は自己代理価格時計より厳密な過去で、相手観測の古さは十五秒以内。窓の始端は目標時刻以前の最新観測かつ目標時刻から三十秒以内。各窓は未来を含めない。欠測や古い資料をゼロ・反対・根拠消失へ置換しない。",
        "注文順序": "前行で有効だった注文をまず処理。新しい反対や予算判定で前行予約を遡及取消しない。新設条件は次の観測から有効。",
        "初回参加": "通常初回の数量・方向判定は変更しない。全場一回未満の候補を合格にせず、不足時の強制参加は別因子とする。",
        "方向対称性": "全ての価格差は保有方向を掛ける同一式。終値後に分かる上昇下落区分は採点だけに用い、手法選択に使わない。",
        "機構の限界": "二市場反対も正常な押しになり得る。アンカー突破は追随を遅らせる。場予算は後の回復利益を捨てる。単独と統合を全経路で比較し、合計利益の大きさだけで採用しない。",
    }
