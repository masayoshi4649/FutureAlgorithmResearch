"""市場や金融を再読せず、公開九段階の指紋・参照・証拠区分を確認する。"""

from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

from bs4 import BeautifulSoup


HERE=Path(__file__).resolve().parent
BASE=HERE.parent.parent
ROOT=BASE.parents[1]
PUBLIC=ROOT/'アルゴリズム調査/00119_戦略の自動選択と場内黒字の再探索'
COUNTS=Counter()


def check(value: bool, label: str) -> None:
    """
    機能: 公開配置の一致を記録し、不一致は停止する。
    引数: value(bool)は期待、label(str)は検査名。
    返り値: None。公開ファイルの修正はしない。
    """
    assert value,label
    COUNTS[label]+=1


def main() -> None:
    """
    機能: 正式公開小会計と目録だけから、コピー・リンク・新旧区分を照合する。
    引数: なし。入力は公開済みJSON・HTML・Markdownと根の小目録。
    返り値: None。証跡は私有領域へ新規保存し、金融や原市場は再生しない。
    """
    target=HERE/'公開九段階の指紋と参照及び新旧区分の独立確認.json'
    assert not target.exists()
    raw=(BASE/'公開目録.json').read_bytes();manifest=json.loads(raw)
    check(manifest['root_checked'] is True and len(manifest['phases'])==9,'根の完成九段階目録')
    check((PUBLIC/'成果の元ファイルと指紋.json').read_bytes()==raw,'公開出典目録が根の完成目録と同bytes')
    stages={};copied=[]
    for phase in manifest['phases']:
        directory=PUBLIC/phase['directory'];store={}
        for item in phase['files']:
            path=directory/item['name'];payload=path.read_bytes()
            check(hashlib.sha256(payload).hexdigest()==item['sha256'],'全段階の正式コピーSHA一致')
            copied.append(dict(path=path.relative_to(ROOT).as_posix(),sha256=item['sha256']))
            store[item['name']]=payload
        proof=json.loads(store['生成証跡.json'])
        if '全合格' in proof:
            check(proof['全合格'] is True and proof['合成fixture'] is False and proof['元結果SHA256']==phase['expected'],'初回も正式実会計で合成fixtureではない')
        else:
            check(proof['passed'] is True and proof['fixture'] is False and proof['result_sha256']==phase['expected'],'各改善も正式実会計で合成fixtureではない')
        stages[phase['directory']]=json.loads(store[phase['data']])
    check(len(copied)==27,'九段階27成果の全数照合')
    links=[];external=[]
    for path in [*PUBLIC.rglob('*.html'),*PUBLIC.rglob('*.md')]:
        text=path.read_text(encoding='utf8')
        if path.suffix=='.html':
            soup=BeautifulSoup(text,'html.parser');refs=[a.get('href',a.get('src')) for a in soup.select('[href],[src]')]
        else:refs=re.findall(r'\[[^\]]*\]\(([^)]+)\)',text)
        for value in refs:
            value=value.strip('<>');parts=urlsplit(value)
            if parts.scheme or parts.netloc:external.append(dict(path=path.relative_to(ROOT).as_posix(),ref=value));continue
            dest=(path.parent/unquote(parts.path)).resolve() if parts.path else path
            check(dest.exists(),'公開HTMLとMarkdownの全相対リンク実在')
            if parts.fragment and dest.suffix=='.html':
                page=BeautifulSoup(dest.read_text(encoding='utf8'),'html.parser')
                check(page.find(id=unquote(parts.fragment)) is not None,'HTML内アンカー実在')
            links.append(dict(path=path.relative_to(ROOT).as_posix(),ref=value))
    h=stages['再確認_少額E01追加'];hr=h['cases']['E01_006_FIXED']['rows'];scenes=h['sessions']
    check(len(hr)==80 and len(scenes)==40 and h['reused_account_rows']==66 and h['new_accounts']==14,'h掲載80行を旧引用66と新14へ区分')
    old=[r for r in hr if r['origin']=='旧33保存会計の引用'];new=[r for r in hr if r['origin']=='追加七場の新金融']
    check(len(old)==66 and len(new)==14 and all(r['unclosed'] is None and r['verified_flat'] is True for r in old),'旧数量nullを零補完せず旧flat保証へ委譲')
    check(all(r['unclosed']==0 and r['verified_flat'] is True for r in new),'新14だけ実終端検査')
    revision=h['input_revision']
    check(revision['prior_financial_accounts']==0 and revision['date_shift_days']==0 and revision['original_rereads']==0 and revision['original_clock_preserved'] and revision['raw_seq_preserved'],'初回停止とh入力資格差を保持')
    dualraw=(PUBLIC/'二口座の合算損益.json').read_bytes();dual=json.loads(dualraw)
    check(hashlib.sha256(dualraw).hexdigest()==manifest['dual']['sha256'],'二口座合算の根指定SHA一致')
    check(len(dual['rows'])==40 and dual['new_financial_replay']==0 and dual['new_independent_evidence'] is False,'dual40は保存二口座の算術合算で新証拠ではない')
    for row in dual['rows']:
        rr=[r for r in hr if r['session']==row['session']]
        check(len(rr)==2 and all(math.isclose(row[k],sum(r[k] for r in rr),rel_tol=0,abs_tol=1e-7) for k in ('profit','loss','net','fees')),'dual全40場が商品別h二口座の金額合計')
    j=stages['改善7_気配差を含む停止予算']
    check(len(j['cases'])==8 and sum(len(c['rows']) for c in j['cases'].values())==320,'j新8条件320組を掲載')
    check(len(j['baseline_cases'])==8 and sum(len(c['rows']) for c in j['baseline_cases'].values())==320 and j['reused_baseline_rows']==320,'j旧8条件320行は別の保存引用')
    check(j['baseline_reference']['financial_replay']==0 and j['baseline_reference']['sha256']=='2f7c15e27d7c0e20b6b14de8ab682ac62d49a55b6ba35d2079b6245d9699dcf4','j旧引用はv8完成結果へ結合し再金融零')
    maintext=BeautifulSoup((PUBLIC/'結論と全セッション損益.html').read_text(encoding='utf8'),'html.parser').get_text(' ',strip=True)
    check('26黒字・1赤字・13無取引' in maintext and '毎場の安定黒字や損小利大を確立したものではありません' in maintext,'暫定候補を完成解へ読み替えない')
    check('保有中の合成時価と最大下落は未検証' in maintext and '分散効果を確認したとはしません' in maintext,'dual共同リスクと経済的同質性の未測定を明示')
    proof=dict(passed=True,scope='公開コピー・参照・小会計の区分だけの確認。市場や金融の再検証ではない。',counts=dict(COUNTS),total_checks=sum(COUNTS.values()),manifest_sha256=hashlib.sha256(raw).hexdigest(),copied=copied,links=links,external=external,h_rows=80,h_saved_rows=66,h_new_accounts=14,dual_sessions=40,dual_new_evidence=False,j_new_pair_sessions=320,j_reused_pair_rows=320,market_reads=0,financial_replay=0,API=0,public_edits=0)
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps(dict(passed=True,checks=sum(COUNTS.values()),links=len(links),sha256=hashlib.sha256(target.read_bytes()).hexdigest()),ensure_ascii=False))


if __name__=='__main__':
    main()
