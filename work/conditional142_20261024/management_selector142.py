"""短期逆行時の維持・半減・全返済を、売買実行から分離して選択する。"""

import numpy as np
from numba import njit


HOLD, HALF, CLOSE = 0, 1, 2
SIDE, QUANTITY, PARTIAL_DONE, GAIN_R, BEST_R, FLOOR_R, FAILED_SAME = range(7)
OWN5_R, PEER5_R, OWN20_R, PEER20_R, OWN40_R, PEER40_R = range(7, 13)
OWN30_R, PEER30_R, OWN120_R, PEER120_R, OWN_OFI, PEER_OFI, SHORT_CONFIRMED = range(13, 20)
SNAPSHOT_SIZE = 20

SNAPSHOT_COLUMNS = (
    '建玉方向', '現在保有枚数', 'この親で半減済み', '初回建値から現在利益R',
    '初回建値から最大利益R', '初回建値から現在停止線R', '候補内の直近同方向失敗数',
    '自己5分差R', '相手5分差R', '自己20分差R', '相手20分差R',
    '自己40分差R', '相手40分差R', '自己30秒差R', '相手30秒差R',
    '自己120秒差R', '相手120秒差R', '自己OFI', '相手OFI', '短期逆行15秒を確認済み',
)
REASONS = {
    10: '短期逆行の継続が未確認', 11: '建玉状態又は短期資料が不正・欠測',
    12: '保有なし', 20: '既に半減済みのため追加半減しない', 21: '1枚のため半減しない',
    101: '二市場5分と20・40分の逆行が一致',
    102: '二市場20・40分の支持を維持', 103: '長短の判断が混在するため半減',
    201: '二市場5・20分逆行をOFI逆行も確認',
    202: '二市場の長い支持とOFI支持が一致', 203: '価格と板の確認不足のため半減',
    301: '価格逆行が一致し初期失敗又は利益消失',
    302: '有意に進行した利益の吐出しで半減',
    303: '含み損と二市場5分逆行で半減', 304: '利益進行と元の停止追尾を維持',
    401: '価格逆行を長い方向又は板が確認し含み損・再失敗',
    402: '長い支持と停止余裕があり同方向の直近失敗なし',
    403: '複合根拠が十分に揃わないため半減',
}


def policies():
    """
    機能: 収支を参照せず固定した四つの管理仮説を返す。
    引数: なし。
    返り値: list[dict]は番号・ID・目的・条件を持つ設定資料。
    """
    return [
        dict(id='M01', policy=1, name='長短の方向を分ける',
             rationale='短い反落と保有仮説全体の崩れを分け、長短が逆行して初めて全返済する。'),
        dict(id='M02', policy=2, name='価格逆行を板変化で確認する',
             rationale='価格だけの一時的逆行と、二市場の提示需給も逆行する状態を分ける。'),
        dict(id='M03', policy=3, name='利益進捗に応じて保護する',
             rationale='まだ進んでいない小玉と、既に進んだ利益の吐出しを同じ返済にしない。',
             progress_r=.75, giveback_r=.25, failed_r=.5),
        dict(id='M04', policy=4, name='価格・板・同方向失敗を組み合わせる',
             rationale='長い支持がある初回小玉は待ち、価格と板の反証や同方向の再失敗には露出を減らす。',
             repeated_failures=2, stop_buffer_r=.25),
    ]


@njit(cache=True)
def _pair_support(x, left, right, side):
    """
    機能: 二市場がともに非逆行で、少なくとも一方が順行か確認する。
    引数: x(ndarray)、left/right(int)は列、side(float)は保有方向。
    返り値: bool。欠測又は両市場同値は支持としない。
    """
    a, b = side*x[left], side*x[right]
    return np.isfinite(a) and np.isfinite(b) and a >= 0. and b >= 0. and (a > 0. or b > 0.)


@njit(cache=True)
def _pair_opposite(x, left, right, side):
    """
    機能: 二市場の方向がともに保有と逆向きか確認する。
    引数: x(ndarray)、left/right(int)は列、side(float)は保有方向。
    返り値: bool。欠測は反証としない。
    """
    a, b = side*x[left], side*x[right]
    return np.isfinite(a) and np.isfinite(b) and a < 0. and b < 0.


@njit(cache=True)
def _half_or_hold(x, reason):
    """
    機能: 一度だけの切捨て半減が可能か確認する。
    引数: x(ndarray)は当時状態、reason(int)は半減を求めた理由。
    返り値: tuple[int,int]は実行可能な提案と理由。枚数自体は変更しない。
    """
    if x[PARTIAL_DONE] != 0.:
        return HOLD, 20
    if x[QUANTITY] < 2.:
        return HOLD, 21
    return HALF, reason


