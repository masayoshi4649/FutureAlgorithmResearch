"""段階投入の全セッション会計と、時間帯別比較を短い日本語で公開する。"""

from collections import defaultdict
from datetime import datetime
from html import escape
import json
from pathlib import Path
import shutil
from zoneinfo import ZoneInfo
import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
PUBLIC=ROOT/'アルゴリズム調査/00137_日経ミニの段階投入と時間帯別運用'
NAMES={'B05':'現行通知・5枚一括','B02':'同じ入口・2枚固定','B03':'同じ入口・3枚固定',
 'P02a':'2枚→0.25R順行で3枚追加','P02b':'2枚→0.5R順行で3枚追加',
 'C02a':'2枚→0.25R＋二市場支持で3枚追加','C02b':'2枚→0.5R＋二市場支持で3枚追加',
 'C03':'3枚→0.25R＋二市場支持で2枚追加','C01':'1枚→0.25R＋二市場支持で4枚追加',
 'CT02':'時間帯と支持で初回1・2・5枚、後に補充',
 'R05':'短期支持だけで5枚一括','R02':'短期支持だけで2枚固定',
 'RP02':'短期支持2枚→順行で追加','RC02':'短期支持2枚→支持の再成立で追加',
 'RT02':'市場時計で初回と確認を切替・支持再成立で追加',
 'RA02':'市場時計切替・寄付と米朝前後は新規を控える'}
for key in list(NAMES):
    if key.startswith('R'):NAMES['H_'+key]='現行＋米国前だけ「'+NAMES[key]+'」'
NAMES['CT00']='時間帯と支持で初回1・2・5枚、追撃しない'
for prefix in ('NB','NC'):
    for suffix,label in (('E5','5枚一括'),('E2','2枚固定'),('EC2','2枚から支持再確認で追加')):
        NAMES[prefix+'_'+suffix]=('基準' if prefix=='NB' else 'CT02')+'＋米国前の境界再試験・'+label
for prefix in ('W','CW'):
    for suffix,label in (('075','0.75R'),('100','1R'),('parent','元親の返済のみ')):
        NAMES[prefix+suffix]=('2枚から支持再確認で追加' if prefix=='W' else '時間帯・支持で初回を変更し追加')+'／追加停止'+label


def read(path):
    """
    機能: 保存済み資料を読み込む。
    引数: path(Path)は資料位置。
    返り値: dictは内容。
    """
    return json.loads(path.read_text(encoding='utf-8-sig'))


def measure(rows):
    """
    機能: 場の勝敗と、通常の勝ち負けの大きさを別々に集計する。
    引数: rows(list[dict])は同一条件の場会計。
    返り値: dictは累計と分母を伴う安定性指標。
    """
    nets=np.array([r['net'] for r in rows]);positive=nets[nets>0];negative=-nets[nets<0]
    profit=sum(r['profit'] for r in rows);loss=sum(r['loss'] for r in rows)
    return dict(sessions=len(rows),wins=len(positive),losses=len(negative),
        no_trade=sum(r['entries']==0 for r in rows),zero_traded=sum(r['entries']>0 and r['net']==0 for r in rows),
        profit=profit,loss=loss,net=float(nets.sum()),fees=sum(r['fees'] for r in rows),
        pf=profit/loss if loss else None,
        mean_win=float(positive.mean()) if len(positive) else 0.,mean_loss=float(negative.mean()) if len(negative) else 0.,
        median_loss=float(np.median(negative)) if len(negative) else 0.,max_loss=float(negative.max()) if len(negative) else 0.,
        top3_removed=float(nets.sum()-sum(sorted(positive,reverse=True)[:3])),
        entries=sum(r['entries'] for r in rows),max_per_side=max((r['max_per_side'] for r in rows),default=0))


def yen(value):
    """
    機能: 円を符号付き整数で表示する。
    引数: value(float)は円額。
    返り値: strは表示文字列。
    """
    return f'{value:+,.0f}'


