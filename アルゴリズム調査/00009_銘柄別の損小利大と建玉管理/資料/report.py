"""同銘柄のサイクル損益比・格子・NTペアを日本語の暗色HTMLへまとめる。"""

from __future__ import annotations

import argparse
import hashlib
import html
import importlib.util
import json
from pathlib import Path
import re
import shutil
import sys

import numpy as np
import pandas as pd

import metrics
import reference

WORK, ROOT = reference.OUT, reference.ROOT
DEST = ROOT/'アルゴリズム調査'/'00009_銘柄別の損小利大と建玉管理'
PAGE = '銘柄別の損小利大と建玉管理.html'
spec = importlib.util.spec_from_file_location('v14_report_parts', reference.OLD/'report.py')
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
money, percent, clean = base.money, base.percent, base.clean


def read_json(name: str, default: object = None) -> object:
    """機能: 完了した今回の成果だけを読み取る。

    引数: name (str)、default (object)。返り値: JSON値 (object)。
    """
    path = WORK/name
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default


def ratio(value: float | None) -> str:
    """機能: 比率の欠損を無限大へ変えず表示する。

    引数: value (float|None)。返り値: 表示文字列 (str)。
    """
    return '算出対象なし' if value is None or pd.isna(value) else f'{value:.3f}'


def all_configs() -> dict:
    """機能: ３種類の再生器の条件を、IDを変えず統合する。

    引数: なし。返り値: ID別条件 (dict)。
    """
    return {c['id']:c for name in ['単独条件一覧.json', '格子条件一覧.json', 'NT条件一覧.json'] for c in read_json(name, [])}


def rules(config: dict, profiles: dict) -> list[str]:
    """機能: 個別銘柄・格子・ペアの固定入口と出口を日本語で示す。

    引数: config/profiles (dict)。返り値: 条件の説明 (list[str])。
    """
    c = config
    if c.get('engine') == 'pair':
        direction = {'ratio_mr':'NT対数比の過去60分平均からの標準化乖離',
                     'ratio_mom':'NT対数比の15分変化÷直近60分の１分比率変化標準偏差÷√15',
                     'residual_mr':'過去60分のlog(NK)対log(TOPIX)回帰の標準化残差'}[c['family']]
        return [f'入口方向：{direction}の絶対値が{c["threshold"]:g}以上。'+('同じ方向へ入る。' if c['family']=='ratio_mom' else '反対方向へ入る。')+'NT買いはNK買い・TOPIX売り、NT売りは逆。',
            '同期と新規：毎分判定。両銘柄の同時刻ブロックを封印してから60秒遅延し、180秒より古い価格を使わない。判断後の各脚の最初の生価格で個別約定。',
            '枚数：'+c['sizing_name']+'。数量は判断時に固定。整数組合せは標準換算合計20枚以内で相対元本差が最小、同値なら少ない枚数を選ぶ。',
            '出口：事前共分散から決めた１Rで損切り、2.5R利確、1.5R以上の最大利益から１R反落で返済指示。120分上限。平均回帰型は残差ゼロ交差でも返済指示。条件判断時刻より後の各脚最初の生価格で返済し、同時刻の別行では約定しない。',
            'Rと時間：１Rは実際の数量による10分標準偏差の円換算で、２脚の２呼値相当の合成幅を下限とする。１R損失を保証する値ではない。日15:35・夜05:50に返済指示、30分前に新規停止、返済後５分待機。mini相当・連続枚数は診断だけ。']
    if c.get('engine') == 'grid':
        gap = f'{c["gap_value"]:g}ATR' if c['gap_mode']=='atr' else f'{c["gap_value"]:g}呼値（NK100ポイント・TOPIX５ポイント）'
        kind = {'limit':'下へ買い指値・上へ売り指値', 'stop':'上へ買い逆指値・下へ売り逆指値', 'mixed':'上下の指値と逆指値を併設'}[c['entry_kind']]
        direction = {'both':'上下両方向', 'long':'買い側だけ', 'short':'売り側だけ'}[c['directions']]
        exit_rules = []
        for field, label in [('initial_stop_gap','個別損切り'), ('target_gap','個別利確'), ('trail_gap','個別追跡幅'),
                             ('basket_stop_gap','組合算の損失上限'), ('basket_target_gap','組合算の利益目標'),
                             ('basket_trail_gap','組合算の追跡幅'), ('session_stop_gap','セッション損失上限')]:
            if c.get(field) is not None:
                exit_rules.append(f'{label}{c[field]:g}段')
        if c.get('holding_min'):
            exit_rules.append(f'個別保有{c["holding_min"]:g}分上限')
        if c.get('protect_start_gap'):
            exit_rules.append(f'{c["protect_start_gap"]:g}段順行後に最大利益の{c["protect_fraction"]*100:g}%を保護')
        return [f'新規：開始20分後の有効価格を中心に、{gap}間隔で{kind}。{direction}で最大{c["max_legs"]}枚。',
            '出口：'+'、'.join(exit_rules)+'。価格条件は前行で指定した価格、合算条件・時間返済は次行の生価格。',
            '再配置：'+('返済価格から順行１段先へ進める。' if c['rearm']=='advance' else '返済後は同じ新規水準へ戻す。')+'既に成立側にいる注文は反対側へ戻った後の再到達を待つ。'+('損切り発生後はそのセッションの新規追加を止める。' if c.get('disable_add_after_loss') else ''),
            '会計：同じ中心の再配置全体を１サイクルとし、利益玉と残った損失玉をまとめて評価する。日15:35・夜05:50に全返済、30分前以降は新規禁止。']
    result = base.rules_for(c, profiles)
    if c['family']=='N02' and c.get('signal_multiplier')==-1:
        result[0]='方向の判定：固定モデルのカルマン・フィルタで水準と速度を逐次推定。観測残差の絶対値がATR以下で、10×推定速度が0.5ATR以上なら売り候補、−0.5ATR以下なら買い候補。推定方向を反転する。学習済みニューラルネットやLSTMは用いない。'
    if c.get('us_pause'):
        result.append('米国開始前後：NY09:30の15分前〜30分後、今回の日本時間22:15以上23:00未満は未約定新規を取り消し、新しい入口を止める。既存建玉は通常の損切り・追跡を継続し、この時間帯になっただけでは強制返済しない。')
    if c.get('initial_stop_atr')==.75 and c.get('trail_start_atr')==1 and c.get('trail_atr')==2:
        result.append('利益保護の意味：１ATR順行で利益が確保されるわけではない。呼値丸めを無視すると、最大順行1.25ATR超で初期損切りより追跡価格が有利になり、２ATRで建値、３ATRで１ATRの利益を保護する。')
    if c.get('guard'):
        guard=c['guard']
        text=guard['label']
        if guard.get('loss') is not None:
            text+='。累積実現収支を各組の固定ATRと設定枚数上限で割って加算し、その損失が基準に達したら停止'
        result.append('追加の新規停止条件：'+text+'。全玉返済後に判定し、同セッションでは再開しない。')
    return result


