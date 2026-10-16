"""損失アンカーの公開数値・知見・369ID・出典・完了登録を金融再生なしで最終監査する。"""

from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser
from pathlib import Path
import hashlib
import json
import math
import re
from urllib.parse import unquote, urlsplit

from risk_sizing_finance_small import goal, near


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
PUBLIC=ROOT/'アルゴリズム調査/00103_往復帯の回避と損失後再参加の統合検証'
SOURCE=ROOT/'work/wave_v106/e01_size_loss_anchor'
READS={}


def read(path: Path) -> dict:
    """
    機能: 授権された公開・集計・登録・既監査小JSONだけを取得する。
    引数: path(Path)は許可されたJSON位置。
    返り値: dictは保存値。正式金融結果・大台帳・packetを開かない。
    """
    assert path.suffix=='.json' and '/finance/' not in path.as_posix()
    data=path.read_bytes();READS[path.relative_to(ROOT).as_posix()]=hashlib.sha256(data).hexdigest()
    return json.loads(data.decode('utf-8-sig'))


def digest(path: Path) -> str:
    """
    機能: 小source・公開資料・計画だけの指紋を取得する。
    引数: path(Path)は小資料。
    返り値: strはSHA256。金融結果・大台帳・原市場資料を対象にしない。
    """
    assert '/finance/' not in path.as_posix() and path.suffix in ('.py','.md','.html','.json')
    return hashlib.sha256(path.read_bytes()).hexdigest()


class View(HTMLParser):
    """
    機能: HTMLの静的table・section・導線だけを取り出す。
    引数: なし。feed(str)で公開HTMLを渡す。
    返り値: インスタンスのtables/links/textは静的表示。Chrome又はJavaScriptを実行しない。
    """
    def __init__(self) -> None:
        """
        機能: 静的表示の取得状態を初期化する。
        引数: なし。
        返り値: Noneは空の解析状態。
        """
        super().__init__();self.tables=[];self.links=[];self.text=[];self.sections=[]
        self.section=None;self.table=None;self.row=None;self.cell=None;self.body=False

    def handle_starttag(self, tag: str, attrs: list) -> None:
        """
        機能: section・tbody行・セル・リンクの開始を取り出す。
        引数: tag(str)、attrs(list)はHTMLの構文。
        返り値: Noneは静的解析状態の更新。
        """
        attr=dict(attrs)
        if tag=='a' and 'href' in attr:self.links.append(attr['href'])
        if tag=='section':self.section=attr.get('data-case');self.sections.append(self.section)
        if tag=='table':self.table=dict(attrs=attr,section=self.section,rows=[])
        if tag=='tbody':self.body=True
        if tag=='tr' and self.table is not None and self.body:self.row=dict(attrs=attr,cells=[])
        if tag=='td' and self.row is not None:self.cell=[]

    def handle_data(self, data: str) -> None:
        """
        機能: 本文とtbodyセルの文字列を集める。
        引数: data(str)はHTMLの文字列。
        返り値: Noneは解析結果への追加。
        """
        self.text.append(data)
        if self.cell is not None:self.cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        """
        機能: tbodyセル・行・table・sectionの終端を閉じる。
        引数: tag(str)は終端タグ。
        返り値: Noneは閉じた静的解析結果。
        """
        if tag=='td' and self.cell is not None:self.row['cells'].append(''.join(self.cell).strip());self.cell=None
        if tag=='tr' and self.row is not None:self.table['rows'].append(self.row);self.row=None
        if tag=='tbody':self.body=False
        if tag=='table' and self.table is not None:self.tables.append(self.table);self.table=None
        if tag=='section':self.section=None


