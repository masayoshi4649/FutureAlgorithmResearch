"""v2公式人工の指紋と独立資料を読み合わせ、設計修正の確定だけを判定する。"""

import hashlib
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
V2 = HERE.parent / 'input_v2'


def digest(path: Path) -> str:
    """
    機能: 小さいsourceとJSONだけの指紋を求める。
    引数: path(Path)は対象ファイル。
    返り値: strはSHA256。大型素材及び生原本は読まない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    """
    機能: 入力source証跡とreview資料だけを読み取る。
    引数: path(Path)は資料。
    返り値: dictはJSONの内容。金融再生結果を読まない。
    """
    assert path.resolve().is_relative_to(HERE.parent.resolve())
    return json.loads(path.read_text(encoding='utf-8'))


# ----------------------------------------

def main() -> None:
    """
    機能: 未解決5点の補足確定、公式人工及び独立oracleが同sourceへつながることを確認する。
    引数: なし。
    返り値: None。新review資料を保存。正式64派生、JIT、実接頭及び金融は未実行。
    """
    destination = HERE / '補足06確定とv2公式人工の独立由来確認.json'
    assert not destination.exists(), '完成資料は上書きしません'
    official_path = V2 / '前価格時計逆行の二列訂正と人工未来不変.json'
    official = read(official_path)
    assert official['全合格'] and official['二列だけ訂正'] and official['不変配列数'] == 42
    assert official['正式全64派生'] == official['原本再読取'] == official['金融再生'] == 0
    checked = {}
    for section in ('保持v1_SHA256', 'コードSHA256'):
        for relative, wanted in official[section].items():
            assert digest(ROOT / relative) == wanted, relative
            checked[relative] = wanted
    schema_path = V2 / '入力schema.json'
    assert digest(schema_path) == official['v2schemaSHA256']
    schema = read(schema_path)
    assert schema['version'] == 2 and len(schema['columns']) == 44
    assert schema['訂正']['変更列'] == ['volume_delta_usable', 'volume_delta']
    false = read(HERE.parent / 'input' / 'v1の価格時計逆行後usableの反例.json')
    assert false['全合格'] is False and false['反例を再現できた'] is True
    independent_paths = [HERE / '定着反転と二市場判断の独立人工反証.json',
                         HERE / 'v2二列訂正と入口接頭未来不変の独立人工.json']
    for path in independent_paths:
        value = read(path)
        assert value['全合格'] and value['金融再生'] == 0 and value['JIT実行'] == 0
        for relative, wanted in value['SHA256'].items():
            assert digest(ROOT / relative) == wanted, relative
            checked[relative] = wanted
    result = dict(全合格=True,
                  scope='設計草案で指摘した5点の補足04〜06確定と、最小二列訂正source・公式人工・独立人工の指紋を照合。正式金融及び実raw接頭は含まない。',
                  五点再判定=dict(R新支持分母='初期own数量へ固定', R偽回復='直前原行比の正増加が必要',
                                  消費済反対判断='全valid-readyで競合判定',
                                  部品省略='次の正常別行で一段階だけ通過',
                                  支持回復='移動段階より後の現在行でready可、同episode再pulse不可'),
                  proxy単独reset資格='正常資格の全resetと隣接正常quoteを満たす区間だけ',
                  v1_false保持=True, 訂正sourceの独立oracle合格=True, 公式人工sourceSHA一致=True,
                  検査指紋件数=len(checked), sourceSHA256=checked,
                  資料SHA256={str(path.relative_to(ROOT)): digest(path) for path in (
                      Path(__file__), official_path, schema_path, *independent_paths,
                      *[HERE.parent / f'数値設計補足{index:02d}.json' for index in range(4, 7)])},
                  正式全64派生=0, 生原本再読取=0, 金融再生=0, 現在API取得=0, 実注文=0,
                  source変更=0, JIT実行=0)
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 検査指紋件数=len(checked), SHA256=digest(destination)), ensure_ascii=False))


if __name__ == '__main__':
    main()