def load_stages(include_current: bool) -> list[dict]:
    """機能: 探索・既知前半・固定後の未知部分を別の評価区間として読む。

    引数: include_current (bool)。返り値: 区間一覧 (list[dict])。
    """
    defs = [('探索７完全', '既知代表', reference.TRAIN, 'train'),
            ('既知ナイト前半・選択外', '既知代表', [reference.KNOWN_NIGHT], 'known')]
    if include_current:
        defs.append(('未知部分の増分・継続組を含む', '現在後半', [reference.KNOWN_NIGHT], 'current'))
    stages = []
    for label, prefix, sessions, key in defs:
        if not (WORK/f'{prefix}_サイクル.json').exists():
            continue
        cycles = [c for c in read_json(f'{prefix}_サイクル.json') if c['session'] in sessions]
        summary = pd.read_csv(WORK/f'{prefix}_セッション集計.csv')
        summary = summary[summary['セッション'].isin(sessions)]
        stages.append(dict(label=label,prefix=prefix,sessions=sessions,key=key,cycles=cycles,summary=summary))
    return stages


def msummary(stage: dict, method: str, symbol: str, session: str | None = None) -> dict:
    """機能: 平均勝負・PFは完了組、全評価は未完了組も含めて集計する。

    引数: stage (dict)、method/symbol (str)、session (str|None)。返り値: 集計 (dict)。
    """
    sessions = [session] if session else stage['sessions']
    cycles = [c for c in stage['cycles'] if c['method']==method and c['symbol']==symbol and c['session'] in sessions]
    result = metrics.summarize(cycles,sessions,'yen')
    rows = stage['summary']
    rows = rows[rows['方式'].eq(method)&rows['銘柄'].eq(symbol)&rows['セッション'].isin(sessions)]
    result['full_dd'] = float(rows['max_drawdown_yen'].max()) if len(rows) and 'max_drawdown_yen' in rows else None
    return result


def metric_rows(stages: list[dict], choices: dict) -> list[list]:
    """機能: 銘柄の順番を保ち、円額で並べ替えず比率表を作る。

    引数: stages (list[dict])、choices (dict)。返り値: 表の行 (list[list])。
    """
    rows = []
    for symbol, method in choices.items():
        for stage in stages:
            m = msummary(stage,method,symbol)
            rows.append([symbol,stage['label'],method,m['complete_cycles'],percent(m['win_rate']),money(m['avg_win']),
                         money(m['avg_loss'],False),ratio(m['payoff_ratio']),ratio(m['profit_factor']),
                         money(m['all_closed_net']),money(m['all_open_net']),money(m['all_net']),
                         f'{m["positive_sessions"]}/{len(stage["sessions"])}',money(m['full_dd'],False)])
    return rows


def distribution(doc: object, cycles: list[dict], symbol: str) -> None:
    """機能: 完了サイクルの損益分布を、方向が分かる棒と値で示す。

    引数: doc (Document)、cycles (list[dict])、symbol (str)。返り値: なし (None)。
    """
    values = sorted([c['net_yen'] for c in cycles if c['complete']])
    if not values:
        return
    scale = max(abs(x) for x in values) or 1.
    bars = ''.join(f'<div class="sample"><span style="height:{abs(v)/scale*90:.1f}px;background:{"#5adeb3" if v>0 else "#ffb36b"}" title="{money(v)}"></span></div>' for v in values)
    doc.parts.append(f'<h3>{symbol}：完了サイクルの小さい順の分布</h3><div class="distribution">{bars}</div>')
    doc.text(f'{symbol}：負け側は橙、勝ち側は緑。最小{money(min(values))}、中央値{money(float(np.median(values)))}、最大{money(max(values))}。１本は全脚をまとめた１サイクル。','note')


