"""第一巡の具体的失敗を根拠に、旧核と一回参加の比較条件を金融前に固定する。"""

from common131 import HERE, read, save
import baseline131


def main():
    """
    機能: 主手法二系統と参加期限三種、方向対照二種の計八条件を保存する。
    引数: なし。
    返り値: None。条件別損益を見る前に作成し、保存結果は変更しない。
    """
    configs = []
    labels = ("開始45分後", "日中12時30分・米国寄付30分後", "日中14時・欧州終了後")
    for variant in (0, 1):
        for schedule in (0, 1, 2):
            configs.append(dict(id=f"S{len(configs)+1:02d}",
                name=("基本核" if variant == 0 else "夜間活発核")+"＋未参加一回："+labels[schedule],
                core_variant=variant, schedule=schedule, style=0))
    for variant in (0, 1):
        configs.append(dict(id=f"S{len(configs)+1:02d}",
            name=("基本核" if variant == 0 else "夜間活発核")+"＋始値方向一回：中盤",
            core_variant=variant, schedule=1, style=1))
    save(HERE/"第二巡条件.json", configs)
    reason = dict(
        question="旧有望核を維持し、既知の市場時計まで未参加なら一度だけ補うことで全場参加と安定性を両立できるか。",
        compares_to=["131_round1_final_時間帯と値動き状態を切り替える全場参加",
            "129_day_round2_チャートと板の失敗機構改善",
            "130_round2_夜間損失のなぜ三段階と再改善",
            "130_round4_夜間損失のなぜ三段階と再改善"],
        change="通常入口を第1巡新核から保存旧核へ戻す。別口座で当行まで未参加なら同量一親のみ追加。期限三種と方向方式の限定対照。",
        repeat_reason="第一巡は全24商品別条件で費用前から赤字。通常入口の多数反復・古い支持・低効率の回帰誤認が主因。旧核と一度だけ補う追加担当は未検証。",
        quantity="旧核TOPIXミニ5枚・NKマイクロ10枚。追加担当も5枚・10枚。片方向同時最大10枚・20枚、合算長短各々で監査する。",
        entry="期限までの主手法新規累積が0なら、当時の二市場20分各1票＋5分各0.5票方向へ一度参加。始値方式は対照2条件のみ。同票は自己20分、自己始値差順。全て0なら次の有効行まで待つ。",
        exit="追加R=max(当時ATR,過去20分帯半幅,ラージ8呼値)。1R損切り、1.5R順行から1R追尾、場内全返済。旧核の出口は保存結果を維持。",
        logic=[
            "主手法は低頻度の既知比較候補で、時計は売買方向ではなく初回機会の待ち時間を決める。",
            "日中12時30分は通常日の現物再開、夜間米国寄付30分後は最初の価格形成後を観測する仮説。30分自体は制度境界でない。",
            "日中14時は終場まで約95分残す実行上の期限であり、市場制度の変化を主張しない。欧州終了は米国中心の時間へ移る既知境界。",
            "開始45分は早期参加の対照。短期方向の過信を避け、同じ場で追加担当が何度も取引することを禁止する。",
            "終日の無取引有無を先読みしない。主手法が追加注文の後に入っても、既発注追加は遡及取消しない。",
            "主手法と追加の損益を別記。枚数増加による単純な利益増と、負け場・最大負け・上位3場依存の改善を区別する。",
        ],
        limitations=[
            "既知43場の開発比較。未知期間の有効性を証明しない。",
            "ラージBBOをmini/micro全量約定の代理とする。実板の約定容量と実受信順は未証明。",
            "ニュースは予定の理論根拠。日別見出し・発表後実績値を売買方向に用いない。",
        ],
        extra_input_paths=[
            "work/regime131_20261020/round1_final/区分別の比較.json",
            "work/regime131_20261020/day_diagnosis/第一巡日中はなぜ悪化したか.md",
            "work/regime131_20261020/night_diagnosis/第一巡夜間の三段階原因と次巡案.md",
            "work/regime131_20261020/news/ニュース予定根拠の確定.json",
            "work/regime131_20261020/news/時間帯の理由と当時使える予定.md",
            "work/regime131_20261020/audit/旧核維持と初回追加の接続条件.md",
        ]+[r["path"] for r in baseline131.source_map.values()])
    save(HERE/"第二巡の変更理由.json", reason)


if __name__ == "__main__":
    main()
