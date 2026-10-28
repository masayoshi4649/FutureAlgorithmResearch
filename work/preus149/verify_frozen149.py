"""研究149の金融再生前に、登録受領とソース・入力目録の同一性を検査する。"""

import json
from register149 import HERE, ROOT, digest


def main():
    """登録後に実装や設定が変わっていないことを確認する。

    引数: なし。
    返り値: None。不一致は金融再生前に停止する。
    """
    receipt=json.loads((HERE/'登録受領149.json').read_text(encoding='utf-8'))
    assert receipt['returncode']==0 and receipt['registered'] is True
    records=[receipt[k] for k in ('plan','implementation','inputs')]+receipt['sources']
    for row in records:
        assert digest(ROOT/row['path'])==row['sha256'],row['path']
    print(f'登録済み実装・設定・目録の{len(records)}指紋一致')


if __name__=='__main__':
    main()
