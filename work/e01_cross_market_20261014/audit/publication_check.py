"""00104の公開会計・全場表・重要な留保・出典リンクを、保存小資料だけで監査する。"""

from pathlib import Path
from urllib.parse import unquote, urlsplit
from bs4 import BeautifulSoup
import hashlib
import json
import math
import re

from cross16_finance_check_v2 import metrics, stability


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PUBLIC = ROOT/'アルゴリズム調査/00104_E01の銘柄差の原因と修正検証'
READS = {}
COUNTS = {}


def text(path: Path) -> str:
    """
    機能: 公開表示・共通知見又は自分の保存小監査を指紋付きで一読する。
    引数: path(Path) は列挙済みの小 JSON・MD・HTML・source。
    返り値: str は UTF-8 保存本文。金融結果や入力・台帳は開かない。
    """
    assert path not in READS and '/finance/' not in path.as_posix()
    saved=path.read_bytes()
    READS[path]=hashlib.sha256(saved).hexdigest()
    return saved.decode('utf-8-sig')


def same(a: object, b: object) -> None:
    """
    機能: 未定義と真偽を保ち、小会計値だけを独立算術に照合する。
    引数: a/b(object) は表示小会計と期待値。
    返り値: None。不一致を例外にし、成功比較数を記録する。
    """
    COUNTS['小会計値']=COUNTS.get('小会計値',0)+1
    if b is None or isinstance(b,bool):
        assert a == b,(a,b)
    else:
        assert a is not None and math.isclose(a,b,abs_tol=1e-5,rel_tol=1e-11),(a,b)


def money(cell: object, expected: float | None) -> None:
    """
    機能: 円の内部数値と表示した丸め整数を独立に確認する。
    引数: cell(BeautifulSoupのTag) は金額セル、expected(float|None) は期待円額。
    返り値: None。-0 と 0 は同金額として扱うが非零の符号は保存する。
    """
    if expected is None:
        assert cell.get('data-value') is None and cell.get_text(strip=True) in ('—','−','-')
    else:
        same(float(cell['data-value']),expected)
        same(float(cell.get_text(strip=True).replace(',','')),round(expected))
    COUNTS['円額セル']=COUNTS.get('円額セル',0)+1


def lots(cell: object, expected: int) -> None:
    """
    機能: 実決済枚数又は親建玉枚数の表示を、その副表に対応して照合する。
    引数: cell(BeautifulSoupのTag) は枚数セル、expected(int) は保存された枚数。
    返り値: None。親方向副表と主決済玉の正負枚数を交換しない。
    """
    assert int(cell.get_text(strip=True).replace(',',''))==expected
    COUNTS['枚数セル']=COUNTS.get('枚数セル',0)+1


def check_link(base: Path, href: str) -> None:
    """
    機能: ローカル出典リンクの相対先が存在するかを内容読取なしで確認する。
    引数: base(Path) は表示元文書、href(str) はリンク先。
    返り値: None。原板・実台帳をリンク確認目的で開かない。
    """
    parsed=urlsplit(href.strip('<>'))
    if parsed.scheme or not parsed.path:
        return
    path=(base.parent/unquote(parsed.path)).resolve()
    assert path.is_relative_to(ROOT) and path.exists(),(base,href,path)
    COUNTS['存在するローカルリンク']=COUNTS.get('存在するローカルリンク',0)+1


