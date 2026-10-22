"""セッション種別だけで日中改修と夜間新造を切り替える研究用の統合入口。"""

from copy import deepcopy
from common128 import HERE, read
from adapter5 import play_day, play_night, summarize


def session_config(session):
    """
    機能: 事前に確定した昼夜の候補をセッション種別だけで選択する。
    引数: session(str)はYYYY-MM-DD_Day又はYYYY-MM-DD_Night。
    返り値: dictは固定した数値条件の複製。終了後の値動きや成績で選び直さない。
    """
    kind=session.rsplit("_",1)[-1]
    if kind not in ("Day","Night"):
        raise ValueError("セッション種別はDay又はNightが必要です")
    config=deepcopy(read(HERE/"採用候補と公開記録.json")["methods"][kind])
    config.setdefault("weak_fraction",1.)
    config.setdefault("risk_floor",.5)
    config.setdefault("protect_start",.5)
    config.setdefault("maximum_extension",1.e9)
    return config


def simulate_session(ready, quotes, market, history, day_feed=None):
    """
    機能: 昼夜の固定候補を選び、当該セッションの原行を順に判断して場内で完結する。
    引数: ready/quotes(dict)、market/history(ndarray)は入力準備仕様で作った因果的特徴。
          day_feed(ndarray又はNone)は日中の元E01通常影通知。夜間では使用しない。
    返り値: tuple[dict,dict]は全注文等の数値配列と手数料後会計。
    """
    config=session_config(ready["session"])
    if config["kind"]=="Day":
        if day_feed is None:
            raise ValueError("日中は因果的に作成したE01通常影通知が必要です")
        result=play_day(config,ready,quotes,market,history,day_feed)
    else:
        result=play_night(config,ready,quotes,market,history)
    return result,summarize(result,ready,config)
