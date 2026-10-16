"""旧確定入力と一回算定した短期位相を、同一場のreadonly packetで提供する。"""

import common


METADATA=common.HERE/'全33場の直近位相準備.json'


def load_session(session: str) -> dict:
    """
    機能: 確定した新位相cacheを同bytes一読で検証して返す。
    引数: session(str)は対象33場の一つ。
    返り値: dictはprepared/cases/measured/quiet/short。旧原本/旧104を読まない。
    """
    meta=common.read(METADATA);assert meta['全合格'] and meta['新金融再生']==0
    for name,sha in meta['input_source_SHA256'].items():assert common.digest(common.ROOT/name)==sha,name
    value=common.unpack(meta['cache'][session]);common.immutable(value)
    assert value['session']==session and value['local_phase_schema_version']==1
    return value
