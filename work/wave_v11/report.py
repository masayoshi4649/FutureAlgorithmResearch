"""予測・注文・複数建玉の検証を思想ごとの暗色図解と文章へ整理する。"""

from __future__ import annotations

import html
import json
import math
from pathlib import Path
import re
import shutil

import numpy as np
import pandas as pd
import signals
import orders

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT/'work/wave_v11'
DEST = ROOT/'アルゴリズム調査/00006_予測と注文手法の組合せ検証'
PHILOSOPHIES = ['予測主導', '予測と注文の組合せ', '注文主導']
COMPLETE = signals.SESSIONS[:-1]


def read_json(name: str, default: object = None) -> object:
    """機能: 作業ディレクトリの日本語JSONを読む。

    引数: name (str)、default (object)。返り値: 読込値 (object)。
    """
    path = OUT/name
    return json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else default


def read_csv(name: str) -> pd.DataFrame:
    """機能: 任意の集計ファイルを表へ読む。

    引数: name (str)。返り値: 表 (DataFrame)。
    """
    path = OUT/name
    return pd.read_csv(path) if path.exists() else pd.DataFrame()


def clean(value: object) -> object:
    """機能: 非有限値を除去して静的HTMLへ埋め込める値にする。

    引数: value (object)。返り値: JSON互換値 (object)。
    """
    if isinstance(value, dict):
        return {str(k):clean(v) for k,v in value.items()}
    if isinstance(value, (list, tuple, np.ndarray)):
        return [clean(v) for v in value]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def money(value: float | None) -> str:
    """機能: 円を符号付き万円表記にする。

    引数: value (float|None)。返り値: 表示文字列 (str)。
    """
    if value is None or pd.isna(value):
        return '—'
    value = 0. if abs(float(value)) < .000001 else float(value)
    return f'{value/10000:+,.1f}'


def aggregate(frame: pd.DataFrame) -> dict:
    """機能: 各評価範囲の全脚収支を足し、最大セッション内下落を別に返す。

    引数: frame (DataFrame)。返り値: 集計 (dict)。
    """
    keys = ['利益円','損失円','収支円','費用倍収支円','評価損益円','取引数','未返済数','勝ち数',
            '枚数上限換算収支円','枚数上限換算費用倍収支円','枚数上限換算評価円']
    result = {k:float(frame[k].sum()) if k in frame else 0 for k in keys}
    result['最大のセッション内下落円'] = float(frame['全行最大下落円'].max()) if len(frame) and '全行最大下落円' in frame else None
    result['最大保有枚数'] = int(frame['最大保有枚数'].max()) if len(frame) and '最大保有枚数' in frame else 0
    result['勝率'] = result['勝ち数']/result['取引数'] if result['取引数'] else None
    return result


def exact_rules(config: dict, definitions: dict) -> list[str]:
    """機能: 入口・出口・枚数を省略しない日本語条件を作る。

    引数: config/definitions (dict)。返り値: 条件文章 (list[str])。
    """
    signal = config.get('signal_family', config.get('signal', config['family']))
    source = definitions.get(signal, {})
    result = [f"方向検知: {source.get('rules', '方向モデルは作らず、以下の注文条件を監視する。')}"]
    if signal == 'P23':
        result = ['確定１分足のEMA3−EMA8が同符号のまま２本連続で縮小し、直前は拡大または同値、２本前の差が0.1ATR以上なら収束通知。差が正なら売り、負なら買い。',
                  '板圧力は60秒OFI比率・上下気配更新比率・同一価格表示数量の純変化比率の平均。各成分は最低５ブロック。±0.1の反対側を２ブロック連続で確認した時に反転通知。初回状態は使わない。',
                  'EMA収束と板反転が同方向で300秒以内にそろった組を一回だけ通知する。']
    if signal == 'P24':
        result = ['板圧力は60秒OFI比率・上下気配更新比率・同一価格表示数量の純変化比率の平均。±0.1の反対側を２ブロックで確認すると反転通知。',
                  '両銘柄の反転方向が一致し、自銘柄は５分以内、他銘柄は公開後60秒待って元時刻から３分以内の情報だけを使う。']
    if config['engine'] == 'orders':
        text = config.get('exact_rules', '')
        if config['family'] == 'O10':
            result.append(f"買い１枚・売り１枚から開始。個別利確は使わず、確定分と全残存脚の清算評価の合計が{config['basket_take_profit_atr']:g}ATRで全返済する。")
            result.append(f"各脚の損切り3ATR、追跡なし、保有上限{config['max_hold_min']:g}分。合算損失4ATRで返済、セッション損失8ATRで停止。固定１時間枠、前の組が残る枠は見送る。")
        elif config['family'] == 'O09':
            result.append(f"買い１枚・売り１枚から開始。{config['gap_atr']:g}ATRの利益条件に達した脚だけ返済し、損失脚を残す。残す脚にも3ATR損切りと{config['max_hold_min']:g}分の保有上限を適用する。追跡なし。")
            result.append('全脚と確定分の合算損失4ATRで返済、セッション損失8ATRで停止。新しい組は固定１時間枠で、前の組が残る枠は見送る。')
        else:
            result.append(text)
        result.append(f"同時総建玉上限{config.get('max_positions',1)}枚。全脚の約定費用・残存含み損を含めて集計する。")
    elif config['philosophy'] == '予測主導':
        result.append(f"確定検知で成立しやすい価格条件を設定し、次の有効な買ask／売bidで１枚新規する抽象再生。新規market APIを使う想定ではない。約定から{config['holding_min']:g}分で返済を発注する。途中の損切り・利確・追跡は使わず、方向予測の寄与を分離する。")
    else:
        mode = config.get('entry_mode', 0)
        offset = config.get('entry_offset', .25)
        entry = '検知後の成行条件' if mode == 1 else f'条件作成時価格から順方向{offset:g}ATRの固定逆指値' if mode == 2 else f'追跡安値から{offset:g}ATR反発で買い／追跡高値から同幅反落で売り'
        result.append(f"入口: {entry}。検知から{config.get('max_age_min',10):g}分以内に成立が必要。成立後の次の有効気配で１枚約定。返済後{config.get('cooldown_min',5):g}分休止。")
        stop = config.get('initial_stop_atr', 2)
        result.append(f"初期損切りは{stop:g}ATR。" if stop is not None else '初期損切りなし。')
        target = config.get('target_atr')
        if target is not None:
            result.append(f'利益{target:g}ATRで返済条件を成立させる。価格通過時は後続気配で約定するため、指定幅と実利益は一致しない。')
        trail = config.get('trail_atr', 2)
        if trail is not None:
            result.append(f"最大順行{config.get('trail_start_atr',0):g}ATRから極値に追跡幅{trail:g}ATRを置く。ストップを損失方向には緩めない。")
        if config.get('tighten_trigger_atr') is not None:
            result.append(f"最大順行{config['tighten_trigger_atr']:g}ATRで追跡幅{config['tighten_width_atr']:g}ATRに短縮。")
        if config.get('protect_fraction'):
            result.append(f"最大順行{config['protect_trigger_atr']:g}ATR以後は最大順行の{config['protect_fraction']:.0%}を残す水準もストップ候補にする。")
        if config.get('weak_width_atr'):
            result.append(f"最大順行{config.get('state_trigger_atr',0):g}ATR以後、板の状態が建玉と逆向きなら追跡幅{config['weak_width_atr']:g}ATRへ短縮。未知の板状態は反対信号にしない。")
        result.append('米国株開始前後22:15〜23:00は新規停止。' if config.get('us_mode') == '新規停止' else '米国株開始前後も同じルールを使う。')
    result.append('ATRは既に確定した５分足の真の値幅を12期間の指数平滑で計算し、足の終了からさらに１分待って利用。新規条件設定時のATRで幅を固定する。')
    result.append('新規market APIは表にないため、成行相当の新規は成立可能なstop/limit条件から発注する抽象モデル。実口座の発注システムは未実装。')
    return result


def candles(path: Path) -> list[list]:
    """機能: 確定５分足だけを表示用の数値配列へ変換する。

    引数: path (Path)。返り値: 時刻・OHLCの一覧 (list[list])。
    """
    frame = pd.read_csv(path)
    if 'closed' in frame:
        frame = frame[frame.closed.astype(str).str.lower().eq('true')]
    return [[pd.Timestamp(r['time']).timestamp(),r['open'],r['high'],r['low'],r['close']]
            for r in frame.to_dict('records')]


def compact_trades(rows: list[dict], display_session: str | None = None) -> list[dict]:
    """機能: 全脚の取引をチャートと明細に必要な情報へ縮約する。

    引数: rows (list[dict])、display_session (str|None)。返り値: 表示用取引 (list[dict])。
    """
    result = []
    for r in rows:
        mul = orders.MULTIPLIERS[r['銘柄']]
        result.append(dict(method=r['方式'],session=display_session or r['セッション'],symbol=r['銘柄'],
            signal=r['signal_time_s'],condition=r['condition_time_s'],entry=r['entry_time_s'],ep=r['entry_price'],
            exit=r.get('exit_time_s',r.get('mark_time_s')),xp=r.get('exit_price',r.get('mark_price')),
            side=r['side'],closed=r['closed'],net=r['net_points']*mul,stress=r['stress_points']*mul,
            atr=r['atr'],mfe=r['max_favorable']*mul,cycle=r.get('cycle_id'),slot=r.get('slot_id'),
            origin=r.get('評価区分',r.get('origin','')),reason=r.get('exit_reason','未返済の評価'),
            hold=r['duration_min']))
    return result


