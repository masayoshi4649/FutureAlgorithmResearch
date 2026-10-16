"""根が実際に閲覧した4画像の確認を、生成HTMLと表示検査へ結び付ける。"""

import hashlib
import json
from pathlib import Path

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
    機能: 根が広幅・狭幅・損益・詳細の4画像を確認した記録を保存する。
    引数: なし。根による当該4画像の実閲覧後だけ実行する。
    返り値: None。自動検査だけを目視済みへ置換しない。
    """
    display_path, generated_path = HERE / '表示の独立検査.json', HERE / '生成結果.json'
    display = json.loads(display_path.read_text(encoding='utf-8'))
    generated = json.loads(generated_path.read_text(encoding='utf-8'))
    assert display['全合格'] and generated['全合格'] and len(display['画面']) == 4
    assert display['HTML_SHA256'] == generated['HTML_SHA256']
    assert {row['画面'] for row in display['画面']} == {
        '安定性の広幅', '安定性の狭幅', '全31実玉群と親', '前後と親内損失及び予算'}
    target = HERE / '根担当の目視確認.json'
    assert not target.exists()
    proof = dict(全合格=True, 確認者='根担当',
        HTML_SHA256=generated['HTML_SHA256'], 表示検査SHA256=digest(display_path),
        生成結果SHA256=digest(generated_path),
        確認内容=['未達の結論と活動不足の参考表示を確認', '両商品を別の安定性表で比較し、狭幅は表内だけ横スクロール',
                '実玉群と親の利益損失を色と補助枚数で分け、同じ収支を加算しない',
                '前後及び買売の損失、黒字親内の負け玉、予算超過ゼロの表示を確認'],
        全31全20数値の範囲='画像は画面内の閲覧。全31と合計及び全20の切替は表示検査のDOM照合で確認。',
        画像SHA256={str(Path(row['画像']).relative_to(ROOT)): digest(Path(row['画像'])) for row in display['画面']},
        API取得=0, 実注文=0)
    target.write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding='utf-8')
    print('4画像の根目視を記録しました。', flush=True)


if __name__ == '__main__':
    main()