# ----------------------------------------
def main() -> None:
    """
    機能: 17条件の1122公開場と全HTMLセルを照合し、00104主張の必要な留保を保存する。
    引数: なし。Chrome・新金融・巨大入力・実台帳は使わない。
    返り値: None。新監査 JSON だけを所有 audit へ保存する。
    """
    target=HERE/'公開00104の全場表示と少活動及び知見出典の静的監査.json'
    assert not target.exists()
    publication_path=PUBLIC/'E01の銘柄差と固定16対照の公開会計.json'
    html_path=PUBLIC/'E01の銘柄差と修正後の全セッション損益.html'
    data=json.loads(text(publication_path))
    html=text(html_path)
    soup=BeautifulSoup(html,'html.parser')
    audited=json.loads(text(HERE/'十六対照1056小会計と128期間及び受理円尺度の独立監査_v2.json'))
    old=json.loads(text(HERE/'同一E01の両商品差と再利用及び事後選択の敵対監査.json'))
    entry=json.loads(text(HERE/'実公開票と全返済小価格からの独立算術監査.json'))
    pre=json.loads(text(HERE/'正式20源八部品と一回1056会計及び登録guardの独立接続.json'))
    assert all(p['全合格'] for p in (data,audited,old,entry,pre))
    assert len(data['sessions'])==33 and len(data['cases'])==17
    assert data['both_goal_pass']==1 and data['both_net_positive']==4
    assert data['initial_case']=='E01_CROSS_B03'
    assert data['金融source_SHA256']==pre['source_SHA256']
    assert audited['正式結果SHA256'] in data['sources'].values()
    for path,wanted in data['金融source_SHA256'].items():
        assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==wanted
    for key in ('金融再生','API','packet','ledger','原板','NPZ'):
        assert data[key]==0
    summary_expected={}
    criteria_map={'target65':'金額利益割合65%以上','target_red20':'赤字場20%以下',
                  'target_worst_mean':'最大赤字を平均黒字1場で補える'}
    for cid,case in data['cases'].items():
        rows=case['rows']
        assert len(rows)==66 and len({(r['session'],r['symbol']) for r in rows})==66
        internal=[]
        for r in rows:
            same(r['profit']-r['loss'],r['net'])
            internal.append(dict(session=r['session'],symbol=r['symbol'],利益=r['profit'],損失=r['loss'],収支=r['net'],
                親数=r['campaigns'],勝ち親=r['winning_campaigns'],負け親=r['losing_campaigns'],
                零親=r['campaigns']-r['winning_campaigns']-r['losing_campaigns'],費用=r['fees'],
                新規枚数=r['winning_lots']+r['losing_lots'],勝ち枚数=r['winning_lots'],負け枚数=r['losing_lots'],零枚数=0))
            COUNTS['公開場']=COUNTS.get('公開場',0)+1
        summary_expected[cid]={}
        for symbol in ('TOPIX','NK225'):
            own=[r for r in internal if r['symbol']==symbol]
            agg=metrics(own)
            goal=stability(own)
            view=case['summary'][symbol]
            if case['baseline']:
                assert cid==old['条件']
                before=old['保存全場'][symbol]
                for a,b in zip(own,before):
                    assert a['session']==b['session']
                    for field in ('利益','損失','収支','親数','勝ち親','負け親','費用','勝ち枚数','負け枚数'):
                        same(a[field],b[field])
            else:
                before=audited['商品と期間'][cid][symbol]['期間']['全33']
                for field in ('利益','損失','収支','費用','親数','勝ち親','負け親','勝ち枚数','負け枚数'):
                    same(agg[field],before['金額'][field])
                assert goal==before['基準']
            mapped={'profit':'利益','loss':'損失','net':'収支','winning_lots':'勝ち枚数','losing_lots':'負け枚数'}
            for dst,src in mapped.items():
                same(view[dst],agg[src])
            for dst,src in (('positive','positive_sessions'),('negative','losing_sessions'),('active','active_sessions'),
                ('no_trade','no_trade_sessions'),('profit_share','profit_share'),('red_all','red_full_rate'),
                ('red_active','red_active_rate'),('mean_positive_session_net','mean_positive_session_net_yen'),
                ('worst_session_loss','worst_negative_session_abs_yen'),('pass_all','all_targets')):
                same(view[dst],goal[src])
            assert list(view['tests'].values())==[goal['target65'],goal['target_red20'],goal['target_worst_mean']]
            summary_expected[cid][symbol]=dict(view)
        COUNTS['公開条件']=COUNTS.get('公開条件',0)+1
    # ----------------------------------------
    # 各セルの期待値は保存会計から取り、金額/枚数/方向の用途を区別する。
    overview_rows=soup.select('table.overview tbody tr')
    for tr in overview_rows:
        cid=tr['data-case-id'];symbol=tr['data-symbol'];v=data['cases'][cid]['summary'][symbol]
        cells=tr.find_all('td',recursive=False)
        assert len(cells)==11
        for index,value in ((2,v['profit']),(3,-v['loss']),(4,v['net']),
            (7,v['mean_positive_session_net']),(8,-v['worst_session_loss'])):
            money(cells[index],value)
        assert cells[5].get_text(strip=True)==('—' if v['profit_share'] is None else f"{v['profit_share']:.1%}")
        assert cells[6].get_text(strip=True)==f"{v['positive']}/{v['negative']}/{v['no_trade']}"
        assert cells[9].get_text(strip=True)==' / '.join('○' if p else '×' for p in v['tests'].values())
        common=all(data['cases'][cid]['summary'][s]['pass_all'] for s in ('TOPIX','NK225'))
        assert cells[10].get_text(strip=True)==('両商品達成' if common else '両商品未達')
    assert len(soup.select('#all-overview tbody tr'))==34
    sections=soup.select('section[data-case]')
    assert len(sections)==17
    for section in sections:
        cid=section['data-case'];case=data['cases'][cid]
        indexed={(r['session'],r['symbol']):r for r in case['rows']}
        trs=section.select('table.sessions tbody tr')
        assert len(trs)==34
        for tr in trs:
            cells=tr.find_all('td',recursive=False)
            assert len(cells)==10
            for j,symbol in enumerate(('TOPIX','NK225')):
                source=indexed[(tr['data-session'],symbol)] if tr.get('data-session') else case['summary'][symbol]
                for k,value in enumerate((source['profit'],-source['loss'],source['net'])):
                    money(cells[j*5+k],value)
                lots(cells[j*5+3],source['winning_lots'])
                lots(cells[j*5+4],source['losing_lots'])
        for tr in section.select('table.top3 tbody tr'):
            source=case['top3'][tr['data-symbol']];cells=tr.find_all('td',recursive=False)
            for index,value in ((1,source['net']),(4,source['mean_positive_session_net']),(5,-source['worst_session_loss'])):
                money(cells[index],value)
            assert cells[2].get_text(strip=True)==('—' if source['profit_share'] is None else f"{source['profit_share']:.1%}")
            assert cells[3].get_text(strip=True)==f"{source['positive']}/{source['negative']}/{source['no_trade']}"
        for tr in section.select('table.chronology tbody tr'):
            source=case['chronology'][tr['data-period']][tr['data-symbol']];cells=tr.find_all('td',recursive=False)
            for index,value in ((2,source['profit']),(3,-source['loss']),(4,source['net'])):
                money(cells[index],value)
            assert cells[5].get_text(strip=True)==('—' if source['profit_share'] is None else f"{source['profit_share']:.1%}")
            assert cells[6].get_text(strip=True)==f"{source['positive']}/{source['negative']}/{source['no_trade']}"
        for tr in section.select('table.directions tbody tr'):
            source=case['directions'][tr['data-symbol']][tr['data-side']];cells=tr.find_all('td',recursive=False)
            for index,value in ((2,source['利益']),(3,-source['損失']),(4,source['収支'])):
                money(cells[index],value)
            lots(cells[5],source['勝ち枚数']);lots(cells[6],source['負け枚数'])
    for a in soup.select('a[href]'):
        check_link(html_path,a['href'])
    options=soup.select('select#case option')
    assert len(options)==17 and {o['value'] for o in options}==set(data['cases'])
    assert [o['value'] for o in options if o.has_attr('selected')]==['E01_CROSS_B03']
    assert 'section[hidden]{display:none}' in html and 'background:#0b1120' in html
    # 重要な留保と00104の5桁出典を静的に確認する。
    docs=[PUBLIC/'README.md',PUBLIC/'判断と損失の具体例.md',
        ROOT/'アルゴリズム調査/共通/知見台帳/入口.md',
        ROOT/'アルゴリズム調査/共通/知見台帳/出口.md',
        ROOT/'アルゴリズム調査/共通/知見台帳/売買の工夫.md',
        ROOT/'README.md',ROOT/'アルゴリズム調査/README.md']
    saved_docs={p:text(p) for p in docs}
    for p,s in saved_docs.items():
        for href in re.findall(r'\]\(([^)]+)\)',s):
            check_link(p,href)
    paragraphs=soup.get_text(' ',strip=True)
    assert all(token in paragraphs for token in ('26無取引','25無取引','7が2票','13が夜間','3,166','1,566','未見検証ではありません'))
    entrance=saved_docs[docs[2]]
    assert all(token in entrance for token in ('00104_E01の銘柄差の原因と修正検証',
        '無敗なので平均損失・平均勝敗比・PFは未定義','入口閾値は原因を見た後に固定した既知データでの探索'))
    b03=data['cases']['E01_CROSS_B03']
    for symbol in ('TOPIX','NK225'):
        assert b03['summary'][symbol]['average_loss'] is None
        assert b03['summary'][symbol]['average_payoff'] is None
        assert b03['summary'][symbol]['pf'] is None
    assert data['b03_diagnostics']['B03二票親数']==entry['B03全15親']['票2の親']==7
    assert data['b03_diagnostics']['B03ナイト親数']==entry['B03全15親']['ナイト親']==13
    output=dict(全合格=True,公開会計SHA256=READS[publication_path],HTML_SHA256=READS[html_path],
        小資料及び文面SHA256={p.relative_to(ROOT).as_posix():h for p,h in READS.items()},検査=COUNTS,
        共通数式合格条件=['E01_CROSS_B03'],毎場安定利益は未確立=True,
        重要留保=['TOP活動7/33・NK8/33と無取引26/25を明示。','15親中13夜間・7二票と実商品板/受信順未観測を明示。',
            '無敗の平均損失・平均勝敗比・PFは未定義。損失側の将来安定性を保証しない。',
            '途中逆行3166/1566円と上位3利益場除外の両黒字を分離。',
            '同じ既知33の原因診断後の閾値探索。前16/後17を未見検証と呼ばない。',
            '表示上の負零は金額0として比較。非零符号/枚数/主親と実玉副表は混同しない。'],
        表示説明への提案='根へ、原因を見た後の0.75閾値探索と平均損失未定義を入口MD以外の主報告にも短く併記する提案、及び料金mini/microの明示提案を通知。共有編集は0。',
        独立source_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        新金融=0,金融結果再読=0,入力=0,台帳=0,原板=0,NPZ=0,API=0,Chrome=0,共有編集=0)
    target.write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(全合格=True,検査=COUNTS,SHA256=hashlib.sha256(target.read_bytes()).hexdigest()),ensure_ascii=False))


if __name__=='__main__':
    main()