def build_payload() -> dict:
    """機能: 探索成績・時間順評価・現在照合を混在させずに表示資料を組み立てる。

    引数: なし。返り値: 表示資料 (dict)。
    """
    configs = read_json('条件一覧.json', [])
    all_rows = read_csv('全条件_セッション集計.csv')
    final = read_json('最終選択.json', {})
    chosen = final.get('現在照合ID', [])
    walk = read_csv('時間順評価.csv')
    symbol_walk = read_csv('銘柄別時間順評価.csv')
    profiles = signals.profiles()
    definitions = {p['id']:p for p in profiles}
    methods = [dict(c,rules=exact_rules(c,definitions)) for c in configs if c['id'] in chosen]
    data = dict(methods=methods,profiles=profiles,order_profiles=[c for c in orders.catalog() if c['id'].endswith('G1_X1')],
        sessions=signals.SESSIONS,complete=COMPLETE,counts=read_json('実行完了.json',{}),selection=final,
        walk=walk.to_dict('records'),symbol_walk=symbol_walk.to_dict('records'),rows=all_rows[all_rows.方式.isin(chosen)].to_dict('records'),
        walk_summary=[dict(思想=p,**aggregate(walk[walk.思想==p])) for p in PHILOSOPHIES],
        candles={},curves=read_json('代表候補_評価曲線.json',{}),
        trades=compact_trades(read_json('代表候補_全取引.json',[])),
        coins=read_csv('定刻コイン_64種.csv').to_dict('records'),
        signal_coins=read_csv('信号時刻固定_方向64種.csv').to_dict('records'),
        contrasts=read_csv('入口と出口の対応比較.csv').to_dict('records'),
        neighbors=read_csv('主候補の一変数近傍.csv').to_dict('records'),
        cost_stress=read_csv('追加費用0_1_2_4呼値.csv').to_dict('records'),
        predictions=read_csv('予測時間別診断.csv').to_dict('records'),
        known_cutoff=pd.Timestamp('2026-09-24T00:02:00+09:00').timestamp(),
        live={},audits=[],notes=read_json('報告コメント.json',{}),statistics=read_json('独立統計診断.json',{}),
        symbol_walk_summary=[dict(思想=p,銘柄=x,**aggregate(symbol_walk[(symbol_walk.思想==p)&(symbol_walk.銘柄==x)]))
            for p in PHILOSOPHIES for x in signals.SYMBOLS] if len(symbol_walk) else [])
    order_rows = all_rows[(all_rows.思想=='注文主導')&all_rows.セッション.isin(COMPLETE)]
    totals = order_rows.groupby('方式').収支円.sum()
    symbol_totals = order_rows.groupby(['方式','銘柄']).収支円.sum()
    data['order_evidence'] = dict(条件数=len(totals), 黒字条件数=int((totals>0).sum()),
        最良合計円=float(totals.max()), 銘柄別組数=len(symbol_totals), 銘柄別黒字数=int((symbol_totals>0).sum()),
        最良銘柄円=float(symbol_totals.max()))
    for session in signals.SESSIONS:
        for symbol in signals.SYMBOLS:
            path = signals.candle_root(session)/'candle_5min'/symbol/f'{session}.csv'
            if path.exists():
                data['candles'][f'{session}|{symbol}'] = candles(path)
    for path in sorted(OUT.glob('*監査*.json')):
        record = read_json(path.name,{})
        data['audits'].append(dict(file=path.name,record=record))
    selfcheck = read_json('注文再生の自己検査.json')
    if selfcheck:
        data['audits'].append(dict(file='注文再生の自己検査.json',record=selfcheck))
    attach_live(data)
    return clean(data)


def attach_live(data: dict) -> None:
    """機能: 一回取得の現在照合資料があれば表示資料へ加える。

    引数: data (dict)。返り値: なし (None)。
    """
    record = read_json('現在照合_取得記録.json',{})
    if not record:
        return
    data['live']['record'] = record
    data['live']['boundary_note'] = read_csv('現在照合_旧保存行境界の補足.csv').to_dict('records')
    for key in ('セッション集計','新信号起源集計','既知起源集計','全体参考集計'):
        frame = read_csv(f'現在照合_{key}.csv')
        if not frame.empty:
            data['live'][key] = frame.to_dict('records')
    if record.get('status') != '取得と検査完了' or not data['live'].get('セッション集計'):
        return
    session = record['session']
    shown = session+f"（全体参考・今回末尾{pd.Timestamp(record['cutoff']).strftime('%H:%M')}まで）"
    data['sessions'] = list(data['sessions'])+[shown]
    data['live']['display_session'] = shown
    data['trades'].extend(compact_trades(read_json('現在照合_全取引.json',[]),shown))
    for key, value in read_json('現在照合_評価曲線.json',{}).items():
        parts = key.split('|')
        data['curves'][f'{parts[0]}|{shown}|{parts[2]}'] = value
    for row in data['live'].get('全体参考集計',[]):
        data['rows'].append(dict(row,セッション=shown))
    for symbol in signals.SYMBOLS:
        path = OUT/'live/candle_5min'/symbol/f'{session}.csv'
        if path.exists():
            data['candles'][f'{shown}|{symbol}'] = candles(path)


def markdown_table(rows: list[dict], columns: list[str]) -> str:
    """機能: 任意の列順でMarkdownの比較表を作る。

    引数: rows (list[dict])、columns (list[str])。返り値: 表文字列 (str)。
    """
    output = ['| '+' | '.join(columns)+' |','| '+' | '.join(['---']*len(columns))+' |']
    for row in rows:
        output.append('| '+' | '.join(str(row.get(c,'—')).replace('|','／').replace('\n',' ') for c in columns)+' |')
    return '\n'.join(output)


