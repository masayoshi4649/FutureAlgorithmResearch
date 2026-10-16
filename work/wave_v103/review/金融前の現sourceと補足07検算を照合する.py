"""補足07の独立検算、公式人工、v2由来及び他担当実接頭を同じ現sourceへ結び付ける。"""

import hashlib
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WAVE = HERE.parent


def digest(path: Path) -> str:
    """
    機能: 小sourceとJSON証跡の指紋を取る。
    引数: path(Path)は対象ファイル。
    返り値: strはSHA256。生原本又は全64npzを再走査しない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    """
    機能: 設計、入力由来、非金融証跡だけを読む。
    引数: path(Path)はJSON。
    返り値: dictは内容。正式金融結果を読まない。
    """
    assert path.resolve().is_relative_to(WAVE.resolve())
    return json.loads(path.read_text(encoding='utf-8'))


# ----------------------------------------

def main() -> None:
    """
    機能: 独立人工と公式人工及び入力由来のsource指紋を確認し、金融前の入口判定を残す。
    引数: なし。
    返り値: None。review新JSONだけを保存し、原本再読取及び金融実行は行わない。
    """
    destination = HERE / '補足07独立入口と現source及びv2由来の金融前判定.json'
    assert not destination.exists(), '完成判定を上書きしません'
    independent_path = HERE / '補足07入口の独立oracleと旧56反例消失及び接頭不変.json'
    artificial_path = WAVE / 'engine' / '独立状態と厳密過去接続及び実配分の人工検査_補足07確定.json'
    prefix_path = WAVE / 'engine' / '固定2場の実状態と二市場pulseの接頭不変.json'
    metadata_path = WAVE / 'input_v2' / 'metadata.json'
    v2_artificial_path = WAVE / 'input_v2' / '前価格時計逆行の二列訂正と人工未来不変.json'
    paths = [independent_path, artificial_path, prefix_path, metadata_path, v2_artificial_path]
    values = [read(path) for path in paths]
    independent, official, prefix, metadata, v2_artificial = values
    assert all(value['全合格'] for value in values)
    assert independent['一致人工ケース数'] == 1120 and independent['旧崩れ56件の持越し消失'] == 56
    assert independent['維持56件で別行段階通過'] == 56
    assert independent['人工接頭数'] == independent['人工未来変更数'] == 3248
    assert official['検査件数']['PythonとJITの状態及び原行ログ一致'] == 840
    assert official['正式金融再生'] == prefix['正式金融再生'] == 0
    assert prefix['対象場'] == ['2026-09-21_Day', '2026-10-12_Night']
    assert prefix['検査件数']['口座'] == 4 and prefix['検査件数']['境界接頭'] == 44
    assert metadata['schema']['version'] == 2 and metadata['口座数'] == metadata['正式全64派生'] == 64
    assert len(metadata['sessions']) == 32 and len(metadata['accounts']) == 64
    assert set(metadata['accounts']) == {session + '|' + symbol for session in metadata['sessions']
                                       for symbol in ('TOPIX', 'NK225')}
    counts = [account['訂正'] for account in metadata['accounts'].values()]
    assert all(count['全合格'] and count['不変配列数'] == 42 for count in counts)
    assert sum(count['usable変更行数'] for count in counts) == 0
    assert sum(count['支持用差変更行数'] for count in counts) == 0
    checked = {}
    for value, key in ((independent, 'SHA256'), (official, 'SHA256'), (prefix, 'SHA256'),
                       (metadata, '小直接依存SHA256'), (v2_artificial, 'コードSHA256'),
                       (v2_artificial, '保持v1_SHA256')):
        for relative, wanted in value[key].items():
            assert digest(ROOT / relative) == wanted, relative
            if relative in checked:
                assert checked[relative] == wanted, relative
            checked[relative] = wanted
    old_false_path = HERE / 'C準備とR回復行の先行移動を忘れる独立人工反例.json'
    old_false = read(old_false_path)
    assert old_false['全合格'] is False and old_false['価格破れで旧活動再使用件数'] == 56
    result = dict(全合格=True,
        scope='独立人工入口と補足07現sourceの照合及び他担当公式証跡への由来接続。私自身が実raw接頭や全64不変列を再実行した判定ではない。金融収益性は未判定。',
        入口の金融前独立判定='補足07を含む現sourceへ事前固定する設計及び局所人工上の障害は見つからない。正式金融は根の別指示が必要。',
        独立oracle=dict(ケース=1120, 旧崩れ持越し消失=56, 維持別行=56, 接頭=3248, 未来変更=3248),
        他担当公式人工=dict(状態素材=105, PythonとJIT比較=840, source一致=True),
        他担当実接頭=dict(対象場=prefix['対象場'], 口座=4, 境界接頭=44,
                        比較=prefix['検査件数'], source一致=True),
        v2完成由来=dict(口座=64, 不変列確認件数=64 * 42, 実訂正0=True,
                        生原本再読取0=True, v1False保持=True, source一致=True),
        指紋検査件数=len(checked), 現sourceSHA256=checked,
        資料SHA256={str(path.relative_to(ROOT)): digest(path) for path in [Path(__file__), *paths, old_false_path]},
        独立担当の正式raw読取=0, 独立担当の正式64派生=0, 独立担当の実接頭実行=0,
        金融再生=0, 現在API取得=0, 実注文=0, 本体source変更=0, 独立担当のJIT実行=0)
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 指紋検査件数=len(checked), SHA256=digest(destination)), ensure_ascii=False))


if __name__ == '__main__':
    main()
