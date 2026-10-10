"""赤字原因と新比較を短い暗色HTMLと検証資料へまとめる。"""

from pathlib import Path
import gzip
import html
import json
import shutil

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
OUT=ROOT/'アルゴリズム調査/00043_赤字原因とエントリー見送り'


def read(path):
    """機能: 保存済みJSONを読む。

    引数: path(Path)。返り値: 保存値(object)。
    """
    raw=path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix=='.gz' else raw)


def amount(value):
    """機能: 金額を符号付き円表示にする。

    引数: value(float)。返り値: 表示(str)。
    """
    return f'{value:+,.0f}円'.replace('-','−')


def gates_data():
    """機能: 見送り比較を共通表示列へ変換し、枚数は決済帳から再集計する。

    引数: なし。返り値: 方式一覧(list[dict])。
    """
    rows=[]
    for source in read(HERE/'gates/見送り条件の比較.json')['条件']:
        number='1' if source['method']=='F50_NONE__E11' else '2'
        ident=source['id'];gate=source['gate']
        name=gate['name'] if gate['id']!='G11' else '片方でも最新EMA60傾きが逆なら休む'
        ledgers=read(HERE/'gates/ledgers'/(ident+'.json.gz'))
        converted=[]
        for s in source['sessions']:
            ledger=next(x for x in ledgers if x['session']==s['session'] and x['symbol']==s['symbol'])
            trades=ledger['trades'];mul=1000 if s['symbol']=='TOPIX' else 10
            win_qty=sum(t[3] for t in trades if t[10]>0);loss_qty=sum(t[3] for t in trades if t[10]<0)
            converted.append(dict(session=s['session'],symbol=s['symbol'],net=s['net_yen'],
                gross_profit=s['gross_profit_yen'],gross_loss=s['gross_loss_yen'],
                win_qty=win_qty,loss_qty=loss_qty,flat_qty=sum(t[3] for t in trades if t[10]==0),trades=s['initial_entries']))
            assert abs(sum(t[10]*mul for t in trades)-s['net_yen'])<1e-6
        periods={}
        for period,by_symbol in source['periods'].items():
            periods[period]={}
            for symbol,s in by_symbol.items():
                periods[period][symbol]=dict(net=s['net_yen'],gross_profit=s['gross_profit_yen'],gross_loss=s['gross_loss_yen'],
                    dd=s['drawdown_yen'],win_sessions=s['win_sessions'],session_count=s['session_count'],
                    trades=s['initial_entries'],unit_payoff=s['average_unit_payoff'],pf=s['money_ratio'])
        rows.append(dict(id=ident,name='候補'+number+'／'+gate['id']+' '+name,group='既存入口に見送りを追加',
            explanation='既存候補'+number+'の途中・出口・枚数は維持。新規の準備と未約定注文だけに「'+name+'」を適用し、その後の全注文を再生。',
            periods=periods,sessions=converted))
    return rows


def mode_explanation(spec):
    """機能: 固定パラメータを入口・途中・出口の日本語へ変換する。

    引数: spec(dict)。返り値: 簡潔な説明(str)。
    """
    mode={0:'追従・反復を自動選択',1:'追従と判定した時だけ運転',2:'反復と判定した時だけ運転'}[spec['mode_choice']]
    book={0:'板の追加確認なし',1:'板変化も入口方向を支持することを要求',2:'反復では逆向きの推定成行と補充を確認、追従では板が同方向'}[spec['book_rule']]
    exits={0:'通常の出口',1:'保有時間30/60分（反復10/20分）で段階短縮',2:'保有時間60/120分（反復20/40分）で段階短縮',
        3:'含み益の最高価格を10分更新しなければ短縮',4:'含み益の最高価格を20分更新しなければ短縮',
        5:'早めの時間短縮と板逆行の短縮',6:'更新停止10分と板逆行の短縮',7:'板が保有と逆向きに変わったら短縮'}[spec['exit_rule']]
    extra=[]
    if spec['flip_rule']==1:extra.append('反復でトレール利確後、毎回反対向きの逆指値を置く')
    if spec['flip_rule']==2:extra.append('反復で利確後、反対側の価格条件と板支持が揃えば反転')
    if spec['mode_exit']:extra.append('休み以外のモードが変化、または追従方向が反転すれば次観測で返済')
    if spec['sr_rule']:extra.append('反復は過去20分の高安から0.25ATR以内で反転を待つ')
    if spec['sr_rule']==2:extra.append('追従は過去20分の高安を0.1ATR突破したことも要求')
    return '入口：'+mode+'。'+book+'。途中・出口：'+exits+'。'+'。'.join(extra)+('。' if extra else '')