def write_markdown(data: dict) -> None:
    """機能: 思想別の仮説・条件・セッション損益を文章にも保存する。

    引数: data (dict)。返り値: なし (None)。
    """
    rows = pd.DataFrame(data['rows'])
    methods = {m['id']:m for m in data['methods']}
    lines = ['# 予測と注文手法の組合せ検証', '',
        '**最初に見る資料: [ダークテーマの検証と売買図](予測と注文手法の検証.html)**', '',
        f"予測24系統、注文10系統から{data['counts'].get('条件数','—'):,}条件を比較した。方向予測、注文ルール、両方の組合せを分け、機会の見送りを減点していない。以下の金額は万円、利益・損失は全脚に費用を課した後の正負別集計。", '',
        '## 評価の分離', '',
        '保存済み完全５セッションを使う探索、最初の２→３・３→４・４→５セッションの時間順選択、既知の9/23ナイト00:02まで、条件固定後の現在追加区間を区別する。過去の研究で既に見た完全５セッションを、研究全体に対して未見と主張しない。短い現在照合も実時間の前向き運用ではなく、取得前に生じた未読区間の一回照合である。', '',
        '### 過去だけで選んだ次セッション３回の合計', '']
    nk_id = data['selection'].get('銘柄別主選択',{}).get('NK225',{}).get('予測と注文の組合せ',{}).get('採用',{}).get('方式')
    if nk_id:
        candidate = aggregate(rows[(rows.方式==nk_id)&(rows.銘柄=='NK225')&rows.セッション.isin(COMPLETE)])
        known_candidate = aggregate(rows[(rows.方式==nk_id)&(rows.銘柄=='NK225')&(rows.セッション=='2026-09-23_Night')])
        latest_candidate = next((r for r in data['live'].get('全体参考集計',[]) if r['方式']==nk_id and r['銘柄']=='NK225'),{})
        now = next((r for r in data['live'].get('セッション集計',[]) if r['方式']==nk_id and r['銘柄']=='NK225'),{})
        paragraph = (f"**NK225の候補は `{nk_id}`。完全５セッションを見た探索では{money(candidate['収支円'])}万円、{int(candidate['取引数'])}脚。"
                     f"ただし既知の9/23ナイト00:02までは{money(known_candidate['収支円'])}万円・{int(known_candidate['取引数'])}脚、条件固定後の追加区間は{money(now.get('追加清算価値円'))}万円・{now.get('区間内新規脚数','—')}新規脚。"
                     f"ナイト全体の今回末尾までは{money(latest_candidate.get('収支円'))}万円・{latest_candidate.get('取引数','—')}脚だった。探索では有望だったが最新夜間に崩れており、安定性も統計的な有意性も確認できていない。**")
        order_evidence = data['order_evidence']
        lines[4:4] = [paragraph, '',
            f"この候補の完全５セッションの売買勝率は{candidate['勝率']:.0%}（{int(candidate['取引数'])}取引中{int(candidate['勝ち数'])}勝）。機械学習やLSTMの予測精度ではない。有取引は４セッションで、9/23デイは新規なし。", '',
            f"純粋な注文主導{order_evidence['条件数']}条件は、完全５セッション・両銘柄合計ですべて赤字（最良でも{money(order_evidence['最良合計円'])}万円）。銘柄ごとの{order_evidence['銘柄別組数']}組もすべて赤字だった。この保存範囲では注文の組合せだけの収益性は見つからなかった。", '',
            '銘柄別の時間順評価は、その時点の過去だけから条件を選び直す「選択方針」の成績であり、最終固定候補だけを通した成績ではない。', '']
    summary = [dict(思想=r['思想'],利益=money(r['利益円']),損失=money(r['損失円']),収支=money(r['収支円']),
                    費用倍収支=money(r['費用倍収支円']),枚数上限換算収支=money(r['枚数上限換算収支円']),取引脚数=int(r['取引数'])) for r in data['walk_summary']]
    lines += [markdown_table(summary,list(summary[0])),'',
        '実枚数での円損益と、各設定の同時総枚数上限で除した値を併記する。後者は同じ枚数枠へ配分した場合の比較であり、証拠金に対する収益率ではない。', '']
    ideas = {
        '予測主導': '方向モデルの寄与を分離する。検知後に成行で１枚入り、５・15・30・60分後の固定時間で返済する。途中の利確・追跡による調整を加えない。',
        '予測と注文の組合せ': '予測はきっかけと方向を担当し、反発待ち・突破待ち、損切りと利確、追跡の短縮、段階利確・利益方向への追加で損益分布を変える。',
        '注文主導': '方向を先に当てるモデルを置かず、固定コイン、上下注文、両建て、有限グリッド、在庫補正、分割返済を使う。価格経路への仮説まで消えるわけではない。'}
    for index, philosophy in enumerate(PHILOSOPHIES,1):
        lines += [f'## 第{index}章　{philosophy}', '', '### 思想と試したこと', '', ideas[philosophy], '',
                  '### 結果と代表条件', '', '以下の代表は完全５セッションを見て選んだ探索内代表である。ここでの好成績を、そのまま将来の有意性とは扱わない。', '']
        by_symbol = [r for r in data['symbol_walk_summary'] if r['思想']==philosophy]
        if by_symbol:
            formatted = [dict(銘柄=r['銘柄'],利益=money(r['利益円']),損失=money(r['損失円']),収支=money(r['収支円']),
                              費用倍収支=money(r['費用倍収支円']),脚数=int(r['取引数'])) for r in by_symbol]
            lines += ['### 銘柄別に条件を選んだ時間順評価', '',
                      '共通条件の結果に銘柄差があったため、銘柄ごとに条件を選ぶ方針を探索途中で追加した。その経緯を隠さず、共通条件の結果も上に残す。', '',
                      markdown_table(formatted,list(formatted[0])), '']
            choices = [r for r in data['symbol_walk'] if r['思想']==philosophy]
            detail = [dict(セッション=r['セッション'],銘柄=r['銘柄'],過去から選んだ条件=r['方式'],収支=money(r['収支円']),費用倍=money(r['費用倍収支円'])) for r in choices]
            lines += [markdown_table(detail,list(detail[0])), '']
        candidates = [c for c in data['methods'] if c['philosophy']==philosophy]
        for cfg in candidates:
            scope = rows[(rows.方式==cfg['id']) & rows.セッション.isin(COMPLETE)]
            value = aggregate(scope)
            uses = [symbol for symbol, policies in data['selection'].get('銘柄別主選択',{}).items()
                    if any(c.get('採用',{}).get('方式')==cfg['id'] for c in policies.values())]
            use_text = []
            for symbol in uses:
                target = aggregate(scope[scope.銘柄==symbol])
                use_text.append(f"**選択用途: {symbol}用。対象銘柄の完全５セッションは利益{money(target['利益円'])}万円、損失{money(target['損失円'])}万円、収支{money(target['収支円'])}万円、費用倍{money(target['費用倍収支円'])}万円、{int(target['取引数'])}脚。**")
            lines += [f"#### {cfg['id']}：{cfg['label']}", '',
                      *use_text, '',
                      f"参考: 同じ条件を両銘柄へ適用した完全５セッション合計は利益{money(value['利益円'])}万円、損失{money(value['損失円'])}万円、収支{money(value['収支円'])}万円、費用倍{money(value['費用倍収支円'])}万円。１銘柄の最大同時{value['最大保有枚数']}枚。", '',
                      *[f'- {rule}' for rule in cfg['rules']], '']
            sr = [dict(セッション=r['セッション']+('（既知・翌00:02まで）' if r['セッション']=='2026-09-23_Night' else ''),銘柄=r['銘柄'],利益=money(r['利益円']),損失=money(r['損失円']),収支=money(r['収支円']),
                       費用倍収支=money(r['費用倍収支円']),未返済評価=money(r['評価損益円']),下落=money(r['全行最大下落円']),脚数=int(r['取引数']))
                  for r in rows[rows.方式==cfg['id']].to_dict('records')]
            lines += [markdown_table(sr,list(sr[0])),'']
    lines += ['## 条件固定後の現在セッション一回照合', '']
    live = data['live'].get('セッション集計',[])
    if live:
        rec = data['live']['record']
        lines += [f"照合範囲は {rec['known_cutoff']} から {rec['cutoff']} 未満。00:02時点で残した建玉も継続し、開始の全脚清算価値から末尾までの増減を主指標にする。区間内の確定損益だけを使うと開始時の含み損や末尾の残存損が隠れるので、別に示す。", '']
        formatted = [dict(方式=r['方式'],銘柄=r['銘柄'],追加清算価値=money(r['追加清算価値円']),
            費用倍追加=money(r['費用倍追加清算価値円']),確定利益=money(r['区間内確定利益円']),確定損失=money(r['区間内確定損失円']),
            確定収支=money(r['区間内確定収支円']),開始評価=money(r['開始評価損益円']),末尾評価=money(r['終了評価損益円']),
            新規脚数=r['区間内新規脚数'],末尾残脚=r['終了未返済数']) for r in live]
        lines += [markdown_table(formatted,list(formatted[0])), '']
        lines += ['時計境界00:02より前と表示される追加観測行も存在する。旧ファイルの最終行を境界とした補助再評価では54セル中３セルだけ＋１万円・＋１万円・−0.5万円の差があり、主なNK候補の−９万円は変わらない。[旧保存行境界の補足](資料/現在照合_旧保存行境界の補足.csv)を参照。主表の境界を結果を見て変更していない。', '']
    else:
        lines += ['資料生成時点では現在照合はまだ終了していない。', '']
    lines += ['## 一次資料と実装への変更点', '',
              '- [予測仮説の文献メモ](資料/文献_予測.md)', '- [注文手法の文献メモ](資料/文献_注文.md)',
              '- [計算式と旧方式の具体条件](資料/主なルールの補足.md)', '- [注文APIへの対応と未実装事項](資料/注文APIへの対応.md)', '',
              '論文の実績値をこのデータへ移植せず、着想を本データで実行可能な条件へ置換した。受信時刻・注文IDがないため受動指値の順番は再現できない。指値の触れによる楽観的約定や、両建ての片側費用の省略はしない。', '',
              '## 再現・監査', '',
              '単建玉と複数建玉は全気配で注文を再生する。未返済評価を含む最大下落も全気配で計算する。途中断面の未返済建玉を架空の返済にせず、実際のセッション終了前に全返済する。原本３フォルダは読み取り専用。詳細は[資料一覧](README.md)と監査JSONを参照。', '']
    (DEST/'検証結果.md').write_text('\n'.join(lines),encoding='utf-8')


def update_index() -> None:
    """機能: 旧作業を保存したまま新作業を一覧の先頭へ追加する。

    引数: なし。返り値: なし (None)。
    """
    root = ROOT/'アルゴリズム調査'
    link = f'{DEST.name}/予測と注文手法の検証.html'
    path = root/'README.md'
    previous = path.read_text(encoding='utf-8')
    if DEST.name not in previous:
        previous = re.sub(r'\*\*最新は.*?\*\*',f'**最新は00006の[予測と注文手法の検証]({link})です。一次研究を参考に、予測・注文・両者の組合せを思想別に比較しています。**',previous,count=1)
        row = f'| `{DEST.name}`（最新） | 予測24系統と注文10系統。複数建玉・時間順評価・含み損込み下落・一回照合 | [検証と売買図]({link}) | [検証結果]({DEST.name}/検証結果.md)・[資料案内]({DEST.name}/README.md) |\n'
        previous = previous.replace('| `00005_',row+'| `00005_',1).replace('`00005_損小利大と時間帯別ルールの検証`（最新）','`00005_損小利大と時間帯別ルールの検証`')
        previous = previous.replace('`00006_内容`','`00007_内容`')
        path.write_text(previous,encoding='utf-8')
    path = root/'index.html'
    previous = path.read_text(encoding='utf-8')
    if DEST.name not in previous:
        previous = previous.replace('class="task latest"','class="task"').replace('作業 00005 <span class="badge">最新</span>','作業 00005')
        previous = re.sub(r'<p class="lead">.*?</p>','<p class="lead">最新は、研究論文を参考に予測と注文手法を組み合わせ、複数建玉と未返済損失まで比較した検証です。</p>',previous,count=1)
        block = f'''  <article class="task latest" aria-labelledby="combination-title">
    <div class="number">作業 00006 <span class="badge">最新</span></div>
    <h2 id="combination-title">予測と注文手法の組合せ検証</h2>
    <p>予測主導・予測と注文の組合せ・注文主導の３章で仮説と結果を整理。平均回帰・出来高・板・２銘柄、両建て・有限グリッド・段階利確などを比較しました。</p>
    <a class="button" href="{link}">思想別の検証結果と売買図を開く →</a>
    <ul><li><a href="{DEST.name}/検証結果.md">詳しい条件とセッション別損益</a></li><li><a href="{DEST.name}/README.md">資料の読む順序・再現手順</a></li></ul>
    <p class="folder">保存先：{DEST.name}</p>
  </article>
'''
        previous = previous.replace('  <article class="task"',block+'  <article class="task"',1)
        path.write_text(previous,encoding='utf-8')


