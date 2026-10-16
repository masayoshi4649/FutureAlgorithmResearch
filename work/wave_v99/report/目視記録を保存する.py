"""根担当が実際に見た五画面を、公開対象のHTMLと照合証跡へ結びつける。"""

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def read(path: Path) -> dict:
    """
    機能: HTML生成又は表示検査の記録を読む。
    引数: path(Path)はJSONファイル。
    返り値: dict。保存された内容。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path: Path) -> str:
    """
    機能: 目視した画像と公開対象の同一性を保存する。
    引数: path(Path)はファイル。
    返り値: str。SHA256。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main() -> None:
    """
    機能: 根担当による五画像の目視後に公開前の確認記録を保存する。
    引数: なし。
    返り値: None。生成HTMLと表示検査そのものは変更しない。
    """
    generated_path, display_path = HERE / '生成結果.json', HERE / '表示の独立検査.json'
    generated, display = read(generated_path), read(display_path)
    assert generated['全合格'] and display['全合格']
    html = ROOT / generated['HTML']
    assert generated['HTML_SHA256'] == display['HTML_SHA256'] == digest(html)
    assert len(display['画面']) == 5
    images = {str(Path(row['画像']).relative_to(ROOT)): digest(Path(row['画像'])) for row in display['画面']}
    result = dict(全合格=True, HTML_SHA256=digest(html),
                  生成結果SHA256=digest(generated_path), 表示検査SHA256=digest(display_path),
                  画像SHA256=images, 確認画像数=5,
                  目視内容=[
                      '広幅で短い三段落の結論、七対照の安定性と全場損益が暗色背景で読める。',
                      '狭幅では比較表内の横スクロールを使い、文書全体の横溢れはない。',
                      '全31セッションと合計行に両商品の利益・損失・収支と枚数が表示される。',
                      '期間別・安定性・入口方向別会計の表が分かれて読める。',
                      '原因と未検証案は折りたたみ内に分け、価格時計の判断296秒と支持格子295秒を区別している。'],
                  判定='切れ、重なり、欠けを認めず公開可能。狭幅比較表は横スクロールを使用。')
    (HERE / '根担当の目視確認.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 確認画像数=5, HTML_SHA256=digest(html)), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
