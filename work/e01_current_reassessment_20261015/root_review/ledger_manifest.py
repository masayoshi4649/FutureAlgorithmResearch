"""保存済み結果から、約定選択診断に必要な台帳目録だけを取り出す。"""

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
SOURCE = HERE / '公開用の同bytes結果.json'
EXPECTED = 'ad0df26bb40ae4bc1b37700decec1d1dbabc60efc4419871665b0d23208cb31b'
CASE = 'E01_CURRENT_VOL_PRICE_RESPONSE_WIDE_TRAIL'

# ----------------------------------------


def main() -> None:
    """
    機能: 保存結果の同bytesコピーを一回読み、主候補66台帳のpathと既存SHAだけを射影する。
    引数: なし。
    返り値: None。台帳本文・入力・原板を開かず、新しい金融計算も行わない。
    """
    purpose = HERE / '約定選択の目録射影目的.json'
    target = HERE / '主候補の約定選択診断用66台帳目録.json'
    assert not purpose.exists() and not target.exists()
    purpose.write_text(json.dumps(dict(
        目的='完結親だけの方向損益と、FAK不成立による約定選択を混同しない補助診断へ目録を渡す。',
        元金融結果=0, 同bytes公開保存結果=1, 台帳本文=0,
        cache=0, 原板=0, NPZ=0, API=0, 新金融=0,
        source=str(SOURCE), 期待SHA256=EXPECTED, case=CASE,
    ), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    raw = SOURCE.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    assert digest == EXPECTED
    saved = json.loads(raw.decode('utf-8'))
    ledgers = saved['results'][CASE]['ledgers']
    assert len(ledgers) == 66
    assert len({(row['session'], row['symbol']) for row in ledgers}) == 66
    assert {row['session'] for row in ledgers} == set(saved['sessions'])
    target.write_text(json.dumps(dict(
        全合格=True, case=CASE, 出典=str(SOURCE), 出典SHA256=digest,
        sessions=saved['sessions'], ledgers=ledgers,
        読取=dict(元金融結果=0, 同bytes公開保存結果=1, 台帳本文=0,
                  cache=0, 原板=0, NPZ=0, API=0, 新金融=0),
    ), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 台帳目録件数=len(ledgers),
                          SHA256=hashlib.sha256(target.read_bytes()).hexdigest()),
                     ensure_ascii=False))


if __name__ == '__main__':
    main()
