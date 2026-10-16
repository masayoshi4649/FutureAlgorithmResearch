"""順行入口とドテンの固定結果を照合し、短い日本語HTMLへまとめる。"""

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = HERE.parents[2]
PUBLIC = ROOT / 'アルゴリズム調査/00080_順行逆指値と反転売買の検証'
MAIN = '順行逆指値とドテンの説明と全セッション損益.html'
ALL = '全108条件の前半比較.html'
SYMBOLS = ('TOPIX', 'NK225')
SOURCES = {}


def read(path):
    """
    機能: 保存資料を読み、公開結果の入力指紋を記録する。
    引数: path (Path) はJSONの絶対パス。
    返り値: dict又はlist の復元された資料。
    """
    raw = path.read_bytes()
    SOURCES[str(path.relative_to(ROOT)).replace('\\', '/')] = hashlib.sha256(raw).hexdigest()
    return json.loads(raw.decode('utf-8-sig'))


def save(path, value):
    """
    機能: 日本語と有限数値のJSONを保存する。
    引数: path (Path)、value (dict又はlist)。
    返り値: None。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def verify_result(result, sessions, fixed, model):
    """
    機能: 全場と期間の会計、枚数、モデル、金額割合を検算する。
    引数: result/fixed (dict)、sessions (list[str])、model (str)。
    返り値: None。不一致は生成せず例外にする。
    """
    assert result['run']['sessions'] == sessions and result['run']['model'] == model
    assert result['run']['delay'] == result['run']['seed'] == result['run']['slip_ticks'] == 0
    rows = result['rows']
    assert len(rows) == 2 * len(sessions)
    assert {(r['session'], r['symbol']) for r in rows} == {(s, p) for s in sessions for p in SYMBOLS}
    fields = ('profit', 'loss', 'net', 'gross', 'fees', 'trades', 'cycle_profit', 'cycle_loss',
              'cycle_net', 'cycles', 'midpoint_gross', 'spread_drag')
    for row in rows:
        cap = 10 if row['symbol'] == 'TOPIX' else 20
        assert row['max_long'] <= cap and row['max_short'] <= cap and row['max_gross'] <= cap
        assert row['max_reserved_long'] <= cap and row['max_reserved_short'] <= cap
        assert abs(row['profit'] - row['loss'] - row['net']) < 1e-6
        assert abs(row['cycle_profit'] - row['cycle_loss'] - row['cycle_net']) < 1e-6
        assert abs(row['net'] - row['cycle_net']) < 1e-6
        assert abs(row['midpoint_gross'] - row['spread_drag'] - row['fees'] - row['net']) < 1e-6
        if model == 'ideal_fee':
            assert row['spread_drag'] == 0
    for period, subset in [('対象', sessions), ('前16', fixed['前16']), ('後14', fixed['後14'])]:
        for symbol in SYMBOLS:
            rs = [r for r in rows if r['symbol'] == symbol and r['session'] in subset]
            saved = result['periods'][period][symbol]
            for field in fields:
                assert abs(sum(r[field] for r in rs) - saved[field]) < 1e-6, (result['config']['id'], period, symbol, field)
            assert saved['winning_sessions'] == sum(r['net'] > 0 for r in rs)
            assert saved['losing_sessions'] == sum(r['net'] < 0 for r in rs)
            assert saved['no_trade_sessions'] == sum(r['trades'] == 0 for r in rs)
            denominator = saved['profit'] + saved['loss']
            assert saved['profit_share'] == (saved['profit'] / denominator if denominator else None)


# ----------------------------------------
def describe(config):
    """
    機能: 入口方向、追尾、返済後の状態を実装と同じ意味で説明する。
    引数: config (dict) は事前固定した一条件。
    返り値: dict の表示用説明。
    """
    family, width, variant = config['family'], config['width_ticks'], config['variant']
    multiplier = (.5, 1, 2)[variant]
    exit_ticks = width * multiplier
    entry = '待機基準の現在値から上へ入口幅なら売り、下へ入口幅なら買い。先に成立した片側だけ。' if family == 0 else '待機基準の現在値から上へ入口幅なら買い、下へ入口幅なら売り。先に成立した片側だけ。'
    if family <= 1:
        during = '追加・両建てをせず、実約定価格から損切り幅と利確幅を監視する。'
        exit_text = '出口幅だけ逆行で損切り、出口幅の3倍順行で利確。返済した観測の現在値を基準に、次の観測から通常待機へ戻る。'
    else:
        during = '実約定価格から極値を初期化。買いは観測済み最高値、売りは最安値を更新する。固定利確や保有時間の期限は設けない。'
        base_exit = '初期損切りは出口幅。順行後は極値から出口幅反転して返済。'
        suffix = {
            2: '返済時の現在値を基準に、次の観測から上下の入口幅を通常待機する。',
            3: '場末以外は、損切り・追尾返済の完了後に反対玉を同枚数で即新規。新玉の極値は新しい約定価格から追跡する。',
            4: '場末以外の返済後、その観測の現在値から反対方向へさらに入口幅進めば反対玉を建てる。元方向へ入口幅戻れば反転待ちを解除し、その位置から通常待機する。',
            5: '場末以外の返済後、手数料を引いた確定損益がプラスのときだけ同枚数で即ドテン。ゼロ又は損失なら通常待機する。',
        }[family]
        exit_text = base_exit + suffix
    conditions = f'入口{width}呼値（TOPIX {width * .5:g}pt／日経{width * 10:g}pt）、出口{exit_ticks:g}呼値（TOPIX {exit_ticks * .5:g}pt／日経{exit_ticks * 10:g}pt）。'
    conditions += ' 新規はTOPIX10枚・日経20枚。反対玉は返済完了後に建て、同時両建てはしない。'
    short = '場末以外の返済は、手数料後プラスなら即ドテン、ゼロ又は損失なら通常待機。返済理由の名称だけでは決めない。' if family == 5 else config['description']
    return dict(id=config['id'], name=config['name'], family=family, short=short,
                entry=entry, during=during, exit=exit_text + ' 場末は全返済し、新規・ドテンをしない。',
                condition=conditions)


def build_methods(selection):
    """
    機能: 主・家族代表・事前固定幅を重複させず選択肢へ整理する。
    引数: selection (dict) は前半選定の確定資料。
    返り値: list[dict] の説明と選定用途。
    """
    values, seen = [], set()
    performance = set(selection['selected_for_performance'])
    for record in selection['primary'] + selection['families'] + selection['common_width']:
        key = record['id']
        if key in seen:
            continue
        seen.add(key)
        method = describe(record['config'])
        method.update(status=record['status'], overview=key in performance,
                      sufficient=record['sufficient'], selected_for_performance=key in performance)
        values.append(method)
    assert seen == set(selection['selected'])
    return values


def comparison_data(selection):
    """
    機能: 入口方向とドテンの同幅比較を別の表示群へ分ける。
    引数: selection (dict) は損益で選んでいない比較組を含む。
    返り値: dict のdirectionとturn比較配列。
    """
    output = dict(direction=[], turn=[])
    for i, pair in enumerate(selection['pairs']):
        assert pair['selected_by_performance'] is False
        row = dict(label='入口8呼値・出口8呼値', first=pair['left_id'], second=pair['right_id'],
                   description=pair['label'].removeprefix('待機対'), difference=pair['difference'])
        output['direction' if i == 0 else 'turn'].append(row)
    assert len(output['direction']) == 1 and len(output['turn']) == 3
    return output


def render(template, payload, script, replacements):
    """
    機能: CSS・会計・操作を含む単体HTMLを生成する。
    引数: template/script (str)、payload (dict)、replacements (dict[str,str])。
    返り値: str の完成HTML。
    """
    markup = (HERE / template).read_text(encoding='utf-8')
    values = dict(replacements, STYLE=(HERE / 'style.css').read_text(encoding='utf-8'),
                  COMMON=(HERE / 'common.js').read_text(encoding='utf-8'),
                  SCRIPT=(HERE / script).read_text(encoding='utf-8'),
                  DATA=json.dumps(payload, ensure_ascii=False, separators=(',', ':'), allow_nan=False).replace('</', '<\\/'))
    for key, value in values.items():
        markup = markup.replace('__' + key + '__', value)
    assert '__DATA__' not in markup and '__SCRIPT__' not in markup
    return markup


# ----------------------------------------
def main():
    """
    機能: 再生済み会計を検算して主報告と前半全条件の2HTMLを出力する。
    引数: なし。既存結果だけを読む。
    返り値: None。戦略再生、候補選び直し、API接続は行わない。
    """
    fixed = read(WORK / 'results/事前固定.json')
    selection = read(WORK / '前半選定.json')
    assert len(fixed['catalog']) == 108 and len(fixed['全30']) == 30
    assert len(fixed['前16']) == 16 and len(fixed['後14']) == 14
    assert selection['後14を参照した選び直し'] is False
    results = dict(main={}, ideal={})
    for model, path, run_model in [('main', 'final/delay0/results', 'quotes'), ('ideal', 'ideal_fee/results', 'ideal_fee')]:
        for key in selection['selected']:
            result = read(WORK / path / (key + '.json'))
            verify_result(result, fixed['全30'], fixed, run_model)
            results[model][key] = result
    train = []
    for config in fixed['catalog']:
        result = read(WORK / 'train/results' / (config['id'] + '.json'))
        verify_result(result, fixed['前16'], fixed, 'quotes')
        assert result['config'] == config
        train.append(result)
    conclusion = read(HERE / '結論文.json')
    diagnosis = read(WORK / 'analysis/同幅6手法の損失構造.json')
    turn_analysis = next(r for r in diagnosis['models']['ideal_fee'] if r['id'] == 'F3_W08_V1')
    assert turn_analysis['symbols']['TOPIX']['analysis']['返済理由']['3']['赤字脚'] == 792
    assert turn_analysis['symbols']['NK225']['analysis']['返済理由']['3']['赤字脚'] == 848
    methods = build_methods(selection)
    supplemental = read(WORK / 'supplement/追加固定.json')
    assert len(supplemental['条件']) == 1
    additional_config = supplemental['条件'][0]
    supplementary_results = {}
    for model, path, run_model in [('main', 'supplement/final/results', 'quotes'), ('ideal', 'supplement/ideal_fee/results', 'ideal_fee')]:
        result = read(WORK / path / (additional_config['id'] + '.json'))
        verify_result(result, fixed['全30'], fixed, run_model)
        supplementary_results[model] = result
    supplement = dict(fixed=supplemental, method=describe(additional_config), results=supplementary_results,
        description='F3_W64_V1は前16場で両商品黒字でしたが、各10取引で最低20件に届きませんでした。主結果を確認した後、この条件を後半損益の閲覧前に追加固定して参考再生。入口と追尾を64呼値まで広げた即ドテンです。全30場はTOPIX−1,187,556円、日経115,880円で、共通の安定利益にはなりませんでした。主14条件は差し替えていません。')
    descriptions = {
        'main': '主成績は買いask・売りbidで全量約定し、実手数料を控除。気配欠測時は次の有効気配を待ちます。',
        'ideal': '理論対照は現在値で必ず全量約定できる仮定。実手数料は同じですが、売買気配での実行可能性を示す成績ではありません。',
    }
    text = {
        'selection-description': f'前16場で主3観点から{selection["primary_unique"]}条件、6家族ごとの比較対象を固定。両商品とも完結した取引20件以上・取引場8以上を活動基準とします。1取引の効率で選ぶ観点には大きな累積赤字の条件も残っており、採用を推奨する結果は得られていません。選択欄には、損益で選ばない入口8・出口8呼値の対照6条件も含めます。',
        'comparison-description': '幅8・出口8呼値は損益を見る前から固定。家族ごとに選んだ最適幅を混ぜず、価格条件をそろえて比較します。固定利確型は損切り1対利確3で共通です。',
        'turn-diagnosis': conclusion.get('ドテンの要点', ''),
        'execution-description': '発動は現在値、買いは最良売り気配ask、売りは最良買い気配bid。返済とドテン新規は別注文で、双方に手数料がかかります。TOPIXミニ片道41.8円／枚、日経マイクロ11円／枚、注文単位で円未満切捨て。行末即時新規の子条件は次の有効現在値から。待機新規が後続行冒頭で約定した場合は、その観測で子条件を1回監視します。日中15:33／夜間翌05:48から新規・ドテン停止、15:34／翌05:49に全返済を発注。通常の保有期限はありません。',
        'split-description': '全30場は既に閲覧した保存データです。前16場で選定し、後14場の新しい再生成績では選び直さない確認です。未知の将来での安定性を証明しません。前半の両商品黒字F3_W64_V1は活動基準不足のため主選定から外し、後から探索的参考として別章へ追加しました。旧00079の逆張りはIOC、新しい逆張り対照は成行相当なので、旧結果と同じ経路になる比較ではありません。',
    }
    payload = dict(methods=methods, results=results, sessions=fixed['全30'], selection=selection,
                   comparisons=comparison_data(selection), model_descriptions=descriptions, conclusion=conclusion, text=text,
                   supplement=supplement)
    save(HERE / '描画資料.json', payload)
    PUBLIC.mkdir(parents=True, exist_ok=True)
    outputs = {}
    markup = render('template.html', payload, 'main.js', dict(ALL=ALL))
    (PUBLIC / MAIN).write_text(markup, encoding='utf-8')
    outputs[MAIN] = hashlib.sha256((PUBLIC / MAIN).read_bytes()).hexdigest()
    all_payload = dict(rows=[dict(config=r['config'], name=r['config']['name'], condition=describe(r['config'])['condition'], metrics=r['periods']['前16']) for r in train],
        families=[dict(id=r['family'], name=r['config']['name']) for r in selection['families']],
        intro='6家族×入口6幅×出口3幅の108条件。前16場だけの探索結果です。追加発注遅延0、売買気配で約定、手数料後。親組と決済取引の収支は一致し、両商品を金額合算せず比較します。')
    save(HERE / '全前半描画資料.json', all_payload)
    (PUBLIC / ALL).write_text(render('all_template.html', all_payload, 'all.js', dict(MAIN=MAIN)), encoding='utf-8')
    outputs[ALL] = hashlib.sha256((PUBLIC / ALL).read_bytes()).hexdigest()
    save(HERE / '生成結果.json', dict(HTML=outputs, 入力SHA256=SOURCES,
        照合='全108前半と固定代表14条件・追加参考1条件の主/理論対照の全30場、期間合計、全玉収支、片方向上限、実手数料を保存結果へ照合。',
        主代表数=selection['primary_unique'], 全30一意条件数=len(selection['selected'])))
    print(json.dumps(outputs, ensure_ascii=False))


if __name__ == '__main__':
    main()
