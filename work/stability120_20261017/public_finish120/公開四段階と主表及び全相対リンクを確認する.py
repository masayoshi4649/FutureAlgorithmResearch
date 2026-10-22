"""公開済み表示だけを一読し、四段階の同bytesと主表及び全相対導線を確認する。"""

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import statistics
from urllib.parse import unquote,urlsplit

from bs4 import BeautifulSoup


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
PUBLIC=ROOT/'アルゴリズム調査/00120_段階トレーリング新規と利益玉の部分回転'
MAIN='段階トレーリングの結論と全セッション損益.html'
PHASES=(('01_提案型と八つの管理',48,'c99743d739c9d24a08088f1b5ebdc78af8285b19e9704773965ea05f13890ce1'),
    ('02_小試行と方向別停止',24,'1071dc7f296d8ffbf3483e26b863d79cde48b82bcca986a7b5810c8e18f9ee9f'),
    ('03_最終約定値による追尾',24,'665cc66e7f5f1788393082a80b2f8dc19468f9b5987f49025f4c813468166c59'),
    ('04_上下対称回転とカバー保持',18,'63766637c69f8572465b1ec3cc3c735e8eef234c1657b3ca0542bd3b6fa9f2ba'))
SYMBOLS=('TOPIX','NK225')
CONTENT={}
PAGES={}
CHECKS=Counter()
READLOG=[]


def read(path: Path) -> bytes:
    """
    機能: 公開範囲の各ファイルを最大一回読み、同じ内容を以後再利用する。
    引数: path(Path)は公開成果。リンク先の市場資料やNPZは読まない。
    返り値: bytesは当該公開ファイルの同一内容。
    """
    path=path.resolve()
    assert path.is_relative_to(PUBLIC.resolve())
    assert path.suffix.lower() not in ('.npz','.pkl','.pickle','.jsonl')
    if path not in CONTENT:
        owned=HERE/'owned_public'/path.relative_to(PUBLIC.resolve())
        if owned.exists():
            CONTENT[path]=owned.read_bytes();origin='自身同bytes保全copy'
        else:
            CONTENT[path]=path.read_bytes();owned.parent.mkdir(parents=True,exist_ok=True)
            owned.write_bytes(CONTENT[path]);origin='公開実体一読後parse前同bytes保全'
        READLOG.append(dict(path=path.relative_to(ROOT).as_posix(),origin=origin,SHA256=hashlib.sha256(CONTENT[path]).hexdigest()))
    return CONTENT[path]


def check(value: bool, name: str) -> None:
    """
    機能: 表示の不整合をその場で停止し、成功確認の範囲を記録する。
    引数: value(bool)は条件、name(str)は検査名。
    返り値: None。原データ・公開成果・台帳は変更しない。
    """
    assert value,name
    CHECKS[name]+=1


def number(value: float, signed: bool=False) -> str:
    """
    機能: 主表の期待円額を公開generatorとは別に整形する。
    引数: value(float)は円額、signed(bool)は符号明示の指定。
    返り値: strは金額。損失は正の絶対額、netは符号を保持する。
    """
    if abs(value)<1e-7:return '0'
    return f'{value:+,.0f}' if signed else f'{value:,.0f}'


def page(path: Path) -> BeautifulSoup:
    """
    機能: 公開HTMLを一度解析し、同じDOMを表・リンク確認で再利用する。
    引数: path(Path)は公開HTML。
    返り値: BeautifulSoupは保存済みDOM。JavaScriptや金融を実行しない。
    """
    path=path.resolve()
    if path not in PAGES:PAGES[path]=BeautifulSoup(read(path).decode('utf8'),'html.parser')
    return PAGES[path]