def document(stages: list[dict], configs: dict, selected: dict, profiles: dict) -> object:
    """機能: 定義、思想、各区間の数値と制約を同じ文書へまとめる。

    引数: stages (list[dict])、configs/selected/profiles (dict)。返り値: 文書部品 (Document)。
    """
    doc=base.Document()
    primary={s:v['採用']['method'] for s,v in selected['主候補'].items() if v['採用']}
    headers=['対象','評価区間','固定条件','完了組','組勝率','平均勝額','平均負額（絶対）','勝/負比','PF','確定全額','含み','全評価','黒字区間','区間内最大下落']
    doc.section('main','１．今回は「同じ銘柄で、勝った額が負けた額を上回るか」を比較する')
    doc.text('手数料・気配差控除は０、指定価格に到達したらその価格で約定する条件を維持する。NK225とTOPIXを円利益の大きさで横並びに順位付けせず、それぞれの完了サイクルの平均勝額÷平均負額、PF、セッションごとの安定性で選ぶ。')
    doc.text(f'比較したのは{len(configs):,}条件。単独方式11,163条件、格子54条件、NT36条件を、思想を分けて検証した。')
    doc.text('金額はラージ相当でNK225価格差×1,000円、TOPIX価格差×10,000円。NTは実際に選んだ２銘柄の枚数を掛けた合算。平均負額は正の絶対額、損失合計は負号で表示する。','note')
    doc.table(headers,metric_rows(stages,primary))
    current=next((s for s in stages if s['key']=='current'),None)
    if current:
        doc.text('今回の未読区間は9/24ナイトの23:19以上〜9/25 00:53未満。固定主候補の増分はNK225−24万円、TOPIX−8.5万円、NT−14万円だった。NTは未返済１組の含み評価で、まだ勝敗は確定していない。この１回の照合でも継続的な優位性は確認できていない。','callout')
        fresh_rows=[]
        for symbol,method in primary.items():
            original=[c for c in current['cycles'] if c['method']==method and c['symbol']==symbol]
            fresh=[c for c in original if not c.get('carried',False)]
            m=metrics.summarize(fresh,current['sessions'],'yen')
            carried=[c for c in original if c.get('carried',False)]
            fresh_rows.append([symbol,len(fresh),m['complete_cycles'],m['incomplete_cycles'],percent(m['win_rate']),ratio(m['payoff_ratio']),ratio(m['profit_factor']),money(m['all_net']),len(carried),money(sum(c['net_yen'] for c in carried))])
        doc.table(['対象','未知部分で開始した組','その完了組','その未完了組','新規組勝率','新規組の勝/負','新規組PF','新規組の全評価','前半からの継続組','継続組の増分'],fresh_rows)
        doc.text('継続組は、同一ナイトの既知前半からの継続玉であり、セッションを跨いだ建玉ではない。上の全体表は未知部分の資産増減を漏れなく示すため継続組の増分も含める。新しい入口の成績は、この新規組だけの表で別に確認する。','note')
    totals=read_json('時間順の合計指標.json',{})
    if totals:
        doc.text('一方、過去だけから毎回選び直した次区間の合計は、'+ '、'.join(s+money(m['all_net']) for s,m in totals.items())+'。良く見える固定候補と、次の区間でも成功する選び方は同じではない。第８章で分けて示す。','callout')
    doc.text('探索７区間と既知ナイト前半は以前に閲覧済み。今回の答え合わせは、条件固定後に１回取得する23:19以降の未読部分だけである。前半から保有した建玉は境界直前の時価を差し引き、昔の含み益を新しい利益へ加えない。','callout')
    for symbol,method in primary.items():
        doc.method(f'{symbol}の固定主候補：{method}',rules(configs[method],profiles))
        m=selected['主候補'][symbol]['採用']
        doc.text(f'選択判定：{selected["主候補"][symbol]["判定"]}。探索７区間の最高成績１区間を除いた収支は{money(m.get("net_without_best_session"))}。この数値は選択後の未来成績を保証するものではない。','note')
    doc.end()
    doc.section('examples','２．手動の経験を、全建玉の会計へ置き換える')
    doc.table(['ユーザーの手動例','今回の機械化','確かめる点'],[
        ['TOPIXを５ポイント刻みで指値10枚、利益玉を裁量利確して再配置','10呼値の格子、１段利確と同じ位置への再配置を参照条件にする','小幅利確の後に残った損失玉と追加玉を、同じ組の最後まで数える'],
        ['同じ格子位置に逆指値も展開し、利益方向を利確して反発を待つ','逆指値格子と、指値・逆指値の併設を比較する','利確・追跡の時期、滞留時間と全玉損失上限を数値にする'],
        ['ファンダメンタルズでNT方向を当てても、割り切れない枚数の方向性で利益が残らない','NT相対方向を価格から機械判定し、整数枚方式を６種類比較する','相対価格の利益と、共通方向の端数損益を厳密に分ける']])
    doc.text('手動例の裁量利確・ファンダメンタルズ判断そのものを再現したとは扱わず、上記の数値規則を代理として検証する。体験談に含まれる場またぎは今回の許可へ拡張せず、従来どおりセッション内で全返済する。','callout')
    doc.text('利益玉の決済回数、サイクルの勝率、平均勝ち負けは別の値である。１つの開始判断からの全玉が返済されるまでを１サイクルとしてまとめ、残った建玉があれば未完了とする。')
    doc.table(['例','部分だけで見る値','全体で確かめる値'],[
        ['高勝率でも小幅利益・大幅損失','６勝４敗でも、１勝＋１・１敗−２なら合計−２','勝率60%に加え、平均勝/負0.5・PF0.75を見る'],
        ['利益玉だけ返済して再配置','＋１を９回決済すれば、途中の返済脚勝率は100%','残玉−12を最後に返せば同じ組の収支は−３'],
        ['NTを逆方向に持つ','NK１枚買い/TOPIX２枚売りなら見かけは両側','NK65000・TOPIX4000から両方＋1%で端数共通要因は−15万円']])
    doc.text('１と２は会計の説明用の数値例で、今回データの成績ではない。３も固定価格を置いた手計算であり、実売買の勝ち例ではない。')
    doc.parts.append('<p><a href="資料/格子注文の配置と会計.md">格子の具体的な配置と再武装条件</a> · <a href="資料/NTペアの条件と端数リスク.md">NT整数枚の条件と分解</a></p>')
    doc.end()
    doc.section('charts','３．５分足と、全建玉のエントリー・イグジット')
    doc.text('現在の図は、実際の新規価格から末尾までの売買を表示する。未知部分の増分会計は第１章・セッション表を参照。NTは表示銘柄を切り替えて２脚を確認でき、評価曲線と数値は常にペア合算である。')
    doc.parts.append('''<div class="chart-controls"><label>表示する銘柄<select id="symbol"><option>NK225</option><option>TOPIX</option></select></label><label class="wide">固定条件<select id="method"></select></label><label>セッション<select id="session"></select></label><button id="primary">この銘柄の主候補</button><button id="pair-chart">NT主候補</button><button id="reset">セッション全体</button></div>
    <div id="rule" class="chart-rule"></div><div id="chart-summary" class="stats"></div><div class="legend"><span class="green">▲ 買い新規</span><span class="orange">▼ 売り新規</span><span class="blue">● 返済</span><span class="purple">◇ 未返済評価</span><span>破線：判定→新規</span></div>
    <div class="chart-box"><canvas id="price" height="490" aria-label="５分足と全脚の売買図"></canvas><div id="tooltip" class="tooltip"></div></div><div class="chart-box"><canvas id="equity" height="190" aria-label="全建玉の含み込み評価"></canvas></div><p id="chart-note" class="note"></p><div id="trade-table" class="table-wrap"></div>''')
    doc.markdown.append(f'[５分足と全脚の図]({PAGE}#charts)\n')
    doc.end()
    doc.section('ratios','４．勝率と損小利大を分ける')
    doc.text('平均勝負比＝勝ちサイクルの平均利益÷負けサイクルの平均損失額。PF＝勝ち利益合計÷負け損失合計。たとえば勝負比２なら、引分を除く損益分岐勝率は1/(1+2)=33.3%。表の通常の組勝率は引分を含む全完了組が分母で、分岐と比較するときは引分を除く勝率を使う。PFと勝負比は同じ損益から作る関連指標で、独立した２つの証拠とは扱わない。')
    train=next((s for s in stages if s['key']=='train'),None)
    if train:
        for symbol,method in primary.items():
            distribution(doc,[c for c in train['cycles'] if c['method']==method and c['symbol']==symbol],symbol)
    doc.text('PF・平均勝負には全返済済みサイクルだけを使う。未完了組に属する返済利益も、勝ちサイクルへは加えず、全評価欄の確定＋含みへ残す。負けが０回のPFは無限大として採用せず、観測不足と表示する。')
    doc.end()
    doc.section('philosophies','５．試した思想と、７区間での結果')
    pool=pd.read_csv(WORK/'全思想_探索集計.csv')
    rows=[]
    for (symbol,philosophy),part in pool.groupby(['symbol','philosophy'],sort=False):
        rows.append([symbol,philosophy,len(part),int(part.qualified.sum()),int(part.diagnostic_only.sum())])
    doc.table(['対象','思想','条件数','損小利大基準を満たす条件数','診断専用'],rows)
    if current:
        doc.text('損失抑制の対応比較：NK225の同じN10・入口・出口に「２連敗後は当該セッションの新規停止」だけを加えた事前固定候補では、未知部分は−５万円。元条件の−24万円から損失を縮めた。未知部分で新しく開始した組だけなら−１万円と−20万円。この１回の差を利益保証とせず、現在を見て主候補へ選び直していない。','callout')
    for key,choice in selected['思想別代表'].items():
        if not choice['採用']:
            continue
        symbol=choice['銘柄'];method=choice['採用']['method']
        doc.method(f'{symbol}／{choice["思想"]}：{method}',rules(configs[method],profiles))
        doc.table(headers,metric_rows(stages,{symbol:method}))
    doc.end()
    doc.section('grid','６．利益玉だけの格子は、全玉を返しても残るか')
    doc.text('格子は18思想×３幅の54条件。上下指値、片側指値、上下逆指値、順行再配置、個別損切り、滞留制限、組全体の追跡を比較する。同じ中心に再配置している間は１サイクルを継続し、小さな利確ごとに勝ちを分割しない。')
    danger=[]
    if train:
        for method in ['G01_T10','G02_T10','G03_T10']:
            for symbol in reference.SYMBOLS:
                rows=train['summary']
                rows=rows[rows['方式'].eq(method)&rows['銘柄'].eq(symbol)]
                if not len(rows):
                    continue
                m=msummary(train,method,symbol)
                danger.append(dict(symbol=symbol,method=method,leg_win_rate=rows.win_count.sum()/rows.closed_count.sum() if rows.closed_count.sum() else None,
                    cycle_win_rate=m['win_rate'],payoff=m['payoff_ratio'],pf=m['profit_factor'],net_yen=m['all_net']))
    if danger:
        doc.table(['銘柄','条件','脚勝率','全組勝率','組の平均勝/負','組PF','全評価'],[[x['symbol'],x['method'],percent(x['leg_win_rate']),percent(x['cycle_win_rate']),ratio(x['payoff']),ratio(x['pf']),money(x['net_yen'])] for x in danger])
    else:
        doc.text('危険参照の脚勝率と全サイクルの結末は、格子のセッション集計・全脚資料に保存する。利益玉だけを返済した途中成績を、全組の確定利益と混同しない。')
    doc.text('10呼値はTOPIX５ポイント、NK225は100ポイント。幅をNK225にも５ポイントとして流用しない。新しい条件は次行から有効とし、価格が既に成立側にいる再配置は一度未成立側へ戻った後の再到達を待つ。')
    if current:
        doc.text('現在の未知部分では、TOPIXの危険参照G01_T10（上下指値）とG03_T10（売り指値）の増分評価が＋43万円になった。ただし同じ中心の未完了１サイクルの途中で、前半からの継続組である。＋34.5万円の区間内確定増分と＋8.5万円の含み増分を合わせた値であり、未完了組を「救済に成功した完了勝利」とは数えない。','callout')
    doc.end()
    doc.section('nt','７．NTの整数枚と、残った共通方向リスク')
    doc.text('NTは平均回帰・持続・回帰残差の６信号×６枚数方式で36条件。等金額の整数組、過去βでの整数組、NK１枚固定を比べる。mini相当と連続枚数は粒度の診断で、今回のラージ主候補には採用しない。')
    doc.text('入口想定元本をA=NK数量×倍率×NK入口価格、B=TOPIX数量×倍率×TOPIX入口価格、各収益率をrN・rTとすると、合計損益=d×(A+B)/2×(rN−rT)+d×(A−B)×(rN+rT)/2。前が相対変化、後が共通方向に残った元本差の要因である。','callout')
    if 'NT' in primary:
        ntrows=[]
        for stage in stages:
            cycles=[c for c in stage['cycles'] if c['method']==primary['NT'] and c['symbol']=='NT']
            ntrows.append([stage['label'],money(sum(c.get('net_yen',0) for c in cycles)),money(sum(c.get('relative_yen',0) for c in cycles)),money(sum(c.get('common_residual_yen',0) for c in cycles))])
        doc.table(['評価区間','合計','NT相対要因','共通方向元本差要因'],ntrows)
        if train:
            comparison=[]
            for mode in range(6):
                method=f'NT_ratio_mom_Z1_S{mode}'
                cfg=configs[method]
                cycles=[c for c in train['cycles'] if c['method']==method and c['symbol']=='NT']
                m=msummary(train,method,'NT')
                if not cycles:
                    continue
                rm=metrics.summarize(cycles,reference.TRAIN,'r')
                comparison.append([cfg['sizing_name'],'診断のみ' if cfg['diagnostic_only'] else '整数ラージ',m['complete_cycles'],ratio(m['payoff_ratio']),ratio(m['profit_factor']),money(m['all_net']),f'{rm["all_net"]:.2f}R',percent(float(np.mean([c['relative_mismatch'] for c in cycles]))),money(sum(c['common_residual_yen'] for c in cycles)),f'{max(c["gross_standard"] for c in cycles):g}'])
            doc.table(['同じNT持続信号の枚数方式','区分','完了組','勝/負比','PF','全評価','R合計','平均元本差率','共通方向元本差要因','実最大標準枚数'],comparison)
    doc.text('この元本差には、整数丸めに加えて各脚の約定時刻差による入口価格の差も含む。β方式は意図的なβ調整と丸め誤差を別の恒等式でも分解した。枚数が増える候補を単独１枚の円利益と横並びに比較しない。')
    doc.parts.append('<p><a href="資料/NTペアの条件と端数リスク.md">36条件の計算式・同期・整数枚・セッション別損益</a></p>')
    doc.end()
    doc.section('time','８．過去だけで選び直した次の区間の結果')
    totals=read_json('時間順の合計指標.json',{})
    if totals:
        doc.table(['対象','４区間の収支','平均勝額','平均負額','平均勝/負','PF','完了組','組勝率'],
            [[s,money(m['all_net']),money(m['avg_win']),money(m['avg_loss'],False),ratio(m['payoff_ratio']),ratio(m['profit_factor']),m['complete_cycles'],percent(m['win_rate'])] for s,m in totals.items()])
        doc.text('これは過去の成績から毎回選び直す方針の４回分で、最後に選んだ主候補を過去へ当てた成績ではない。探索７区間で良く見える候補と、この選び直し方針の成績を区別する。','callout')
    walk=read_json('時間順評価.json',[])
    if walk:
        doc.parts.append('<pre>'+html.escape(json.dumps(walk,ensure_ascii=False,indent=2))+'</pre>')
    else:
        path=WORK/'時間順の実評価.csv'
        if path.exists():
            frame=pd.read_csv(path)
            doc.table(['対象','学習区間数','次の区間','採用方式','次区間の収支','勝/負比','PF'],
                [[r['銘柄'],int(r['学習数']),base.session_label(r['評価']),r['方式'],money(r['cycle_all_net']),ratio(r['cycle_payoff_ratio']),ratio(r['cycle_profit_factor'])] for r in frame.to_dict('records')])
        else:
            doc.text('先頭３→４、４→５、５→６、６→７の条件選択を保存した。各区間の選択にはその次の区間を含めない。詳細は時間順選択の資料を参照。')
    doc.text('この期間自体は過去の調査で既知であり、研究全体として完全に未知だった検証とは呼ばない。今回新たに取得する後半とは別の診断である。')
    doc.end()
    doc.section('sessions','９．固定主候補のセッション別の利益・損失・収支')
    rows=[]
    for symbol,method in primary.items():
        for stage in stages:
            for session in stage['sessions']:
                m=msummary(stage,method,symbol,session)
                rows.append([symbol,base.session_label(session),stage['label'],money(m['gross_profit']),money(-m['gross_loss']),money(m['all_closed_net']),money(m['all_open_net']),money(m['all_net']),m['complete_cycles'],m['incomplete_cycles'],ratio(m['profit_factor']),ratio(m['payoff_ratio']),money(m['full_dd'],False)])
    doc.table(['対象','セッション','区分','完了組の利益','完了組の損失','確定全額','含み','全評価','完了組','継続組','PF','勝/負比','全玉最大下落'],rows)
    doc.text('完了組の利益・損失はサイクルを相殺してから集計する。未完了組の既返済分がある場合、完了組利益＋損失と確定全額は一致しない。全評価＝確定全額＋含みである。最大下落は各セッション内の全玉評価で、完了サイクルだけの段階的下落とは異なる。','note')
    doc.end()
    doc.section('audit','10．事前固定・未知部分の境界・監査資料')
    doc.text('条件資格は完了10組以上、勝ち負け各３組以上、有取引４区間以上、平均勝/負>1、PF>1、過半数区間黒字、最高区間を外しても補助単位の収支が正。得点は１区間を除外する全場合のPF・平均勝/負の下限から決める。単独・格子の補助はATRと上限枚数での正規化、NTは事前に固定した１Rであり、証拠金利益率ではない。')
    doc.text('本研究の条件は機械的に逐次実行できる。ATRと板特徴は確定・解放後だけ参照し、オンライン学習は正解が確定した過去だけで更新する。未来の価格を入力に入れず、将来を削っても過去の通知と確定売買が変わらない監査を行う。LSTMは用いていない。')
    files=['検証計画.md','主３条件の入口出口と説明監査.md','監査総括.md','NT_事前設計補足.md','NT_自己監査.json','格子再生_手計算と未来打切り監査.json','サイクル指標の独立監査.json','新規停止の独立監査.json','格子とNTの独立監査.json','境界分割の独立監査.json','条件選択の独立監査.json','独立監査まとめ.md','現在照合_凍結記録.json','現在照合_取得記録.json','現在照合_評価記録.json','現在後半_境界監査.json','現在照合の独立監査.json','現在照合器_通信なし監査.json']
    for filename in files:
        if (WORK/filename).exists():
            doc.parts.append(f'<p><a href="資料/{filename}">{filename}</a></p>')
            doc.markdown.append(f'[{filename}](資料/{filename})\n')
    doc.text('旧条件の移植は、通知を受けた原本行だけで新規採用し、保有・待機・停止中に見送った通知を後から拾い直さない。以前のv11の売買を価格だけ置き換えた厳密再現ではない。')
    doc.end()
    return doc


