"""保存済み検証結果を統一会計の説明・損益HTMLへまとめる。"""

from __future__ import annotations

import csv
from datetime import date, timedelta
import gzip
import html
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = ROOT / 'アルゴリズム調査/00048_E01連敗原因と再参加アルゴリズム'
TITLE = '連敗原因と新手法の検証.html'
SYMBOLS = ('TOPIX', 'NK225')


def read(path: Path) -> object:
    """機能: UTF-8 JSONと圧縮JSONを読む。

    引数: path(Path)。返り値: 保存内容(object)。
    """
    raw = path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix == '.gz' else raw)


def save(path: Path, value: object) -> None:
    """機能: 非有限値を許さず説明用JSONを保存する。

    引数: path(Path)、value(object)。返り値: なし(None)。
    """
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')


def normalize(row: dict) -> dict:
    """機能: 各研究の場別会計を共通名へ変換し、収支を照合する。

    引数: row(dict)。返り値: 共通会計(dict)。
    """
    result = dict(session=row['session'], symbol=row['symbol'])
    for target, names in {'profit': ('gross_profit_yen', 'profit'), 'loss': ('gross_loss_yen', 'loss'),
                          'net': ('net_yen', 'net'), 'win_qty': ('profit_units', 'win_qty'),
                          'loss_qty': ('loss_units', 'loss_qty'), 'flat_qty': ('zero_units', 'flat_qty')}.items():
        result[target] = int(round(next(row[n] for n in names if n in row)))
    assert result['profit'] - result['loss'] == result['net']
    return result


def total(rows: list[dict]) -> dict:
    """機能: 銘柄内で利益・損失・枚数・勝ち場数を集計する。

    引数: rows(list[dict])。返り値: 集計(dict)。
    """
    result = {k: sum(r[k] for r in rows) for k in ('profit', 'loss', 'net', 'win_qty', 'loss_qty', 'flat_qty')}
    result.update(sessions=len(rows), wins=sum(r['net'] > 0 for r in rows),
                  active=sum(r['win_qty'] + r['loss_qty'] + r['flat_qty'] > 0 for r in rows))
    result['pf'] = result['profit'] / result['loss'] if result['loss'] else None
    result['payoff'] = ((result['profit'] / result['win_qty']) / (result['loss'] / result['loss_qty'])
                        if result['win_qty'] and result['loss_qty'] and result['loss'] else None)
    result['without_best'] = result['net'] - max((r['net'] for r in rows), default=0)
    return result


