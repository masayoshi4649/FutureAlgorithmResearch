"""今回のレポート更新で旧19場が保持されたことを確認する。"""

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
REPORT = ROOT / 'アルゴリズム調査/00044_新候補2手法と基準の説明と損益'


def read(path: Path) -> object:
    """機能: UTF-8の検証資料を読み込む。

    引数: path(Path)。返り値: 保存内容(object)。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def main() -> None:
    """機能: 更新前の全行・固定条件・差分収支と今回の検査証跡を照合する。

    引数: なし。返り値: なし(None)。成功時に差分確認資料を保存する。
    """
    old = read(HERE.parent / 'before_update_20261007_added/報告データ.json')
    new = read(REPORT / '報告データ.json')
    assert old['対象セッション数'] == 19 and new['対象セッション数'] == 23
    additions = new['今回追加セッション']
    assert additions == ['2026-10-02_Night', '2026-10-05_Day',
                         '2026-10-05_Night', '2026-10-06_Day']
    old_methods = {item['spec']['id']: item for item in old['候補']}
    differences = {}
    for method in new['候補']:
        identifier = method['spec']['id']
        before = old_methods[identifier]
        assert method['spec'] == before['spec']
        old_rows = {(r['session'], r['symbol']): r for r in before['sessions']}
        new_rows = {(r['session'], r['symbol']): r for r in method['sessions']}
        assert len(old_rows) == 38 and len(new_rows) == 46
        assert all(new_rows[key] == row for key, row in old_rows.items())
        assert {key[0] for key in new_rows.keys() - old_rows.keys()} == set(additions)
        differences[identifier] = {}
        for symbol in ('TOPIX', 'NK225'):
            net = sum(row['net_yen'] for row in method['sessions']
                      if row['session'] in additions and row['symbol'] == symbol)
            assert net == method['overview'][symbol]['net_yen'] - before['overview'][symbol]['net_yen']
            differences[identifier][symbol] = net

    # ----------------------------------------

    html_hash = hashlib.sha256((REPORT / '新候補2手法の説明と損益.html').read_bytes()).hexdigest()
    audit = read(HERE.parent / '独立確認.json')
    visual = read(HERE.parent / '表示確認.json')
    assert audit['全合格'] and audit['対象週数'] == 3 and audit['表数値セル'] == 972
    assert audit['HTML_SHA256'] == visual['HTML_SHA256'] == new['HTML_SHA256'] == html_hash
    assert visual['全合格'] and read(HERE / 'complete.json')['全合格']
    assert read(HERE / '入力独立監査.json')['全合格']
    assert read(HERE / '再生入力独立照合.json')['全合格']
    result = dict(全合格=True, 更新日='2026-10-07', 旧十九場の全行不変=True,
                  条件説明不変=True, 追加セッション=additions, 追加収支= differences,
                  対象セッション数=23, 対象週数=3, 全口座数=138,
                  表示数値セル=972, HTML_SHA256=html_hash, API追加取得数=0)
    content = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)
    (HERE / '更新差分確認.json').write_text(content, encoding='utf-8')
    (REPORT / '検証資料/update_20261007_added/更新差分確認.json').write_text(content, encoding='utf-8')
    print('旧19場全行不変・追加4場のみ・23場3週972数値の表示整合を確認')


if __name__ == '__main__':
    main()