def early_data():
    """機能: 元の入口を固定した早期保護比較を共通列にする。

    引数: なし。返り値: 方式一覧(list[dict])。
    """
    rows=[]
    for source in read(HERE/'early/早期保護の比較.json')['条件']:
        spec=source['variant'];name=spec['name']
        if spec['id']=='E09':name='0.75ATR順行後、基準影の収支ゼロ水準へ保護'
        periods={}
        for period,by_symbol in source['periods'].items():
            periods[period]={}
            for symbol,s in by_symbol.items():
                periods[period][symbol]=dict(net=s['net_yen'],gross_profit=s['gross_profit_yen'],gross_loss=s['gross_loss_yen'],
                    dd=s['drawdown_yen'],win_sessions=s['win_sessions'],session_count=s['session_count'],
                    trades=s['cycles'],unit_payoff=s['average_unit_payoff'],pf=s['money_ratio'])
        sessions=[dict(session=s['session'],symbol=s['symbol'],net=s['net_yen'],gross_profit=s['gross_profit_yen'],gross_loss=s['gross_loss_yen'],
            win_qty=s['profit_units'],loss_qty=s['loss_units'],flat_qty=s['zero_units'],trades=s['initial_entries']) for s in source['sessions']]
        explanation='入口は候補1と全件同一。途中減量・2ATR部分利確は維持し、出口を「'+name+'」へ変更。早く退出しても元の通常運転の終了まで待ち、途中で入り直さない。'
        if spec['id']=='E09':explanation+='基準影と実口座の部分返済は異なるため、実口座の収支ゼロを保証しない。'
        rows.append(dict(id=spec['id'],name=spec['id']+' 元の入口／'+name,group='既存候補1の損切り・早期保護',
            explanation=explanation,periods=periods,sessions=sessions))
    return rows


def main():
    """機能: 保存結果を集約し、短い結論と全場損益を公開する。

    引数: なし。返り値: なし(None)。
    """
    OUT.mkdir(parents=True,exist_ok=True)
    rows=gates_data()
    rows+=early_data()
    modes=read(HERE/'modes/自動モードの比較.json')
    for source in modes:
        rows.append(dict(id=source['spec']['id'],name=source['spec']['id']+' '+source['spec']['name'],
            group='新しい追従・反復の比較',explanation=mode_explanation(source['spec']),periods=source['periods'],sessions=source['sessions']))
    data=dict(方式=rows,数量='TOPIXミニ初回5枚／上限10枚、NKマイクロ初回10枚／上限20枚。新20方式は増玉・分割決済なし。',
        期間='2026/09/21デイ〜09/30ナイトの16セッション',未見試験=False,費用=0,API取得数=0)
    (OUT/'全比較データ.json').write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')
    cards=''
    for ident,label in [('F50_NONE__E11__G00','元の候補1'),('F50_NONE__E11__G12','最新の両市場方向を再確認'),('E01','E01 元入口・初期損切0.75ATR'),('E08','E08 元入口・初期損切と追跡0.5ATR'),('A00','追従・反復の自動選択'),('A03','自動選択＋時間短縮'),('SR02','支持抵抗の反発・突破')]:
        r=next(x for x in rows if x['id']==ident)
        vals=[r['periods'][p][s]['net'] for p in ('旧15','問題Night') for s in ('TOPIX','NK225')]
        cards+='<tr><th>'+label+'</th>'+''.join('<td class="'+('up' if v>0 else 'down' if v<0 else '')+'">'+amount(v)+'</td>' for v in vals)+'</tr>'
    options=''.join('<optgroup label="'+group+'">'+''.join('<option value="'+r['id']+'">'+html.escape(r['name'])+'</option>' for r in rows if r['group']==group)+'</optgroup>' for group in dict.fromkeys(r['group'] for r in rows))
    embedded=json.dumps(data,ensure_ascii=False,allow_nan=False).replace('</','<\\/')
    page=TEMPLATE.replace('@@CARDS@@',cards).replace('@@OPTIONS@@',options).replace('@@DATA@@',embedded)
    (OUT/'赤字原因と改善案の検証.html').write_text(page,encoding='utf8')
    materials=OUT/'検証資料';materials.mkdir(exist_ok=True)
    for folder,files in {
        'diagnosis':['赤字原因.md','原因の証拠.json'],
        'gates':['条件の事前固定.json','見送り条件の比較.json','完了.json','新比較設計の解釈.md'],
        'early':['条件の事前固定.json','早期保護の比較.json','完了.json'],
        'modes':['方式の事前固定.json','特徴定義.json','特徴監査.json','模式の時間比.json','会計検算.json'],
        'audit':['旧4方式16場の会計検算.json','新規取消の原本順検査.json','原因数値の独立確認.json','見送り比較の独立検算.json','自動モード注文器の人工監査.json','自動モード実データの独立監査.json','早期保護比較の独立監査.json','早期保護の既成立注文監査.json','独立敵対的監査.md']}.items():
        target=materials/folder;target.mkdir(exist_ok=True)
        for name in files:shutil.copy2(HERE/folder/name,target/name)
    print('HTMLと全比較データを生成',flush=True)


