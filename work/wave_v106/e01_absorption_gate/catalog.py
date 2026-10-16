"""表示が減らない逆板への反復接触を、一つの入口部品へ固定する。"""

TRIAL_ID = '106_E01同価格逆板の無減少と反復接触を入口で見送る'
BASELINE_ID = 'E01_TRADE_W60_KNOWN_VETO_D0_P1L8'
CANDIDATE_ID = 'E01_TRADE_W60_KNOWN_VETO_ABSORB_D0_P1L8'
QUANTITY = {'TOPIX': 5, 'NK225': 10}
CAP = {'TOPIX': 10, 'NK225': 20}
WINDOW = 60
MINIMUM_TOUCHES = 2
MINIMUM_ACTIVITY_RATIO = 1.
FIELDS = ('raw_seq', 'price_time_s', 'last', 'bid', 'ask', 'bid_qty', 'ask_qty',
          'volume_delta', 'volume_delta_usable', 'volume_reset_reason',
          'best_quantity_valid', 'price_row_valid', 'price_transition_valid',
          'execution_to_raw_index')


def definition() -> dict:
    """
    機能: 結果を見る前の固定述語と情報資格を返す。
    引数: なし。
    返り値: dictは単一部品。多条件探索・最適化を追加しない。
    """
    return dict(
        代理窓秒=WINDOW, 最小接触回数=MINIMUM_TOUCHES,
        接触更新行の公表出来高差の初期数量比下限=MINIMUM_ACTIVITY_RATIO,
        元資格='W60 knownかつdirection_votes>=2。元KNOWN_VETOの拒否理由は維持。',
        尾部='元票first_vote_raw_rowから公開candidate_raw_rowまでの末尾同価格逆側最良区間。',
        基準='尾部最初の原行eの逆側最良価格p・数量Q0・支持側最良価格。',
        接触='eより後の同区間原行のみ。usable正出来高差、Last==p、Last対直前BBOの元方向票==入口側。1原行1票。',
        活動規模='接触に該当する原行の公表出来高差合計>=初期Q0。真の方向別数量や同価格消費量ではない。',
        数量='尾部全行の逆側最良数量>=Q0。少しでも減少すれば不成立、後の回復では救済しない。',
        支持='買いでは尾部全bid<=初bid。売りでは尾部全ask>=初ask。少しでも順方向へ進めば不成立。',
        資格='e含む全尾部で正常両BBO/最良数量/price_row_valid。transition_validはe+1以後だけ要求。',
        境界='尾部外の数量不明は混ぜない。逆側価格の不明で同価格区間開始を特定できない場合は未知。',
        未知='追加述語の未知だけでは元maskを変更しない。元KNOWN_VETOの未知/少票拒否はそのまま。',
        限界='真の攻撃方向・補充・同一主体・実受信順の同定ではない。量の方向配賦はしない。')
