"""実際に目視した三画面の確認結果を保存する。"""

import json
from pathlib import Path


def main():
    """
    機能: 広幅・狭幅・全セッション表の目視確認を記録する。
    引数: なし。
    返り値: None。既存の表示照合資料を更新する。
    """
    target = Path(__file__).resolve().parent / '表示の独立検査.json'
    value = json.loads(target.read_text(encoding='utf-8'))
    assert value['全合格'] and len(value['画面']) == 3
    value['目視確認'] = True
    value['目視所見'] = '三画面を確認。本文は暗色で判読可能。狭画面の比較表は枠内で横スクロールし、全セッション表は30場と合計を表示。'
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


if __name__ == '__main__':
    main()
