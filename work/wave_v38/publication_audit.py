"""検算済みの損益・売買図・資料案内を同じ公表成果として結合する。"""

from __future__ import annotations

from pathlib import Path
import re
from urllib.parse import unquote, urlsplit
from bs4 import BeautifulSoup
import adaptive_runner as runner

HERE,ROOT=runner.HERE,runner.ROOT
OUT=ROOT/'アルゴリズム調査/00033_復元方式の自動選択と改善8条件の反証'


def main() -> None:
    """機能: 数表・描画・リンクとそれぞれの固定指紋を公表前に確認する。

    引数: なし。返り値: なし (None)。売買条件・経済判定は変更しない。
    """
    references={}
    def bind(path: Path, expected: str|None=None) -> str:
        """機能: 実物の指紋を照合し、公表資料へ結合する。

        引数: path (Path)、expected (str|None)。返り値: SHA256 (str)。
        """
        actual=runner.digest(path)
        if expected is not None: assert actual==expected,str(path)
        references[path.relative_to(ROOT).as_posix()]=actual
        return actual
    complete=runner.read(HERE/'経済完備監査.json')
    assert complete['経済検証完了'] and complete['全体目標達成'] is False
    assert complete['検証完了'] is False and complete['実装状態契約合格'] is False
    assert complete['完全実装合格'] is False
    for name,sha in complete['参照資料SHA256'].items(): bind(ROOT/name,sha)
    bind(HERE/'economic_completion_guard.py',complete['ガードSHA256'])
    test=runner.read(HERE/'economic_completion_guard_test.json')
    assert test['全合格'] and test['破損拒否数']==44
    bind(HERE/'economic_completion_guard.py',test['ガードSHA256'])
    bind(HERE/'economic_completion_checks.py',test['補助SHA256'])
    bind(HERE/'economic_completion_guard_test.py',test['試験SHA256'])
    table=runner.read(HERE/'report_contract_audit.json')
    assert table['全合格'] and table['全金額枚数行数']==33116 and table['比較行数']==24
    assert table['表示操作']['合格'] and table['表示操作']['操作数']==974 and table['候補直接リンク数']==8
    assert table['合否表示数']==3 and table['候補表行数']==8 and table['全比較ラベル一致']
    assert table['経済検証と状態不合格の分離表示'] and table['乱数対照数の表示一致']
    for name,sha in table['HTML_SHA256'].items(): bind(OUT/name,sha)
    fixed=runner.read(HERE/'chart_fixed.json')
    for name,sha in fixed['実装SHA256'].items(): bind(HERE/name,sha)
    chart=OUT/'５分足と売買.html'
    for name,mapkey,flags in (
        ('chart_audit.json','ソースSHA256',('全収支一致','全返済一致','全注文一致','全台帳一致','全数量asof一致','全分岐一致')),
        ('chart_data_audit.json','元資料SHA256',('全注文一致','全返済一致','全数量独立asof一致','全操作根拠一致','全原本足一致','全リンク一致','全分岐根拠一致','全終端残玉ゼロ'))):
        proof=runner.read(HERE/name)
        assert proof['全図示数']==156 and all(proof[k] is True for k in flags)
        bind(chart,proof['HTML_SHA256']);bind(HERE/'chart_fixed.json',proof['固定SHA256'])
        for path,sha in proof[mapkey].items(): bind(Path(path),sha)
    visual=runner.read(HERE/'chart_visual_check.json')
    assert visual['全操作合格'] and visual['各描画で全156選択']
    assert len(visual['固定描画例'])==3
    bind(chart,visual['HTML_SHA256'])
    for row in visual['固定描画例']:
        assert row['成功'] and row['全選択数']==156 and row['売買画素数']>0
        bind(HERE/row['画像'],row['画像SHA256'])
    # ----------------------------------------
    # 手元の成果と案内から辿る全リンクを、同じディレクトリ解決で確かめる。
    links=0
    documents=[OUT/'復元方式の自動選択と改善8条件の反証.html',OUT/'全条件損益.html',chart,OUT/'README.md',HERE/'今回の到達点.md']
    for path in documents:
        text=path.read_text(encoding='utf-8')
        assert '独立監査中の暫定' not in text
        urls=[a['href'] for a in BeautifulSoup(text,'html.parser').select('[href]')] if path.suffix=='.html' else re.findall(r'\]\(([^)]+)\)',text)
        for url in urls:
            split=urlsplit(url)
            if split.scheme or not split.path: continue
            target=(path.parent/unquote(split.path)).resolve()
            assert target.exists(),(path.name,url)
            links+=1
        bind(path)
    # ----------------------------------------
    # 数表の実描画は親が2画面、売買図は1画面を目視済み。全切替は別の自動検査。
    pages=runner.read(HERE/'html_visual_check.json')
    assert {p['ファイル'] for p in pages}==set(table['HTML_SHA256'])
    for page in pages:
        assert page['描画後DOM保存'] and page['画像バイト']>10000
        bind(HERE/page['PNG'])
    for name in ('経済完備監査.json','economic_completion_guard_test.json','report_contract_audit.json',
        'chart_fixed.json','chart_audit.json','chart_data_audit.json','chart_visual_check.json',
        'chart_backlink_revision.json','chart_format_revision.json','chart_terminal_revision.json','html_visual_check.json',
        'report_adaptive.py','report_contract_audit.py','publication_audit.py'):
        bind(HERE/name)
    runner.save(HERE/'公表確認.json',dict(公表可能=True,全条件=974,全金額枚数行数=33116,
        直接リンク8件=True,全図示数=156,内部リンク数=links,主担当目視画面数=3,
        経済検証完了=True,実装状態契約合格=False,完全実装合格=False,
        全体目標達成=False,現在API取得数=0,参照SHA256=references))
    print('974条件の数表・156売買図・資料リンクを公表成果へ結合。',flush=True)


if __name__=='__main__':main()
