"""保存会計を照合し、注文手法の説明と全場損益をダークHTMLへまとめる。"""

import hashlib
import html
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = HERE.parents[2]
PUBLIC = ROOT / 'アルゴリズム調査/00079_方向予測を使わない注文手法の検証'
MAIN = '予測を使わない注文手法と全セッション損益.html'
FAMILY = '家族別12手法の説明と全セッション損益.html'
ALL = '全288条件の前半比較.html'
SYMBOLS = ('TOPIX', 'NK225')
SOURCES = {}
SUM_FIELDS = ('profit', 'loss', 'net', 'gross', 'fees', 'trades', 'cycle_profit',
              'cycle_loss', 'cycle_net', 'cycles', 'midpoint_gross', 'spread_drag')


def read(path):
    """
    機能: JSONを読み、生成資料の入力指紋を保存する。
    引数: path (Path) は保存資料の絶対パス。
    返り値: dict又はlist の復元された保存内容。
    """
    raw = path.read_bytes()
    SOURCES[str(path.relative_to(ROOT)).replace('\\', '/')] = hashlib.sha256(raw).hexdigest()
    return json.loads(raw.decode('utf-8-sig'))


def write_json(path, value):
    """
    機能: 日本語を保った有限数のJSONを保存する。
    引数: path (Path)、value (dict又はlist)。
    返り値: None。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def check_result(result, sessions, fixed):
    """
    機能: 各場、期間合計、親組と脚、枚数、執行条件を独立照合する。
    引数: result (dict)、sessions (list[str])、fixed (dict)。
    返り値: None。不一致なら例外で生成を中止する。
    """
    assert result['run']['delay'] == 0 and result['run']['slip_ticks'] == 0
    assert result['run']['sessions'] == sessions
    rows = result['rows']
    assert len(rows) == len(sessions) * 2
    assert {(r['session'], r['symbol']) for r in rows} == {(s, p) for s in sessions for p in SYMBOLS}
    for row in rows:
        cap = 10 if row['symbol'] == 'TOPIX' else 20
        assert abs(row['profit'] - row['loss'] - row['net']) < 1e-6
        assert abs(row['cycle_profit'] - row['cycle_loss'] - row['cycle_net']) < 1e-6
        assert abs(row['net'] - row['cycle_net']) < 1e-6
        assert abs(row['midpoint_gross'] - row['spread_drag'] - row['fees'] - row['net']) < 1e-6
        assert 0 <= row['max_long'] <= cap and 0 <= row['max_short'] <= cap
        assert row['max_reserved_long'] <= cap and row['max_reserved_short'] <= cap
        assert row['max_gross'] <= cap * 2 and row['max_net'] <= cap
    for period, subset in [('対象', sessions), ('前16', fixed['前16']), ('後14', fixed['後14'])]:
        for symbol in SYMBOLS:
            rs = [r for r in rows if r['symbol'] == symbol and r['session'] in subset]
            saved = result['periods'][period][symbol]
            for field in SUM_FIELDS:
                assert abs(sum(r[field] for r in rs) - saved[field]) < 1e-6, (result['config']['id'], period, symbol, field)
            assert saved['sessions'] == len(rs)
            assert saved['winning_sessions'] == sum(r['net'] > 0 for r in rs)
            assert saved['losing_sessions'] == sum(r['net'] < 0 for r in rs)
            assert saved['no_trade_sessions'] == sum(r['trades'] == 0 for r in rs)


# ----------------------------------------
def describe(config, criteria=None):
    """
    機能: 正式な家族・変数を、入口・途中・出口の簡潔な日本語へ展開する。
    引数: config (dict)、criteria (list[str]又はNone) は前半の選定観点。
    返り値: dict の表示用説明。損益の大小から説明を変更しない。
    """
    family, variant, width = config['family'], config['variant'], config['width_ticks']
    entry = [
        '全玉返済後、固定乱数で買いか売りを決めて建てる。',
        '全玉返済後、買いと売りを交互に建てる。',
        '買いと売りを同時に建てる。両方の返済後に再開する。',
        '買いと売りを同時に建てる。両方の返済後に再開する。',
        '待機開始価格から上へ1幅で買い、下へ1幅で売り。先に成立した片側だけを建てる。',
        '待機中の安値から1幅反発なら買い、高値から1幅反落なら売り。両方同時成立なら基準を置き直す。',
        '待機開始価格から下へ1幅で買い、上へ1幅で売り。条件価格を限度とする即時IOC。',
        '待機開始時の基準価格から上下各5段へ1幅刻みの指値条件。下で買い、上で売る。指値条件は即時IOC。',
        '買いと売りを同時に建てる。利益を返済した脚だけ、同方向に建て直す。',
        '待機開始時の基準価格の上下1幅を先に越えた方向へ、上限の5分の1だけ建てる。',
        '待機開始時の基準価格の上下1幅を先に越えた方向へ、半分ずつ2注文で建てる。',
        '主玉を上限まで建てる。主玉の方向は、全玉を返すたびに買い・売りを交互にする。',
    ][family]
    during = [
        '追加しない。損切りと利確の両条件を監視する。',
        '追加しない。損切りと利確の両条件を監視する。',
        '各脚を別々に監視する。片脚返済後も残りの損益を含める。',
        '各脚で順行極値を追跡する。片脚返済後も残りの損益を含める。',
        '順行した極値を更新し、反対側の新規条件は解除する。',
        '新規約定後は順行極値を追跡する。',
        '価格制約に合わなければ取消。約定後は追加しない。',
        '各段の玉は1幅の反発で利確。空き枠は価格がその段の内側へ戻ってから再び待機する。',
        '利益脚の返済・再建を繰り返す。残った損失脚も、組全体の清算時価と場末返済に含める。',
        '直前の実約定から1幅順行するごとに上限の5分の1を追加。上限以降は増やさない。',
        '半分は1幅で利確。残り半分は順行極値を追跡し、利益延長を狙う。',
        '主玉から1〜5幅逆行した各段で反対玉を5分の1ずつ追加。カバーは追尾で返す。',
    ][family]
    if family in (0, 1, 2, 6):
        sl, tp = [(1, 1), (1, 2), (1, 3), (2, 4)][variant]
        exit_text = f'各脚の約定価格から{sl}幅逆行で損切り、{tp}幅順行で利確。'
        condition = f'損切り{sl}幅／利確{tp}幅'
    elif family in (3, 4, 5, 9, 10):
        sl, activation, trail = [(1, 0, 1), (1, 1, 1), (2, 1, 2), (2, 2, 1)][variant]
        activation_text = '約定直後から' if activation == 0 else f'{activation}幅順行後から'
        exit_text = f'損切り{sl}幅。{activation_text}、順行極値から{trail}幅戻れば返済。'
        if family == 9:
            exit_text = f'初回約定から損切り{sl}幅。{activation_text}、全玉共通の順行極値から{trail}幅戻れば全返済。'
        if family == 10:
            exit_text = f'両脚の損切り{sl}幅。半分は1幅利確、残りは{activation_text}、極値から{trail}幅戻れば返済。'
        condition = f'損切り{sl}幅／追尾開始{activation}幅／追尾幅{trail}幅'
    elif family == 7:
        exit_text = f'各脚1幅で利確、{(2, 4, 8)[variant]}幅で損切り。' if variant < 3 else '各脚1幅で利確。組全体の損失が4単位で全返済し、基準を置き直す。'
        condition = f'1幅利確／個別損切り{(2, 4, 8)[variant]}幅' if variant < 3 else '1幅利確／全玉損失4単位'
    elif family == 8:
        exit_text = [
            '各脚1幅で利確して同方向を再建。途中の全玉損切りはなく、残玉は場末に全返済する。',
            '各脚1幅で利確して再建。組全体の損失4単位で全返済する。',
            '1幅順行後は1呼値戻りで返済・再建。組全体の損失4単位で全返済する。',
            '2幅順行後は1幅戻りで返済・再建。組全体の損失4単位で全返済する。',
        ][variant]
        condition = ['1幅利確／途中の全玉止めなし', '1幅利確／全玉損失4単位', '1幅順行から1呼値追尾／全玉損失4単位', '2幅順行から1幅追尾／全玉損失4単位'][variant]
    else:
        activation, trail = [(0, 1), (1, 1), (1, 2), (2, 1)][variant]
        exit_text = f'主玉は8幅、カバーは2幅で損切り。カバーは{activation}幅順行後に{trail}幅追尾。組全体の損失4単位、又は主玉返済で残玉も全返済。'
        condition = f'主玉損切り8幅／カバー損切り2幅・起動{activation}幅・追尾{trail}幅／全玉損失4単位'
    allocation = '各新規はTOPIX10枚・日経20枚。両建てなら買い・売りそれぞれ同枚数。'
    if family in (7, 9):
        allocation = '1段はTOPIX2枚・日経4枚。片方向でTOPIX10枚・日経20枚まで。'
    elif family == 10:
        allocation = '2つの新規注文は各TOPIX5枚・日経10枚。合計TOPIX10枚・日経20枚。'
    elif family == 11:
        allocation = '主玉TOPIX10枚・日経20枚。反対カバーは1段TOPIX2枚・日経4枚、最大5段。'
    width_text = f'1幅＝{width}呼値（TOPIX {width * .5:g}ポイント／日経 {width * 10:g}ポイント）。'
    suffix = ' 1単位＝片方向上限枚数×1幅の値動きの金額。全玉停止の発動は現在値による概算損益、報告会計は売買気配で全返済した額。' if family in (7, 8, 11) else ''
    return dict(id=config['id'], name=config['name'], family=family, short=config['description'],
                condition=width_text + condition, entry=entry, during=during,
                exit=exit_text + ' 定めた場内清算時刻では残玉を全返済する。',
                execution=width_text + suffix + ' 発動は現在値。買いは当該行の最良売り気配ask、売りは最良買い気配bidで約定。',
                allocation=allocation, criteria=criteria or [])


def unique_methods(records):
    """
    機能: 複数観点で同じ条件が選ばれた場合、一手法として説明する。
    引数: records (list[dict]) は前半固定の選定記録。
    返り値: list[dict] の重複しない表示手法。
    """
    order, grouped = [], {}
    for record in records:
        if record['id'] not in grouped:
            order.append(record['id'])
            grouped[record['id']] = dict(config=record['config'], criteria=[], status=record['status'], sufficient=record['sufficient'])
        grouped[record['id']]['criteria'].append(record['criterion'])
    return [dict(describe(grouped[key]['config'], grouped[key]['criteria']),
                 status=grouped[key]['status'], sufficient=grouped[key]['sufficient']) for key in order]


# ----------------------------------------
def text_data(selection, family_page):
    """
    機能: 数値に依存しない会計と実行条件の説明を組み立てる。
    引数: selection (dict)、family_page (bool)。
    返り値: dict の要素ID別説明。
    """
    selection_text = '各家族24条件のうち、前16場で両商品の低い親組金額利益割合を優先して1条件を固定。12代表とも全30場を掲載します。' if family_page else f'前16場だけで「親組の金額利益割合」「赤字場の少なさ」「1親組あたりの効率」の3観点から固定。同じ条件が重なれば一つにまとめ、今回は{selection["primary_unique"]}手法です。'
    return {
        'selection-description': selection_text + ' 初回固定13条件に、全30場で両商品とも黒字の条件はありません。両商品とも親組20以上・取引した場8以上を活動基準とし、満たさない代表は参考扱いです。',
        'accounting-description': '金額利益割合＝利益÷（利益＋損失）。主表示は、玉がない状態から全玉返済までを1親組として損益をまとめます。「決済脚」へ切替えても最終収支は同じです。取引ゼロの場は休止で、勝ちに含めません。',
        'trade-unit-description': '1注文の新規・返済ごとに手数料を課し、円未満切捨て。TOPIXミニ片道41.8円／枚、日経マイクロ11円／枚。最大総玉は買い＋売り、最大差引玉は買い−売りの絶対値です。',
        'execution-assumptions': '同一原本行の有効気配で買いask・売りbid。気配がなければ次の有効気配を待ちます。指値条件の価格制約に合わないIOCは取消。基準価格は全玉終了後の待機開始時に置き直します。次の新規サイクル・追加、行末に即時約定した新規の通常返済監視は次行以降。後続行の冒頭で待機新規が約定した場合は、その観測で子条件を1回監視します。1行内で取引を無限に反復しません。日中15:33、夜間翌05:48以降は新規停止、15:34／翌05:49に場内全返済を発注します。',
        'split-description': '全30場は既に閲覧した保存相場です。前16場で幅と配分を選び、後14場の新しい再生結果では代表を選び直していません。この範囲の確認であり、未知の将来での安定性の証明ではありません。',
        'remaining-limitations': '指定時点で全量約定する仮定には限界があります。固定5秒待ちの成績は今回使いません。判断後5秒以内の最悪価格による確認とは別の条件です。注文管理だけで全市場に優位性がある、又はないという一般論は、この範囲だけで断定しません。',
    }


def default_conclusion(selection, results, train):
    """
    機能: 保存数値だけから未達・達成の範囲が分かる初期結論を作る。
    引数: selection/results (dict)、train (list[dict])。
    返り値: dict の短文と数量。採用判断を自動で肯定しない。
    """
    all_positive = [r['config']['id'] for r in results.values() if all(r['periods']['対象'][s]['net'] > 0 for s in SYMBOLS)]
    later_positive = [key for key in all_positive if all(results[key]['periods']['後14'][s]['net'] > 0 for s in SYMBOLS)]
    front_positive = [r['config']['id'] for r in train if all(r['periods']['前16'][s]['net'] > 0 for s in SYMBOLS)]
    return {
        '主文': f'方向予測を使わない288条件を比較し、前半固定の{len(results)}条件中、全30場で両商品とも黒字は{len(all_positive)}条件でした。',
        '補足': f'そのうち後14場でも両商品黒字は{len(later_positive)}条件。利益脚だけの成績で判断せず、全残玉と手数料を含めた親組単位で確認します。',
        '前半両黒字条件': front_positive, '全30両黒字条件': all_positive,
        '全30と後14両黒字条件': later_positive,
    }


def render(template, data, substitutions):
    """
    機能: 単体で開けるHTMLへJSON、CSS、JavaScriptを埋め込む。
    引数: template (str)、data (dict)、substitutions (dict[str,str])。
    返り値: str の完成HTML。
    """
    markup = (HERE / template).read_text(encoding='utf-8')
    values = dict(substitutions, STYLE=(HERE / 'style.css').read_text(encoding='utf-8'),
                  COMMON=(HERE / 'common.js').read_text(encoding='utf-8'),
                  DATA=json.dumps(data, ensure_ascii=False, separators=(',', ':'), allow_nan=False).replace('</', '<\\/'))
    for key, value in values.items():
        markup = markup.replace('__' + key + '__', value)
    assert '__DATA__' not in markup and '__SCRIPT__' not in markup
    return markup


def main():
    """
    機能: 固定結果を全件照合し、主代表・家族代表・全前半の3HTMLを生成する。
    引数: なし。入力は既存の確定結果だけを読み込む。
    返り値: None。戦略計算・代表選択・API取得は行わない。
    """
    fixed = read(WORK / 'results/事前固定.json')
    selection = read(WORK / '前半選定.json')
    assert len(fixed['catalog']) == 288 and len(fixed['全30']) == 30
    assert len(fixed['前16']) == 16 and len(fixed['後14']) == 14
    assert selection['後14を参照した選び直し'] is False
    results, ideal, ideal_fee, train = {}, {}, {}, []
    for key in selection['selected']:
        result = read(WORK / 'final/delay0/results' / (key + '.json'))
        check_result(result, fixed['全30'], fixed)
        assert result['run']['seed'] == 0
        results[key] = result
        contrast = read(WORK / 'ideal/results' / (key + '.json'))
        check_result(contrast, fixed['全30'], fixed)
        assert all(contrast['periods']['対象'][s]['fees'] == 0 and contrast['periods']['対象'][s]['spread_drag'] == 0 for s in SYMBOLS)
        ideal[key] = contrast
        intermediate = read(WORK / 'ideal_fee/results' / (key + '.json'))
        check_result(intermediate, fixed['全30'], fixed)
        assert all(intermediate['periods']['対象'][s]['spread_drag'] == 0 for s in SYMBOLS)
        ideal_fee[key] = intermediate
    for config in fixed['catalog']:
        result = read(WORK / 'train/results' / (config['id'] + '.json'))
        check_result(result, fixed['前16'], fixed)
        assert result['config'] == config and result['run']['seed'] == 0
        train.append(result)
    sensitivity = read(WORK / 'sensitivity/無作為20種の比較.json')
    assert [r['seed'] for r in sensitivity['rows']] == list(range(20))
    for row in sensitivity['rows']:
        raw = read(WORK / f'sensitivity/seed{row["seed"]:02d}/results' / (sensitivity['config']['id'] + '.json'))
        check_result(raw, fixed['全30'], fixed)
        assert row['metrics'] == raw['periods']['対象']
    theory = read(WORK / 'theory/注文管理だけで利益を生む仮説と10家族.json')
    diagnosis_source = read(WORK / 'diagnosis/12家族代表の損失構造.json')
    diagnosis = {row['config']['id']: row for row in diagnosis_source['families'] + diagnosis_source.get('primary_extra', [])}
    persistent_spec = read(WORK / 'persistent/固定条件.json')
    assert persistent_spec['変数の選び直し'] is False
    persistent = []
    for key in persistent_spec['対象']:
        changed = read(WORK / 'persistent/results' / (key + '.json'))
        check_result(changed, fixed['全30'], fixed)
        assert changed['config'] == results[key]['config']
        persistent.append(dict(parent_id=key, config=changed['config'], original=results[key], result=changed))
    assert len(persistent) == 3
    summary_path = HERE / '結論文.json'
    conclusion = read(summary_path) if summary_path.exists() else default_conclusion(selection, results, train)
    if not summary_path.exists():
        write_json(summary_path, conclusion)
    PUBLIC.mkdir(parents=True, exist_ok=True)
    generated = {}
    for filename, records, family_page in [(MAIN, selection['primary'], False), (FAMILY, selection['families'], True)]:
        methods = unique_methods(records)
        data = dict(methods=methods, final={'0': {m['id']: results[m['id']] for m in methods}},
                    sessions=fixed['全30'], selection=records, conclusion=conclusion, sensitivity=sensitivity,
                    ideal={m['id']: ideal[m['id']] for m in methods},
                    ideal_fee={m['id']: ideal_fee[m['id']] for m in methods}, diagnosis=diagnosis,
                    persistent=persistent, persistent_spec=persistent_spec,
                    persistent_description='全30場を確認した後の仮説修正です。主2条件とグリッド代表の数値を固定したまま、不成立ですぐ取り消すIOCをやめ、指値を保持。対向気配が指値以内へ到達したら、元の指値で全量約定と仮定します。有利な気配への価格改善は与えません。待機後の新規が後続行の冒頭で約定した場合は、その観測の現在値で返済条件を1回監視します。期限・全玉損失停止で未約定も取消。注文維持と約定モデルの比較であり、待ち順位・板量・部分約定の再現はありません。',
                    sources=theory['一次資料'], text=text_data(selection, family_page))
        write_json(HERE / ('家族別描画資料.json' if family_page else '主代表描画資料.json'), data)
        markup = render('template.html', data, dict(TITLE=html.escape(filename[:-5]), HEADING=html.escape(filename[:-5]),
            SIBLING=MAIN if family_page else FAMILY, SIBLING_LABEL='主代表の説明と全場損益' if family_page else '12家族すべての説明と全場損益',
            ALL=ALL, SCRIPT=(HERE / 'main.js').read_text(encoding='utf-8')))
        path = PUBLIC / filename
        path.write_text(markup, encoding='utf-8')
        generated[filename] = hashlib.sha256(path.read_bytes()).hexdigest()
    all_data = dict(rows=[dict(config=r['config'], name=r['config']['name'], condition=describe(r['config'])['condition'],
                              metrics=r['periods']['前16']) for r in train],
                    families=[dict(id=r['family'], name=r['config']['name']) for r in selection['families']],
                    intro='12家族×6つの幅×4種類の出口・配分、計288条件。判断当該行の売買気配で即時約定、手数料後。利益と損失は全玉返済までの親組単位。前16場だけの探索であり、同じ家族・幅の似た条件を独立した成功例として数えません。')
    write_json(HERE / '全前半描画資料.json', all_data)
    markup = render('all_template.html', all_data, dict(MAIN=MAIN, SCRIPT=(HERE / 'all.js').read_text(encoding='utf-8')))
    (PUBLIC / ALL).write_text(markup, encoding='utf-8')
    generated[ALL] = hashlib.sha256((PUBLIC / ALL).read_bytes()).hexdigest()
    write_json(HERE / '生成結果.json', dict(HTML=generated, 入力SHA256=SOURCES,
        照合='全288前半・固定代表全30・無費用対照・気配差なし実手数料対照・指値保持3条件・乱数20種について全場/期間会計、親組と脚の収支一致、片方向枚数上限、指定追加遅延0を照合。指値保持は気配到達まで待機。',
        主手法数=selection['primary_unique'], 家族数=len(selection['families']), 最終一意条件数=len(results)))
    print(json.dumps(generated, ensure_ascii=False))


if __name__ == '__main__':
    main()