def local_links(path: Path) -> list[str]:
    """
    機能: 対象公開HTML/Markdownの相対ファイルと明示アンカーを存在確認する。
    引数: path(Path)は今回の公開導線・知見。
    返り値: list[str]は確認した相対リンク。大資料の内容を読み取らない。
    """
    text=path.read_text(encoding='utf-8');references=[]
    if path.suffix=='.html':
        parser=View();parser.feed(text);references=parser.links
    else:references=re.findall(r'(?<!!)\[[^\]]*\]\(([^)]+)\)',text)
    found=[]
    for item in references:
        item=item.strip().split(' "',1)[0].strip('<>');uri=urlsplit(item)
        if uri.scheme or uri.netloc:continue
        target=(path.parent/unquote(uri.path)).resolve() if uri.path else path
        assert target.is_relative_to(ROOT) and target.is_file(),(path,item)
        if uri.fragment and target.suffix in ('.md','.html'):
            fragment=unquote(uri.fragment);body=target.read_text(encoding='utf-8')
            explicit=re.findall(r'\bid=["\']([^"\']+)["\']',body)
            headings=[re.sub(r'[^\w\-\s]','',line.lstrip('# ').lower()).replace(' ','-') for line in body.splitlines() if line.startswith('#')]
            assert fragment in explicit or fragment in headings,(path,item,'アンカー不在')
        found.append(item)
    return found


def japanese_rows(rows: list[dict]) -> list[dict]:
    """
    機能: 公開英語keyの小会計を独立基準の日本語keyへ変換する。
    引数: rows(list[dict])は公開済み66行。
    返り値: list[dict]は純再集計に使う値。新しい金融取引を作らない。
    """
    return [dict(session=r['session'],symbol=r['symbol'],利益=r['profit'],損失=r['loss'],収支=r['net'],親数=r['campaigns']) for r in rows]


def match_summary(saved: dict, computed: dict) -> None:
    """
    機能: 公開総損益・三基準・無取引・平均黒字を独立小再集計へ照合する。
    引数: saved/computed(dict)は公開値と独立算術。
    返り値: None。不活動を黒字又は65%成功へ含めない。
    """
    for before,after in (('profit','利益'),('loss','損失'),('net','収支'),('profit_share','金額利益割合'),
            ('active','活動'),('positive','黒字'),('negative','赤字'),('no_trade','無取引'),
            ('mean_positive_session_net','平均黒字'),('worst_session_loss','最大赤字'),('red_all','赤字率全場')):
        near(saved[before],computed[after])
    assert saved['tests']==dict(金額利益65以上=computed['基準']['金額65'],赤字全場20以下=computed['基準']['赤字20'],
        最大赤字は平均黒字以下=computed['基準']['平均黒字補填'])
    assert saved['pass_all']==computed['全基準合格']


