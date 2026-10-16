"""00104の保存小資料だけから、執行・票母数・昼夜活動の次対照を整理する。"""

import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.stdout.reconfigure(encoding='utf-8')
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
INPUTS = {
    '十六会計': dict(path='work/e01_cross_market_20261014/engine/finance/結果.json',
        SHA256='dd52f4401096942c5001b73306a3365759826611f18936192d7ec524c3a48585'),
    '旧四十三親': dict(path='work/e01_cross_market_20261014/diagnosis/同母二商品43実親の原因射影.json',
        SHA256='e8451fd00380d04199072443f4f6c04e6561de039bad20e6b698a59a8279da73'),
    '新十六親': dict(path='work/e01_cross_market_20261014/entry_diagnosis/実公開票と事後逆行の追加射影.json',
        SHA256='bc44cdd7dbf0f69f737a559c9af0bd912fb3dca7d4722e8b5a884a3d028ded60')}
SYMBOLS = ('TOPIX', 'NK225')


def write(name: str, data: dict) -> None:
    """
    機能: 新所有域へ小計画又は小診断を新規保存する。
    引数: name(str)、data(dict)はファイル名と内容。
    返り値: None。旧領域・共有・公開へ書かない。
    """
    target = HERE/name
    assert target.resolve().is_relative_to(HERE) and not target.exists()
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8', newline='\n')


def fix() -> None:
    """
    機能: 小3資料だけの再整理目的と根の18対照案を読取前に固定する。
    引数: なし。
    返り値: None。旧保存小資料の本文もまだ読まない。
    """
    write('小資料だけの原因再整理計画.json', dict(全合格=True, inputs=INPUTS,
        source_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        目的='執行価格capと拡幅を分け、票の少なさと昼夜不足を診断。銘柄差パラメータを許容した既保存候補と活動を両面評価し、次18対照の分析順を固定する。',
        分母='旧CONFIRM25実親43、B03実親15とB01唯一TOP敗1、既正式16条件66口座。全公開候補の分母ではない。',
        根案=dict(新十八='.25/.5/.75・min2 と .5・min4 の4入口 × cap0/1観測呼値FAK × P1/.25R の16、.5min4成行 × 2利確の2。',
            旧再利用='既成行3入口 × 2利確の6は保存政策。同じ根拠を新有効性証拠へ数えない。', 拡幅='今回の18にspread門は入れない。'),
        検査=['cap0/1の旧親価格資格と、価格不利のみ・拡幅のみ・両方の件数/例。PLを合算して新条件を推定しない。',
            'B03の票数/昼夜/事後逆行、B01敗がmin4では拒否されない反例。',
            '保存B03/B01とB04/B01を同じE01の銘柄パラメータ差候補として個別指標を併記。新18の実績と混同しない。',
            '利確幅が変わった共通TOP B03/B04の場差だけを保存し、一日依存を見分ける。',
            'Day/Nightの活動と、無取引場の受理アンカー有無を小境界から数える。未受理のgate/数量/静観内訳は未測。'],
        小本文一読上限=3, 新金融=0, API=0, 入力=0, 台帳=0, 原板=0, NPZ=0, 旧公開編集=0, 共有編集=0))


def small_read(item: dict) -> dict:
    """
    機能: 固定保存小JSONを同bytes一読しSHAを照合する。
    引数: item(dict)は旧小資料の位置/指紋。
    返り値: dictは完成小内容。pickle・NPZ・API・金融moduleを使わない。
    """
    target = ROOT/item['path']; assert target.suffix == '.json' and target.stat().st_size < 10_000_000
    saved = target.read_bytes(); assert hashlib.sha256(saved).hexdigest() == item['SHA256']
    result = json.loads(saved.decode('utf-8-sig')); assert result['全合格']
    return result


def compact_parent(row: dict) -> dict:
    """
    機能: 旧43親の公開・D0fillの価格資格を短く射影する。
    引数: row(dict)は測定済み旧実親。
    返り値: dictは資格と原行。将来成績の条件選択に使わない。
    """
    pub, fill, side = row['公開'], row['新規'], row['side']
    before = pub['ask' if side == 1 else 'bid']; after = fill['ask' if side == 1 else 'bid']
    adverse = side*(after-before)/row['観測呼値']
    widening = fill['ask']-fill['bid'] > pub['ask']-pub['bid']
    return dict(session=row['session'], symbol=row['symbol'], parent=row['paper_parent'], side=side,
        元勝敗='勝ち' if row['実親']['収支'] > 0 else '負け', 公開=pub, D0fill=fill,
        不利呼値=adverse, 不利=adverse > 0, 拡幅=widening, 拡幅だけ=widening and adverse <= 0,
        cap0価格不成立=adverse > 0, cap1価格不成立=adverse > 1,
        元実収支=row['実親']['収支'], 票数=row['初回方向票数'], balance=row['候補方向釣合い'])