def main() -> None:
    """
    機能: 114条件・全40場・正式四表示のSHAと主表、全相対リンクを照合する。
    引数: なし。根の公開完了通知後だけ実行する。
    返り値: None。私有証跡だけ保存し、結果・入力・台帳を再計算しない。
    """
    target=HERE/'公開四段階114条件と主表全40場及び全導線の最終確認.json'
    assert not target.exists()
    manifest=json.loads(read(PUBLIC/'公開目録.json'))
    check(manifest['root_checked'] is True and len(manifest['phases'])==4,'正式四段階だけを掲載')
    cases=[];bundles=[];symbols_positive=Counter();scenes=None
    for phase,(directory,count,resultsha) in zip(manifest['phases'],PHASES):
        check((phase['directory'],phase['policies'],phase['result_sha256'])==(directory,count,resultsha),'順序48_24_24_18と指定完成SHAを保持')
        folder=PUBLIC/directory
        generated=json.loads(read(folder/'生成証跡.json'))
        check(generated['passed'] is True and generated['fixture'] is False and generated['policies']==count,'合成と停止版を正式四表示へ混ぜない')
        check(generated['result_sha256']==resultsha and generated['symbol_sessions']==count*80,'e1実1440だけを18条件として数える')
        for name,sha in phase['files'].items():
            check(hashlib.sha256(read(folder/name)).hexdigest()==sha,'四表示のHTML_JSON_README生成証跡は元正式版同bytes')
        for name,sha in generated['artifacts'].items():
            check(hashlib.sha256(read(folder/name)).hexdigest()==sha,'元生成証跡の全公開成果SHAを保持')
        data=json.loads(read(folder/'data.json'))
        check(data['fixture'] is False and data['source_SHA256']==resultsha,'各段階の根拠結果SHAと実測区分')
        check(len(data['cases'])==count and len(data['sessions'])==len(set(data['sessions']))==40,'全条件と唯一40場を保持')
        if scenes is None:scenes=data['sessions']
        check(scenes==data['sessions'],'四段階は同じ既知40場')
        check(len(page(folder/phase['report']).select('table.sessions'))==count,'全114条件の場表を省略しない')
        for identity,case in data['cases'].items():
            check(len(case['rows'])==80 and len({(r['session'],r['symbol']) for r in case['rows']})==80,'商品とセッションを跨ぐ欠行重複なし')
            for symbol in SYMBOLS:
                rows=[r for r in case['rows'] if r['symbol']==symbol]
                check(len(rows)==40 and all(r['unclosed']==0 for r in rows),'全玉返済と無取引勝ちの混同なし')
                net=sum(r['net'] for r in rows)
                check(net==case['metrics'][symbol]['net'],'各商品の全場合計は元公開40行から一致')
                symbols_positive[symbol]+=int(net>0)
            ranked=next(r for r in data['common_ranking'] if r['id']==identity)
            cases.append(dict(**ranked,phase=directory,case=case))
        bundles.append(data)
    check(len(cases)==114 and sum(p['policies']*80 for p in manifest['phases'])==9120,'旧96と最新18で正式114条件9120会計')
    cases.sort(key=lambda r:(not r['qualified'],-r['min_black'],
        -r['min_normalized_median'] if r['min_normalized_median'] is not None else float('inf'),
        r['max_worst_to_mean_black'] if r['max_worst_to_mean_black'] is not None else float('inf'),r['id']))
    featured=cases[0]
    check(manifest['featured']==dict(id=featured['id'],phase=featured['phase']),'主表は同じ参考順位で代表を固定')
    both=sum(all(r['case']['metrics'][s]['net']>0 for s in SYMBOLS) for r in cases)
    eligible=sum(r['qualified'] for r in cases)
    every=sum(all(r['case']['metrics'][s]['all_positive'] for s in SYMBOLS) for r in cases)
    check((both,eligible,every)==(manifest['both_net_positive'],manifest['qualification_count'],manifest['all40_positive']),'達成を隠さず114条件全数で判定')
    check(symbols_positive==Counter(TOPIX=0,NK225=0),'各商品でも全場合計黒字は0条件')
    check(hashlib.sha256(read(PUBLIC/MAIN)).hexdigest()==manifest['main_sha256'],'主HTMLは公開目録の完成SHA')
    document=page(PUBLIC/MAIN);tables=document.select('table');check(len(tables)==2,'主ページは修正比較と代表40場を区別')
    wanted=((0,'HEDGE_S2_T1'),(1,'CREDIT_S2_T1'),(1,'COST_S2_T1'),(2,'COST_LAST_S2_T1'),(3,'KEEP_S2_T1'),(3,'RESCUE_S2_T1'),(3,'ROTATE_S2_T1'))
    trs=tables[0].select('tbody tr');check(len(trs)==7,'中間同幅同追尾の七対照を保持')
    for tr,(index,identity) in zip(trs,wanted):
        expected=[]
        for symbol in SYMBOLS:
            m=bundles[index]['cases'][identity]['metrics'][symbol]
            expected.extend((number(m['net'],True),f"{m['black']}／{m['red']}／{m['inactive']}",number(m['worst'],True)))
        check(tr.th.get_text(strip=True)==identity and [td.get_text(strip=True) for td in tr.select('td')]==expected,'主比較表の収支黒赤無最悪を全セル独立照合')
    case=featured['case'];rows={(r['session'],r['symbol']):r for r in case['rows']}
    check(len(tables[1].select('tbody tr'))==40,'主表に全40場を表示')
    for tr,scene in zip(tables[1].select('tbody tr'),scenes):
        expected=[]
        for symbol in SYMBOLS:
            r=rows[scene,symbol]
            expected.extend((number(r['profit']),number(r['loss']),number(r['net'],True)))
        check(tr['data-session']==scene and [td.get_text(strip=True) for td in tr.select('td')]==expected,'主表全40場の両商品利益損失収支は元会計と一致')
    footer=[]
    for symbol in SYMBOLS:
        rr=[rows[scene,symbol] for scene in scenes]
        footer.extend((number(sum(r['profit'] for r in rr)),number(sum(r['loss'] for r in rr)),number(sum(r['net'] for r in rr),True)))
    check([td.get_text(strip=True) for td in tables[1].select('tfoot td')]==footer,'主40場footerは独立足算')
    text=document.get_text(' ',strip=True)
    for marker in ('114条件','最後の18条件','3990→3993','3980へ更新','上下を逆','後続の売買気配','同じ40場の開発比較','個別回転','組全体回収'):
        check(marker in text,'旧96最新18と入口三例及び約定の意味を明示')
    for item in manifest['loss_diagnoses']:
        check(hashlib.sha256(read(PUBLIC/item['destination'])).hexdigest()==(item.get('published_sha256') or item['sha256']),'診断の公開位置修正後SHAを保持')
    for name,sha in (('最悪場の確定損益と全玉清算時価及び長短枚数_暗色.png','15fc90c22cd14dee67465364402d65ca96094e1d313e06b32555e5f068f12a94'),
        ('最悪場の確定損益と全玉清算時価及び長短枚数_暗色.svg','da5e5448e7c8a9b4f77b720d0d327e68442310e7c3f7dc95121208dec2b5342b'),
        ('損失の具体例.md','69f543e96f199d6ecabe6406faf9483bf349d97366725f7bfe816fbb81265a79')):
        check(hashlib.sha256(read(PUBLIC/name)).hexdigest()==sha,'既確認の暗色図とb診断を同bytesで公開')
    links=[]
    for path in sorted(PUBLIC.rglob('*')):
        if not path.is_file() or path.suffix.lower() not in ('.html','.md'):continue
        if path.suffix.lower()=='.html':
            refs=[e.get('href',e.get('src')) for e in page(path).select('[href],[src]')]
        else:refs=re.findall(r'!?\[[^\]]*\]\(([^)]+)\)',read(path).decode('utf8'))
        for ref in refs:
            parts=urlsplit(ref.strip('<>'))
            check(not parts.scheme and not parts.netloc,'公開表示から外部通信を要求しない')
            destination=(path.parent/unquote(parts.path)).resolve() if parts.path else path.resolve()
            check(destination.is_file(),'全相対リンクと図が実在')
            if parts.fragment and destination.suffix.lower()=='.html':check(page(destination).find(id=unquote(parts.fragment)) is not None,'公開政策アンカーが実在')
            links.append(dict(from_path=path.relative_to(ROOT).as_posix(),href=ref,target=destination.relative_to(ROOT).as_posix()))
    proof=dict(passed=True,scope='公開表示と導線のみ。元金融結果・NPZ・市場・試行台帳を再読せず、正式表示の由来と主表を確認。',
        phases=[48,24,24,18],policies=114,accounts=9120,source_results=[p[2] for p in PHASES],featured=manifest['featured'],
        counts=dict(CHECKS),total_checks=sum(CHECKS.values()),links=links,read_log=READLOG,
        public_SHA256={p.relative_to(ROOT).as_posix():hashlib.sha256(v).hexdigest() for p,v in CONTENT.items()},
        script_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),root_main_visual_review='根担当、別記録',
        financial_result_reads=0,NPZ_reads=0,market_reads=0,financial_replay=0,registry_reads=0,API=0)
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')
    print(json.dumps(dict(passed=True,checks=proof['total_checks'],links=len(links),files=len(CONTENT),path=str(target),SHA256=hashlib.sha256(target.read_bytes()).hexdigest()),ensure_ascii=False))


# ----------------------------------------


if __name__=='__main__':
    main()
