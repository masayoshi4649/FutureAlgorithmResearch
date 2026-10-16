"""根が実際に閲覧した4画像の確認を、生成HTMLと表示検査へ結び付ける。"""

import argparse
import hashlib
import json
from pathlib import Path

from verify import MAIN, formal_evidence

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def digest(path: Path) -> str:
    """
    機能: 閲覧した画面とHTML及び検査証跡を識別する。
    引数: path(Path)。
    返り値: str。SHA256。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main() -> None:
    """
    機能: 根が広幅・狭幅・元31損益・追加1と全32の4画像を確認した記録を保存する。
    引数: CLIの--root-four-images-viewed (bool) は根による当該4画像の実閲覧完了。
    返り値: None。自動検査だけを目視済みへ置換しない。
    """
    parser = argparse.ArgumentParser(description='根が現在の4画像を実際に閲覧した後だけ目視を記録します。')
    parser.add_argument('--root-four-images-viewed', action='store_true')
    args = parser.parse_args()
    assert args.root_four_images_viewed, '自動検査だけで根目視済みにはできません'
    evidence = formal_evidence()
    display_path, generated_path = HERE / '表示の独立検査.json', HERE / '生成結果.json'
    display = json.loads(display_path.read_text(encoding='utf-8'))
    generated = json.loads(generated_path.read_text(encoding='utf-8'))
    assert display['全合格'] and generated['全合格'] and len(display['画面']) == 4
    assert display['保存会計口座数'] == 1240 and display['保存追加会計口座数'] == 40 and display['保存全32口座数'] == 1280
    assert display['HTML_SHA256'] == generated['HTML_SHA256']
    assert digest(MAIN) == generated['HTML_SHA256']
    for relative, expected in display['正式根拠SHA256'].items():
        assert digest(ROOT / relative) == expected, relative
    assert {row['画面'] for row in display['画面']} == {
        '安定性の広幅', '安定性の狭幅', '全31実玉群と親', '追加1と全32合計'}
    target = HERE / '根担当の目視確認.json'
    assert not target.exists()
    proof = dict(全合格=True, 確認者='根担当',
        HTML_SHA256=generated['HTML_SHA256'], 表示検査SHA256=digest(display_path),
        生成結果SHA256=digest(generated_path),
        確認内容=['現在の正式結論と参考の位置付けを確認', '両商品を別の安定性表で比較し、狭幅は表内だけ横スクロール',
                '実玉群と親の利益損失を色と補助枚数で分け、同じ収支を加算しない',
                '元31を保持した追加ナイトと全32合計の別表を確認'],
        全20数値の範囲='画像は画面内の閲覧。元31と合計・追加1と全32の二会計4行、前後・買売・親内損失・予算は全20切替のDOM照合で確認。',
        元31独立口座=1240, 追加独立口座=40, 全32合算口座=1280,
        画像SHA256={str(Path(row['画像']).relative_to(ROOT)): digest(Path(row['画像'])) for row in display['画面']},
        原因の使用範囲=evidence['cause']['scope'],
        目視記録コードSHA256={str(Path(__file__).relative_to(ROOT)): digest(Path(__file__))},
        API取得=0, 実注文=0)
    target.write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding='utf-8')
    print('4画像の根目視を記録しました。', flush=True)


if __name__ == '__main__':
    main()