def financial_case(finance: dict, cid: str, symbol: str) -> dict:
    """
    機能: 同商品保存会計の達成・活動・昼夜・方向を小再集計する。
    引数: finance(dict)、cid/symbol(str)は完成16政策と対象。
    返り値: dictは既保存の事実。別条件へ注文やPnLを比例換算しない。
    """
    case = finance['results'][cid]; rows = [r for r in case['rows'] if r['symbol'] == symbol]
    assert len(rows) == 33
    stages = {}
    for stage in ('Day', 'Night'):
        own = [r for r in rows if r['session'].endswith('_'+stage)]
        stages[stage] = dict(全場=len(own), 活動=sum(r['親数'] > 0 for r in own), 黒字=sum(r['収支'] > 0 for r in own),
            赤字=sum(r['収支'] < 0 for r in own), 無取引=sum(r['親数'] == 0 for r in own), 収支=sum(r['収支'] for r in own))
    no_trade = {r['session'] for r in rows if r['親数'] == 0}
    empty = [r for r in finance['boundary'][cid] if r['symbol'] == symbol and r['session'] in no_trade]
    assert len(empty) == len(no_trade)
    summary = case['symbols'][symbol]; mean = case['stability'][symbol]['mean_positive_session_net_yen']
    budget = 5000. if symbol == 'TOPIX' else 2000.
    return dict(id=cid, symbol=symbol, symbols=summary, stability=case['stability'][symbol],
        上位三除外=case['periods'][symbol]['上位3正収支場除外'],
        前十六=case['periods'][symbol]['前16'], 後十七=case['periods'][symbol]['後17'],
        direction=case['directional_symbols'][symbol], 昼夜=stages,
        無取引受理=dict(分母=len(empty), 受理なし=sum(not r['anchor']['成立'] for r in empty),
            受理あり実親なし=sum(r['anchor']['成立'] for r in empty),
            未測='受理なしを方向票門/数量0/静観等へ分解する全候補台帳は本目的では読まない。'),
        名目損失枠対平均黒字場=budget/mean if mean else None,
        その比の留保='未発火の名目枠と平均黒字の尺度。実現損失や新ストレス収支ではなく、損失枠による損小利大保証はない。')


