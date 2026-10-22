"""段階追尾の八運用を、同じ三つの幅と二つの利確追尾で比較する。"""

from datetime import datetime, timedelta, timezone


MODES = (
    ('HEDGE', '両方向の利益玉を個別追尾', '反発で買い、反落で売りを段階追加。利益玉だけを個別に追尾返済し、その枠を再準備する。'),
    ('NET', '反対の新規を減玉へ使う', '反対玉がある間、反対方向の新規信号を最も不利な反対玉一枚の返済へ使う。両建ての固定を避ける。'),
    ('FLIP', '反転確認で方向を持ち替える', '反対方向の新規条件が成立したら、旧方向を全返済予約し、新方向へ段階参加する。'),
    ('RECYCLE', '確保した利益で損失玉を整理', '両建ての利益玉を個別追尾。累積確定純益が最悪損失玉の清算損の二倍以上なら、その一枚を整理する。'),
    ('HARD', '各玉へ初期損切りを付ける', '利益玉の追尾に加え、各一枚の費用後清算損が三単位に達したら返済する。'),
    ('FIXED', '対照：待機の極値を追わない', '枠を準備した価格から段階幅を固定し、新安値・新高値で新規水準を更新しない。それ以外は両建て型と同じ。'),
    ('ONCE', '対照：返済後の枠を再利用しない', '段階ごとに一枚だけ新規し、返済済みの枠はその場では使わない。それ以外は両建て型と同じ。'),
    ('ALLSIDE', '対照：利確合図で同方向全返済', '一枚の利益追尾が成立したら、その方向の玉を含み損玉も含めて全返済する。反対玉は別に管理する。'),
)


def specifications() -> list[dict]:
    """
    機能: 数値結果を見る前に同じ四十八条件を列挙する。
    引数: なし。
    返り値: list[dict]はID、運用、当初価格割合、追尾幅と日本語説明。
    """
    result = []
    for mode, (tag, name, description) in enumerate(MODES):
        for width, fraction in enumerate((.000125, .00025, .0005), 1):
            for trail in (1., 3.):
                result.append(dict(id=f'{tag}_S{width}_T{int(trail)}', mode=mode,
                    name=name, description=description, fraction=fraction, trail=trail,
                    width_id=width, activation=trail + 1.,
                    rules=dict(入口='各空き枠の中値安値＋3/4/5…単位で買い、高値−同幅で売り。各段一枚。',
                        途中='新規は当該方向へ中値が動いた行だけ。返済後の同枠は現在中値から再準備。',
                        出口='純益の最高値が追尾幅＋1単位を超えた玉は、追尾幅戻りかつ現在純益が正なら返済予約。次気配の損失約定も計上。')))
    assert len(result) == 48
    return result


def settings(symbol: str, session: str) -> dict:
    """
    機能: 保存比較と同じ場内締切・商品倍率・注文料金を決める。
    引数: symbol(str)はTOPIX又はNK225、session(str)は日付_Day/Night。
    返り値: dictは数量上限、倍率、料金、観測刻み、絶対時刻。
    """
    date, kind = session.split('_')
    day = datetime.fromisoformat(date).replace(tzinfo=timezone(timedelta(hours=9)))
    if kind == 'Day':
        start = day.replace(hour=8, minute=45)
        close = day.replace(hour=15, minute=20)
        end = day.replace(hour=15, minute=45)
    else:
        start = day.replace(hour=17)
        close = (day + timedelta(days=1)).replace(hour=5, minute=40)
        end = (day + timedelta(days=1)).replace(hour=6)
    top = symbol == 'TOPIX'
    return dict(cap=10 if top else 20, multiplier=1000. if top else 10., fee=41.8 if top else 11.,
        observed_tick=.5 if top else 10., session_start=start.timestamp(),
        entry_end=close.timestamp() - 1200, close_time=close.timestamp(), session_end=end.timestamp())