def main() -> None:
    """機能: 最新の確定済み集計からHTML・文章・資料案内を生成する。

    引数: なし。返り値: なし (None)。履歴APIは呼び出さない。
    """
    DEST.mkdir(parents=True,exist_ok=True)
    data = build_payload()
    encoded = json.dumps(data,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c')
    (DEST/'予測と注文手法の検証.html').write_text(TEMPLATE.replace('__DATA__',encoded),encoding='utf-8')
    write_markdown(data)
    materials = DEST/'資料'
    materials.mkdir(exist_ok=True)
    for path in OUT.iterdir():
        if path.is_file() and path.suffix in ('.py','.json','.csv','.md','.npz'):
            shutil.copy2(path,materials/path.name)
    (DEST/'README.md').write_text('''# 00006　予測と注文手法の組合せ検証

**最初に見るファイルは[予測と注文手法の検証.html](予測と注文手法の検証.html)です。**

## 読む順序

1. [HTML](予測と注文手法の検証.html): ３つの思想の仮説と結果、時間順評価、５分足の全脚エントリー・返済、含み損込み資産曲線。
2. [検証結果.md](検証結果.md): 正確な入口・出口、代表条件の各セッションの利益・損失・収支。
3. [予測の文献メモ](資料/文献_予測.md)と[注文の文献メモ](資料/文献_注文.md): 一次資料から何を採り、何を置き換えたか。
4. [全条件の集計](資料/全条件_セッション集計.csv)・[条件一覧](資料/条件一覧.json)・[全取引数値](資料/全売買数値.npz)・[数値形式](資料/数値形式.json): 代表以外を含む明細。
5. [検証計画](資料/検証計画.md)と[監査設計](資料/監査設計.md)、各監査JSON: 先読み、約定遅延、枚数、費用、未返済評価の検査。

## 再現手順

再生ソースの正本はプロジェクトルートの `work/wave_v11`。ここに置く `.py` は参照用の写しで、単独実行パッケージではない。依存する過去の抽出器・気配データ・保存済み現在照合データもプロジェクト内に必要。

プロジェクトルートで `python -X utf8 work/wave_v11/report.py` を実行すると、保存済み結果からこの資料を再生成する。履歴APIは取得しない。保存データの再計算は `python -X utf8 work/wave_v11/research.py`。現在照合の取得は一回限定なので、確認目的で再取得しない。

`book`・`candle_1min`・`candle_5min` は原本のまま読み取り専用。現在照合の原本と取得記録は `work/wave_v11/live` と `work/wave_v11/現在照合_*` に保存する。

ラージ１銘柄あたり１〜３枚、２銘柄では最大６枚の取引を全脚集計する。枚数上限で除した額は、証拠金に対する収益率ではない。未返済の評価と確定収支は分けて読む。
''',encoding='utf-8')
    update_index()
    print(f'図解作成: {DEST} / 代表{len(data["methods"])}条件・{len(data["trades"])}脚')


TEMPLATE = r'''<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>00006｜予測と注文手法の検証</title>
<style>
:root{color-scheme:dark;--bg:#080e19;--panel:#111d2e;--line:#2a3c57;--text:#eaf2ff;--sub:#b0c1d8;--up:#58ddb0;--down:#ff8d9d;--blue:#87bfff;--amber:#ffd386}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.8 "Yu Gothic UI","Meiryo",sans-serif}main{max-width:1510px;margin:auto;padding:40px 26px 80px}h1{font-size:34px;line-height:1.4;margin:12px 0}h2{font-size:24px;margin:0 0 18px}h3{font-size:19px}a{color:var(--blue)}p{margin:12px 0}.eyebrow{font-size:12px;letter-spacing:.14em;color:var(--blue)}.lead{color:#d5e0ef;font-size:17px;max-width:1120px}.muted{color:var(--sub)}.small{font-size:12px}.panel{margin:28px 0;padding:25px;border:1px solid var(--line);border-radius:16px;background:var(--panel)}.notice{border-left:4px solid var(--amber);background:#282619;padding:15px 18px;color:#f6e5be;margin:16px 0}.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}.card{border:1px solid var(--line);border-radius:11px;padding:18px;background:#18263b}.card strong{font-size:26px;display:block}.up{color:var(--up)}.down{color:var(--down)}.scroll{overflow:auto;max-height:620px}table{width:100%;border-collapse:collapse;font-size:13px;white-space:nowrap}td,th{padding:10px 12px;text-align:right;border-bottom:1px solid var(--line)}td:first-child,th:first-child{text-align:left}th{position:sticky;top:0;background:#1b2c44;z-index:1}tbody tr:hover{background:#1d304d}details{border:1px solid var(--line);border-radius:9px;margin:12px 0;padding:12px 16px}summary{cursor:pointer;color:#d7e8ff;font-weight:600}.rules{border-left:3px solid var(--blue);padding:8px 18px;background:#15243c;white-space:normal}.rule{margin:7px 0}.nav{display:flex;flex-wrap:wrap;gap:20px;margin:22px 0}.controls{display:flex;flex-wrap:wrap;gap:14px;align-items:end}.controls label{font-size:12px;color:var(--sub);display:flex;flex-direction:column;gap:6px}select,button{background:#1b2c45;color:var(--text);border:1px solid #4b6485;border-radius:7px;padding:9px 12px;font:inherit}select{max-width:680px}button{cursor:pointer}.chartbox{position:relative;border:1px solid var(--line);background:#0a1423;border-radius:12px;overflow:hidden;margin:15px 0}canvas{display:block;width:100%;height:490px;background:#0a1423}#equity{height:240px}.tooltip{display:none;position:absolute;pointer-events:none;background:#1d2e49;border:1px solid #7e9ec7;border-radius:8px;padding:10px 13px;font-size:12px;max-width:390px;z-index:4}.legend{display:flex;flex-wrap:wrap;gap:18px;font-size:12px;color:var(--sub)}.selected{background:#294362!important}.badge{font-size:11px;border:1px solid #496285;padding:2px 7px;border-radius:4px}.filelinks{display:flex;flex-wrap:wrap;gap:18px}.wrap{white-space:normal;min-width:240px;max-width:660px}footer{color:var(--sub);font-size:12px;border-top:1px solid var(--line);padding-top:25px}.chapter-caption{color:#91bff5;font-size:13px}.duo{display:grid;grid-template-columns:1fr 1fr;gap:20px}@media(max-width:900px){main{padding:24px 14px}.panel{padding:17px}.grid,.duo{grid-template-columns:1fr}h1{font-size:26px}select{max-width:88vw}canvas{height:410px}}
</style></head><body><main>
<!--
[コンポーネント概要]
#overview は完全５セッションの選択と次セッション評価の違いを明示します。
#chapters は予測主導・組合せ・注文主導の順に思想と実績を表示します。
#method/#symbol/#session は５分足・全脚明細・評価曲線の対象を切り替えます。
#chart は確定５分足と各建玉の新規・返済・未返済評価を描きます。
#equity は全残存脚の返済費用込み評価を含む資産曲線です。
#live は既知終端からの追加区間の清算価値変化を示します。
-->
<div class="eyebrow">00006 · 一次研究から仮説を作り、保存された全気配で検証</div>
<h1>予測と注文手法を、どこで組み合わせるか</h1>
<p class="lead">方向を当てる力、損益を整える注文ルール、複数建玉の扱いを分けて比較しました。利益の出た脚だけでなく、残した損失脚・約定費用・含み損込みの下落を含めて判断します。</p>
<div class="filelinks"><a href="検証結果.md">詳しい条件と結果</a><a href="README.md">読む順序・資料一覧</a><a href="../index.html">調査一覧</a></div>
<nav class="nav"><a href="#overview">評価の要点</a><a href="#chapter0">予測主導</a><a href="#chapter1">予測と注文</a><a href="#chapter2">注文主導</a><a href="#live">現在照合</a><a href="#visual">売買図</a><a href="#research">文献・全仮説</a></nav>
<section class="panel" id="overview"><h2>過去だけで選んだ次セッションではどうだったか</h2><div id="overview-text"></div><div class="grid" id="overview-cards"></div><div id="overview-table"></div><div class="notice">上の数字は、過去２→次の１、過去３→次の１、過去４→次の１の３回を合算した時間順評価です。完全５セッションを全部見て選んだ代表の探索成績とは分けています。今回の前にも閲覧済みの保存期間なので、研究全体に対する未見データとは呼びません。</div><details><summary>３回の評価をセッション・銘柄別に見る</summary><div id="walk-detail"></div></details></section>
<section class="panel"><h2>共通の評価条件</h2><div class="duo"><div><h3>注文と費用</h3><p>条件成立の行を約定価格へ流用せず、後続の有効気配で約定。価格待ち条件は作成と成立も別行。成行相当の新規は成立可能なstop/limit条件による抽象再生です。買いはask、売りはbid、返済は逆側の気配。気配差に加えて各脚に往復２呼値の費用を課し、４呼値でも比較します。</p><p>指値の触れだけで約定したとは扱いません。相手気配が１呼値通過後、後続行の相手気配で新規約定。条件価格より不利に変化した場合もその価格を使い、価格保証は置きません。複数脚は同じ行の最良数量を共有します。</p></div><div><h3>枚数と残存損失</h3><p>１銘柄あたり単建玉１枚、両建て２枚、グリッド・追加・段階返済は総３枚上限。２銘柄では最大６枚です。円損益に加え、各銘柄の設定最大総枚数で別々に除して合算した比較も表示します。証拠金に対する収益率ではありません。</p><p>デイ15:35・ナイト翌05:50に全返済を開始。途中断面は未返済評価を別掲し、セッション末尾と取り違えません。最大下落は含み損を入れて全気配で測っています。</p></div></div><p class="small muted">最良気配の時計は最終約定時刻の代理であり、共通受信時計ではありません。２銘柄比較は相手情報の公開から60秒待ちます。上下逆指値の競合取消は同方向OCO APIとは別で、実通信中の取消競合は再現していません。</p></section>
<div id="chapters"></div>
<section class="panel" id="live"><h2>条件固定後の現在セッション一回照合</h2><div id="live-content"></div></section>
<section class="panel" id="visual"><h2>５分足・全脚の入出場・含み損込み資産曲線</h2><p class="muted">同じ条件を各セッションに適用した図です。今回末尾の選択肢も17:00からの全体参考で、00:02以降の追加成績は上の現在照合表に示します。代表は完全５セッションの探索から選択されています。ローソクは表示用で、注文再生は生気配の１行ごとに行います。</p><div class="controls"><label>条件<select id="method"></select></label><label>銘柄<select id="symbol"><option>NK225</option><option>TOPIX</option></select></label><label>セッション<select id="session"></select></label><label>範囲<select id="range"><option value="all">全体</option><option value="current">00:02以降</option><option value="trade">選択した脚の前後</option></select></label><button id="reset">脚の強調を解除</button></div><div class="rules" id="chart-rules"></div><div id="session-summary"></div><div class="legend"><span style="color:#58ddb0">▲ 買い新規</span><span style="color:#ff8d9d">▼ 売り新規</span><span style="color:#eaf2ff">× 返済</span><span style="color:#ffd386">◇ 未返済評価</span><span>破線は同じ脚の新規→返済／評価</span></div><div class="chartbox"><canvas id="chart" aria-label="５分足と全脚の新規・返済"></canvas><div class="tooltip" id="tooltip"></div></div><h3>清算価値の推移（確定分＋全残存脚の評価）</h3><div class="legend"><span style="color:#58ddb0">― 往復２呼値費用</span><span style="color:#ffb57f">― 往復４呼値費用</span><span>返済費用を未返済脚にも見込み済み</span></div><div class="chartbox"><canvas id="equity" aria-label="未返済損益を含む清算価値の推移"></canvas></div><p class="small muted">曲線の表示記録は毎分、最大下落の計算は全気配です。表の脚をクリックすると入出場を強調します。</p><div id="trade-table"></div><details><summary>この条件のセッション別・銘柄別の収支</summary><div id="method-table"></div></details></section>
<section class="panel" id="diagnostics"><h2>偶然・費用・変更の影響をどう確認したか</h2><div id="diagnostic-content"></div></section>
<section class="panel" id="research"><h2>研究から作った仮説と出典</h2><p>論文の収益率をここへ移植したものではありません。価格の時間幅、データ、約定条件が違うため、研究の着想をこのデータで実行可能な条件へ置換しました。動的グリッドの原論文は現物の長期保有を含みますが、O05は全返済して中心を作り直す別仮説です。</p><div class="filelinks"><a href="資料/文献_予測.md">予測の文献メモ</a><a href="資料/文献_注文.md">注文の文献メモ</a><a href="資料/条件一覧.json">全パラメーター</a></div><p class="small muted">P06は保存範囲で信号０件、P18は２件だけで、検出力の評価材料が不足。P02はセッション近似VWAPの出来高完全性を満たさないセッションで停止し、平均回帰の不成立とは解釈しません。</p><details><summary>予測24系統：思想・検知条件・一次資料</summary><div id="prediction-list"></div></details><details><summary>注文10系統：在庫・入口・出口・出典</summary><div id="order-list"></div></details></section>
<section class="panel" id="audit"><h2>監査・再現資料</h2><div id="audit-content"></div><p class="muted">未来の行を削除しても過去に確定した取引が不変か、単建玉と複数建玉の費用・損益・約定順序・全行評価を検査します。短い保存期間で、探索した多数の条件から選んだ利益だけを統計的な有意性の証拠にはしません。</p><div class="filelinks"><a href="資料/全条件_セッション集計.csv">全条件集計</a><a href="資料/時間順評価.csv">時間順の明細</a><a href="資料/全売買数値.npz">全取引数値</a><a href="資料/数値形式.json">数値形式</a><a href="README.md">再現案内</a><a href="資料/監査結果要約.md">監査結果の要約</a><a href="資料/主なルールの補足.md">具体的な計算式</a><a href="資料/注文APIへの対応.md">注文APIへの対応</a></div></section>
<footer>機会費用と見送り頻度には減点を置きません。ただし取引しない条件を優秀と認定せず、共通選択では両銘柄、銘柄別選択では対象銘柄に学習期間中１回以上の取引を要します。現時点の結果は保存期間と費用・約定仮定に依存します。</footer>
</main><script type="application/json" id="data">__DATA__</script><script>
const D=JSON.parse(document.getElementById('data').textContent),$=id=>document.getElementById(id);let selected=-1,points=[],visibleTrades=[];
/**
 * 機能: HTMLの特殊文字を表示用に変換する。
 * @param {unknown} x - 表示値。
 * @returns {string} 安全な文字列。
 */
function esc(x){return String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
/**
 * 機能: 円を万円の表示にする。
 * @param {number|null} x - 円。
 * @returns {string} 金額表記。
 */
function yen(x){if(x==null)return '—';x=Math.abs(x)<.000001?0:x;return (x>0?'+':'')+(x/10000).toLocaleString('ja-JP',{minimumFractionDigits:1,maximumFractionDigits:1});}
/**
 * 機能: 数値の正負を色付きで表示する。
 * @param {number|null} x - 円。
 * @returns {string} HTML。
 */
function cash(x){return `<span class="${x>0?'up':x<0?'down':''}">${yen(x)}</span>`;}
/**
 * 機能: 秒時刻を日本時間の月日と時分秒にする。
 * @param {number} t - Unix秒。
 * @param {boolean} date - 日付を表示するか。
 * @returns {string} 時刻。
 */
function clock(t,date=false){return new Date(t*1000).toLocaleString('ja-JP',{timeZone:'Asia/Tokyo',...(date?{month:'2-digit',day:'2-digit'}:{}),hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false});}
/**
 * 機能: 行と列定義からスクロール表を作る。
 * @param {Array<object>} rows - 行。
 * @param {Array<Array>} cols - 見出しと取得関数。
 * @returns {string} 表HTML。
 */
function table(rows,cols){return `<div class="scroll"><table><thead><tr>${cols.map(c=>`<th>${esc(c[0])}</th>`).join('')}</tr></thead><tbody>${rows.map(r=>'<tr>'+cols.map(c=>`<td>${c[1](r)}</td>`).join('')+'</tr>').join('')}</tbody></table></div>`;}
/**
 * 機能: 指定範囲の確定取引を合算する。
 * @param {Array<object>} rows - 集計行。
 * @returns {object} 合算値。
 */
function sum(rows){const out={};for(const k of ['利益円','損失円','収支円','費用倍収支円','評価損益円','取引数','未返済数','勝ち数','枚数上限換算収支円'])out[k]=rows.reduce((a,r)=>a+(r[k]||0),0);out.dd=Math.max(0,...rows.map(r=>r.全行最大下落円||0));return out;}
/**
 * 機能: ナイト保存断面の既知部分を完全セッションと区別する。
 * @param {string} value - セッション識別子。
 * @returns {string} 表示名。
 */
function sessionLabel(value){return value==='2026-09-23_Night'?value+'（既知・翌00:02まで）':value;}
/**
 * 機能: 条件を選んだ対象銘柄と、同条件の参考適用を区別する。
 * @param {string} id - 条件識別子。
 * @param {string} symbol - 銘柄。
 * @returns {string} 選択用途。
 */
function methodUse(id,symbol){const uses=Object.entries(D.selection.銘柄別主選択??{}).filter(([s,p])=>Object.values(p).some(c=>c.採用?.方式===id)).map(([s])=>s);return uses.includes(symbol)?symbol+'用の主候補':uses.length?'他銘柄への参考適用':'共通・群別候補';}
/**
 * 機能: 全脚の標準集計列を返す。
 * @returns {Array<Array>} 表列。
 */
function metricCols(){return [['利益／万円',r=>cash(r.利益円)],['損失／万円',r=>yen(r.損失円)],['収支／万円',r=>cash(r.収支円)],['費用倍／万円',r=>cash(r.費用倍収支円)],['未返済評価／万円',r=>cash(r.評価損益円)],['全行下落／万円',r=>yen(r.全行最大下落円??r.dd)],['確定脚数',r=>r.取引数],['未返済脚',r=>r.未返済数??0]];}
/**
 * 機能: 主評価と思想別の章を描画する。
 * @returns {void} 返り値はない。
 */
function renderChapters(){const names=['予測主導','予測と注文の組合せ','注文主導'],hypotheses=['方向予測の寄与を分けるため、検知後に成行で入り、５・15・30・60分後の固定時間で返します。平均回帰、出来高、継続、板、２銘柄の24系統を比べます。','方向の検知に、反発・突破を待つ入口、小損切りと大きい利益、条件付き追跡短縮、段階利確・利益方向への追加を組み合わせます。見送りへの減点は設けません。','方向予測モデルを置かず、固定コイン、同時両建て、上下逆指値、固定・再中心化・在庫補正グリッド、利益脚の先行返済を比較します。価格経路への暗黙の仮説は残ります。'];
 $('overview-text').innerHTML=`<p>${D.counts.条件数?.toLocaleString()??'—'}条件、予測24系統・注文10系統を比較。全${D.counts.売買数?.toLocaleString()??'—'}件の新規・返済／未返済記録を保存しました。</p>`;
 $('overview-cards').innerHTML=D.walk_summary.map(r=>`<div class="card"><span>${esc(r.思想)}</span><strong class="${r.収支円>=0?'up':'down'}">${yen(r.収支円)}万円</strong><span>費用倍 ${yen(r.費用倍収支円)}万円／${r.取引数}脚<br>最大枚数で除した収支 ${yen(r.枚数上限換算収支円)}万円</span></div>`).join('');
 $('overview-table').innerHTML=table(D.walk_summary,[['思想',r=>esc(r.思想)],...metricCols().filter(c=>!['未返済脚','全行下落／万円','未返済評価／万円'].includes(c[0])),['上限枚数換算／万円',r=>cash(r.枚数上限換算収支円)]]);
 $('walk-detail').innerHTML=table(D.walk,[['思想',r=>esc(r.思想)],['評価セッション',r=>esc(sessionLabel(r.セッション))],['銘柄',r=>r.銘柄],['過去だけで選んだ条件',r=>esc(r.方式)],...metricCols()]);
 $('chapters').innerHTML=names.map((name,idx)=>{const ms=D.methods.filter(m=>m.philosophy===name), primary=D.selection.主選択?.[name]?.採用?.方式, history=ms.flatMap(m=>['NK225','TOPIX'].map(symbol=>({id:m.id,label:m.label,cap:m.max_positions,symbol,usage:methodUse(m.id,symbol),...sum(D.rows.filter(r=>r.方式===m.id&&r.銘柄===symbol&&D.complete.includes(r.セッション)))})));return `<section class="panel" id="chapter${idx}"><div class="chapter-caption">第${idx+1}章</div><h2>${esc(name)}</h2><h3>思想と試したこと</h3><p>${hypotheses[idx]}</p><h3>結果はどうだったか</h3><p>完全５セッションの探索で選ばれた主候補は <b>${esc(primary??'該当なし')}</b>。下表は思想内の群別代表を含む探索内の成績を銘柄ごとに示します。個別用として選んだ条件を他銘柄へ適用した参考結果も分けています。上の時間順３回とは異なる範囲です。</p>${table(history,[['代表条件',r=>`<a href="#visual" data-select="${esc(r.id)}">${esc(r.id)}</a><div class="small muted wrap">${esc(r.label)}</div>`],['銘柄',r=>r.symbol],['選択用途',r=>esc(r.usage)],['総枚数上限／銘柄',r=>r.cap],...metricCols().filter(c=>!['未返済脚','未返済評価／万円'].includes(c[0])),['上限枚数換算／万円',r=>cash(r.枚数上限換算収支円)]])}<p class="small muted">下落は各銘柄の５セッションの含み損込み最大下落のうち最大値。複数日を連結した下落ではありません。損失は正の大きさで表示。</p>${ms.map(m=>`<details><summary>${esc(m.id)}｜具体的な入口・出口</summary><p>${esc(m.label)}</p><div class="rules">${m.rules.map(x=>`<p class="rule">${esc(x)}</p>`).join('')}</div><p><a href="#visual" data-select="${esc(m.id)}">この条件をチャートで確認</a></p></details>`).join('')}</section>`;}).join('');}
/**
 * 機能: 研究仮説、診断と監査の一覧を描画する。
 * @returns {void} 返り値はない。
 */
function renderResearch(){ $('prediction-list').innerHTML=table(D.profiles,[['系統',r=>esc(r.id)],['思想',r=>esc(r.group)],['仮説と条件',r=>`<div class="wrap"><b>${esc(r.label)}</b><br>${esc(r.rules)}</div>`],['一次資料',r=>`<a href="${esc(r.source)}">${esc(r.source_name)}</a>`]]);$('order-list').innerHTML=table(D.order_profiles,[['系統',r=>esc(r.family)],['注文仮説',r=>`<div class="wrap">${esc(r.label)}</div>`],['最大総枚数',r=>r.max_positions],['条件',r=>`<div class="wrap">${esc(r.exact_rules)}</div>`],['一次資料',r=>`<a href="${esc(r.provenance)}">研究の着想</a>`]]);
 let text='<p>コイントスは、都合のよい乱数を選ばず、主乱数を固定した上で64種類の感度を調べます。固定した予測の信号時刻でも方向だけを入れ替え、時刻と方向の寄与を分けます。入口・出口の比較は、相手側の条件をそろえた対応比較を使います。</p>';
 for(const [label,key,file] of [['定刻コインと３脚分割の64乱数','coins','定刻コイン_64種.csv'],['信号時刻をそろえた方向64乱数','signal_coins','信号時刻固定_方向64種.csv'],['入口と出口の対応比較','contrasts','入口と出口の対応比較.csv']]){const rows=D[key]??[];text+=`<details><summary>${label}（${rows.length}行）</summary><p><a href="資料/${file}">全明細CSV</a></p>`+(rows.length?table(rows.slice(0,100),Object.keys(rows[0]).map(k=>[k,r=>typeof r[k]==='number'?Number(r[k].toFixed(3)).toLocaleString('ja-JP'):esc(r[k])])):'<p>資料作成時点で診断結果は未保存。</p>')+'</details>';}
 text+='<p class="small muted">出口プリセットは初期損切りや利確も一緒に変わる場合があります。プリセット差を「追跡幅の短縮だけの効果」とは扱いません。多数条件からの選択と短い期間のため、無調整の勝率や順位だけで有意とは認定しません。</p>';$('diagnostic-content').innerHTML=text;
 $('audit-content').innerHTML=D.audits.map(a=>`<details><summary>${esc(a.file)}</summary><p><a href="資料/${esc(a.file)}">監査記録を開く</a></p><pre class="scroll small">${esc(JSON.stringify(a.record,null,2).slice(0,12000))}</pre></details>`).join('');
 $('live-content').innerHTML=D.live.record?'<p>一回取得記録を読み込み済み。区間別の全脚清算価値と明細は最終集計の組込み後に表示します。</p>':'<p class="notice">現在セッションの追加区間は、保存データでの比較と条件固定を終えてから一回だけ取得・照合します。この資料の生成時点では未取得です。</p>';}
/**
 * 機能: 銘柄ごとに条件を選ぶ追加方針を、共通条件と分けて表示する。
 * @returns {void} 返り値はない。
 */
function renderSymbolChoices(){const policies=D.selection.銘柄別主選択??{},names=['予測主導','予測と注文の組合せ','注文主導'];for(const [index,name] of names.entries()){const rows=(D.symbol_walk_summary??[]).filter(r=>r.思想===name),chosen=Object.entries(policies).map(([symbol,x])=>({symbol,id:x[name]?.採用?.方式})).filter(x=>x.id);const section=document.createElement('div');section.innerHTML=`${name==='注文主導'?`<p class="notice">注文主導${D.order_evidence.条件数}条件は、完全５セッション・両銘柄合計ですべて赤字。最良でも${cash(D.order_evidence.最良合計円)}万円で、銘柄別${D.order_evidence.銘柄別組数}組もすべて赤字でした。利益脚だけを先に確定しても、損失脚と全費用を合わせた優位性はこの範囲で見つかりませんでした。</p>`:''}<h3>銘柄ごとに条件を分けるとどうか</h3><p class="muted">共通条件の銘柄差を見て、探索途中で追加した選択方針です。上の共通条件を置き換えず、同じ３回の時間順評価を並べます。</p>${table(rows,[['銘柄',r=>r.銘柄],...metricCols().filter(c=>!['全行下落／万円','未返済脚','未返済評価／万円'].includes(c[0]))])}<details><summary>実際に各回で選んだ条件と損益</summary>${table(D.symbol_walk.filter(r=>r.思想===name),[['評価セッション',r=>esc(sessionLabel(r.セッション))],['銘柄',r=>r.銘柄],['選んだ条件',r=>esc(r.方式)],['収支／万円',r=>cash(r.収支円)],['費用倍／万円',r=>cash(r.費用倍収支円)]])}</details><p>完全５セッションから固定した条件: ${chosen.map(r=>`${esc(r.symbol)} <a href="#visual" data-select="${esc(r.id)}">${esc(r.id)}</a>`).join(' ／ ')}</p>`;const anchor=$('chapter'+index).querySelector('h3:nth-of-type(2)');anchor.after(section);}
 const id=policies.NK225?.['予測と注文の組合せ']?.採用?.方式;if(id){const hist=sum(D.rows.filter(r=>r.方式===id&&r.銘柄==='NK225'&&D.complete.includes(r.セッション))),walk=D.symbol_walk_summary.find(r=>r.思想==='予測と注文の組合せ'&&r.銘柄==='NK225'),known=sum(D.rows.filter(r=>r.方式===id&&r.銘柄==='NK225'&&r.セッション==='2026-09-23_Night')),latest=D.live.全体参考集計?.find(r=>r.方式===id&&r.銘柄==='NK225');const hero=document.createElement('div');hero.className='notice';hero.innerHTML=`<b>探索では有望だったが、最新夜間に崩れた候補: NK225の${esc(D.methods.find(m=>m.id===id)?.label??id)}</b><p>完全５セッションの探索で ${cash(hist.収支円)}万円／${hist.取引数}脚・${hist.勝ち数}勝（売買勝率${(100*hist.勝ち数/hist.取引数).toFixed(0)}%）。有取引４セッションで9/23デイは新規なし。これはLSTMの予測精度ではありません。NKで過去だけから条件を選び直す方針の時間順３回は ${cash(walk?.収支円)}万円、費用倍でも ${cash(walk?.費用倍収支円)}万円。最終固定条件だけの３回成績ではありません。TOPIXへ同じ条件をそのまま適用できるとは判断しません。</p><p>既に閲覧済みの9/23ナイト17:00〜翌00:02は ${cash(known.収支円)}万円・${known.取引数}脚。今回の未読追加区間では ${cash(D.live.セッション集計?.find(r=>r.方式===id&&r.銘柄==='NK225')?.追加清算価値円)}万円、区間内新規${D.live.セッション集計?.find(r=>r.方式===id&&r.銘柄==='NK225')?.区間内新規脚数??'—'}脚。ナイト全体の今回末尾までは ${cash(latest?.収支円)}万円・${latest?.取引数??'—'}脚でした。既知部分の失速も含め、安定した規則を確認できたとは判断しません。</p><p>有望な候補と、統計的に確認済みの規則は分けています。銘柄別方針は探索途中の追加で、現在照合の結果も下で確認してください。時間順では9/22デイは追跡新規0.25ATR、9/22ナイトと9/23デイは検知後の成行相当が選ばれました。<a href="#visual" data-select="${esc(id)}">入口・出口と全売買を見る</a></p>`;$('overview-text').prepend(hero);}}
/**
 * 機能: 一回照合の清算価値変化を、確定損益と残存評価から分けて表示する。
 * @returns {void} 返り値はない。
 */
function renderLive(){const rows=D.live.セッション集計??[];if(!rows.length)return;const rec=D.live.record,policies=[];for(const [name,x] of Object.entries(D.selection.主選択??{})){for(const symbol of ['NK225','TOPIX']){const r=rows.find(r=>r.方式===x.採用?.方式&&r.銘柄===symbol);if(r)policies.push({...r,policy:'共通条件／'+name});}}for(const [symbol,all] of Object.entries(D.selection.銘柄別主選択??{})){for(const [name,x] of Object.entries(all)){const r=rows.find(r=>r.方式===x.採用?.方式&&r.銘柄===symbol);if(r)policies.push({...r,policy:'銘柄別／'+name});}}
 const cols=[['銘柄',r=>r.銘柄],['条件',r=>`<a href="#visual" data-live="${esc(r.方式)}" data-symbol="${r.銘柄}">${esc(r.方式)}</a>`],['追加清算価値／万円',r=>cash(r.追加清算価値円)],['費用倍／万円',r=>cash(r.費用倍追加清算価値円)],['上限枚数換算／万円',r=>cash(r.枚数上限換算追加円)],['新起源分／万円',r=>cash(r.新信号起源追加円)],['旧起源分／万円',r=>cash(r.旧起源追加円)],['区間内新規脚',r=>r.区間内新規脚数],['末尾残脚',r=>r.終了未返済数],['判定材料',r=>r.区間内新規脚数===0?(r.旧起源追加円!==0?'新規なし・旧建玉の評価継続':'新規なし・材料不足'):'新規あり']];
 $('live-content').innerHTML=`<p>対象は ${esc(rec.known_cutoff)} から ${esc(rec.cutoff)} 未満。条件を固定後、２銘柄×生板・１分足・５分足の６URLを一回だけ取得しました。</p><div class="notice">主指標は「00:02直前の全脚清算価値」から「取得末尾の全脚清算価値」への変化です。既知区間で作った建玉も継続し、旧建玉の損失や末尾の未返済評価を隠しません。取得前に生じた未読データの照合であり、実時間の前向き運用ではありません。</div>${table(policies,[['選択方針',r=>esc(r.policy)],...cols])}<details><summary>全固定候補の追加区間成績</summary>${table(rows,cols)}</details><details><summary>確定利益・損失・開始評価・終了評価の内訳</summary>${table(rows,[['条件',r=>esc(r.方式)],['銘柄',r=>r.銘柄],['区間確定利益／万円',r=>cash(r.区間内確定利益円)],['区間確定損失／万円',r=>yen(r.区間内確定損失円)],['区間確定収支／万円',r=>cash(r.区間内確定収支円)],['開始含み評価／万円',r=>cash(r.開始評価損益円)],['末尾含み評価／万円',r=>cash(r.終了評価損益円)],['追加清算価値／万円',r=>cash(r.追加清算価値円)]])}</details><p class="small muted">旧保存ファイルの最終行を境界にした補助評価も確認しました。最終約定時刻が古いまま届いた行による差は54セル中３セルのみ（＋１万円・＋１万円・−0.5万円）で、NK主候補−９万円は同じ。主表の00:02境界は凍結通りです。<a href="資料/現在照合_旧保存行境界の補足.csv">行境界の補足</a></p><p class="small muted">新規が０脚で評価変化も０なら、この区間で予測精度が確認できたことにはなりません。確定損益には00:02以前からの値動きも含む場合があるため、追加清算価値と別の数字です。</p><p><a href="資料/現在照合_セッション集計.csv">照合集計CSV</a> ／ <a href="資料/現在照合_凍結記録.json">条件とソースの凍結記録</a> ／ <a href="資料/現在照合_取得記録.json">６要求の取得記録</a></p>`;}
/**
 * 機能: 有望候補の幅感度と公平な方向対照を、選択後の診断として示す。
 * @returns {void} 返り値はない。
 */
function renderCandidateDiagnostics(){const id=D.selection.銘柄別主選択?.NK225?.['予測と注文の組合せ']?.採用?.方式;if(!id)return;const cfg=D.methods.find(m=>m.id===id),n=D.neighbors.filter(r=>r.元方式===id&&r.銘柄==='NK225'&&D.complete.includes(r.セッション)),grouped=new Map();for(const r of n){const key=r.変更項目+'|'+r.倍率;if(!grouped.has(key))grouped.set(key,{change:r.変更項目,old:r.元値,new:r.変更値,rows:[]});grouped.get(key).rows.push(r);}const rows=[...grouped.values()].map(g=>({...g,...sum(g.rows)})),labels={entry_offset:'新規の反発待ち幅',initial_stop_atr:'初期損切り幅',trail_atr:'追跡返済幅'};const hist=sum(D.rows.filter(r=>r.方式===id&&r.銘柄==='NK225'&&D.complete.includes(r.セッション))),coin=D.signal_coins.filter(r=>r.元方式===id&&r.銘柄==='NK225'),seeds=new Map();for(const r of coin)seeds.set(r.乱数種,(seeds.get(r.乱数種)||0)+r.収支円);const values=[...seeds.values()].sort((a,b)=>a-b),median=values.length?(values[(values.length-1)>>1]+values[values.length>>1])/2:0;
 const section=document.createElement('div');section.innerHTML=`<h3>NK225の候補 ${esc(id)}：入口と出口の幅のトレードオフ</h3><p>主設定の完全５セッションは ${cash(hist.収支円)}万円、費用倍 ${cash(hist.費用倍収支円)}万円。次の表は一つの数値だけを±25%変更した探索後の感度です。</p>${table(rows,[['変えた箇所',r=>esc(labels[r.change]??r.change)],['元のATR倍',r=>r.old],['変更後',r=>r.new],['収支／万円',r=>cash(r.収支円)],['費用倍／万円',r=>cash(r.費用倍収支円)],['確定脚数',r=>r.取引数]])}<p>利益の返却を減らすため追跡幅を狭めても、細かな揺れで返済が増え、収支が下がる場合があります。「幅を狭めるほど正しい」とは評価しません。</p>${values.length?`<p>同じ信号時刻で方向だけを64乱数に変えたNK225の５セッション収支は、最小 ${cash(values[0])}万円、中央値 ${cash(median)}万円、最大 ${cash(values.at(-1))}万円。実方向 ${cash(hist.収支円)}万円以上は${values.filter(v=>v>=hist.収支円).length}/${values.length}種でした。ただし候補を既知結果から選んだ後の診断なので、この比率を有意確率とは呼びません。</p>`:''}<p class="small muted">追加費用０・１・２・４呼値の表は、注文経路を基本２呼値の条件のまま固定して再採点したものです。条件判断まで各費用で作り直す再実行とは異なります。<a href="資料/追加費用0_1_2_4呼値.csv">費用感度CSV</a></p>`;$('diagnostic-content').prepend(section);
 const stats=Object.entries(D.statistics.時間順全政策??{}).map(([name,r])=>({name,...r}));if(stats.length){const block=document.createElement('div');block.innerHTML='<h3>経済的な候補と統計的な確認を分ける</h3>'+table(stats,[['選択方針',r=>esc(r.name)],['時間順セッション数',r=>r.セッション数],['未補正の符号反転比率',r=>r.未補正比率],['６政策のHolm補正',r=>r.全政策のHolm補正比率]])+'<p class="muted">時間順３ブロックでは両側比率は最小でも0.25です。セッション独立性・符号対称性も確認できず、これまでの研究の設計変更まで補正できません。<a href="資料/独立統計診断.md">独立統計診断</a></p>';$('diagnostic-content').append(block);}
 const prediction=D.predictions.filter(r=>r.系統===cfg?.signal&&r.銘柄==='NK225'&&D.complete.includes(r.セッション)),horizons=[5,15,30,60].map(h=>{const a=prediction.filter(r=>r.予測分===h),number=a.reduce((s,r)=>s+r.予測数,0),ok=a.reduce((s,r)=>s+r.方向正解,0),ng=a.reduce((s,r)=>s+r.方向不正解,0);return {h,number,rate:ok+ng?ok/(ok+ng):null,mean:number?a.reduce((s,r)=>s+(r.平均費用後円||0)*r.予測数,0)/number:null};});const box=document.createElement('details');box.innerHTML='<summary>長い時間幅ほど方向正答率が上がるか：NK候補の信号診断</summary><p>公開信号ごとの５・15・30・60分後を比べる事後診断です。期間が重なる予測は独立な取引ではありません。方向正答率は同値を除き、売買勝率とは別です。</p>'+table(horizons,[['予測時間／分',r=>r.h],['評価信号数',r=>r.number],['方向正答率',r=>r.rate==null?'—':(r.rate*100).toFixed(1)+'%'],['平均費用後／万円',r=>cash(r.mean)]])+'<p class="small muted">時間幅を長くすれば必ず有効になる、という前提は置いていません。この診断ラベルを入口の計算へ逆流させていません。</p>';$('diagnostic-content').append(box);}
/**
 * 機能: 表示する条件・銘柄・セッションの組を返す。
 * @returns {object} 選択値と対応データ。
 */
function selection(){const method=$('method').value,symbol=$('symbol').value,session=$('session').value;return {method,symbol,session,cfg:D.methods.find(m=>m.id===method),bars:D.candles[`${session}|${symbol}`]??[],trades:D.trades.filter(t=>t.method===method&&t.symbol===symbol&&t.session===session),curve:D.curves[`${method}|${session}|${symbol}`]??[]};}
/**
 * 機能: 選択した条件のルールと全脚明細を描画する。
 * @returns {void} 返り値はない。
 */
function refresh(){const s=selection();visibleTrades=s.trades;$('chart-rules').innerHTML=s.cfg?.rules.map(x=>`<p>${esc(x)}</p>`).join('')??'';const row=D.rows.filter(r=>r.方式===s.method&&r.セッション===s.session&&r.銘柄===s.symbol);$('session-summary').innerHTML=table(row,[['総枚数上限／銘柄',r=>r.設定最大枚数],...metricCols(),['上限枚数換算／万円',r=>cash(r.枚数上限換算収支円)]]);
 $('trade-table').innerHTML='<div class="scroll"><table><thead><tr>'+['脚','組','方向','条件作成','新規','新規価格','返済／評価','価格','確定収支／万円','未返済評価／万円','最大順行／万円','理由'].map(x=>`<th>${x}</th>`).join('')+'</tr></thead><tbody>'+s.trades.map((t,i)=>`<tr data-trade="${i}" class="${selected===i?'selected':''}"><td>${i+1}</td><td>${t.cycle==null?'—':t.cycle+1}</td><td>${t.side>0?'買':'売'}</td><td>${clock(t.condition)}</td><td>${clock(t.entry)}</td><td>${t.ep.toLocaleString()}</td><td>${clock(t.exit)}</td><td>${t.xp.toLocaleString()}</td><td>${t.closed?cash(t.net):'—'}</td><td>${t.closed?'—':cash(t.net)}</td><td>${yen(t.mfe)}</td><td>${esc(t.reason)}</td></tr>`).join('')+'</tbody></table></div>';
 $('method-table').innerHTML=table(D.rows.filter(r=>r.方式===s.method),[['セッション',r=>esc(sessionLabel(r.セッション))],['銘柄',r=>r.銘柄],...metricCols()]);draw(s);}
/**
 * 機能: 高解像度のキャンバス描画領域を初期化する。
 * @param {string} id - キャンバスID。
 * @returns {object} 文脈と寸法。
 */
function canvas(id){const el=$(id),r=el.getBoundingClientRect(),dpr=window.devicePixelRatio||1;el.width=r.width*dpr;el.height=r.height*dpr;const ctx=el.getContext('2d');ctx.scale(dpr,dpr);ctx.fillStyle='#0a1423';ctx.fillRect(0,0,r.width,r.height);ctx.font='12px "Yu Gothic UI",sans-serif';return {ctx,w:r.width,h:r.height};}
/**
 * 機能: 時間と値の範囲に沿って暗色の目盛を描く。
 * @param {object} c - 描画領域。
 * @param {number} lo - 開始秒。
 * @param {number} hi - 終了秒。
 * @param {number} bottom - 最小値。
 * @param {number} top - 最大値。
 * @param {boolean} cashAxis - 万円で表示するか。
 * @returns {object} 座標変換関数。
 */
function axes(c,lo,hi,bottom,top,cashAxis=false){const {ctx,w,h}=c,L=76,R=22,T=26,B=39,x=t=>L+(t-lo)/(hi-lo)*(w-L-R),y=v=>h-B-(v-bottom)/(top-bottom)*(h-T-B);ctx.strokeStyle='#253952';ctx.fillStyle='#aebed5';ctx.lineWidth=1;for(let k=0;k<=5;k++){const yy=T+k*(h-T-B)/5,v=top-k*(top-bottom)/5;ctx.beginPath();ctx.moveTo(L,yy);ctx.lineTo(w-R,yy);ctx.stroke();ctx.textAlign='right';ctx.fillText(cashAxis?(v/10000).toFixed(1):v.toLocaleString('ja-JP',{maximumFractionDigits:1}),L-9,yy+4);}for(let k=0;k<=6;k++){const t=lo+k*(hi-lo)/6,xx=x(t);ctx.beginPath();ctx.moveTo(xx,T);ctx.lineTo(xx,h-B);ctx.stroke();ctx.textAlign='center';ctx.fillText(clock(t).slice(0,5),xx,h-15);}if(cashAxis){ctx.textAlign='left';ctx.fillText('万円',12,14);}return {x,y,L,R,T,B};}
/**
 * 機能: ５分足、建玉線、エントリー・返済記号、資産曲線を描画する。
 * @param {object} s - 選択したデータ。
 * @returns {void} 返り値はない。
 */
function draw(s){points=[];let lo=s.bars[0]?.[0]??s.curve[0]?.[0],hi=Math.max(s.bars.at(-1)?.[0]+300||0,...s.trades.map(t=>t.exit||0),s.curve.at(-1)?.[0]||0);if(!lo||!hi){const c=canvas('chart');c.ctx.fillStyle='#b0c1d8';c.ctx.fillText('この範囲の描画データはありません。',30,50);canvas('equity');return;}if($('range').value==='current'&&s.session.includes('Night'))lo=Math.min(hi-300,Math.max(lo,D.known_cutoff));if($('range').value==='trade'&&s.trades[selected]){const t=s.trades[selected];lo=Math.max(lo,t.entry-1800);hi=Math.min(hi,t.exit+1800);}if(hi-lo<600)hi=lo+600;const bars=s.bars.filter(b=>b[0]+300>=lo&&b[0]<=hi),ts=s.trades.map((t,i)=>({...t,i})).filter(t=>t.exit>=lo&&t.entry<=hi),prices=bars.flatMap(b=>[b[2],b[3]]).concat(ts.flatMap(t=>[t.ep,t.xp]));if(!prices.length)return;let low=Math.min(...prices),high=Math.max(...prices),pad=Math.max((high-low)*.12, s.symbol==='NK225'?30:1.5);low-=pad;high+=pad;const c=canvas('chart'),{ctx,w,h}=c,a=axes(c,lo,hi,low,high),body=Math.max(1,Math.min(11,(w-98)*300/(hi-lo)*.63));
 if(s.session.includes('23_Night')&&D.known_cutoff>=lo&&D.known_cutoff<=hi){ctx.fillStyle='#9478e018';ctx.fillRect(a.x(D.known_cutoff),a.T,w-a.x(D.known_cutoff)-22,h-a.T-a.B);ctx.fillStyle='#c0aaf3';ctx.textAlign='right';ctx.fillText('00:02以降の追加区間',w-25,17);}
 for(const b of bars){const xx=a.x(b[0]+150),up=b[4]>=b[1];ctx.strokeStyle=ctx.fillStyle=up?'#51cca5':'#ee8294';ctx.beginPath();ctx.moveTo(xx,a.y(b[2]));ctx.lineTo(xx,a.y(b[3]));ctx.stroke();ctx.fillRect(xx-body/2,Math.min(a.y(b[1]),a.y(b[4])),body,Math.max(1,Math.abs(a.y(b[1])-a.y(b[4]))));}
 for(const t of ts){const focus=selected===t.i,alpha=selected>=0&&!focus ? .2 : .8;ctx.globalAlpha=alpha;ctx.strokeStyle=t.net>=0?'#67e2b2':'#ff9fa8';ctx.lineWidth=focus?2.5:1;ctx.setLineDash([5,4]);ctx.beginPath();ctx.moveTo(a.x(t.entry),a.y(t.ep));ctx.lineTo(a.x(t.exit),a.y(t.xp));ctx.stroke();ctx.setLineDash([]);const x=a.x(t.entry),y=a.y(t.ep),r=focus?8:6;ctx.fillStyle=t.side>0?'#58ddb0':'#ff8d9d';ctx.beginPath();ctx.moveTo(x,y+(t.side>0?-r:r));ctx.lineTo(x-r,y+(t.side>0?r:-r));ctx.lineTo(x+r,y+(t.side>0?r:-r));ctx.closePath();ctx.fill();points.push({x,y,trade:t});const xx=a.x(t.exit),yy=a.y(t.xp);ctx.strokeStyle=t.closed?'#ecf4ff':'#ffd386';ctx.lineWidth=2;ctx.beginPath();if(t.closed){ctx.moveTo(xx-5,yy-5);ctx.lineTo(xx+5,yy+5);ctx.moveTo(xx+5,yy-5);ctx.lineTo(xx-5,yy+5);}else{ctx.moveTo(xx,yy-7);ctx.lineTo(xx+7,yy);ctx.lineTo(xx,yy+7);ctx.lineTo(xx-7,yy);ctx.closePath();}ctx.stroke();points.push({x:xx,y:yy,trade:t});ctx.globalAlpha=1;}ctx.textAlign='left';ctx.fillStyle='#d5e5fa';ctx.fillText(`${s.symbol} ｜ ${s.session} ｜ ${s.method}`,80,17);
 const ec=canvas('equity'),curve=s.curve.filter(r=>r[0]>=lo&&r[0]<=hi);if(curve.length){const values=curve.flatMap(r=>[r[2],r[3]]).concat([0]);let mn=Math.min(...values),mx=Math.max(...values),p=Math.max((mx-mn)*.1,10000);const e=axes(ec,lo,hi,mn-p,mx+p,true);for(const [col,color] of [[2,'#58ddb0'],[3,'#ffb57f']]){ec.ctx.strokeStyle=color;ec.ctx.lineWidth=1.8;ec.ctx.beginPath();curve.forEach((r,i)=>i?ec.ctx.lineTo(e.x(r[0]),e.y(r[col])):ec.ctx.moveTo(e.x(r[0]),e.y(r[col])));ec.ctx.stroke();}}}
/**
 * 機能: 最寄りの売買マーカーの明細を表示する。
 * @param {MouseEvent} event - マウス移動。
 * @returns {void} 返り値はない。
 */
function tooltip(event){const r=$('chart').getBoundingClientRect(),x=event.clientX-r.left,y=event.clientY-r.top,p=points.reduce((best,p)=>Math.hypot(p.x-x,p.y-y)<Math.hypot((best?.x??-1e5)-x,(best?.y??-1e5)-y)?p:best,null),el=$('tooltip');if(!p||Math.hypot(p.x-x,p.y-y)>16){el.style.display='none';return;}const t=p.trade;el.innerHTML=`<b>脚${t.i+1} ${t.side>0?'買い':'売り'} ${t.cycle==null?'':`／組${t.cycle+1}`}</b><br>新規 ${clock(t.entry,true)}　${t.ep}<br>${t.closed?'返済':'評価'} ${clock(t.exit,true)}　${t.xp}<br>${t.closed?'確定収支':'未返済評価'} ${cash(t.net)}万円<br>ATR ${t.atr.toFixed(2)}／最大順行 ${yen(t.mfe)}万円<br>${esc(t.reason)}`;el.style.display='block';el.style.left=Math.min(x+14,r.width-360)+'px';el.style.top=Math.min(y+12,r.height-160)+'px';}
// ----------------------------------------
renderChapters();renderResearch();renderSymbolChoices();renderLive();renderCandidateDiagnostics();$('method').innerHTML=D.methods.map(m=>`<option value="${esc(m.id)}">${esc(m.id)}｜${esc(m.label)}</option>`).join('');$('session').innerHTML=D.sessions.map(s=>`<option value="${esc(s)}">${esc(sessionLabel(s))}</option>`).join('');const primary=D.selection.銘柄別主選択?.NK225?.['予測と注文の組合せ']?.採用?.方式??D.selection.主選択?.['予測と注文の組合せ']?.採用?.方式;if(primary)$('method').value=primary;$('session').value='2026-09-22_Night';
for(const id of ['method','symbol','session'])$(id).addEventListener('change',()=>{selected=-1;refresh();});$('range').addEventListener('change',refresh);$('reset').addEventListener('click',()=>{selected=-1;refresh();});$('trade-table').addEventListener('click',e=>{const tr=e.target.closest('[data-trade]');if(tr){selected=Number(tr.dataset.trade);refresh();}});document.addEventListener('click',e=>{const live=e.target.closest('[data-live]');if(live){$('method').value=live.dataset.live;$('symbol').value=live.dataset.symbol;$('session').value=D.live.display_session;$('range').value='current';selected=-1;refresh();return;}const a=e.target.closest('[data-select]');if(a){$('method').value=a.dataset.select;selected=-1;refresh();}});$('chart').addEventListener('mousemove',tooltip);$('chart').addEventListener('mouseleave',()=>{$('tooltip').style.display='none';});window.addEventListener('resize',()=>draw(selection()));refresh();
</script></body></html>'''


if __name__ == '__main__':
    main()
