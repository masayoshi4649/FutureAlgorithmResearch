"""金融結果を再読せず、受領済みコピーから主要比較二文だけを表示に加える。"""

import json
from pathlib import Path

from bs4 import BeautifulSoup

import render123 as R


HERE=Path(__file__).resolve().parent
EXPECTED='91475e3757d4a9462f1ecc9405c43e76145967693b0802c56e73068dd0db416c'
PREVIOUS='33e3c2228ce1aad94d4acf0fcaa2bbfc7a09e4d6bed7c166b4e7bc6dd8cf9953'


def main() -> None:
    """
    機能: 旧HTMLと全表同値のまま二つの説明と診断導線を公開する。
    引数: なし。受領済み結果と同bytes保全した旧HTMLだけを参照する。
    返り値: None。公開HTMLの表示改訂と新しい私有証跡を保存する。
    """
    archive=HERE/'archive/主要比較二文を追加する前'
    old=(archive/R.NAME).read_bytes();assert R.digest(old)==PREVIOUS
    assert R.digest(R.OUTPUT.read_bytes())==PREVIOUS
    received=HERE/'received/途中利確なしの十九間隔と全四十場.json'
    raw=received.read_bytes();assert R.digest(raw)==EXPECTED
    text,metrics=R.render(json.loads(raw),EXPECTED);payload=text.encode('utf8')
    before=BeautifulSoup(old,'html.parser');after=BeautifulSoup(payload,'html.parser')
    assert [str(e) for e in before.select('table')]==[str(e) for e in after.select('table')]
    assert str(before.select_one('#condition'))==str(after.select_one('#condition'))
    assert before.script.string==after.script.string
    plain=after.get_text(' ',strip=True)
    for phrase in ('-1,031,046円・11黒字29赤字','-318,722円・12黒字28赤字','653→271枚','-255,406円でも6黒字33赤字1無取引'):
        assert phrase in plain,phrase
    links=after.select('a[href]');assert len(links)==1
    assert (R.OUTPUT.parent/links[0]['href']).resolve().is_file()
    R.OUTPUT.write_bytes(payload)
    proof=dict(passed=True,revision=2,result_SHA256=EXPECTED,previous_HTML_SHA256=PREVIOUS,HTML_SHA256=R.digest(payload),
        report_SHA256=R.digest((HERE/'render123.py').read_bytes()),all_tables_same=True,selector_same=True,script_same=True,
        change='同じ所有結果の既存小集計から主要比較二文を追加し、診断MDへの相対リンク一つを付けた。',
        original_result_additional_reads=0,own_copy_reads=1,NPZ_reads=0,market_reads=0,financial_replay=0,registry_reads=0,API=0)
    target=HERE/'主要比較二文だけの表示改訂と全表不変.json';assert not target.exists()
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')
    print(json.dumps(dict(passed=True,HTML_SHA256=proof['HTML_SHA256'],proof_SHA256=R.digest(target.read_bytes())),ensure_ascii=False))


if __name__=='__main__':
    main()