def chart_data(configs: dict, selected: dict, profiles: dict, live_root: Path | None) -> dict:
    """機能: 図は実売買の全期間を用い、未知部分の時価置換とは分ける。

    引数: configs/selected/profiles (dict)、live_root (Path|None)。返り値: 図解用辞書 (dict)。
    """
    prefixes=['既知代表']+(['現在全体'] if live_root and (WORK/'現在全体_全取引.json').exists() else [])
    trades,curves,summaries=[],{},{}
    for prefix in prefixes:
        current=prefix=='現在全体'
        for t in read_json(prefix+'_全取引.json',[]):
            if not current and live_root and t['セッション']==reference.KNOWN_NIGHT:
                continue
            trades.append(dict(method=t['方式'],symbol=t['銘柄'],session=t['セッション'],condition=t.get('条件設定時刻',t['新規時刻']),
                entry=t['新規時刻'],exit=t['返済評価時刻'],ep=t['新規価格'],xp=t['返済評価価格'],side=int(t['方向']),
                closed=bool(t['返済済み']),pnl=t['収支円'],reason=t['返済理由'],leg=int(t.get('脚番号',0))+1,
                cycle=int(t.get('サイクル番号',0))+1,atr=float(t.get('固定ATR') or 0),holding=float(t.get('保有分') or (t['返済評価時刻']-t['新規時刻'])/60),
                qty=t.get('枚数',1),multiplier=t.get('倍率',1000 if t['銘柄']=='NK225' else 10000)))
        curves.update(read_json(prefix+'_資産曲線.json',{}))
        path=WORK/(prefix+'_セッション集計.csv')
        if path.exists():
            for row in pd.read_csv(path).to_dict('records'):
                summaries[f'{row["方式"]}|{row["セッション"]}|{row["銘柄"]}']=row
    for mapping in (curves,summaries):
        for key,value in list(mapping.items()):
            if key.endswith('|NT'):
                for symbol in reference.SYMBOLS:
                    mapping[key[:-2]+symbol]=value
    for key,row in summaries.items():
        method,session,symbol=key.split('|')
        part=[t for t in trades if t['method']==method and t['session']==session and (configs[method].get('engine')=='pair' or t['symbol']==symbol)]
        row['closed_count']=sum(t['closed'] for t in part)
        row['open_count']=sum(not t['closed'] for t in part)
        row['profit_yen']=sum(max(0,t['pnl']) for t in part if t['closed'])
        row['loss_yen']=sum(min(0,t['pnl']) for t in part if t['closed'])
        row['closed_net_yen']=sum(t['pnl'] for t in part if t['closed'])
        row['open_yen']=sum(t['pnl'] for t in part if not t['closed'])
        row['net_yen']=sum(t['pnl'] for t in part)
    sessions={s:base.session_label(s)+('【探索】' if s in reference.TRAIN else '【現在・全期間】' if live_root else '【既知前半】') for s in [*reference.TRAIN,reference.KNOWN_NIGHT]}
    candles={}
    for session in sessions:
        source=(live_root or reference.OLD/'live') if session==reference.KNOWN_NIGHT else ROOT
        for symbol in reference.SYMBOLS:
            frame=pd.read_csv(source/f'candle_5min/{symbol}/{session}.csv')
            candles[f'{session}|{symbol}']=[[pd.Timestamp(r['time']).timestamp(),r['open'],r['high'],r['low'],r['close']] for r in frame.to_dict('records')]
    ids=selected['照合ID']
    return clean(dict(candles=candles,trades=trades,curves=curves,summaries=summaries,sessions=sessions,
        boundary=pd.Timestamp(reference.KNOWN_CUTOFF).timestamp() if live_root else None,
        methods={m:dict(label=base.label_for(configs[m]),rules=rules(configs[m],profiles),cap=configs[m].get('max_legs',1),engine=configs[m].get('engine','single')) for m in ids},
        primary={s:v['採用']['method'] for s,v in selected['主候補'].items() if v['採用']}))


