"""一場の全normal票と旧同normal気配を返す。"""

import prepare
import common


def load_session(session: str) -> dict:
    """
    機能: 完成manifestから一場cacheを同bytes一読して返す。
    引数: session(str)は固定33場。
    返り値: dictは全normal当時票・元q/record。原NPZを再読しない。
    """
    meta=common.read(common.HERE/'全33場の保有中取引更新票.json');assert meta['全合格']
    return prepare.load(meta['cache'][session])