def run() -> None:
    """
    機能: 根授権済み旧小3資料を各一読し、次対照の原因と勝ち反証を保存する。
    引数: なし。
    返り値: None。金融/API/入力/台帳・旧公開・共有は0。
    """
    plan = json.loads((HERE/'小資料だけの原因再整理計画.json').read_text(encoding='utf-8'))
    assert plan['source_SHA256'] == hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    values = {name: small_read(item) for name, item in plan['inputs'].items()}
    finance, old, fresh = (values[k] for k in ('十六会計', '旧四十三親', '新十六親'))
    assert len(finance['configs']) == 16 and len(old['実親']) == 43 and len(fresh['parent_projections']) == 16
    assert fresh['保存結果SHA256'] == plan['inputs']['十六会計']['SHA256']
    execution = [compact_parent(r) for r in old['実親']]
    counts = {}
    for symbol in SYMBOLS:
        counts[symbol] = {}
        for tag in ('勝ち', '負け'):
            own = [r for r in execution if r['symbol'] == symbol and r['元勝敗'] == tag]
            counts[symbol][tag] = dict(分母=len(own), **{key: sum(r[key] for r in own)
                for key in ('不利', '拡幅', '拡幅だけ', 'cap0価格不成立', 'cap1価格不成立')})
    b03 = [r for r in fresh['parent_projections'] if r['case_id'] == 'E01_CROSS_B03']; assert len(b03) == 15
    group = {}
    for symbol in SYMBOLS:
        own = [r for r in b03 if r['symbol'] == symbol]
        group[symbol] = dict(実親=len(own), 二票=sum(r['publication']['direction_votes'] == 2 for r in own),
            二又は三票=sum(r['publication']['direction_votes'] < 4 for r in own),
            Night=sum(r['session'].endswith('_Night') for r in own), Day=sum(r['session'].endswith('_Day') for r in own),
            最大事後清算逆行=max(r['risk']['fee_liquidation_MAE_yen'] for r in own))
    snapshots = {cid: {s: financial_case(finance, cid, s) for s in SYMBOLS}
        for cid in ('E01_CROSS_B01', 'E01_CROSS_B02', 'E01_CROSS_B03', 'E01_CROSS_B04')}
    pairs = {
        '入口だけ銘柄差': dict(TOPIX=snapshots['E01_CROSS_B03']['TOPIX'], NK225=snapshots['E01_CROSS_B01']['NK225'],
            定義='同じE01/一観測呼値純目標/予算/サイズで、方向票thresholdだけTOP.75・NK.5へ静的銘柄設定。',
            地位='既保存二商品会計の事後組合せ。新金融ではなく相関や共有資金を新再生しない。'),
        '利確も銘柄差': dict(TOPIX=snapshots['E01_CROSS_B04']['TOPIX'], NK225=snapshots['E01_CROSS_B01']['NK225'],
            定義='TOPは.75/利確.25R、NKは.5/利確P1。',
            地位='同じE01だが二つのパラメータ差を含む。TOPの追加利益が特定場だけかを別に確認。')}
    a = {(r['session'], r['symbol']): r for r in finance['results']['E01_CROSS_B03']['rows']}
    b = {(r['session'], r['symbol']): r for r in finance['results']['E01_CROSS_B04']['rows']}
    changes = [dict(session=s, symbol=k, 旧P1収支=a[s,k]['収支'], ATR四分の一収支=b[s,k]['収支'], 差=b[s,k]['収支']-a[s,k]['収支'])
        for s,k in a if k == 'TOPIX' and b[s,k]['収支'] != a[s,k]['収支']]
    selected = [r for r in fresh['parent_projections'] if r['case_id'] == 'E01_CROSS_B01']
    assert len(selected) == 1
    result = dict(全合格=True, 計画SHA256=hashlib.sha256((HERE/'小資料だけの原因再整理計画.json').read_bytes()).hexdigest(),
        source_SHA256=plan['source_SHA256'], sources=plan['inputs'], 小本文一読=3,
        旧執行資格集計=counts, 旧執行観測=execution, B03母数と昼夜=group,
        B03少票回復勝ち=[r for r in b03 if r['publication']['direction_votes'] < 4],
        B01強票でも不利fillの敗戦=selected[0], 保存B四条件=snapshots, 銘柄設定差の保存候補=pairs,
        TOP_B03対B04変更場=changes,
        次対照の順序=['一回FAKcap0/1Tの価格境界。gate・利確が同じ対照を見て、未約定/取消/後再参加/qの実再生で原因を測る。',
            '.5min4の票母数。min2同門/同cap/同利確と比べる。強票.7・20票の敗戦はmin4単独で見送れない。',
            'P1対.25Rの利確尺度。同入口・同cap・同min票で分離。勝ちや一日の約定改善だけを根拠に選ばない。',
            '銘柄差は設定表として固定。上記同部品の保存対照からTOP/NKを選ぶ。場の未来方向や結果による切替は使わない。',
            '経済三基準・上位三除外・前後期間・買売を確認後、Day/Night活動と全候補門→q→FAK不成立→実新規の母数を評価。無取引を勝ちにしない。'],
        不足=['新B03の公開両BBO・実fillclockは小射影に未保存。旧43の価格資格を新15親へ勝手に継承しない。',
            '旧43/新15のwin/lossは実現後の診断ラベル。金融新18の収支を親削除で推定しない。',
            '昼不足が元候補不足、票門、数量0、静観、取消のどこから生じたかは全候補対応未測定。新金融で既取得する入力を使う準備母数の保存を推奨。',
            'min4は代理更新を増やすだけで、真の攻撃注文の数量/独立性を保証しない。',
            '拡幅だけの敗戦は価格capの保証外。今回spread門を入れず価格門の効果として合算しない。'],
        新金融=0, API=0, 入力=0, 台帳=0, 原板=0, NPZ=0, 旧公開編集=0, 共有編集=0)
    assert plan['source_SHA256'] == hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    write('旧小事実と銘柄別候補及び次十八対照の因果順序.json', result)
    print(json.dumps(dict(全合格=True, 旧執行資格=counts, B03母数=group, TOP利確変更場=changes,
        新金融=0, 入力=0, 台帳=0, API=0), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument('--fix-only', action='store_true'); actions.add_argument('--small-reviewed', action='store_true')
    args = parser.parse_args(); fix() if args.fix_only else run()
