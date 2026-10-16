"""利益を残す出口と再参加時計の効果を、全組合せで先に固定する。"""


def catalog():
    """
    機能: 共通入口のまま出口五系統と再参加時計四系統を組み合わせる。
    引数: なし。
    返り値: list[dict] の二十条件。
    """
    exits = [
        ('T0', '元の広幅', {}),
        ('T1', '幅1ATR', dict(activation_atr=1., main_trail=1., tighten_atr=3., tight_width=.75)),
        ('T2', '幅0.5ATR', dict(activation_atr=.75, main_trail=.5, tighten_atr=0., tight_width=.5)),
        ('T3', '伸びたら幅0.5ATR', dict(activation_atr=1., main_trail=1.5, tighten_atr=1.5, tight_width=.5)),
        ('T4', '逆行を見たら幅0.5ATR', dict(activation_atr=1., main_trail=1.5, tighten_atr=3., tight_width=.75)),
    ]
    clocks = [('S', '元の再参加待ち', 'shadow', 300.),
              ('A5', '全返済後5分で再準備', 'actual', 300.),
              ('A1', '全返済後1分で再準備', 'actual', 60.),
              ('A0', '全返済後の次観測から再準備', 'actual', 0.)]
    values = []
    for code, label, changes in exits:
        for clock, clock_label, mode, seconds in clocks:
            identifier = 'E01_G_U' if (code, clock) == ('T0', 'S') else code + '_' + clock
            values.append(dict(id=identifier, name=label+'・'+clock_label, exit_id=code,
                clock_id=clock, mask=1, time_mode='U', changes=changes,
                reentry_mode=mode, cooldown_seconds=seconds, dynamic_trail=code == 'T4',
                dynamic_activation_atr=1., dynamic_width_atr=.5))
    return values


def specification():
    """
    機能: 今回の仮説・変更点・評価方法を結果より先に文章化する。
    引数: なし。
    返り値: dict の固定仕様。
    """
    return dict(
        仮説='広い出口で戻していた利益を狭い出口で確定し、方向条件の再成立と新しい待機注文で再参加する。',
        主仮説='T3_A1。1ATR順行で1.5ATR幅、1.5ATR順行後は0.5ATR幅。全返済後1分で新しい注文準備。',
        入口='E01_G_Uと同じ二市場EMA開始条件・短期支持・0.25ATR反発反落確認。入口閾値そのものは緩めない。',
        途中='元の部分利確と一度だけの悪化半減を維持。増玉・復元はしない。',
        T4='自己のB00逆行が保有後に新しく公開され、最大順行が準備時ATRの1倍以上なら0.5ATR幅へ短縮。新しい追跡線は次の保存観測から有効。一度狭めた幅は戻さない。',
        再参加='Sは元の通常影終了後の時計を維持。Aは実際の全返済で影と古い待機を破棄し、指定秒数経過後かつ次の観測以降に新しい準備を要求。即座の同価格再建ては仮定しない。',
        共通='TOPIXミニ初回5枚・上限10枚、日経マイクロ初回10枚・上限20枚。追加なし。セッション内返済。米国現物開始前後15分は全返済・新規禁止。',
        約定='観測現在値で入口と出口を再計算するモデルを主とし、指定線約定を感度確認とする。両方とも手数料込み、固定5秒遅延なし。',
        検証='保存済み既知30セッション。前16・後14、買い売り、上昇下落別も確認。未来極値は事後診断以外に使わない。未見検証とは呼ばない。',
        評価='商品間の金額を合算しない。両商品が黒字の条件について、商品別の純収支/最大下落の小さい方を参考順位とする。金額利益割合・黒字場数・最大下落・料金と回数を必ず併記。基準より両商品で改善するかを別判定。',
        改善判定='両商品とも基準以上の純収支、金額利益割合、黒字セッション数、基準以下の最大下落を同時達成するか。順位1位だけで改善と呼ばない。',
        件数=20, API取得=0, 実注文=0)
