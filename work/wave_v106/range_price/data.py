"""新しい価格境界反発の固定入力だけを一場単位で提供する。"""

import common


METADATA=common.HERE/'全33場の価格境界反発準備.json'


def load_session(session: str) -> dict:
    """
    機能: 当時six観測と元C正常入力を、原本再読なく一場だけ返す。
    引数: session(str)は完了証跡にある場名。
    返り値: dictはprepared/cases/measured/quiet。全配列はreadonly。
    """
    meta=common.read(METADATA)
    assert meta['全合格'] and meta['新金融再生']==meta['原板読取']==0
    for path,sha in meta['source_SHA256'].items():
        assert common.digest(common.ROOT/path)==sha,path
    value=common.unpack(meta['cache'][session]);common.immutable(value)
    assert value['session']==session and value['schema_version']==1
    return value