TEMPLATE='''<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>赤字原因と改善案の検証｜00043</title>
<style>
:root{color-scheme:dark;background:#0b121b;color:#dfebf7;font-family:Meiryo,"Yu Gothic",sans-serif;line-height:1.75}body{max-width:1180px;margin:auto;padding:30px 22px 80px}a{color:#85cdfb}h1{font-size:1.8rem;margin:12px 0}h2{font-size:1.3rem;margin-top:38px}h3{font-size:1.05rem}p{margin:.6em 0}.muted,small{color:#a6b9cf}.tag{font-size:.8rem;color:#94c8e8;letter-spacing:.15em}.lead{border-left:4px solid #68cfc0;background:#132333;padding:16px 22px;margin:20px 0}.warn{border-left:4px solid #ecbc70;padding:10px 18px;background:#201e20}.up{color:#82dfbd}.down{color:#ff9faf}.scroll{overflow:auto;border:1px solid #2a4058;border-radius:8px;margin:16px 0}table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums;white-space:nowrap;font-size:.87rem}th,td{padding:10px 12px;border-bottom:1px solid #29394d;text-align:right}th:first-child,td:first-child{text-align:left}thead{background:#192b3d;color:#c6def1}tbody th{font-weight:400}tfoot{background:#182b3c;font-weight:bold}select{max-width:100%;width:100%;padding:12px;border:1px solid #527896;background:#152739;color:#edf6ff;border-radius:7px;font:inherit}details{border:1px solid #2a4058;border-radius:8px;padding:12px 16px;margin:16px 0}summary{cursor:pointer;color:#a8d8fa;font-weight:bold}img{max-width:100%;height:auto}.cols{display:grid;grid-template-columns:1fr 1fr;gap:20px}.box{background:#111e2d;padding:15px 20px;border-radius:8px}.compact{line-height:1.65}#rules{min-height:90px}.foot{border-top:1px solid #2a4058;padding-top:16px;margin-top:36px;font-size:.85rem}@media(max-width:700px){body{padding:18px 12px}h1{font-size:1.45rem}.cols{grid-template-columns:1fr}th,td{padding:8px} .lead{padding:12px}}
</style></head><body>
<!--
[コンポーネント概要]
#method は全方式の選択欄。選択後、説明・期間集計・セッション損益を同期更新する。
#totals は旧15場・問題ナイト・全16場の比較、#sessions は各場の利益・損失・収支と決済枚数。
検証の詳細と図は折り畳み、最初の画面では結論と代表比較を表示する。
-->
<a href="../index.html">調査一覧</a><div class="tag">作業 00043 ／ 保存済み16セッション</div>
<h1>赤字原因と改善案の検証</h1>
<div class="lead"><b>主因は、往復相場を継続する波と判断し、伸びる前の損切りを繰り返したことです。</b><br>損失軽減の候補は、元の入口を保つ「初期損切り0.75ATR」。ただし利益も減ります。支持・抵抗や自動モード切替は、両銘柄共通の改善には至りませんでした。</div>
<p class="muted">TOPIXミニ初回5枚・上限10枚／NKマイクロ初回10枚・上限20枚。費用ゼロ。全玉をセッション内に返済。</p>

<h2>1．なぜ9月30日ナイトで負けたか</h2>
<div class="cols"><div class="box"><b>入口：方向一致を、続く波と見なした</b><p>全18初回で「保持中の主方向」は両銘柄一致。それでも入った後に失速しました。加えてNKの2組は、最新の傾きが逆でも過去の方向が残っていました。</p><small>例：NK22:24の買いは、両銘柄の最新傾きと5・15・30分変化が下向き。結果は−12,000円。</small></div>
<div class="box"><b>出口：利益保護の開始前に負けた</b><p>候補1の負けはTOPIX6連敗・NK8連敗。うちTOPIX5組・NK8組は、利益保護を始める1.5ATRまで一度も伸びませんでした。</p><small>TOPIX −34,000円／NK −68,000円。幅を狭める出口だけでは、この損切りの大半に届きません。</small></div></div>
<p>なお、当時この仕様で参照できた直近5分変化が両銘柄で逆向きだった元の入口3件は、すべて利益でした。不一致を一律に避けると、良い売りまで落としました。自銘柄・相手銘柄で公開遅延が異なるため、同じ瞬間の実市場が逆向きだったという意味ではありません。</p>
<details><summary>5分足と入口・決済損益を見る</summary><img src="今回ナイトの売買図.png" alt="TOPIXとNKの5分足、入口番号、損失取引の期間、確定損益の推移"><p class="muted">図は原因確認用。後から見える高値・安値を売買判定には使っていません。</p><a href="今回ナイトの売買図.svg">拡大できる図</a> ／ <a href="検証資料/diagnosis/赤字原因.md">全18入口の証拠</a></details>

<h2>2．何を変えるとどうなったか</h2>
<p>見送り12条件×既存2候補、新しい自動モードなど20方式、元の入口を固定した早期保護10条件を比較しました。基準を含む延べ57方式・1,824口座です。</p>
<div class="scroll"><table id="highlights"><thead><tr><th rowspan="2">代表比較</th><th colspan="2">以前の15セッション</th><th colspan="2">問題の9月30日ナイト</th></tr><tr><th>TOPIX</th><th>NK</th><th>TOPIX</th><th>NK</th></tr></thead><tbody>@@CARDS@@</tbody></table></div>
<p class="muted">新20方式は単一保有の共通試作器です。元の候補1の途中減量・分割利確・待機方式とは異なるため、差額をモード切替だけの効果とは呼びません。</p>
<div class="box"><b>残す候補はE01。損小利大を維持した損失軽減案です。</b><p>初期損切りを1ATRから0.75ATRへ変更。全16場の1枚平均勝ち／負けは、TOPIX <b>2.15→2.83</b>、NK <b>1.94→2.45</b>。勝ち場数は13/16・11/16を維持しました。一方、収支はTOPIX <b>641,500→477,000円</b>、NK <b>237,200→185,700円</b>に減少。</p><small>時価最大下落はTOPIX183,000→168,500円、NK132,000→108,500円。大幅な安定化や、今回のNK黒字化まで達成したわけではありません。</small></div>
<details><summary>比較から分かったこと</summary><ul>
<li><b>見送り：</b>12条件とも今回を黒字にはできませんでした。最新EMA15の両市場一致はNKの損を減らす一方、以前15場の両銘柄利益を減らし、TOPIXの時価最大下落も拡大。</li>
<li><b>時間短縮：</b>A03は新しい基本A00より期間収支が改善。ただしTOPIXは全16場で赤字、NKの時価最大下落も改善せず。</li>
<li><b>板：</b>厚さだけでなく、注文変化・近い価格帯の変化・補充を使用。NKに効く例はあっても、共通の入口改善とは確認できず。</li>
<li><b>支持・抵抗：</b>SR02はNKの収支を改善しましたが、TOPIXは赤字。NKでも1枚当たり平均勝ち／平均負けは1未満で、損小利大の完成形とはいえません。</li>
<li><b>利確後の反転：</b>毎回反転A10は基本より全体収支が改善しても今回TOPIXを悪化。価格・板の再確認A11は実際の売買を変えず、効果を判定できません。</li>
<li><b>さらに早い保護：</b>E05は0.5ATR順行から幅0.5ATRで追跡。最大下落をTOPIX80,000円／NK59,500円へ削減しましたが、1枚平均勝ち／負けが0.72／0.74まで下がりました。損失を軽減する効果と、損小利大の達成は別です。</li>
<li><b>狭め過ぎる問題：</b>初期損切りだけ0.5ATRにしたE02は、今回TOPIXの勝ち売り2組を＋33,500／＋63,000円から各−15,000円へ変えました。元の負け組を軽減しても補えず、今回収支は−34,000→−110,000円に悪化。</li>
<li><b>最大下落を重視する別案：</b>E08は初期損切りも0.5ATR。最大下落はTOPIX105,000円／NK30,500円、1枚平均勝ち／負け1.36／1.47。一方、勝ち場数10/16・9/16で、約8割という希望には届きません。</li>
<li><b>伸びない取引を時間で縮小：</b>E10は15分で0.5ATR未達なら損失枠を0.5ATRへ縮めます。今回は元と同じ損失で、全16場の利益も減り、NK最大下落も悪化しました。</li>
</ul></details>

<h2>3．各方式の説明と、全セッションの利益・損失</h2>
<label for="method">確認する手法</label><select id="method" onchange="showMethod()">@@OPTIONS@@</select>
<p id="rules" class="box compact"></p>
<div class="scroll"><table id="totals"><thead><tr><th>期間・銘柄</th><th>利益</th><th>損失</th><th>収支</th><th>時価最大下落</th><th>勝ち場</th><th>初回数</th><th>1枚平均勝／負</th></tr></thead><tbody></tbody></table></div>
<details id="session-detail"><summary>セッション別の金額・決済枚数を開く</summary>
<p class="muted">枚数は勝ち・負けになった<b>累計決済枚数</b>です。同時保有枚数ではありません。差枚数だけでは収益性を判断しません。</p>
<div class="scroll"><table id="sessions"><thead><tr><th>セッション・銘柄</th><th>利益</th><th>損失</th><th>収支</th><th>勝ち枚数</th><th>負け枚数</th><th>差枚数</th><th>同値枚数</th></tr></thead><tbody></tbody><tfoot></tfoot></table></div></details>

<h2>4．新20方式の機械的な判定方法</h2>
<div class="cols"><div class="box"><b>追従／反復／休みを自動選択</b><p>両銘柄の最新の移動平均が同方向で、20分の動きが一方向なら追従。往復が多く、変動幅と移動平均の乖離が範囲内なら反復。どちらでもなければ新規を休みます。</p><small>同じ状態が60秒続いてから採用。序盤の暖機は最速でも約62〜66分。前セッションの情報は使いません。</small></div>
<div class="box"><b>入口・途中・出口</b><p>0.2ATRの反発を待って入ります。追従は1ATRで損切りし、大きく伸びたら追跡。反復は0.8ATRで損切り、0.5ATR伸びたら0.35ATRで追跡します。</p><small>短縮したストップを既に通過していたら、過ぎた良い値段ではなく次の観測価格で返済します。</small></div></div>
<details><summary>支持抵抗・板・参照範囲と未検証の点</summary>
<p>支持・抵抗は、その時点で利用可能な直近20実分の確定高値・安値。後から確定した転換点を過去へ置きません。SR01は範囲の端で反発を待ち、SR02は追従時に範囲突破も要求します。</p>
<p>足は開始から120秒後、相手銘柄はさらに60秒後から利用。ATRは公開済みデータのみで計算し、新規準備時の値を固定。板は原本順に公開した特徴を使い、元時刻から20秒超または気配差3呼値超は無効です。</p>
<p>板の減少には取消も含みます。「同じ参加者が食われた分を補充した」とは証明できません。実受信時刻がなく、保存時刻の代理を使用する制約があります。</p>
<p>新20方式の時間・板による短縮は、追従1.5ATR／反復0.5ATRの順行後に作動します。これとは別にE10で、伸びない取引の時間による損失枠縮小を検証しました。20分以外の支持抵抗、前日高安、序盤専用ルールの最適化は未実施。</p>
<p>支持抵抗での反転・突破加速には通貨市場で注文集積を調べた研究がありますが、今回の先物や20分幅の有効性を保証するものではありません。<a href="https://www.newyorkfed.org/research/staff_reports/sr125.html">NY連銀・Osler</a>。板については静的な厚さより注文変化との関係を扱った<a href="https://arxiv.org/abs/1011.6402">Contほかの研究</a>を参照しました。</p>
</details>
<div class="warn"><b>新しい条件は探索結果です。</b>問題のナイトを見た後の設計なので、未見データでの合格とは扱いません。E01は継続観察する損失軽減候補。利益と安定性を同時に上げた完成形ではなく、既存4候補の本採用条件は変更していません。</div>
<p class="foot">資料：<a href="README.md">読む順序・再現方法</a> ／ <a href="全比較データ.json">全数値</a> ／ <a href="検証資料/gates/条件の事前固定.json">見送り条件</a> ／ <a href="検証資料/modes/方式の事前固定.json">新20方式の定義</a> ／ <a href="検証資料/modes/特徴監査.json">未来参照の監査</a><br>新規API取得0回。既存00042の結果は変更していません。金額は銘柄内で比較し、TOPIXとNKの合算順位は作っていません。</p>
<script id="data" type="application/json">@@DATA@@</script>
<script>
const data=JSON.parse(document.querySelector('#data').textContent);
/**
 * 機能: 数値を日本語の金額表示に変換する。
 * @param {number} value 金額。
 * @returns {string} 返り値は符号付き表示文字列。
 */
function money(value){return (value>0?'+':value<0?'−':'')+Math.abs(Math.round(value)).toLocaleString('ja-JP')+'円';}
/**
 * 機能: 金額セルを作成する。
 * @param {number} value 金額。
 * @returns {string} 返り値は暗色用の色を付けたセル。
 */
function cell(value){return '<td class="'+(value>0?'up':value<0?'down':'')+'">'+money(value)+'</td>';}
/**
 * 機能: 選択した方式の説明と全期間・各セッションの損益を表示する。
 * @returns {undefined} 返り値なし。表の内容を同期更新する。
 */
function showMethod(){
 const r=data.方式.find(x=>x.id===document.querySelector('#method').value);document.querySelector('#rules').textContent=r.explanation;
 let totals='';for(const p of ['旧15','問題Night','全16'])for(const s of ['TOPIX','NK225']){const v=r.periods[p][s];totals+='<tr><th>'+p+'・'+(s==='TOPIX'?'TOPIXミニ':'NKマイクロ')+'</th>'+cell(v.gross_profit)+cell(-v.gross_loss)+cell(v.net)+'<td>'+money(-v.dd)+'</td><td>'+v.win_sessions+'/'+v.session_count+'</td><td>'+v.trades+'</td><td>'+(v.unit_payoff===null?'—':v.unit_payoff.toFixed(2))+'</td></tr>';}
 document.querySelector('#totals tbody').innerHTML=totals;
 let body='';const sums={};for(const v of r.sessions){const s=v.symbol;if(!sums[s])sums[s]={gross_profit:0,gross_loss:0,net:0,win_qty:0,loss_qty:0,flat_qty:0};for(const k in sums[s])sums[s][k]+=v[k];body+=sessionRow(v.session.replace('_Day',' デイ').replace('_Night',' ナイト')+'・'+s,v);}
 document.querySelector('#sessions tbody').innerHTML=body;document.querySelector('#sessions tfoot').innerHTML=['TOPIX','NK225'].map(s=>sessionRow('全16合計・'+s,sums[s])).join('');
}
/**
 * 機能: セッションの金額と累計決済枚数を一行にする。
 * @param {string} label 行名。
 * @param {object} v 損益・枚数。
 * @returns {string} 返り値は表の行。
 */
function sessionRow(label,v){return '<tr><th>'+label+'</th>'+cell(v.gross_profit)+cell(-v.gross_loss)+cell(v.net)+'<td>'+v.win_qty+'</td><td>'+v.loss_qty+'</td><td>'+(v.win_qty-v.loss_qty)+'</td><td>'+v.flat_qty+'</td></tr>';}
showMethod();
</script></body></html>'''


if __name__=='__main__':main()
