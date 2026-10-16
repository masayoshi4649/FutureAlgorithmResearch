"""料金商品と既知内探索を明示した最終表示を、旧QAを保持して別領域で確認する。"""

from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path

import report_view


def main() -> None:
    """
    機能: 同じ表示QAを最終文章へ接続し、旧画像・証跡を上書きしない。
    引数: なし。公開HTML・小会計を読み、金融入力は読まない。
    返り値: None。金融源・結果・APIを変更せず、三画面を新領域へ保存する。
    """
    report_view.OUTPUT = Path(__file__).resolve().parent/'report_review_v2'
    with redirect_stdout(io.StringIO()):
        report_view.main()
    proof_path = report_view.OUTPUT/report_view.PROOF_NAME
    proof = json.loads(proof_path.read_text(encoding='utf-8'))
    proof['最終文章QAの実行source_SHA256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    proof['理由'] = '料金がミニ・マイクロである点と、既知内探索・無敗時平均損失未定義を追記した表示変更。旧QAは保持。金融再生0。'
    proof_path.write_text(json.dumps(proof, ensure_ascii=False, indent=2)+'\n', encoding='utf-8', newline='\n')
    print(json.dumps(dict(全合格=proof['全合格'], 画面数=len(proof['画面']),
        全場セル数=proof['静的照合']['件数']['全場円枚数'],
        HTML_SHA256=proof['HTML_SHA256'], 根目視確認=False, 金融再生=0), ensure_ascii=False))


if __name__ == '__main__':
    main()