def script() -> str:
    """機能: 旧図解の描画を再利用し、枚数とNTの対象切替を追加する。

    引数: なし。返り値: JavaScript (str)。元のファイルは変更しない。
    """
    value=base.SCRIPT
    value=value.replace("['利益',yen", "['返済脚の利益',yen").replace("['損失',yen", "['返済脚の損失',yen").replace("返済脚／未返済", "返済脚／未返済脚")
    value=value.replace("definition.label+' ／ '+definition.rules[0]", "(definition.engine==='pair'?'【NT２脚合算】 ':'')+definition.label+' ／ '+definition.rules[0]")
    value=value.replace("+'</td><td>'+timeText(t.entry)","+'</td><td>'+t.qty.toLocaleString('ja-JP',{maximumFractionDigits:4})+'</td><td>'+timeText(t.entry)")
    value=value.replace("['組–脚','方向','新規時刻'", "['組–脚','方向','枚数','新規時刻'")
    value=value.replace("t.atr.toFixed(2)","(t.atr?t.atr.toFixed(2):'—')")
    value=value.replace("...visibleTrades.map(t=>t.exit+120)","...visibleTrades.map(t=>t.exit+120),...(DATA.curves[key()]||[]).map(r=>r[0]+120)")
    value=value.replace("drawEquity(start,end);}","if(DATA.boundary&&DATA.boundary>=start&&DATA.boundary<=end){const bx=g.X(DATA.boundary);ctx.strokeStyle='#c1a2ff';ctx.setLineDash([5,5]);ctx.beginPath();ctx.moveTo(bx,g.p.t);ctx.lineTo(bx,g.p.b);ctx.stroke();ctx.setLineDash([]);ctx.fillStyle='#c1a2ff';ctx.fillText('未知部分 23:19 →',Math.min(bx+8,g.p.r-135),g.p.t+16);}drawEquity(start,end);}")
    value=value.replace("$('symbol').addEventListener('change',()=>{$('method').value=DATA.primary[$('symbol').value];update();});", "$('symbol').addEventListener('change',()=>{if(DATA.methods[$('method').value].engine!=='pair')$('method').value=DATA.primary[$('symbol').value];update();});")
    value=value.replace("window.addEventListener('resize',draw);update();", "$('pair-chart').addEventListener('click',()=>{$('method').value=DATA.primary.NT;update();});\nwindow.addEventListener('resize',draw);update();")
    return value


