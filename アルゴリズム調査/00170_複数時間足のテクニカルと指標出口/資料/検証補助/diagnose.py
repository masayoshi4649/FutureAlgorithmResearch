"""選定済み候補の実約定から損失箇所と同初回入口の出口差を記録する。"""
import collections
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path


def stamp(ns):
    """
    機能: 原板価格時計を日本時間へ変換。引数:ns(int)。返り値:str。
    """
    return datetime.fromtimestamp(ns/1e9,timezone(timedelta(hours=9))).isoformat(timespec='seconds')


def money(x):
    """
    機能: 金額表示。引数:x(float)。返り値:str。
    """
    return f'{x:+,.0f}'


def main():
    """
    機能: 全損失を分類し大きい具体例を保存。引数:なし。返り値:None。
    """
    here=Path(__file__).resolve().parent;study=here.parents[1]/'アルゴリズム調査/00170_複数時間足のテクニカルと指標出口'
    source=json.loads((here/'details-summary.json').read_text(encoding='utf-8'))
    original=json.loads((here/'summary.json').read_text(encoding='utf-8'))
    fixed=json.loads((study/'選定固定.json').read_text(encoding='utf-8'))['selection']
    rows={(r['symbol'],r['session'],r['config_id']):r for r in source['results']}
    originalrows={(r['symbol'],r['session'],r['config_id']):r for r in original['results']}
    # ----------------------------------------
    # 詳細の再生が初回集計と一致しなければ原因説明を出しません。
    for key,r in rows.items():
        o=originalrows[key]
        for field in ['realized_yen','gross_profit_yen','gross_loss_yen','unrealized_yen','entry_count','fills','max_drawdown_yen','positive_then_negative']:
            assert r[field]==o[field],(key,field)
    lines=['# 選定候補の損失経路と出口の照合','','日経mini10枚・TOPIXmini10枚、手数料0。時刻は日本時間の価格時計。原行はbook.jsonlの物理行番号。理由は同時成立時の優先理由で、他の条件が成立しなかった証明ではない。','']
    evidence=[]
    for g in fixed['selected']:
        group=[r for r in source['results'] if r['symbol']==g['symbol'] and r['config_id']==g['method_id'] and r['session'].endswith('_'+g['kind'])]
        selected_episodes=[ep for r in group for ep in r.get('episode_details',[])]
        by_reason=collections.defaultdict(lambda:{'count':0,'net':0,'positive_then_negative':0})
        for r in group:
            trades=[json.loads(s) for s in (study/'data'/f"{r['symbol']}_{r['session']}_{r['config_id']}.trades.jsonl").read_text(encoding='utf-8').splitlines()]
            for ep in r.get('episode_details',[]):
                close=next(t for t in trades if t['source_line']==ep['exit_line'] and t['type'] in ['LongR','ShortR'])
                reason=close['reason'];stat=by_reason[reason];stat['count']+=1;stat['net']+=ep['profit_yen'];stat['positive_then_negative']+=int(ep['positive_then_negative'])
        lines.extend([f"## {g['algorithm_id']} / {g['kind']}",'',f"全決済{len(selected_episodes)}件、正益を一度見た後に赤字返済{sum(ep['ever_positive'] and ep['profit_yen']<0 for ep in selected_episodes)}件。途中の正益消失は{sum(ep['positive_then_negative'] for ep in selected_episodes)}件（最終赤字とは別）。",'', '| 返済理由 | 件数 | 収支 | 途中の正益消失件数 |','|---|---:|---:|---:|'])
        for reason,stat in sorted(by_reason.items()):lines.append(f"| {reason} | {stat['count']} | {money(stat['net'])} | {stat['positive_then_negative']} |")
        lines.extend(['','### 赤字上位3セッションの具体例','','| 場・収支 | 新規→返済時刻 | 向き | 最高含み→確定 | 新規/返済原行 | 返済理由 |','|---|---|---|---:|---|---|'])
        for r in sorted([x for x in group if x['realized_yen']<0],key=lambda x:x['realized_yen'])[:3]:
            trades=[json.loads(s) for s in (study/'data'/f"{r['symbol']}_{r['session']}_{r['config_id']}.trades.jsonl").read_text(encoding='utf-8').splitlines()]
            for ep in sorted(r.get('episode_details',[]),key=lambda x:x['profit_yen'])[:3]:
                close=next(t for t in trades if t['source_line']==ep['exit_line'] and t['type'] in ['LongR','ShortR'])
                entry=next(t for t in trades if t['source_line']==ep['entry_line'] and t['type'] in ['LongN','ShortN'])
                lines.append(f"| {r['session']} / {money(r['realized_yen'])} | {stamp(ep['entry_ns'])[11:19]}→{stamp(ep['exit_ns'])[11:19]} | {'買い' if ep['side']>0 else '売り'} | {money(ep['max_unrealized_yen'])}→{money(ep['profit_yen'])} | {ep['entry_line']}/{ep['exit_line']} | {close['reason']} |")
                evidence.append({'symbol':r['symbol'],'session':r['session'],'config_id':r['config_id'],'method_id':r['method_id'],'entry':entry,'close':close,'episode':ep,'resource':r['symbol']+'/'+r['session']+'/'+r['config_id']})
        # ----------------------------------------
        # 最初の約定が一致するものだけは、同一入口での出口差として扱えます。
        lines.extend(['','### 初回入口を厳密に揃えた対照','','各場の最初の1取引だけを比較した損益合計。場全体の全取引合計ではない。','','| 出口 | 同初回件数 | 選定初回収支 | 対照初回収支 | 選定−対照 |','|---|---:|---:|---:|---:|'])
        for cid in dict.fromkeys([g['control_id'],g['indicator_control_id']]):
            if cid==g['method_id']:continue
            a=[];b=[]
            for r in group:
                other=rows[(r['symbol'],r['session'],cid)]
                if not r.get('episode_details') or not other.get('episode_details'):continue
                x=r['episode_details'][0];y=other['episode_details'][0]
                if (x['entry_ns'],x['entry_line'],x['side'])==(y['entry_ns'],y['entry_line'],y['side']):a.append(x['profit_yen']);b.append(y['profit_yen'])
            lines.append(f"| {cid} | {len(a)} | {money(sum(a))} | {money(sum(b))} | {money(sum(a)-sum(b))} |")
        lines.append('')
    lines.extend(['## 解釈の限界','','「最大含み益で返済すればよかった」は未来の頂点の利用なので改善案として採用しない。Fの利益床は事前固定済みの比較。I/Tは同じ入口式だが、保有時間が違うため2回目以後の入口時刻まで同一とは限らない。上表はその混同を避け初回だけ揃えた。','', '終端確認は予定終了の6分以内に有効価格がある意味で、全時間の連続観測を保証しない。最大の価格時計間隔・交差気配等は結果監査を参照。利益床も次原行の気配で約定するため最低利益の保証ではない。',''])
    (study/'損失経路の確認.md').write_text('\n'.join(lines),encoding='utf-8')
    (here/'loss-evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'detailed_rows_checked':len(rows),'loss_examples':len(evidence)},ensure_ascii=False))


if __name__=='__main__':main()
