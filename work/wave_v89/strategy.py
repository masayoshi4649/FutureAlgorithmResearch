"""固定三源の公開注文を、過去完了成績による新規採否へ接続する。"""

from pathlib import Path
import importlib.util
import sys

HERE = Path(__file__).resolve().parent


def module(name, path):
    """
    機能: 今回だけの固有名で実行器を読み込む。
    引数: name(str)、path(Path)。
    返り値: module。
    """
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


engine = module('wave89_completed_source_engine', HERE/'engine.py')


def initialize(inputs, feeds):
    """
    機能: 全口座に三源の公開注文があることだけを確認する。
    引数: inputs(dict[tuple,dict])、feeds(dict[tuple,dict])。
    返り値: dict[tuple,dict]。既存注文の未来親損益を事前計算しない。
    """
    assert set(inputs) == set(feeds)
    for key in inputs:
        assert set(feeds[key]) == set(engine.SOURCES)
    return feeds


# ----------------------------------------


def play(config, key, ready, feeds, history=None, finish=True):
    """
    機能: 固定配分と完了履歴を渡し、当口座の機械的採否を再生する。
    引数: config(dict)、key(tuple[str,str])、ready(dict)、feeds(dict)、
        history(dict[str,list[dict]]又はNone)、finish(bool)。
    返り値: dict の実行結果。履歴は商品別に呼出側が保存する。
    """
    assert key == (ready['session'], ready['symbol'])
    data = feeds[key] if key in feeds else feeds
    source_orders = {name: data[name]['orders'] if isinstance(data[name], dict) else data[name]
                     for name in engine.SOURCES}
    gate = dict(config.get('gate', dict(mode='all', window=0, threshold=0.)))
    if gate.get('history_mode', 'session') == 'session':
        history = None
    else:
        assert gate['history_mode'] == 'carry'
    return engine.execute(ready, source_orders, config['budgets'], gate, history, finish)