def navigation() -> None:
    """機能: 過去作業を変更せず、全体索引だけに今回の案内を追加する。

    引数: なし。返り値: なし (None)。
    """
    folder=DEST.name
    path=DEST.parent/'README.md'
    text=path.read_text(encoding='utf-8')
    text=re.sub(r'\*\*最新は.*?\*\*',f'**最新は00009の[銘柄別の損小利大と建玉管理]({folder}/{PAGE})です。同銘柄の平均勝ち負け・PF、格子の全玉会計、NT整数枚を比較します。**',text,count=1)
    text=re.sub(r'^\| `00009_.*\n','',text,flags=re.M).replace('`00008_指定価格と費用ゼロの再探索`（最新）','`00008_指定価格と費用ゼロの再探索`')
    line=f'| `{folder}`（最新） | 同銘柄サイクルの平均勝/負とPF、格子54条件、NT36条件、固定後の未知部分 | [５分足と検証]({folder}/{PAGE}) | [結果]({folder}/検証結果.md)・[案内]({folder}/README.md) |\n'
    text=text.replace('| --- | --- | --- | --- |\n','| --- | --- | --- | --- |\n'+line,1).replace('`00009_内容`','`00010_内容`')
    path.write_text(text,encoding='utf-8')
    path=DEST.parent/'index.html';text=path.read_text(encoding='utf-8')
    text=re.sub(r'\s*<!--00009開始-->.*?<!--00009終了-->','',text,flags=re.S)
    text=text.replace('class="task latest"','class="task"').replace(' <span class="badge">最新</span>','')
    text=re.sub(r'<p class="lead">.*?</p>','<p class="lead">最新は、銘柄別の平均勝ち負けと建玉全体の会計から、損小利大を再探索した資料です。</p>',text,count=1,flags=re.S)
    text=re.sub(r'<footer>最新作業は.*?</footer>','<footer>最新作業は00009です。過去の作業資料を残し、今後の別作業は00010以降の番号で追加します。</footer>',text,count=1,flags=re.S)
    card=f'''<!--00009開始--><article class="task latest"><div class="number">作業00009 <span class="badge">最新</span></div><h2>銘柄別の損小利大と建玉管理</h2><p>平均勝/負・PFと７区間の安定性を比較。利益玉の格子と全玉の結末、NT整数枚に残る共通方向を分けて検証します。</p><a class="button" href="{folder}/{PAGE}">検証と５分足売買図を開く →</a><p><a href="{folder}/検証結果.md">検証結果</a> · <a href="{folder}/README.md">読む順序</a></p></article><!--00009終了-->'''
    path.write_text(text.replace('</header>','</header>'+card,1),encoding='utf-8')