def methods() -> list[dict]:
    """機能: 事前選抜代表・基準・後付参考を明示して場別会計を集める。

    引数: なし。返り値: 掲載手法(list[dict])。
    """
    overlays = read(HERE / 'overlay/選択結果.json')['候補']
    combined = read(HERE / 'combined/結果.json')
    selected = combined['選択']['id']
    combination = next(r for r in combined['候補'] if r['spec']['id'] == selected)
    descriptions = [
        ('E01', '従来E01', '比較基準', '指定価格',
         '両市場の保持方向を照合し、追跡した価格から0.25ATR戻ったところで入る。',
         '順行後に両市場・公開中値の短期変化が悪化したら部分減量。損切り後も比較用の仮想保有が終わるまで次の新規を待つ。',
         '逆行0.75ATRで損切り。利益1.5ATRから追跡し、3ATR到達後は幅0.75ATRへ短縮。場内返済。',
         '直近の連敗は残る。今回も全23場の基準として使用。', read(HERE / 'clock_search/sessions/K00.json.gz')),
        ('O03', 'E01＋2連敗後45分休止', '先頭10場で選抜', '指定価格',
         'E01と同じ。実際に採用した組が2連敗したら、新規を45分休む。',
         'E01の仮想口座を並行運転し、見送り中も次の準備時計を更新する。45分経過だけでは再入を保証しない。',
         '採用した組の出口はE01と同じ。含み損だけで連敗とは判定しない。',
         'TOPIXの損失縮小候補。NKは悪化し、共通改善の証拠はない。', next(r['sessions'] for r in overlays if r['spec']['id'] == 'O03')),
        ('R04_W30_C0_X2', '低効率の往復を平均回帰で取る', '全23場を見た後の参考', '次観測価格',
         '直前30本の効率比≤0.20、EMA30から0.8ATR以上離れ、直近3本が平均へ0.1ATR超戻る。相手の強い逆向きトレンドでは入らない。',
         '入口ATRを固定。平均まで0.25ATR以上の余地を判断時に確認。15分で0.5ATRも伸びなければ撤退。',
         '損切り0.9ATR。平均回帰目標又は利益追跡で返済。1ATR順行後の追跡幅1.5ATRを30分につき1ATR縮め、最小0.5ATR。最長120分。',
         '両市場黒字だが取引が少ない。先頭10場の活動条件未達で事前選抜されなかったため、今後の固定観察用。', read(HERE / 'search/sessions/R04_W30_C0_X2.json')),
        ('K20', '損切り時計を揃えて再参加', '先頭10場で選抜', '指定価格',
         'E01の通常仮想口座も0.75ATRで損切りし、終了15分後から次の入口を準備する。',
         '入口の時刻が変わり、再試行数も変わる。実口座の途中減量はE01と同じ。',
         '実口座の出口はE01と同じ。', '回復への再参加には成功したが、全体成績は大きく悪化。採用しない。', read(HERE / 'clock_search/sessions/K20.json.gz')),
        (selected, '再参加＋累積損失で停止', '先頭10場で選抜', '指定価格',
         '通常仮想口座も0.75ATRで損切りし、終了30分後から準備。実確定収支が累積−2R以下なら場内の新規を止める。',
         'Rは各組の初回枚数×入口ATRで正規化した損益。現在保有の返済は継続する。',
         '実口座の出口はE01と同じ。', '連敗休止との組合せでも直近4場を改善できなかった。', combination['sessions']),
        ('A04_D000_T30', '同じ価格帯での再失敗を避ける', '先頭10場で選抜', '指定価格',
         'E01の休止を15分とし、負けた組の終了から30分は同方向の新規を制限する。',
         '買いなら前の失敗した入口以上、売りなら以下へ発注元価格が進むまで再参加しない。反対方向は別管理。',
         '採用組の出口はE01と同じ。', '先頭10場では改善したが、その後で崩れた。採用しない。', read(HERE / 'rearm/sessions/A04_D000_T30.json')),
        ('R02_W15_C1_X1', '両市場方向＋平均線付近で追従', '独立96条件の先頭10場1位', '次観測価格',
         '両市場の直近15本で方向を確認し、平均線から離れ過ぎていない入口に絞る。',
         '公開済みの足だけで更新。入口ATRを固定して保有管理する。',
         '固定損切り、時間短縮の利益追跡、不発撤退。条件表に全閾値を保存。', '後半9場・全23場とも両市場赤字。採用しない。', read(HERE / 'search/sessions/R02_W15_C1_X1.json')),
        ('O01_P025_C30_T120_X0', '上下の逆指値で突破を待つ', '注文方式・系統内の先頭10場代表', '次観測価格',
         '現在価格の上下0.25ATRに逆指値を準備し、先に抜けた方向へ入る。反対側は取り消す。',
         '方向を先読みしない。組終了後30分休止。未成立も含め準備から最長120分。',
         '損切り0.75ATR、利益1.5ATRから幅1ATRの追跡。場内返済。', 'TOPIXは黒字、NKは赤字。共通の解にはならなかった。', read(HERE / 'order_methods/sessions/O01_P025_C30_T120_X0.json')),
        ('O02_P000_C30_T60_X1', '両建て＋損失側を早く返済', '注文方式・系統内の先頭10場代表', '次観測価格',
         '同時に同枚数を買い・売り。各側TOPIX5枚／NK10枚。',
         '各脚を独立管理し、損失玉も含めて全口座の損益を計上。組終了30分休止、準備から最長60分。',
         '各脚0.5ATR損切り。0.75ATR順行後に幅0.75ATRで追跡し時間で短縮。不発15分撤退。', '両市場で赤字。片側の利確だけを数えると成績を誤認する。', read(HERE / 'order_methods/sessions/O02_P000_C30_T60_X1.json')),
        ('O03_P000_C05_T60_X0', 'コイントス方向＋損切りと追跡', '注文60条件の先頭10場1位', '次観測価格',
         '事前固定seedの疑似乱数で買い・売りを決める。結果によるseed変更なし。',
         '終了後5分休止。準備から最長60分。',
         '損切り0.75ATR、利益1.5ATRから幅1ATR追跡。場内返済。', '直近4場は改善したが、後半9場のTOPIXは−407,500円。採用しない。', read(HERE / 'order_methods/sessions/O03_P000_C05_T60_X0.json')),
    ]
    result = []
    for ident, name, status, fill, entry, middle, exit_rule, conclusion, rows in descriptions:
        sessions = [normalize(r) for r in rows]
        names = sorted({r['session'] for r in sessions})
        assert len(sessions) == 46 and len(names) == 23
        periods = dict(先頭10=names[:10], 次9=names[10:19], 追加4=names[19:], 全23=names)
        weeks = {}
        for session in names:
            day = date.fromisoformat(session[:10])
            monday = (day - timedelta(days=day.weekday())).isoformat()
            weeks.setdefault(monday, []).append(session)
        result.append(dict(id=ident, name=name, status=status, fill=fill, entry=entry, middle=middle,
                           exit=exit_rule, conclusion=conclusion, sessions=sessions,
                           periods={p: {s: total([r for r in sessions if r['symbol'] == s and r['session'] in ids]) for s in SYMBOLS} for p, ids in periods.items()},
                           weeks={p: {s: total([r for r in sessions if r['symbol'] == s and r['session'] in ids]) for s in SYMBOLS} for p, ids in weeks.items()}))
    return result