# ----------------------------------------
def main() -> None:
    """
    機能: 369ID範囲・公開816円額・264会計・二例系譜・凍結17源と完了登録を確認する。
    引数: なし。金融結果は過去の独立小監査SHAへ参照する。
    返り値: Noneは新証跡JSON。共有docs/sourceは変更しない。
    """
    target=HERE/'loss_anchor_公開369範囲と215登録及び損失具体例の最終静的監査.json'
    assert not target.exists()
    public_path=PUBLIC/'枚数に合わせた損失停止4比較の公開会計.json';public=read(public_path)
    own_path=HERE/'loss_anchor_全264小会計と比例境界及び最新三基準の独立確認.json';own=read(own_path)
    prior_path=HERE/'goal_anchor_全264小会計と寄与境界及び最新三基準の独立確認.json';prior=read(prior_path)
    fixed=read(SOURCE/'金融事前固定.json');plan=read(SOURCE/'試行計画.json')
    sources={p.relative_to(ROOT).as_posix():digest(p) for p in sorted(SOURCE.glob('*.py'))}
    assert len(sources)==17 and sources==fixed['source_SHA256']==plan['spec']['implementation']==public['金融source_SHA256']
    assert digest(SOURCE/'試行計画.json')==fixed['計画SHA256']
    for path,sha in own['source_SHA256'].items():assert public['sources'][path]==sha
    old_result='work/wave_v106/e01_size_goal_anchor/finance/結果.json'
    assert public['sources'][old_result]==prior['source_SHA256'][old_result]
    assert public['全合格'] and public['保存GU再利用']==132 and public['both_goal_pass']==public['both_net_positive']==0
    assert public['both_test_counts']==dict(金額利益65以上=0,赤字全場20以下=0,最大赤字は平均黒字以下=0)
    assert public['criterion']==dict(金額利益割合=.65,赤字全場割合=.2,一場損失='最大赤字場net絶対額<=平均黒字場net')
    assert '完結実親net' in public['定義']['金額'] and public['定義']['無取引']=='勝ちに含めない'
    for key in ('新金融再生','API取得','packet読取','ledger読取','原板読取','NPZ読取'):assert public[key]==0
    for path,sha in public['表示source_SHA256'].items():assert digest(ROOT/path)==sha
    html_path=PUBLIC/'枚数に合わせた損失停止の修正と全セッション損益.html'
    html=html_path.read_text(encoding='utf-8');view=View();view.feed(html)
    assert 'background:#0b1120' in html and '<html lang="ja"' in html and 'charset="utf-8"' in html
    assert 'addEventListener' in html and 'change' in html and 'hidden' in html
    overview=next(t for t in view.tables if t['attrs'].get('id')=='overview')
    assert len(overview['rows'])==8 and set(view.sections)==set(public['cases'])
    cases=0;amounts=0;counts=0;overview_metrics=0
    for cid,data in public['cases'].items():
        rows=japanese_rows(data['rows']);assert len(rows)==66
        by={(r['session'],r['symbol']):r for r in data['rows']};assert len(by)==66
        assert {s for s,_ in by}==set(public['sessions']) and len(public['sessions'])==33
        table=next(t for t in view.tables if t['attrs'].get('class')=='sessions' and t['section']==cid)
        assert len(table['rows'])==34
        for index,item in enumerate(table['rows']):
            cells=item['cells'];assert len(cells)==11
            label='全33合計' if index==33 else public['sessions'][index].replace('_Day',' デイ').replace('_Night',' ナイト')
            assert cells[0]==label
            for product_index,symbol in enumerate(('TOPIX','NK225')):
                row=data['summary'][symbol] if index==33 else by[public['sessions'][index],symbol]
                for offset,key in enumerate(('profit','loss','net','winning_lots','losing_lots')):
                    display_value=0. if row[key]==0 else row[key]
                    assert cells[1+5*product_index+offset]==f"{display_value:,.0f}"
                    if offset<3:amounts+=1
                    else:counts+=1
        for symbol in ('TOPIX','NK225'):
            subset=[r for r in rows if r['symbol']==symbol];computed=goal(subset)
            match_summary(data['summary'][symbol],computed)
            saved=data['summary'][symbol];ind=own['新基準'][cid][symbol]
            assert computed==ind['全場']
            remove=set(ind['除外場']);tail=goal([r for r in subset if r['session'] not in remove])
            match_summary(data['top3'][symbol],tail);assert tail==ind['上位3除外']
            assert data['top3'][symbol]['sessions']==30 and set(data['top3'][symbol]['removed_sessions'])==remove
            prior_id=data['comparison']['id'];old_rows=japanese_rows(data['comparison']['rows'])
            old_computed=goal([r for r in old_rows if r['symbol']==symbol]);match_summary(data['comparison']['summary'][symbol],old_computed)
            assert old_computed==prior['新基準'][prior_id][symbol]['全場']
            display=next(r['cells'] for r in overview['rows'] if r['attrs'].get('data-case-id')==cid and r['attrs'].get('data-symbol')==symbol)
            for offset,key in ((2,'profit'),(3,'loss'),(4,'net')):assert display[offset]==f"{saved[key]:,.0f}";amounts+=1
            assert display[5]==f"{saved['profit_share']:.1%}"
            assert display[6]==f"{saved['negative']}/33 ({saved['red_all']:.1%})"
            assert display[7]==f"{saved['mean_positive_session_net']:,.1f}"
            assert display[8]==f"{saved['worst_session_loss']:,.0f}"
            assert display[9]==' / '.join('達成' if value else '未達' for value in saved['tests'].values())
            assert display[10]==f"{saved['positive']}/{saved['negative']}/{saved['no_trade']}";overview_metrics+=6
        cases+=1
    assert cases==4 and amounts==816 and counts==544 and overview_metrics==48
    # ----------------------------------------
    # 完了登録を現在の金融源へ結び、未達と未知確認0を維持する。
    registry_path=ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/data/trials.json'
    registry=read(registry_path);assert len(registry['trials'])==215
    registered=[t for t in registry['trials'] if t['id']==plan['id']];assert len(registered)==1
    trial=registered[0];assert trial['status']=='検証済み' and trial['spec']==plan['spec']
    ref=trial['completed_result'];new_result='work/wave_v106/e01_size_loss_anchor/finance/結果.json'
    assert ref['path']==new_result and ref['sha256']==own['source_SHA256'][new_result]
    assert ref in trial['evidence'] and '同時合格0/4' in trial['result']
    assert '独立標本ではない' in trial['completion_limitations'] and '未知確認0' in trial['completion_limitations']
    # 最新369は357主評価ID+数量/利確/損失の各4。PRICE参考及び同値群は別扱い。
    latest_path=ROOT/'work/wave_v106/new_goal/初回受理損失四条件追加後の65基準と全候補判定.json'
    latest=read(latest_path);assert latest['全合格']
    assert (latest['summary']['display_cases'],latest['summary']['distinct_ids'],latest['summary']['eligible_ids'])==(372,370,369)
    assert latest['summary']['ideal_reference_ids']==['L_D20_PRICE']
    for key in ('both_full_pass','both_robust_pass','both_active_pass','both_robust_active_pass'):assert latest['summary'][key]==[]
    assert set(latest['新候補'])==set(public['cases']) and '独立標本数ではない' in latest['旧同値群']
    assert latest['新金融元']==dict(path=new_result,sha256=own['source_SHA256'][new_result])
    previous=None
    for reference in latest['過去資料']:
        path=ROOT/reference['path'];assert digest(path)==reference['sha256']
        if path.name=='初回受理目標四条件追加後の65基準と全候補判定.json':previous=read(path)
    assert previous is not None
    for key in ('display_cases','distinct_ids','eligible_ids'):assert latest['summary'][key]==previous['summary'][key]+4
    assert previous['summary']['eligible_ids']==365 and latest['summary']['per_symbol']==previous['summary']['per_symbol']
    assert latest['summary']['economic_same_account_groups']==previous['summary']['economic_same_account_groups']
    for cid,candidate in latest['新候補'].items():
        assert not candidate['saved_alias'] and candidate['config']==public['cases'][cid]['config']
        new_rows={(r['session'],r['symbol']):r for r in candidate['rows']}
        for row in public['cases'][cid]['rows']:
            other=new_rows[row['session'],row['symbol']]
            for key in ('profit','loss','net','campaigns','fees'):near(other[key],row[key])
    # 二実例は金融後の保存親から診断前に選定したもの。計画のIDで曖昧性を解消。
    selection_path=ROOT/'work/wave_v106/loss_stop_diagnosis/二例の初回同数量回復勝ちを調べる固定計画.json'
    selection=read(selection_path);diagnosis_path=ROOT/'work/wave_v106/loss_stop_diagnosis/同一初回の比例損切りと旧回復実利確の二例.json'
    diagnosis=read(diagnosis_path);small=read(HERE/'loss_anchor_二実例気配損益と必要呼値の独立算術.json')
    cid='E01_LOSS_ANCHOR_W60_CONFIRM_D0_P1_L2_A1';old_id='E01_ANCHOR_W60_CONFIRM_D0_P1_L2_A1'
    assert selection['条件']==cid and selection['比較元']==old_id and selection['全合格'] and len(selection['selected'])==2
    assert digest(diagnosis_path)==small['診断SHA256']
    for path,sha in selection['metadata_SHA256'].items():assert sha==(own['source_SHA256']|prior['source_SHA256'])[path]
    for case in selection['selected']:
        d=next(r for r in diagnosis['results'] if r['session']==case['session'] and r['symbol']==case['symbol'])
        assert case['old_net']==d['旧利益'] and case['new_net']==d['新損失'] and case['parent']==d['parent']
        assert case['old_boundary']['anchor']==case['new_boundary']['anchor']
        assert case['first']==case['old_boundary']['実政策初回新規']==case['new_boundary']['実政策初回新規']
        assert cid in case['new_ledger']['path'] and old_id in case['old_ledger']['path']
        assert selection['input_packets'][case['session']]==plan['spec']['data']['保存input33の指紋'][case['session']]
        assert case['old_ledger']==fixed['comparisons'][cid]['ledgers'][case['session']+'|'+case['symbol']]
    # ----------------------------------------
    markdown=PUBLIC/'損失停止を狭めて失った回復勝ちの具体例.md'
    exit_md=ROOT/'アルゴリズム調査/共通/知見台帳/出口.md'
    trade_md=ROOT/'アルゴリズム調査/共通/知見台帳/売買の工夫.md'
    docs=[html_path,markdown,exit_md,trade_md,PUBLIC/'README.md',ROOT/'README.md',ROOT/'アルゴリズム調査/README.md',ROOT/'アルゴリズム調査/index.html']
    links={p.relative_to(ROOT).as_posix():local_links(p) for p in docs}
    body=markdown.read_text(encoding='utf-8');law=exit_md.read_text(encoding='utf-8')
    assert cid in body and old_id in body and '条件IDは計画へ束縛' in body
    for term in ('58.3%','61.0%','0.417pt','1.083pt','7.8円','22.2円','厚さ・補充','真の方向反転','全取引の代表確率ではありません'):
        assert term in body
    assert '読み取り診断の前に選んだ' in law and '金融再生の前に選んだ事例ではない' in law
    assert '全取引の勝率・先着確率ではない' in law and '実約定損失の保証ではない' in law
    for path in (PUBLIC/'README.md',ROOT/'README.md',ROOT/'アルゴリズム調査/README.md',ROOT/'アルゴリズム調査/index.html'):
        text=path.read_text(encoding='utf-8');assert '369' in text and html_path.name in text and markdown.name in text
        assert '未発見' in text or '合格0' in text or '達成' in text and '0件' in text
    source_end={p.relative_to(ROOT).as_posix():digest(p) for p in sorted(SOURCE.glob('*.py'))};assert sources==source_end
    # trial毎の登録時刻はない。source guardで入力前登録照合を確認済み、mtimeは補助だけ。
    paths=[SOURCE/'試行計画.json',SOURCE/'金融事前固定.json',SOURCE/'finance/開始.json',SOURCE/'finance/結果.json',selection_path,diagnosis_path,html_path]
    times={p.relative_to(ROOT).as_posix():datetime.fromtimestamp(p.stat().st_mtime,timezone(timedelta(hours=9))).isoformat() for p in paths}
    assert paths[0].stat().st_mtime<=paths[1].stat().st_mtime<=paths[2].stat().st_mtime<=paths[3].stat().st_mtime<=paths[4].stat().st_mtime<=paths[5].stat().st_mtime<=paths[6].stat().st_mtime
    proof=dict(全合格=True,金融source_SHA256=sources,公開及び登録小JSON_SHA256=READS,
        公開HTML_SHA256=digest(html_path),独立source_SHA256=digest(Path(__file__)),公開条件=cases,
        初版checker失敗と訂正='公開JSONのloss=-0.0に対し初版checkerが-0表示を期待して停止。HTMLは0で正しい。初版源を保持し、表示ゼロの符号だけ正規化。公開会計・金融源変更0。',
        公開円額照合=amounts,公開枚数照合=counts,概要指標照合=overview_metrics,主評価ID=369,表示=372,異なるID=370,
        完了登録trial=trial['id'],登録trial総数=215,completed_result=ref,
        三基準='手数料後完結親netの総利益/(総利益+総損失)>=65%。赤字数/全33<=20%。最大赤字場net絶対額<=正net場の平均。',
        二例条件=dict(新=cid,旧=old_id,金融後の読み取り診断前選定=True),相対リンク照合数=sum(map(len,links.values())),相対リンク=links,
        時系列補助mtime=times,
        留保=['registered_atはtrial毎に保存されていない。厳密な登録秒を再構成したとは主張しない。入力前登録guardは事前独立源監査で確認。',
              '二例は保存結果を見た後の診断対象選定。金融前の例の選定又は確率推定ではない。',
              '369は評価ID数。同値群と同じ33経路を共有するため独立の標本又は独立成功試行数ではない。',
              '凍結17源の不変更・未達の掲載を確認。未知確認0、物理約定・板厚み・補充の追加検証なし。',
              'HTMLの静的金額・導線監査。Chromeでの描画監査は根が別途実施し、この証跡では実行していない。'],
        共有docs変更=0,凍結source変更=0,新金融=0,正式結果再読=0,大入力=0,大台帳=0,原板=0,NPZ=0,API=0,Chrome=0)
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(全合格=True,公開円額=amounts,公開枚数=counts,主評価ID=369,登録=215,
        リンク=sum(map(len,links.values())),SHA256=hashlib.sha256(target.read_bytes()).hexdigest()),ensure_ascii=False))


if __name__=='__main__':main()
