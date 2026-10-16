"""保存済み66紙上注文を、同原行の価格・気配・予定窓へ接続する。"""

import gzip
import pickle
import numpy as np

import common


def packet(path) -> dict:
    """
    機能: 既存の紙上注文を一回読み込む。
    引数: path(Path)は保存gzip pickle。
    返り値: dict。新しい紙上運転はしない。
    """
    with gzip.open(path, 'rb') as stream:
        return pickle.load(stream)


def prepare() -> None:
    """
    機能: 旧33の時刻・native呼値・気配・紙上feedを一つの保存素材へまとめる。
    引数: なし。
    返り値: None。原本/API/金融再生を行わない。
    """
    target = common.HERE / 'prepared.pkl'; assert not target.exists()
    baseline = common.read(common.REFERENCE / '結果.json'); assert baseline['全合格']
    meta = common.read(common.REFERENCE / 'prepared/入力準備の完了.json')
    qpath = common.REFERENCE / 'prepared/quotes.pkl'
    assert common.digest(qpath) == meta['全気配SHA256']
    quotes = common.read(qpath)
    oldpath = common.ROOT / 'work/wave_v83/prepared/inputs.pkl'
    oldmeta = common.read(common.ROOT / 'work/wave_v83/prepared/価格入力の照合.json')
    assert common.digest(oldpath) == oldmeta['出力SHA256']
    old = common.read(oldpath); extras = {}; sources = {
        str(oldpath.relative_to(common.ROOT)).replace('\\', '/'): oldmeta['出力SHA256'],
        str(qpath.relative_to(common.ROOT)).replace('\\', '/'): meta['全気配SHA256'],
        str((common.REFERENCE / '結果.json').relative_to(common.ROOT)).replace('\\', '/'):
            common.digest(common.REFERENCE / '結果.json')}
    for session in ('2026-10-12_Day', '2026-10-12_Night', '2026-10-13_Day'):
        path = common.REFERENCE / 'prepared' / session / 'new_inputs.pkl'
        sources[str(path.relative_to(common.ROOT)).replace('\\', '/')] = common.digest(path)
        extras.update(common.read(path))
    material = {}; checks = []
    for key, q in sorted(quotes.items()):
        original = old[key] if key in old else extras[key]
        for field in ('seq', 'time_s'):
            np.testing.assert_array_equal(q[field], original[field])
        ready = dict(seq=q['seq'], time_s=q['time_s'], last=original['price'] if key in old else original['last'],
            tick=float(original['tick']), start=float(original['start']), limit=float(original['limit']))
        assert ready['time_s'][-1] > ready['limit']
        path = common.REFERENCE / 'paper' / (key[0] + '_' + key[1] + '.pkl.gz')
        relative = str(path.relative_to(common.REFERENCE)).replace('\\', '/')
        assert common.digest(path) == baseline['紙上SHA256'][relative]
        sources[str(path.relative_to(common.ROOT)).replace('\\', '/')] = common.digest(path)
        paper = packet(path); assert paper['key'] == key
        quiet = common.TIME.features(ready, 'U')
        np.testing.assert_array_equal(paper['feed'][:, :8], paper['orders'])
        assert paper['settings']['initial_qty'] == common.QUANTITY[key[1]]
        assert paper['settings']['audit_cap'] == common.CAP[key[1]]
        material[key] = dict(ready=ready, quote=q, paper=paper, quiet=quiet,
            baseline=next(r for r in baseline['results']['L_D20_BBO']['rows'] if (r['session'], r['symbol']) == key))
        checks.append(dict(session=key[0], symbol=key[1], 原行時計一致=True,
            native呼値=ready['tick'], 元紙上注文不変=True, 紙上再生=0))
    assert len(material) == 66
    with target.open('wb') as stream:
        pickle.dump(material, stream, protocol=5)
    common.save(common.HERE / '保存紙上66の入力接続.json', dict(全合格=True, sessions=sorted({k[0] for k in material}),
        入力数=66, 紙上再生=0, 新金融=0, 元入力SHA256=sources, 出力SHA256=common.digest(target),
        検査=checks, sourceSHA256=common.sources(), API=0, 原本再読=0,
        元方向由来='無変更のE01_G_U紙上feedを、生成時の元E01入力/信号監査と固定SHAへ委譲する。相手市場条件は追加しない。'))
    print('保存紙上66の原行・呼値・気配・予定接続完了、紙上0金融0', flush=True)


if __name__ == '__main__':
    prepare()
