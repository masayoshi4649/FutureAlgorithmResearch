"""新基準の公開資料・知見出典・介入ゼロ再利用を最終静的確認する。"""

from html.parser import HTMLParser
from pathlib import Path
import json
import re
from urllib.parse import unquote, urlsplit

from range_engine_check import digest


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PUBLIC = ROOT/'アルゴリズム調査/00103_往復帯の回避と損失後再参加の統合検証'
ENTRY = ROOT/'アルゴリズム調査/共通/知見台帳/入口.md'
EXIT = ROOT/'アルゴリズム調査/共通/知見台帳/出口.md'


class Links(HTMLParser):
    """静的HTMLのリンクと明示アンカーを保持する。"""

    def __init__(self) -> None:
        """
        機能: 副作用のない静的HTML収集器を初期化する。
        引数: なし。
        返り値: None。リンク・ID以外を実行しない。
        """
        super().__init__(); self.links=[]; self.ids=set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str,str|None]]) -> None:
        """
        機能: 要素のhrefとidを文字列として記録する。
        引数: tag(str)、attrs(list[tuple[str,str|None]])は解析要素。
        返り値: None。JavaScript・通信は実行しない。
        """
        values = dict(attrs)
        if values.get('href'): self.links.append(values['href'])
        if values.get('id'): self.ids.add(values['id'])


def read(path: Path) -> dict:
    """
    機能: 保存小JSONを読取専用で解析する。
    引数: path(Path)は資料の位置。
    返り値: dictは保存値。台帳・原板を再生しない。
    """
    return json.loads(path.read_text(encoding='utf-8-sig'))


def links(path: Path) -> list[str]:
    """
    機能: HTML又はMarkdownのローカル参照文字列を取り出す。
    引数: path(Path)は公開文書。
    返り値: list[str]は参照先。外部ページは取得しない。
    """
    text = path.read_text(encoding='utf-8')
    if path.suffix=='.html':
        parser = Links(); parser.feed(text); return parser.links
    return re.findall(r'\[[^\]]+\]\(([^)]+)\)',text)


def local_targets(paths: list[Path]) -> tuple[list[dict],list[dict]]:
    """
    機能: ローカルファイルと明示アンカーの参照を、静的に存在確認する。
    引数: paths(list[Path])は対象公開文書。
    返り値: tuple[list[dict],list[dict]]は確認済みと不成立参照。
    """
    good=[]; bad=[]
    for doc in paths:
        for value in links(doc):
            target_text = value.strip('<>'); parsed = urlsplit(target_text)
            if parsed.scheme or parsed.netloc: continue
            target = (doc.parent/unquote(parsed.path)).resolve() if parsed.path else doc
            item = dict(元文書=doc.relative_to(ROOT).as_posix(),参照=value,対象=str(target))
            if not target.exists(): bad.append(item); continue
            if parsed.fragment and target.is_file():
                text = target.read_text(encoding='utf-8'); fragment = unquote(parsed.fragment)
                explicit = set(re.findall(r'\bid=["\']([^"\']+)["\']',text))
                headings = set(re.findall(r'^#{1,6}\s+(.+?)\s*$',text,re.M))
                if fragment not in explicit and fragment not in headings:
                    # 既存Markdownの自動アンカーを、この静的収集器の範囲で確認する。
                    generated = {re.sub(r'[^\w\-\s]','',h.lower()).replace(' ','-') for h in headings}
                    if fragment not in generated: bad.append(dict(item,理由='明示又は見出しアンカー未確認')); continue
            good.append(item)
    return good,bad


