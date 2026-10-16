"""許可済み旧104peerと完成106入力を各一場一回読み、途中相手列を保存する。"""

import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import pickle
import sys
import traceback

import numpy as np

import peer


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUTPUT = HERE/'全33場の途中相手準備.json'
FIXED = HERE/'途中相手準備の事前固定.json'
DAY = '2026-10-13_Day'


def read(path: Path) -> dict:
    """
    機能: 小さい目録又は人工証跡を読む。
    引数: path(Path)は入力JSONの位置。
    返り値: dictは保存値。原本・金融・APIを取得しない。
    """
    return json.loads(path.read_text(encoding='utf-8-sig'))


def digest(path: Path) -> str:
    """
    機能: 小さいsourceと証跡の内容指紋を得る。
    引数: path(Path)はsource又は小JSON。
    返り値: strはSHA256。巨大入力は読取りbytesから一度だけ計算する。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, value: dict) -> None:
    """
    機能: 新所有thesisだけへUTF-8証跡を保存する。
    引数: path(Path)、value(dict)は保存位置と値。
    返り値: None。過去source/cacheを変更しない。
    """
    assert path.resolve().is_relative_to(HERE)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n',
                    encoding='utf-8', newline='\n')


def dependencies() -> list[Path]:
    """
    機能: 入力・数学・人工の直接依存を抽出前に列挙する。
    引数: なし。
    返り値: list[Path]は小依存。金融結果と原板は含めない。
    """
    result = list(HERE.glob('*.py')) + [HERE/'複製由来.json',
        HERE/'支持破れと相手逆進行の人工検査.json', HERE/'途中判断の仕様.json',
        ROOT/'work/wave_v106/input/全33場の因果特徴準備.json',
        ROOT/'work/wave_v104/入口準備の全32結果.json',
        ROOT/'work/wave_v104/holdout_input/追加Dayの活動と19入口.json',
        ROOT/'work/wave_v106/catalog.py', ROOT/'work/wave_v106/engine/core.py',
        ROOT/'work/wave_v106/engine/interface.py']
    return sorted(set(result))


def register() -> dict:
    """
    機能: 全33場の二入力位置・stat・登録SHAとsourceを本文読取前に固定する。
    引数: なし。
    返り値: dictは読取計画。再登録による入力入替は許さない。
    """
    assert not FIXED.exists() and not OUTPUT.exists()
    artificial = read(HERE/'支持破れと相手逆進行の人工検査.json')
    assert artificial['全合格'] and artificial['新金融再生'] == 0
    for name, wanted in artificial['source_SHA256'].items():
        assert digest(ROOT/name) == wanted
    light = read(ROOT/'work/wave_v106/input/全33場の因果特徴準備.json')
    old = read(ROOT/'work/wave_v104/入口準備の全32結果.json')
    extra = read(ROOT/'work/wave_v104/holdout_input/追加Dayの活動と19入口.json')
    assert light['全合格'] and old['全合格'] and extra['全合格']
    assert len(light['sessions']) == 33 and set(light['sessions']) == set(old['sessions']) | {DAY}
    items = {}
    for session in light['sessions']:
        value = dict(normal=dict(light['cache'][session]),
                     peer=dict(extra if session == DAY else old['cache'][session]))
        for role in ('normal', 'peer'):
            item = value[role]
            path = (ROOT/item['path']).resolve()
            permitted = (ROOT/'work/wave_v106/input/cache' if role == 'normal' else
                         ROOT/'work/wave_v104/holdout_input/activity_peer' if session == DAY else
                         ROOT/'work/wave_v104/prepared')
            assert path.is_relative_to(permitted.resolve())
            stat = path.stat()
            value[role] = dict(path=str(path.relative_to(ROOT)).replace('\\','/'),
                SHA256=item['SHA256'], size=stat.st_size, mtime_ns=stat.st_mtime_ns)
        items[session] = value
    result = dict(全合格=True, sessions=light['sessions'], cache=items,
        source_SHA256={str(p.relative_to(ROOT)).replace('\\','/'):digest(p) for p in dependencies()},
        登録日時=datetime.now(timezone.utc).isoformat(), 原本読取=0, 金融再生=0, API取得=0)
    write(FIXED, result)
    return result


def load_registered(item: dict) -> dict:
    """
    機能: 既登録cacheを一回読み、同bytesでSHAと読取前後statを照合する。
    引数: item(dict)はpath・SHA・size・mtime。
    返り値: dictは既存pickle。原本再抽出や再prepareはしない。
    """
    path = ROOT/item['path']
    before = path.stat()
    assert (before.st_size, before.st_mtime_ns) == (item['size'], item['mtime_ns'])
    saved = path.read_bytes()
    assert hashlib.sha256(saved).hexdigest() == item['SHA256']
    after = path.stat()
    assert (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns)
    return pickle.loads(gzip.decompress(saved))


def run() -> None:
    """
    機能: 許可済み一回の33場入力接続を保存し、失敗証跡を保持する。
    引数: なし。--root-thesis-input-reviewedでのみ呼ぶ。
    返り値: None。旧二cache各33読取と新cache保存だけで金融再生は0。
    """
    assert not OUTPUT.exists(), '既終端を上書き又は自動再実行しない'
    fixed = read(FIXED)
    result = dict(全合格=False, sessions=fixed['sessions'], cache={},
        source_SHA256=fixed['source_SHA256'], 入力固定SHA256=digest(FIXED),
        normal_packet読取=0, peer_packet読取=0, 正常経済口座保持=0,
        counts={}, 原本読取=0, 金融再生=0, API取得=0, 旧source変更=0)
    try:
        for name, wanted in fixed['source_SHA256'].items():
            assert digest(ROOT/name) == wanted, name
        for session in fixed['sessions']:
            light = load_registered(fixed['cache'][session]['normal'])
            result['normal_packet読取'] += 1
            saved = load_registered(fixed['cache'][session]['peer'])
            result['peer_packet読取'] += 1
            packet = saved['peer'] if session == DAY else saved
            value = peer.prepared_session(light, packet)
            assert value['session'] == session
            result['正常経済口座保持'] += 2
            result['counts'][session] = {symbol:{str(window):dict(
                known=int(np.count_nonzero(value['peers'][symbol][str(window)]['known'])),
                self_known=int(np.count_nonzero(value['peers'][symbol][str(window)]['self_known'])),
                up=int(np.count_nonzero(value['peers'][symbol][str(window)]['known'] &
                                       (value['peers'][symbol][str(window)]['direction'] == 1))),
                down=int(np.count_nonzero(value['peers'][symbol][str(window)]['known'] &
                                         (value['peers'][symbol][str(window)]['direction'] == -1))))
                for window in (10,30)} for symbol in ('TOPIX','NK225')}
            target = HERE/'cache'/(session+'.pkl.gz')
            target.parent.mkdir(parents=True, exist_ok=True)
            assert not target.exists()
            content = gzip.compress(pickle.dumps(value, protocol=5), compresslevel=2, mtime=0)
            target.write_bytes(content)
            result['cache'][session] = dict(path=str(target.relative_to(ROOT)).replace('\\','/'),
                SHA256=hashlib.sha256(content).hexdigest())
            del light, saved, packet, value, content
            print(session+'：途中相手10/30秒を同normal行へ準備', flush=True)
        for name, wanted in fixed['source_SHA256'].items():
            assert digest(ROOT/name) == wanted, name
        assert len(result['cache']) == result['normal_packet読取'] == result['peer_packet読取'] == 33
        assert result['正常経済口座保持'] == 66
        result.update(全合格=True, 開始終端source一致=True)
    except Exception as error:
        result.update(失敗=str(error), traceback=traceback.format_exc())
        write(OUTPUT, result)
        raise
    write(OUTPUT, result)
    print('33場の準備完了、金融再生0', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='不変104相手公表窓の途中判断入力を準備する。')
    parser.add_argument('--register-only', action='store_true')
    parser.add_argument('--root-thesis-input-reviewed', action='store_true')
    args = parser.parse_args()
    assert args.register_only != args.root_thesis_input_reviewed
    register() if args.register_only else run()