def main():
    """
    機能: 全条件の集計・変化分解・全場表・追跡可能な具体例を公開する。
    引数: なし。結果.jsonと結論文.jsonを参照する。
    返り値: None。保存金融結果は変更しない。
    """
    data=read(HERE/'結果.json');groups=defaultdict(list)
    for name in ('結果2.json','結果3.json'):
        if (HERE/name).exists():data['rows']+=read(HERE/name)['rows']
    for r in data['rows']:groups[r['method']].append(r)
    summaries={key:{kind:measure([r for r in rows if kind=='全体' or r['kind']==kind])
                    for kind in ('全体','Day','Night')} for key,rows in groups.items()}
    base={r['session']:r for r in groups['B05']};comparisons={}
    for key,rows in groups.items():
        delta=[];legs=defaultdict(float);old_winner=old_loser=0.
        for row in rows:
            b=base[row['session']]; d=row['net']-b['net']
            delta.append(dict(session=row['session'],base=b['net'],new=row['net'],difference=d))
            for parent in row['parents']:
                for leg,info in parent['legs'].items():legs[str(leg)]+=info['net']
            if b['net']>0:old_winner+=d
            if b['net']<0:old_loser+=d
        comparisons[key]=dict(best=sorted(delta,key=lambda d:d['difference'],reverse=True)[:3],
            worst=sorted(delta,key=lambda d:d['difference'])[:3],old_winner_change=old_winner,
            old_loser_change=old_loser,legs=dict(legs))
    PUBLIC.mkdir(parents=True,exist_ok=True)
    report=dict(summary=summaries,comparisons=comparisons,rows=data['rows'],source='../../work/staged137_20261022/結果.json')
    (PUBLIC/'比較集計.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    decisions=read(HERE/'結論文.json') if (HERE/'結論文.json').exists() else {'headline':'比較完了。累計だけでなく赤字場数と負けの深さを確認する。','paragraphs':[]}
    def table(keys):
        """
        機能: 同じ45場の条件比較表を生成する。
        引数: keys(list[str])は手法ID。
        返り値: strはHTML表。
        """
        body=[]
        for key in keys:
            s=summaries[key]['全体']
            body.append(f'<tr><td>{escape(key)}</td><td>{escape(NAMES[key])}</td><td>{s["wins"]}/{s["losses"]}/{s["no_trade"]}</td>'
                f'<td>{yen(s["net"])}</td><td>{yen(-s["mean_loss"])}</td><td>{yen(-s["max_loss"])}</td><td>{yen(s["top3_removed"])}</td></tr>')
        return '<div class="scroll"><table><thead><tr><th>ID</th><th>手法</th><th>黒／赤／無取引</th><th>収支</th><th>赤字場平均</th><th>最大赤字</th><th>上位3黒字除外</th></tr></thead><tbody>'+''.join(body)+'</tbody></table></div>'
    html=['<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
        '<title>日経ミニの段階投入と時間帯別運用</title><style>html{color-scheme:dark}body{font:16px/1.7 "Yu Gothic UI",sans-serif;background:#101722;color:#e3eaf3;max-width:1300px;margin:auto;padding:24px}a{color:#85c7ff}table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}td,th{padding:8px 12px;border-bottom:1px solid #334155;white-space:nowrap;text-align:right}td:first-child,td:nth-child(2),th:first-child,th:nth-child(2){text-align:left}thead{background:#1d2b40}details{margin:20px 0;background:#172233;padding:15px}.scroll{overflow:auto}.lead{background:#21344b;padding:18px;border-left:4px solid #6ab6ff}small{color:#b1bfd0}h1{font-size:26px}h2{font-size:21px}</style>',
        '<!-- この資料は固定条件の過去比較です。集計表と各手法の全45場会計を示し、折り畳みで詳細を分離します。 -->',
        '<h1>日経ミニの段階投入と時間帯別運用</h1>',f'<p class="lead">{escape(decisions["headline"])}</p>',
        '<p>日経mini・片方向上限10枚。2026年9月21日デイ〜10月21日デイの同じ45場。立会手数料38.5円／枚／片道、注文ごと切捨て。実ミニの約定はラージの次正常気配で代理。</p>']
    html += ['<p>'+escape(p)+'</p>' for p in decisions['paragraphs']]
    selected=[k for k in ('B05','Wparent','CWparent','CT00') if k in groups]
    html += ['<h2>主な比較</h2>',table(selected),
        '<p>Wparentは最初2枚、順行と新しい二市場支持を確認して3枚追加。CWparentは時間帯・支持で初回を1・2・5枚に変える。両案とも追撃玉を元の損切り・部分返済・追尾で管理する。CT00は同じ初回調整だけで追撃しない。上限10枚のうち主担当は最大5枚、未参加補完は最大5枚。今回の最大同時保有実績は5枚。</p>',
        '<details><summary>第一巡：一括投入・少量固定・追撃の全対照</summary>',table([k for k in groups if not k.startswith(('R','H','NB','NC','W','CW'))]),
        '<p>同じ現行通知を仮想層で固定し、枚数を変える比較。5枚一括が基準。追撃後は合計5枚まで。追撃玉だけ0.5Rで停止し、元玉の停止線を動かさない。Rは初回判断時の公開ATRと20円の大きい方。CT02は時間帯・初回数量も変える複合条件。</p>',
        '</details>',
        '<details><summary>追撃の停止幅を広げた追加比較</summary>',table([k for k in groups if k.startswith(('W','CW'))]),
        '<p>追撃玉の0.5R停止だけを0.75R・1R・元親通知のみへ変更した。元玉と追加判断は保持している。</p></details>',
        '<details><summary>共通ロジックを時間帯で切り替える新案と、米国開始前の追加運用</summary>',
        table([k for k in groups if k.startswith('R')]),table([k for k in groups if k.startswith('H')]),
        table([k for k in groups if k.startswith(('NB','NC'))]),
        '<p>R系は二市場の過去120秒・30秒支持で初回、各玉を独立追尾する新案。RTは寄付・米朝・米寄付で1枚かつ確認を強化、昼休みも1枚。RAは急変帯の新規を控える。H系は日中を基準のまま、米国現物開始15分前までだけR系を追加し、その後は現行手法へ戻す。NB/NCは米国前の入口を現行NV25の価格帯再試験へ変更。時刻は方向を与えず、米欧夏時間を反映する。無取引は達成扱いにしない。</p></details>',
        '<h2>各手法の全セッション損益</h2>']
    for key,rows in groups.items():
        html.append(f'<details><summary>{escape(key)}：{escape(NAMES[key])} ／ 累計 {yen(summaries[key]["全体"]["net"])}円</summary><div class="scroll"><table><tr><th>セッション</th><th>利益</th><th>損失</th><th>収支</th></tr>')
        for row in rows:html.append(f'<tr><td>{row["session"]}</td><td>{yen(row["profit"])}</td><td>{yen(-row["loss"])}</td><td>{yen(row["net"])}</td></tr>')
        s=summaries[key]['全体'];html.append(f'<tr><th>累計</th><th>{yen(s["profit"])}</th><th>{yen(-s["loss"])}</th><th>{yen(s["net"])}</th></tr></table></div></details>')
    html.append('<p><a href="README.md">仕様・検証範囲</a> ／ <a href="../../work/staged137_20261022/preus_diagnostic/時間区分の診断.md">時間帯の性質と一次資料</a> ／ <a href="比較集計.json">集計データ</a></p><small>これは既知標本での比較。確信度の将来勝率を校正したものではない。Go実運転を変更せず、現行仮想通知を固定した数量層と独立新案の比較である。</small></html>')
    (PUBLIC/'日経ミニの段階投入と全セッション損益.html').write_text('\n'.join(html),encoding='utf-8')
    print(json.dumps({k:v['全体'] for k,v in summaries.items()},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