def main() -> None:
    """
    機能: 新HTMLの主張・共通知見・aliasの八部品と保存66会計を静的に点検する。
    引数: なし。既実施UI数値・目視確認を再実行せず、大型入力も読まない。
    返り値: Noneは最終監査証跡。未実施の数量変更を成果に数えない。
    """
    target = HERE/'goal107_公開主張出典と介入ゼロ再利用の最終静的監査.json'; assert not target.exists()
    html = PUBLIC/'変更後65%基準の判定と全セッション損益.html'
    account = read(PUBLIC/'65基準の公開会計.json'); result_path = ROOT/account['集計元']; result = read(result_path)
    assert account['全合格'] and account['集計元SHA256']==digest(result_path) and account['新金融再生']==0
    assert account['全候補判定']==result['summary'] and result['summary']['both_full_pass']==[] and result['summary']['both_robust_pass']==[]
    for ident,value in account['cases'].items(): assert value==result['cases'][ident]
    text = html.read_text(encoding='utf-8')
    for phrase in ('両銘柄で目標を満たす手法は、まだありません','同じ33場','357条件ID','再集計で売買は再実行していません',
        '平均黒字1場で補える','無取引は黒字に数えません','未知確認は0','初回TOPIXミニ5枚／日経マイクロ10枚'):
        assert phrase in text,phrase
    assert 'background:#0b1120' in text and '<meta charset="utf-8">' in text and '<html lang="ja">' in text
    # ----------------------------------------
    # 数量減少と支持進行の観測を一括して価格応答とした総括は、保存値に合わせ是正された。
    entry = ENTRY.read_text(encoding='utf-8'); exit_text = EXIT.read_text(encoding='utf-8')
    assert 'これらは入口で価格が応答しなかった例ではなく' not in entry
    scenes = read(ROOT/'work/wave_v106/e01_absorption_gate/diagnosis/全299公開の表示維持観測と条件交差.json')['指定時刻の公開観測']
    measured=[]
    for scene in scenes[:3]:
        assert len(scene['該当公開'])==1; w = scene['該当公開'][0]
        assert w['Qmin']<w['Q0']; measured.append(dict(商品=scene['symbol'],場=scene['session'],時計=scene['指定時計'],
            Q0=w['Q0'],Qmin=w['Qmin'],支持最大順行=w['maximum_support_advance']))
    assert measured[0]['支持最大順行']==0 and measured[1]['支持最大順行']==measured[2]['支持最大順行']==10
    assert '日経2例' in entry and '数量' in entry
    assert '新金融0' in exit_text and '平均的な黒字1場で補える' in exit_text and '全過去調査の全試行数' in exit_text
    # ----------------------------------------
    # 介入ゼロの記録は元の66小会計と同じ。旧ledger bytesは読まずロケータだけを照合する。
    alias_root = ROOT/'work/wave_v106/e01_absorption_result'; alias_path = alias_root/'介入ゼロの保存66会計再利用.json'
    alias = read(alias_path); plan = read(alias_root/'保存会計再利用の試行計画.json')
    original_path = ROOT/'work/wave_v106/e01_known_veto/finance/結果.json'; original = read(original_path)
    old = original['results'][alias['基準ID']]
    assert alias['全合格'] and alias['新金融再生']==0 and alias['結果種別']=='保存結果再利用（介入0）'
    assert alias['rows']==old['rows'] and alias['symbols']==old['symbols'] and alias['保存元ledger']==old['ledgers']
    assert len(alias['rows'])==len(alias['保存元ledger'])==66 and alias['元金融SHA256']==digest(original_path)
    assert alias['同値証明SHA256']==digest(ROOT/'work/wave_v106/price_review/absorption_全公開mask同値と保存66会計再利用の独立確認.json')
    assert alias['source_sha256']==digest(alias_root/'alias.py') and plan['金融再生']==plan['追加介入']==0
    assert set(plan['spec'])=={'entry','management','exit','allocation','costs','execution','data','implementation'}
    assert '測定後の同値会計再利用' in plan['記録の段階']
    for item in alias['inputs']: assert digest(ROOT/item['path'])==item['sha256']
    for path,sha in plan['spec']['implementation'].items(): assert digest(ROOT/path)==sha
    table_path = ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/data/trials.json'; registry = read(table_path)
    saved = [t for t in registry['trials'] if t['id']==plan['id']]; assert len(saved)==1 and saved[0]['spec']==plan['spec']
    assert saved[0]['status']=='保存結果再利用（介入0）' and saved[0]['completed_result']['sha256']==digest(alias_path)
    # ----------------------------------------
    # 新しい導線と知見出典を確かめる。過去アーカイブの数値やsourceは編集しない。
    documents = [html,PUBLIC/'README.md',ROOT/'README.md',ROOT/'アルゴリズム調査/README.md',ENTRY,EXIT,
        ROOT/'アルゴリズム調査/調査方針.md']
    good,bad = local_targets(documents)
    assert not bad,bad
    index = ROOT/'アルゴリズム調査/index.html'; parser = Links(); parser.feed(index.read_text(encoding='utf-8'))
    new_links = [h for h in parser.links if '変更後65%基準の判定と全セッション損益.html' in h]
    assert len(new_links)>=1 and all((index.parent/unquote(urlsplit(h).path)).resolve()==html.resolve() for h in new_links)
    assert all('変更後65%基準の判定と全セッション損益.html' in p.read_text(encoding='utf-8') for p in (ROOT/'README.md',ROOT/'アルゴリズム調査/README.md',PUBLIC/'README.md'))
    assert '全候補再集計' in exit_text and '介入0は利益を改善した証拠ではない' in entry
    proof = dict(全合格=True,範囲='新公開HTMLの要点と65小会計、知見出典導線、介入0の保存66会計・登録を静的確認。UIは根の既実施QAを再実行しない。',
        source_SHA256={p.relative_to(ROOT).as_posix():digest(p) for p in documents+[index]},
        レビューsource_SHA256=digest(Path(__file__)),ローカル参照確認数=len(good),新index導線数=len(new_links),
        alias結果SHA256=digest(alias_path),登録時点trial数=len(registry['trials']),alias金融再生=0,
        是正=dict(当初過剰表現='3例を一括して入口で価格が応答しなかった例ではないとした。',
            観測=measured,修正='3例の逆側数量減少と日経2例の支持順行を区別。TOPIXの支持は非進行であり、全件の価格応答を断定しない。',
            共通知見及びREADMEの是正確認=True),
        出典是正=dict(初回静的検査='入口.mdの前後安定性と赤字上位3場への既存参照1件が不成立。',
            原因='regime_price配下の相対パスにfinance階層が欠けていた。',
            正規対象='work/wave_v106/regime_price/finance/全26の前後安定性と赤字上位3場の具体時刻.json',
            訂正後全対象確認=True,当該金融JSONの再読=0),
        大型inputs=0,原板=0,NPZ=0,API=0,新金融=0,公開ファイル編集=0,
        留意点=['新基準でも有効性目標は未達。合格の真偽は保存会計と定義の整合に対する監査結果である。',
            '数量変更の私有草案は金融未実施で、このaliasや新基準の有効性結果へ追加していない。',
            '同価格部品の介入0は既存結果再利用の根拠で、新しい成功標本ではない。',
            '過去80%評価はその時点の記録であり、現在65%主基準への変更と分けている。'])
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print('新基準公開と知見出典及びaliasの最終静的監査合格',len(good),digest(target))


if __name__=='__main__': main()
