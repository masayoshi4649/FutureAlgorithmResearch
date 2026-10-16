"""既存の両商品診断を六口座・十八取引の表示資料へ統一する。売買を再生しない。"""

from collections import defaultdict
import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
REASONS = {1: '初期損切り', 2: '幅トレーリング', 3: '30分期限', 4: '場内返済'}


def load(path: Path) -> dict:
    """機能: 現作業で完成済みの診断資料を読取専用で開く。

    引数: path(Path)。返り値: 内容(dict)。
    """
    return json.loads(path.read_text(encoding='utf8'))


def digest(path: Path) -> str:
    """機能: 説明資料の出典を再照合できるよう内容指紋を作る。

    引数: path(Path)。返り値: SHA256(str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stage(time=None, price=None, index=None, seq=None, bid=None, ask=None, bid_qty=None, ask_qty=None) -> dict:
    """機能: 判断・参照・約定の時点を同じ形へ揃える。

    引数: time(str|None)、price/bid/ask/bid_qty/ask_qty(float|None)、index/seq(int|None)。
    返り値: 一時点(dict)。seqは原本の0始まり位置、表示行は明示的に1を加える。
    """
    return dict(時刻=time, 価格=price, 準備行=index, 原本seq=seq, 原本表示行=seq+1 if seq is not None else None,
                bid=bid, ask=ask, 買数量=bid_qty, 売数量=ask_qty)


def top_stage(p: dict | None, price=None) -> dict:
    """機能: TOPIX診断の原本点を統一する。

    引数: p(dict|None)、price(float|None)。返り値: 時点(dict)。資料にない値はnull。
    """
    p = p or {}
    return stage(p.get('最終約定時計'), price, p.get('抽出行'), p.get('原本0始まり行'),
                 p.get('bid'), p.get('ask'), p.get('bid_qty'), p.get('ask_qty'))


def window(ret=None, bid=None, ask=None, actual=None) -> dict:
    """機能: 価格窓の表示単位を統一する。

    引数: ret/bid/ask/actual(float|None)。返り値: 価格進行窓(dict)。
    """
    return dict(中値変化bp=ret, 買気配変化呼値=bid, 売気配変化呼値=ask, 実観測秒=actual)


def flow(source: dict, sufficient=None, support=None, reversed_=None) -> dict:
    """機能: J2追加条件のOFIを旧入口の価格進行と混ぜず保持する。

    引数: source(dict)、sufficient/support/reversed_(bool|None)。返り値: 表示用OFI(dict)。
    """
    return dict(比=source.get('ofi_ratio'), 和=source.get('ofi_sum'), 絶対和=source.get('ofi_abs_sum'),
                非ゼロ数=source.get('nonzero_ofi_count'), 実観測秒=source.get('actual_seconds'),
                観測十分=sufficient, 同方向支持=support, 明確な逆向き=reversed_,
                観測有効=source.get('valid'), 元データ=source)


def top_market(old: dict, gate: dict, grid_time: str) -> dict:
    """機能: TOPIX取引の二市場根拠を旧入口と追加J2に分けて整える。

    引数: old/gate(dict)、grid_time(str)。返り値: 一市場の判断根拠(dict)。
    同一準備行と明示できる時だけ、旧入口点の時計と数量をJ2点へ共有する。
    """
    current = gate['現在']; w = gate['進行300秒']; f = gate['フロー15秒']
    known = next((old[name] for name in ('現在', '過去15秒', '過去300秒') if old[name]['抽出行'] == current['index']), None)
    gate_point = top_stage(known)
    gate_point.update(準備行=current['index'], bid=current.get('bid'), ask=current.get('ask'))
    return dict(旧入口=dict(参照=top_stage(old['現在']), 過去15秒参照=top_stage(old['過去15秒']),
                            過去300秒参照=top_stage(old['過去300秒']),
                            窓15=window(old.get('進行15bp'), old.get('bid進行15呼値'), old.get('ask進行15呼値'), old.get('実時間15秒')),
                            窓300=window(old.get('進行300bp'), actual=old.get('実時間300秒')),
                            OFI15=dict(比=old.get('OFI15比'), 和=old.get('OFI15和'), 絶対和=old.get('OFI15絶対和'), 非ゼロ数=old.get('非ゼロOFI数'))),
                追加J2=dict(判断格子時刻=grid_time, 参照=gate_point,
                            窓15=window(f.get('mid_change_bp'), f.get('bid_change_ticks'), f.get('ask_change_ticks'), f.get('actual_seconds')),
                            窓300=window(w.get('ret_bp'), w.get('bid_change_ticks'), w.get('ask_change_ticks'), w.get('actual_seconds')),
                            OFI15=flow(f, gate.get('フロー観測十分'), gate.get('同方向OFI支持'), gate.get('明確な逆OFI')),
                            最良数量偏り=current.get('best_imbalance'), 距離加重数量偏り=current.get('depth_imbalance'),
                            直進率300秒=w.get('efficiency'), 直前レンジ180秒=gate.get('レンジ180秒')))


def top_cases(detail: dict, summary: dict) -> list[dict]:
    """機能: TOPIXの指定三場全八取引を変換する。

    引数: detail/summary(dict)。返り値: 三ケース(list[dict])。
    """
    comments = {(r['セッション'], r['組']): r['解釈'] for r in summary['表示行']}
    cases = []
    for account in detail['セッション']:
        session = account['セッション']; trades = []
        for t in account['取引']:
            side = 1 if t['方向'] == '買い' else -1
            q = 'ask' if side == 1 else 'bid'
            pnl = t['損益']; after = t['判断後の診断']; cid = t['組']
            marks = []
            for name, value in after['後に観測された状態'].items():
                marks.append(dict(条件名=name, 時刻=value.get('判断予定時計') if value else None,
                                  新規後秒=value.get('新規から秒') if value else None,
                                  同行清算評価円=value.get('同行清算評価円') if value else None,
                                  元データ=value))
            trades.append(dict(ID=f'TOPIX|{session}|{cid+1}', 組番号=cid+1, 元組番号=cid, 元組番号の起点=0,
                商品='TOPIX', セッション=session, 方向=t['方向'], 枚数=t['枚数'],
                判断格子時刻=t['旧入口判断予定時刻'], J2追加判断格子時刻=t['追加フィルター判断予定時刻'],
                時点=dict(発注判断=top_stage(t['入口判断'], t['入口判断'][q]), 新規約定=top_stage(t['入口約定'], t['入口価格']),
                          返済判断=top_stage(t['返済判断'], t['返済判断']['bid' if side == 1 else 'ask']), 返済約定=top_stage(t['返済約定'], t['返済価格'])),
                返済理由=t['返済理由'], 保有秒=t['保有秒'], 固定幅pt=t['固定トレール幅pt'],
                損益=dict(収支円=pnl['手数料後円'], 価格差円=pnl['価格損益円'], 中値差円=pnl['中値変動分円'],
                          気配差円=pnl['売買気配差分円'], 手数料円=pnl['手数料円']),
                二市場={s: top_market(v, t['判断時に既知の追加フィルター'][s], t['追加フィルター判断予定時刻']) for s, v in t['判断時に既知の旧入口根拠'].items()},
                事後=dict(MFE円=after['最大順行清算評価円'], MAE円=after['最大逆行清算評価円'],
                          MFE時刻=after['最大順行時点']['最終約定時計'], MAE時刻=after['最大逆行時点']['最終約定時計'],
                          初回利益消失時刻=after.get('初めて費用後黒字から赤字へ戻った時刻'), 最初の状態変化=marks),
                コメント=comments[(session, cid)], 出典=f'topix/TOPIX上位3赤字場の診断.json → {session} → 組{cid}'))
        cases.append(dict(ID='TOPIX|'+session, 商品='TOPIX', 商品表記='TOPIXミニ10枚', セッション=session,
                          会計=dict(利益円=account['利益円'], 損失円=account['損失円'], 収支円=account['収支円'],
                                    中値差円=account['価格変動分円'], 気配差円=account['気配差分円'], 手数料円=account['手数料円']), 取引=trades))
    return cases


def nk_snapshot(rows: dict, key: str, index=None, seq=None) -> dict | None:
    """機能: 保存済みNK診断の生板抜粋から明示された位置だけを参照する。

    引数: rows(dict)、key(str)、index/seq(int|None)。返り値: 原本行又は欠測(dict|None)。
    """
    values = rows.get(key, [])
    return next((r for r in values if (seq is not None and r.get('原本seq') == seq)
                 or (index is not None and r.get('準備行') == index)), None)


def nk_stage(raw: dict | None, time=None, price=None, index=None, seq=None) -> dict:
    """機能: NK原本抜粋を時点へ変換し、抜粋にない気配を作らない。

    引数: raw(dict|None)、time(str|None)、price(float|None)、index/seq(int|None)。返り値: 時点(dict)。
    """
    if raw is None:
        return stage(time, price, index, seq)
    buy = raw.get('買十段価格数量', [[None, None]])[0]
    sell = raw.get('売十段価格数量', [[None, None]])[0]
    return stage(time or raw.get('CurrentPriceTime'), price, index if index is not None else raw.get('準備行'),
                 seq if seq is not None else raw.get('原本seq'), buy[0], sell[0], buy[1], sell[1])


def nk_market(v: dict, raw_rows: dict, key: str, grid_time: str) -> dict:
    """機能: NK取引の二市場根拠を、旧入口とJ2追加で分けて整える。

    引数: v/raw_rows(dict)、key/grid_time(str)。返り値: 一市場の判断根拠(dict)。
    """
    current = v['J2判断格子の現在']; f = v['J2判断格子の15秒OFI']; w = v['300秒価格窓']
    source = v['原本小窓']['参照原本seq']
    old = stage(v.get('旧入口参照JST'), index=v.get('旧入口参照行'), seq=source,
                bid=v.get('旧入口bid'), ask=v.get('旧入口ask'), bid_qty=v.get('旧入口買数量'), ask_qty=v.get('旧入口売数量'))
    raw = nk_snapshot(raw_rows, key, index=v['J2追加条件参照行'])
    gate = nk_stage(raw, v.get('J2参照JST'), index=v['J2追加条件参照行'])
    gate.update(bid=current.get('bid'), ask=current.get('ask'))
    return dict(旧入口=dict(参照=old,
                            過去15秒参照=stage(v.get('旧15秒参照JST'), index=v.get('旧15秒参照行')),
                            過去300秒参照=stage(v.get('旧300秒参照JST'), index=v.get('旧300秒参照行')),
                            窓15=window(v.get('15秒中値変化bp'), v.get('15秒買気配変化呼値'), v.get('15秒売気配変化呼値')),
                            窓300=window(v.get('300秒中値変化bp'), v.get('300秒買気配変化呼値'), v.get('300秒売気配変化呼値')),
                            OFI15=dict(比=None, 和=None, 絶対和=None, 非ゼロ数=None)),
                追加J2=dict(判断格子時刻=grid_time, 参照=gate,
                            窓15=window(f.get('mid_change_bp'), f.get('bid_change_ticks'), f.get('ask_change_ticks'), f.get('actual_seconds')),
                            窓300=window(w.get('ret_bp'), w.get('bid_change_ticks'), w.get('ask_change_ticks'), w.get('actual_seconds')),
                            OFI15=flow(f, v.get('OFIが観測十分'), v.get('OFIが入口方向を支持0_1以上'), v.get('OFIが明確に逆向き0_1以上')),
                            最良数量偏り=current.get('best_imbalance'), 距離加重数量偏り=current.get('depth_imbalance'),
                            直進率300秒=w.get('efficiency'), 直前レンジ180秒=v.get('180秒直前レンジ')))


def nk_cases(detail: dict, summary: dict) -> list[dict]:
    """機能: 日経指定三場全十取引を変換し、別場の黒字対照を混入しない。

    引数: detail/summary(dict)。返り値: 三ケース(list[dict])。
    """
    grouped = defaultdict(list)
    raw = detail['生板小窓']
    explanations = {
        ('2026-09-29_Night', 3): summary['入口の事前警告'][0],
        ('2026-10-09_Day', 2): summary['入口の事前警告'][1],
        ('2026-09-29_Night', 4): summary['入口の事前警告'][2],
    }
    for t in detail['全組診断']:
        if t['役割'] != '指定赤字場の全組':
            continue
        session = t['セッション']; number = t['組番号']; pnl = t['利益損失分解']; after = t['事後経路']
        r = nk_snapshot(raw, session+'|NK225', seq=t['入口判断原本seq'])
        info = t['入口時の可観測情報']
        support = all(v['OFIが入口方向を支持0_1以上'] for v in info.values())
        commentary = explanations.get((session, number))
        note = ' '.join(commentary[k] for k in ('観測', '意味', '事後')) if commentary else (
            ('両15秒OFIの同方向支持があった。' if support else '両15秒OFIの同方向支持は揃っていなかった。')
            +f"費用後最大清算評価は{after['費用後最大清算評価']:+,.0f}円、最終収支は{pnl['収支']:+,.0f}円。"
            +'入口時点の支持と、その後の持続は別に評価する。')
        events = []
        for name, value in after['共同判断の変化'].items():
            if isinstance(value, (dict, type(None))):
                events.append(dict(条件名=name, 時刻=value.get('時刻') if value else None,
                                   新規後秒=value.get('新規後秒') if value else None,
                                   同行清算評価円=value.get('その判断時の費用後清算評価') if value else None, 元データ=value))
        grouped[session].append(dict(ID=f'NK225|{session}|{number}', 組番号=number, 元組番号=number, 元組番号の起点=1,
            商品='NK225', セッション=session, 方向=t['方向'], 枚数=t['枚数'],
            判断格子時刻=t['判断格子JST'], J2追加判断格子時刻=t['J2追加判断格子JST'],
            時点=dict(発注判断=nk_stage(r, t['発注判断JST'], t['発注時追いかけ'].get('自発注判断価格'), t['入口判断準備行'], t['入口判断原本seq']),
                      新規約定=stage(t['新規約定JST'], t['新規価格']), 返済判断=stage(t['返済判断JST']), 返済約定=stage(t['返済約定JST'], t['返済価格'])),
            返済理由=REASONS.get(t['返済理由番号']), 保有秒=t['保有秒'], 固定幅pt=None,
            損益=dict(収支円=pnl['収支'], 価格差円=pnl['売買価格差損益'], 中値差円=pnl['同じ約定時刻の中値差損益'],
                      気配差円=pnl['気配差負担'], 手数料円=pnl['料金']),
            二市場={s: nk_market(v, raw, session+'|'+s, t['J2追加判断格子JST']) for s, v in info.items()},
            事後=dict(MFE円=after['費用後最大清算評価'], MAE円=after['費用後最小清算評価'],
                      MFE時刻=after.get('最大順行JST'), MAE時刻=after.get('最大逆行JST'),
                      初回利益消失時刻=(after.get('初回含み益消失') or {}).get('時刻'), 最初の状態変化=events),
            コメント=note, 出典=f'nk225/赤字三場の全組と入口根拠.json → {session} → 組{number}'))
    cases = []
    for session, account in detail['三場会計'].items():
        trades = grouped[session]
        cases.append(dict(ID='NK225|'+session, 商品='NK225', 商品表記='日経225マイクロ20枚', セッション=session,
                          会計=dict(利益円=sum(max(t['損益']['収支円'], 0) for t in trades),
                                    損失円=sum(max(-t['損益']['収支円'], 0) for t in trades), 収支円=account['収支'],
                                    中値差円=account['同じ約定時刻の中値差損益'], 気配差円=account['気配差負担'], 手数料円=account['料金']), 取引=trades))
    return cases


def main() -> None:
    """機能: 全六口座・十八取引を一つのJSONへ保存し、元会計を照合する。

    引数: なし。返り値: なし(None)。不足値はnullで残し、売買・特徴量を再計算しない。
    """
    files = [WORK/'topix/TOPIX上位3赤字場の診断.json', WORK/'topix/TOPIX根本原因と予防案.json',
             WORK/'nk225/赤字三場の全組と入口根拠.json', WORK/'nk225/NK赤字三場の原因と反証.json']
    values = [load(p) for p in files]
    cases = top_cases(*values[:2])+nk_cases(*values[2:])
    flat = [t for case in cases for t in case['取引']]
    assert len(cases) == 6 and len(flat) == 18 and len({t['ID'] for t in flat}) == 18
    for case in cases:
        c = case['会計']
        assert sum(t['損益']['収支円'] for t in case['取引']) == c['収支円']
        assert c['利益円']-c['損失円'] == c['収支円'] == c['中値差円']-c['気配差円']-c['手数料円']
        for t in case['取引']:
            p = t['損益']
            assert p['収支円'] == p['価格差円']-p['手数料円'] == p['中値差円']-p['気配差円']-p['手数料円']
            assert set(t['二市場']) == {'TOPIX', 'NK225'}
            for m in t['二市場'].values():
                assert m['旧入口']['参照']['時刻'] < t['判断格子時刻']
        worst = min(case['取引'], key=lambda t: t['損益']['収支円'])
        case['代表大負けID'] = worst['ID']
        case['代表大負けコメント'] = worst['コメント']
    output = dict(基準='J2_F0_B0_H0_R0', ケース数=len(cases), 取引数=len(flat),
        仕様=dict(時刻='日本時間。最終約定の代理時計で、実受信時刻ではない。同時計の別原本行は順序で区別する。',
                  判断根拠='二市場.旧入口は15秒格子に由来する採用根拠。二市場.追加J2は5秒格子の追加フィルター。値を相互補完しない。',
                  旧入口の条件='両300秒が同方向3bp以上、自市場の15秒bid/askが各1呼値以上順行、相手の15秒中値が逆行していないこと。旧入口OFI欄は診断値で、この基本入口には使われていない。',
                  J2の追加条件='観測十分な明確な逆OFIを除外し、両300秒進行の弱い側が強い側の1/4以上。現行J2で両OFIの積極的支持は必須ではない。',
                  未収録='源JSONにない価格・数量・時刻・旧OFI等はnull。0とは違う。生板抜粋に明示された準備行又は原本seqが一致する値だけ共有する。',
                  行番号='準備行と原本seqは0始まり。原本表示行と組番号は1始まり。元の組番号と起点も保存。',
                  損益='中値差円−気配差円−手数料円＝収支円。利益/損失は費用後の正負取引を集計した金額。',
                  事後='MFE/MAE、最初の状態変化、コメントの結果部分は事後説明。新条件の約定収支ではなく、入口で知られていたことにしない。',
                  範囲='赤字上位3場ずつの全取引。NK別場の6勝ち対照は6ケースの会計へ含めない。'),
        ケース=cases, 全取引=flat, 出典SHA256={str(p.relative_to(ROOT)): digest(p) for p in files},
        変換器SHA256=digest(Path(__file__)), 検査=dict(会計6件一致=True, 全18件分解一致=True, 旧入口参照は判断より前=True),
        新戦略再生=0, API取得=0, 元診断の変更=False)
    HERE.mkdir(exist_ok=True)
    (HERE/'6ケース.json').write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')
    print(json.dumps(dict(ケース数=len(cases), 取引数=len(flat), 会計一致=True,
                         ケース=[dict(ID=c['ID'], 件数=len(c['取引']), 収支=c['会計']['収支円']) for c in cases]), ensure_ascii=False))


if __name__ == '__main__':
    main()
