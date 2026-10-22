"""原因別の比較条件を金融再生より前に保存する。"""

from common131 import HERE, LAST, save, reference


def main():
    """
    機能: 追随・回帰・時計・状態の違いを12条件へ分離する。
    引数: なし。
    返り値: None。損益の最適化・金融再生は行わない。
    """
    configs = []
    labels = ("押戻り追随", "帯の端から回帰", "時計で追随と回帰",
              "観測した進行で切替", "時計と観測した進行で切替")
    for selector, label in enumerate(labels):
        for width in (0, 1):
            configs.append(dict(
                id="R"+str(len(configs)+1).zfill(2),
                name=label+("・20分帯を含む幅" if width else "・ATR幅"),
                selector=selector, width_mode=width, stop=1., trail_start=1., trail_width=.75,
                per_phase=2, participation_seconds=2700., conversion=0, withdrawal=0))
    configs.append(dict(configs[-1], id="R11", name="時計と状態・回帰から進行へ移行", conversion=1))
    configs.append(dict(configs[-1], id="R12", name="時計と状態・両市場逆行の持続で撤退", withdrawal=1))
    save(HERE / "第一巡条件.json", configs)
    save(HERE / "第一巡の変更理由.json", dict(
        question="無取引を残さず、現物市場の有無と当時の進行状態で追随・回帰を切り替えると安定性が増すか。",
        compares_to=["00129の日中DV07/DV05", "00130の夜間NV01/NV25/W07/W12"],
        change="E01の拒否済み影を復活するのでなく、押戻り・帯回帰・初回参加を独立した状態機械として作る。",
        repeat_reason="00130は追加確認で参加不足、初回価格の長時間固定で機会消失。現物休場を含む時計×状態の切替と全場参加を一体で測っていない。",
        logic=[
            "東京現物の寄付・昼休み・引け、現物休場日、欧米重複時間は裁定と参加者が異なる仮説。時間が上昇下落を決めるとは仮定しない。",
            "活発さと方向効率は別。時計だけ/効率だけ/併用を比較し、回帰単独も対照として失敗を含める。",
            "条件が揃うまで待つ手法には無取引があるため、開始45分後も新規がなければ当時の二市場20分変化から同量で一度参加する。",
            "期限参加は利益を保証せず、発生回数と損益を別記。未取引になった場を後から選ぶ方式ではない。",
            "損切りと追尾は同じ原行模型、費用は実注文単位。新旧の合算損益で片方を隠さない。"
        ],
        quantity="TOPIXミニ5枚・日経マイクロ10枚、追加なし。期限参加も同量。",
        scope="既知43場。過去資料だけで判断するが、未知データでの検証とは呼ばない。",
        prior_result=reference(LAST / "最終全場比較_確定.json")))


if __name__ == "__main__":
    main()
