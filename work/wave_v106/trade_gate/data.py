"""取引更新確認の保存入力と外部入口maskを、金融実行なしで提供する。"""

import copy

import common
import votes


TARGET=common.HERE/'全33場の取引更新代理準備_v2.json'


def load_session(session: str) -> dict:
    """
    機能: 結果前固定された同normal・当時自己方向票を、一場一gzipで返す。
    引数: session(str)は保存済み33場の名前。
    返り値: dictはprepared、4旧AUTO正常入力、3窓の候補当時特徴。全配列はreadonly。
    """
    metadata=common.read(TARGET)
    assert metadata['全合格'] and metadata['新金融再生']==metadata['原book読取']==metadata['API取得']==0
    for path,sha in metadata['source_SHA256'].items():assert common.digest(common.ROOT/path)==sha,path
    result=common.unpack(metadata['cache'][session]);common.immutable(result)
    assert result['session']==session and result['schema_version']==1
    return result


def for_case(packet: dict, symbol: str, config: dict) -> dict:
    """
    機能: 元同値AUTO正常入力へ指定scopeと窓の外部maskだけを添える。
    引数: packet(dict)、symbol(str)、config(dict)は保存入力・商品・固定36設定。
    返り値: dictはnormal、entry_filter、filter_reason。入口表示ID以外の元経済列は変えない。
    """
    original=packet['normals'][config['baseline_id']][symbol]
    normal=copy.copy(original);normal['entry_id']=config['id']
    features=packet['trade_features'][symbol][str(config['trade_window_seconds'])]
    mask,reasons=votes.entry_filter(original,features,config['gate_scope'])
    return dict(normal=normal,entry_filter=mask,filter_reason=reasons)