def main() -> None:
    """機能: 完成した既知・固定後の結果を配布用資料へまとめる。

    引数: --include-current (bool)、--live-root (Path)。返り値: なし (None)。
    """
    parser=argparse.ArgumentParser()
    parser.add_argument('--include-current',action='store_true')
    parser.add_argument('--live-root',type=Path)
    args=parser.parse_args()
    configs=all_configs();selected=read_json('最終選択.json')
    profiles={p['id']:p for p in json.loads((reference.OLD/'信号条件一覧.json').read_text(encoding='utf-8'))}
    stages=load_stages(args.include_current)
    doc=document(stages,configs,selected,profiles)
    chart=chart_data(configs,selected,profiles,args.live_root)
    DEST.mkdir(parents=True,exist_ok=True);materials=DEST/'資料';materials.mkdir(exist_ok=True)
    for path in WORK.iterdir():
        if path.is_file() and path.suffix in ['.py','.md','.csv','.json']:
            shutil.copy2(path,materials/path.name)
    css=base.CSS+'\n.distribution{display:flex;align-items:end;gap:4px;min-height:112px;padding:12px;background:#0b1422;border:1px solid #32445f;border-radius:8px;overflow-x:auto}.sample{flex:1;min-width:6px;display:flex;align-items:end;height:90px}.sample span{width:100%;min-height:2px}pre{white-space:pre-wrap;word-break:break-word;font-size:12px}'
    payload=json.dumps(chart,ensure_ascii=False,allow_nan=False,separators=(',',':')).replace('</','<\\/')
    page='''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>銘柄別の損小利大と建玉管理｜00009</title><style>'''+css+'''</style></head><body>
<!--
[コンポーネント概要]
本文は同銘柄の完了サイクルの平均勝ち負けと全建玉評価を比較する静的資料です。
#symbol/#method/#session は表示銘柄・固定条件・セッションを選びます。
#price は実売買の５分足図、#equity は全玉の評価曲線、#trade-table は数量を含む全脚です。
#pair-chart はNT固定主候補を表示し、銘柄変更ではNT条件を保ったまま脚を切り替えます。
表の行は対象脚へ拡大し、#reset はセッション全体へ戻します。通信は行いません。
--><main><header><div class="eyebrow">作業00009 ／ NK225・TOPIX・NTペア</div><h1>勝った額と負けた額から<br>損小利大と建玉管理を検証</h1><p class="lead">同じ銘柄の平均勝ち負け、全玉の結末、整数枚に残る方向リスクを見る。</p><div class="badges"><span>費用０</span><span>指定価格約定</span><span>全建玉を評価</span><span>セッション内返済</span></div></header><nav><a href="#main">主候補</a><a href="#charts">５分足売買図</a><a href="#grid">格子と残玉</a><a href="#nt">NTと整数枚</a><a href="#sessions">セッション別</a><a href="#audit">監査</a><a href="../index.html">全作業</a></nav>'''+''.join(doc.parts)+'''<footer>図と文章はオフラインで開けます。元データと過去の調査フォルダは変更していません。</footer></main><script id="data" type="application/json">'''+payload+'''</script><script>'''+script()+'''</script></body></html>'''
    (DEST/PAGE).write_text(page,encoding='utf-8')
    (DEST/'検証結果.md').write_text('# 銘柄別の損小利大と建玉管理\n\n'+'\n'.join(doc.markdown),encoding='utf-8')
    (DEST/'README.md').write_text(f'''# 00009 銘柄別の損小利大と建玉管理

**最初に見るファイル：[検証結果と５分足図]({PAGE})**

1. 第１章で、同銘柄の平均勝/負・PFと、探索・既知前半・未知部分の違いを読む。
2. 第３章で実売買の全脚・枚数を見る。NT主候補ボタン後は銘柄変更で両脚を確認できる。
3. 第５〜７章で、予測・格子・NTの思想と結果を読む。
4. 第９章のセッション別利益・損失・含み・全評価を確認する。
5. [文字の報告書](検証結果.md)、[事前の検証計画](資料/検証計画.md)、[NTの条件](資料/NTペアの条件と端数リスク.md)、[格子の注文](資料/格子注文の配置と会計.md)を読む。

平均勝負とPFは全返済済みサイクルだけに基づく。含み損の残る利益玉決済を勝ち組へ数えない。NTの円利益を単独１枚の利益と横断順位付けしない。

資料フォルダはソースと集計の参照用コピー。再実行は元の `work/wave_v14` と過去の依存コード・原本を用いる。
''',encoding='utf-8')
    navigation()
    print(json.dumps(dict(報告=str(DEST/PAGE),方式数=len(chart['methods']),全脚=len(chart['trades']),HTML_SHA256=hashlib.sha256((DEST/PAGE).read_bytes()).hexdigest()),ensure_ascii=False))


if __name__ == '__main__':
    main()