def all_conditions() -> list[dict]:
    """機能: 探索269設定の前半成績と評価済み期間を記録する。

    引数: なし。返り値: 一覧(list[dict])。未再生期間は空値とする。
    """
    result = []
    for folder, title in [('overlay', '入口許可・休止32'), ('combined', '時計＋停止9'), ('rearm', '再失敗防止24')]:
        data = read(HERE / folder / ('結果.json' if folder == 'combined' else '全候補結果.json'))
        for item in data['候補']:
            ps = item['periods']
            result.append(dict(family=title, id=item['spec']['id'], spec=item['spec'],
                               first=[ps['開発10'][s]['net_yen'] for s in SYMBOLS],
                               all=[ps['全23'][s]['net_yen'] for s in SYMBOLS]))
    clocks = read(HERE / 'clock_search/結果.json')['集計']
    for path in sorted((HERE / 'clock_search/training').glob('K*.json')):
        row = read(path)
        ident = row['条件']['id']
        result.append(dict(family='再参加時計48', id=ident, spec=row['条件'],
                           first=[row['先頭10'][s]['net_yen'] for s in SYMBOLS],
                           all=[clocks[ident]['periods']['全23'][s]['net_yen'] for s in SYMBOLS] if ident in clocks else None))
    for folder, title in [('search', '新しい方向判定96'), ('order_methods', '予測なし注文60')]:
        for ident, ps in read(HERE / folder / '結果一覧.json').items():
            result.append(dict(family=title, id=ident, spec={}, first=[ps['開発10'][s]['net'] for s in SYMBOLS],
                               all=[ps['全23'][s]['net'] for s in SYMBOLS]))
    assert len(result) == 269
    return result


