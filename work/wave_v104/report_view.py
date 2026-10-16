"""根担当が実画像を目視した事実を、最終HTMLと画像の指紋へ結ぶ。"""

import json
from pathlib import Path

import base


HERE = Path(__file__).resolve().parent


def main() -> None:
    """
    機能: 目視完了した四画像と最終下書きの内容指紋を保存する。
    引数: なし。根担当の実画像確認後だけ実行する。
    返り値: None。新しい確認証跡を保存し、金融計算は行わない。
    """
    generated = base.read(HERE/'report/生成結果.json')
    names = ('比較表の広幅', '比較表の狭幅', 'U_P10_T2の全場表', 'P50_P10_T2の全場表')
    images = {str((HERE/'report/visual'/(name+'.png')).relative_to(base.ROOT)):
              base.digest(HERE/'report/visual'/(name+'.png')) for name in names}
    proof = dict(全合格=True, HTML_SHA256=generated['HTML_SHA256'], 画像SHA256=images,
        実画像目視=True, 結論と追加場表示='明瞭', 全33場と二合計の表='表示あり',
        狭幅='表だけ横スクロール。本文は画面内に折り返す。',
        旧版の保存='長い内部理由列挙を一文へ変更。旧下書きと旧画像を保存。',
        数値変更=0, 金融再生=0, 実注文=0)
    path = HERE/'report/根担当の目視確認.json'
    assert not path.exists()
    path.write_text(json.dumps(proof, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print('4 images verified', flush=True)


if __name__ == '__main__':
    main()
