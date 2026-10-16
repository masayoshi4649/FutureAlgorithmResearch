"""根担当が確認した五画面を、現在の公開前資料へ結び付ける。"""

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def digest(path: Path) -> str:
    """
    機能: 目視した画像と資料の同一性を固定する。
    引数: path(Path)は確認済みファイル。
    返り値: str。SHA256の文字列。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main() -> None:
    """
    機能: 数値検査と別に、根担当の完了した目視内容を記録する。
    引数: なし。
    返り値: None。確認済み画像を結び付けた日本語JSONを保存する。
    """
    display_path = HERE / '表示の独立検査.json'
    display = json.loads(display_path.read_text(encoding='utf-8'))
    generated = json.loads((HERE / '生成結果.json').read_text(encoding='utf-8'))
    assert display['全合格'] and generated['全合格']
    assert display['HTML_SHA256'] == generated['HTML_SHA256']
    assert len(display['画面']) == 5
    proof = dict(
        全合格=True,
        HTML_SHA256=generated['HTML_SHA256'],
        確認範囲='根担当が現行HTMLから描画した五画面を目視。広幅・狭幅、全31損益、安定性及び前後、原因と詳細条件を確認した。',
        結論='暗色で損失と利益を区別できる。全31行と合計、無取引、活動場率を掲載。狭幅では表内だけ横スクロール。低活動の主を採用せず、価格時計と受信時計の違い、真の二市場受信順が未証明である点を記載した。',
        画像SHA256={str(Path(row['画像']).relative_to(ROOT)): digest(Path(row['画像'])) for row in display['画面']},
        表示検査SHA256=digest(display_path),
    )
    (HERE / '根担当の目視確認.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 確認画面数=5, HTML_SHA256=proof['HTML_SHA256']), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