def csv_export(data: list[dict], intervals: dict) -> None:
    """機能: 表示値と同じ場別・30分別会計を日本語CSVへ書く。

    引数: data(list[dict])、intervals(dict)。返り値: なし(None)。
    """
    with (OUT / '代表10手法のセッション損益.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['手法', 'セッション', '銘柄', '利益円', '損失円', '収支円', '利益決済枚数', '損失決済枚数', '同値決済枚数'])
        for m in data:
            for row in m['sessions']:
                writer.writerow([m['id']] + [row[k] for k in ('session', 'symbol', 'profit', 'loss', 'net', 'win_qty', 'loss_qty', 'flat_qty')])
    with (OUT / '30分区間損益.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.writer(stream)
        keys = list(intervals['口座'][0]['区間'][0])
        writer.writerow(['手法', 'セッション', '銘柄'] + keys)
        for account in intervals['口座']:
            for row in account['区間']:
                writer.writerow([account[k] for k in ('手法', 'セッション', '銘柄')] + [row[k] for k in keys])


def property_evidence() -> str:
    """機能: 売買順位とは独立の性質測定を、保存数値から短い説明へ変換する。

    引数: なし。返り値: HTML断片(str)。
    """
    e01 = read(HERE / 'properties_e01/性質の数値.json')
    price = read(HERE / 'properties_price/状態別集計.json')
    book = read(HERE / 'properties_book/市場性質結果.json')
    overlap = read(HERE / 'properties_book/価格応答との重複.json')
    quality = read(HERE / 'properties_price/将来区間品質監査.json')
    rows = []
    for symbol in SYMBOLS:
        for period in ('旧19', '追加4'):
            r = e01['集計'][period][symbol]['組単位']
            rows.append(f'<tr><td>{symbol} {period}場</td><td>{r["非ゼロ成功率"]:.1%}</td>'
                        f'<td>{r["損益分岐成功率"]:.1%}</td><td>{r["平均勝ち円"]:,.0f}</td>'
                        f'<td>{r["平均負け円"]:,.0f}</td><td>{r["平均勝損比"]:.2f}</td></tr>')
    out = '<h3>1. E01の強みは「高勝率」ではなく、大きい成功で小損を回収すること</h3>'
    out += '<p>追加4場では回収に必要な成功頻度を下回りました。NKは平均勝損比が改善しても赤字。TOPIXは1場の負けが2.58組→5.50組に増え、平均利益も縮小しています。</p><details><summary>成功率と平均勝敗の内訳・入口の遅さ</summary>'
    out += '<div class="scroll"><table><thead><tr><th>銘柄・期間</th><th>実成功率</th><th>損益分岐</th><th>平均勝ち 円</th><th>平均負け 円</th><th>勝／負</th></tr></thead><tbody>' + ''.join(rows) + '</tbody></table></div>'
    out += '<p class="muted">新規から全返済までの組単位、損益ゼロ除外。損益分岐＝平均負け÷（平均勝ち＋平均負け）。各期間の実績から計算した値で、事前に分かっていた必要勝率ではありません。</p>'
    out += '<p>TOPIXの1場あたりの負けは2.58組→5.50組、勝ちは1.74組→2.00組。「勝つ機会が消えた」より、失敗頻度の増加が大きいです。返済までの事後的な最大順行で分類すると、負け41組の「1.5ATRまで伸びない」は、旧19場でも負け102組中97組に見られました。市場の原因そのものを識別した分類ではありません。</p>'
    out += '<p>E01は長期EMA・足公開待ちのため、両市場の判定材料が揃うまで開始65〜73分かかる設計です。長い方向が続く途中を狙う方式で、早い転換への追随が得意な設計ではありません。</p></details>'
    selected = [r for r in price if r['period'] == '全23' and r['state'] == '同方向高効率'
                and r['hypothesis'] == '過去30分方向' and r['horizon'] == 30]
    out += '<h3>2. 過去の方向一致は、これからの継続と同じではない</h3>'
    out += '<p>両市場の過去の方向が揃っても、次の順行幅と途中の逆行は別の問題です。今回は昼夜や価格観測の空白の扱いで結果が変わり、方向一致が継続につながる法則はまだ確定できません。</p><details><summary>時間帯別の結果と観測上の限界</summary>'
    out += '<div class="scroll"><table><thead><tr><th>商品・時間帯</th><th>観測点数</th><th>同方向へ進んだ割合</th><th>平均変化 ATR</th></tr></thead><tbody>'
    for symbol in SYMBOLS:
        for part in ('全体', 'Day', 'Night'):
            matches = [r for r in selected if r['symbol'] == symbol and r['sampling'] == '5分全観測' and r['part'] == part]
            if not matches:
                continue
            r = matches[0]
            out += f'<tr><td>{symbol} {dict(Day="昼",Night="夜").get(part,part)}</td><td>{r["n"]}</td><td>{r["continue_direction"]:.1%}</td><td>{r["terminal_atr"]:+.3f}</td></tr>'
    out += '</tbody></table></div>'
    out += '<p class="muted">現在状態は確定済みの連続30分・過去の効率比で判定し、未来は結果だけに使用。5分観測は重複します。60分間隔では両市場とも9点に減り、平均変化の符号も正へ変わるため、強い結論には不足します。現在・終端の鮮度を要求した標本の性質で、全時間へ一般化していません。</p>'
    out += '<p class="muted">将来区間内の原本観測間隔も追加監査しました。上表の高効率30分では、60秒を超える空白がTOPIX14/114点・NK38/112点にあり、最大順行・先着順を観測し損ねた可能性があります。空白60秒以内だけの感度では継続50.0%／60.8%、平均変化＋0.052／＋0.070ATRへ変化。非重複では8点／4点しか残りません。これは約定時計の間隔で、無約定と通信・収集断は区別できません。未来の空白を入口の採否には利用していません。<a href="../../work/wave_v51/properties_price/将来区間品質監査.json">追加品質監査</a></p></details>'
    out += '<details><summary>十分な順行が、損切り相当の逆行より先に起きるか</summary><div class="scroll"><table><thead><tr><th>商品</th><th>＋1.5ATR先着</th><th>−0.75ATR先着</th><th>双方未到達</th><th>平均最大順行 ATR</th><th>平均最大逆行 ATR</th></tr></thead><tbody>'
    for r in selected:
        if r['sampling'] == '5分全観測' and r['part'] == '全体':
            out += f'<tr><td>{r["symbol"]}</td><td>{r["hit_win"]:.1%}</td><td>{r["hit_loss"]:.1%}</td><td>{r["untouched"]:.1%}</td><td>{r["mfe_atr"]:.2f}</td><td>{r["mae_atr"]:.2f}</td></tr>'
    out += '</tbody></table></div><p>直前30分の向きを基準に、次30分の経路を測った値です。未到達を負けやゼロ決済と決めつけず、E01の勝率とも混同しません。これはE01の入口とは異なる固定時刻観測で、入口をこの結果で選び直してはいません。</p></details>'
    out += '<h3>3. 板の指標と将来変化の関係は、今回の観測では不安定</h3>'
    out += '<p>公開済みの板OFIと将来変化には弱い関係が見えます。ただし直前価格変化との重なりを線形に調整すると、関係はかなり弱まります。今回の指標が価格以上の情報を持つかは未確認です。</p><details><summary>板と将来変化の相関・吸収候補の不足</summary>'
    out += '<div class="scroll"><table><thead><tr><th>商品・期間</th><th>1分先との相関</th><th>5分先との相関</th><th>15分先との相関</th></tr></thead><tbody>'
    bs = [r for r in book['連続値の相関'] if r['feature'] == 'ofi' and r['period'] in ('全23', '既知追加4')]
    for r in bs:
        values = ''.join(f'<td>{r["outcomes"][str(h)]["pearson"]:+.3f}</td>' for h in (60, 300, 900))
        out += f'<tr><td>{r["symbol"]} {r["period"]}</td>{values}</tr>'
    out += '</tbody></table></div><p class="muted">相関係数は勝率ではありません。15分間隔の固定観測774点に品質を限定。強圧力はTOPIX18点・NK8点で、圧力が強いのに価格が進まない「吸収候補」は不足しました。点数を増やすため閾値を緩める再探索はしていません。</p></details>'
    adjusted = [r for r in overlap['自市場'] if r['period'] == '全23' and r['feature'] == 'ofi']
    out += '<details><summary>板情報が、直前の値動きの言い換えになっていないか</summary><div class="scroll"><table><thead><tr><th>商品</th><th>OFIと直前価格変化の相関</th><th>価格調整後 1分</th><th>価格調整後 5分</th><th>価格調整後 15分</th></tr></thead><tbody>'
    for r in adjusted:
        vals = ''.join(f'<td>{r["future"][str(h)]["adjusted_price"]:+.3f}</td>' for h in (60, 300, 900))
        out += f'<tr><td>{r["symbol"]}</td><td>{r["same_window"]:+.3f}</td>{vals}</tr>'
    out += '</tbody></table></div><p>OFIは直前の値動きと強く重なり、その影響を線形に調整すると将来変化との相関はかなり弱まります。現指標の独自情報は未確認です。非線形な関係や個別の補充まで否定した検査ではありません。</p></details>'
    out += '<p class="notice"><strong>設計へ持ち込める結論：</strong>どの観測条件で、保有方向・枚数・返済をどう変えると正の期待損益が生まれるのか。その源泉を先に確認します。継続、反復、価格応答や変動幅も対象です。今回の単純な方向一致・板指標だけでは安定した源泉を確認できていないため、新しい採用ルールを断定しません。</p>'
    out += '<p class="links"><a href="../../work/wave_v51/properties_e01/性質の要点.md">E01の性質と数理</a><a href="../../work/wave_v51/properties_price/README.md">価格の性質・状態遷移</a><a href="../../work/wave_v51/properties_book/README.md">板の性質・観測限界</a><a href="性質の表示元.json">この説明の表示元</a></p>'
    save(OUT / '性質の表示元.json', dict(E01=e01['集計'], 価格=selected, 板=bs, 価格調整後=adjusted, 将来区間の品質=quality))
    return out


def main() -> None:
    """機能: 説明HTML・全候補HTML・CSV・案内を生成する。

    引数: なし。返り値: なし(None)。
    """
    OUT.mkdir(parents=True, exist_ok=True)
    data, candidates = methods(), all_conditions()
    intervals = read(HERE / 'interval_audit/時間区間損益.json.gz')
    expected = {(m['id'], r['session'], r['symbol']): r for m in data for r in m['sessions']}
    checked = 0
    for account in intervals['口座']:
        key = tuple(account[k] for k in ('手法', 'セッション', '銘柄'))
        if key not in expected:
            continue
        row = expected[key]
        for field, source in [('profit', '確定利益円'), ('loss', '確定損失円'), ('net', '時価収支円'), ('win_qty', '利益返済枚数'), ('loss_qty', '損失返済枚数'), ('flat_qty', '同値返済枚数')]:
            assert abs(row[field] - sum(r[source] for r in account['区間'])) < 1e-6, (key, field)
        checked += 1
    document = dict(methods=data, intervals=intervals['口座'], candidates=candidates)
    save(OUT / '報告データ.json', document)
    csv_export(data, intervals)
    template = (HERE / 'report_template.html').read_text(encoding='utf8')
    source = template.replace('@@PROPERTIES@@', property_evidence()).replace('@@DATA@@', json.dumps(document, ensure_ascii=False, separators=(',', ':'), allow_nan=False).replace('</', '<\\/'))
    (OUT / TITLE).write_text(source, encoding='utf8')
    save(OUT / '報告会計検算.json', dict(全合格=True, 手法数=len(data), 場別行数=len(expected), 区間と照合済み口座=checked,
                                        条件設定数=len(candidates), 原本更新なし=True, API取得数=0))
    print(json.dumps(dict(手法数=len(data), 区間照合=checked, 条件数=len(candidates)), ensure_ascii=False))


if __name__ == '__main__':
    main()