@njit(cache=True)
def choose_action(policy_id, snapshot):
    """
    機能: 当時資料だけから、短期逆行に対する維持・半減・全返済を提案する。
    引数: policy_id(int)は1～4、snapshot(ndarray[20])はSNAPSHOT_COLUMNS順の状態。
    返り値: tuple[int,int]は0維持/1半減/2全返済とREASONSの理由番号。

    呼出側が正常板・継続時計・既発注の不存在を管理し、元停止・利益追尾・場末返済を優先する。
    SHORT_CONFIRMEDは過去から15秒持続したことを示す。単発の方向値を代用しない。
    利益のRは初回固定R、方向のRは当時各市場R。OFIは約定方向や真の補充を断定しない。
    本関数は時計、注文列、将来価格、口座状態の変更を持たない。
    """
    assert len(snapshot) == SNAPSHOT_SIZE
    assert 1 <= policy_id <= 4
    x = snapshot
    side = x[SIDE]
    if not np.isfinite(x[QUANTITY]) or x[QUANTITY] <= 0.:
        return HOLD, 12
    if side not in (-1., 1.) or not np.isfinite(x[GAIN_R]) or not np.isfinite(x[BEST_R]) or not np.isfinite(x[FLOOR_R]):
        return HOLD, 11
    if not np.isfinite(x[FAILED_SAME]) or x[FAILED_SAME] < 0. or not np.isfinite(x[PARTIAL_DONE]):
        return HOLD, 11
    if x[SHORT_CONFIRMED] != 1.:
        return HOLD, 10
    for col in (OWN30_R, PEER30_R, OWN120_R, PEER120_R):
        if not np.isfinite(x[col]):
            return HOLD, 11
    if not (side*x[OWN30_R] <= -.1 and side*x[PEER30_R] <= -.1
            and side*x[OWN120_R] < 0. and side*x[PEER120_R] < 0.):
        return HOLD, 10
    # ----------------------------------------
    # 長短方向と提示需給を独立の確認にし、欠測を一致へ読み替えない。
    fast_against = _pair_opposite(x, OWN5_R, PEER5_R, side)
    medium_against = _pair_opposite(x, OWN20_R, PEER20_R, side)
    long_against = _pair_opposite(x, OWN40_R, PEER40_R, side)
    long_support = _pair_support(x, OWN20_R, PEER20_R, side) and _pair_support(x, OWN40_R, PEER40_R, side)
    flow_against = _pair_opposite(x, OWN_OFI, PEER_OFI, side)
    flow_support = _pair_support(x, OWN_OFI, PEER_OFI, side)
    flow_known = np.isfinite(x[OWN_OFI]) and np.isfinite(x[PEER_OFI])
    gain, best = x[GAIN_R], x[BEST_R]
    if policy_id == 1:
        if fast_against and medium_against and long_against:
            return CLOSE, 101
        if long_support:
            return HOLD, 102
        return _half_or_hold(x, 103)
    if policy_id == 2:
        if fast_against and medium_against and flow_against:
            return CLOSE, 201
        if long_support and flow_support:
            return HOLD, 202
        return _half_or_hold(x, 203)
    if policy_id == 3:
        # ----------------------------------------
        # 初期失敗と利益吐出しを分ける。閾値は特定日の約定へ合わせていない。
        if fast_against and medium_against and (gain <= -.5 or (best >= .75 and gain <= 0.)):
            return CLOSE, 301
        if best >= .75 and best-gain >= .25:
            return _half_or_hold(x, 302)
        if gain < 0. and fast_against:
            return _half_or_hold(x, 303)
        return HOLD, 304
    # ----------------------------------------
    # 同方向失敗数は候補内で完了した仮想約定会計から渡す。現在玉や将来の損失を数えない。
    rejection = fast_against and medium_against and (long_against or flow_against)
    if rejection and (gain <= 0. or x[FAILED_SAME] >= 2.):
        return CLOSE, 401
    if long_support and flow_known and not flow_against and x[FAILED_SAME] == 0. and gain > x[FLOOR_R]+.25:
        return HOLD, 402
    return _half_or_hold(x, 403)


@njit(cache=True)
def snapshot_from_features(side, heldtotal, gain_r, best_r, floor_r, partial_done, failed_same,
                           features, short_confirmed=True):
    """
    機能: engineの30列特徴と実保有状態を、独立選択用の固定20列へ変換する。
    引数: side/heldtotal/failed_same(int)、gain_r/best_r/floor_r(float)、partial_done/short_confirmed(bool)、features(ndarray[30])。
    返り値: ndarray[20]は固定列の当時状態。入力配列を書き換えない。

    featuresの28/29列は公開済みの自己/相手20分価格差とする。
    5/20/40分差は自己9列R・相手18列Rで割る。欠測又は非正RはNaNで残す。
    相手は同時刻の後続原行を含めず、公開遅延・鮮度検査を済ませて渡す。
    """
    assert len(features) >= 30
    x = np.full(SNAPSHOT_SIZE, np.nan)
    x[SIDE], x[QUANTITY], x[PARTIAL_DONE] = side, heldtotal, 1. if partial_done else 0.
    x[GAIN_R], x[BEST_R], x[FLOOR_R], x[FAILED_SAME] = gain_r, best_r, floor_r, failed_same
    r, pr = features[9], features[18]
    if np.isfinite(r) and r > 0.:
        x[OWN5_R], x[OWN20_R], x[OWN40_R] = features[3]/r, features[28]/r, features[4]/r
    if np.isfinite(pr) and pr > 0.:
        x[PEER5_R], x[PEER20_R], x[PEER40_R] = features[14]/pr, features[29]/pr, features[15]/pr
    x[OWN30_R], x[PEER30_R] = features[12], features[20]
    x[OWN120_R], x[PEER120_R] = features[13], features[21]
    x[OWN_OFI], x[PEER_OFI] = features[24], features[26]
    x[SHORT_CONFIRMED] = 1. if short_confirmed else 0.
    return x


@njit(cache=True)
def select_from_features(policy_id, side, heldtotal, gain_r, best_r, floor_r, partial_done,
                         failed_same, features, short_confirmed=True):
    """
    機能: engineの状態を変換し、同じ独立純粋関数へ選択を委譲する。
    引数: policy_id/side/heldtotal/failed_same(int)、利益関連値(float)、partial_done/short_confirmed(bool)、features(ndarray[30])。
    返り値: tuple[int,int]は維持・半減・全返済と理由番号。
    """
    snapshot = snapshot_from_features(side, heldtotal, gain_r, best_r, floor_r,
                                      partial_done, failed_same, features, short_confirmed)
    return choose_action(policy_id, snapshot)
