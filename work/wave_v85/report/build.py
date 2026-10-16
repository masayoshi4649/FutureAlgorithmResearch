"""原E01と固定した改修の会計を照合し、短い暗色HTMLへまとめる。"""

import gzip
import hashlib
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = HERE.parents[2]
PUBLIC = ROOT / 'アルゴリズム調査/00081_E01原版と知見統合改修の再検証'
MAIN = 'E01原版と改修の説明と全セッション損益.html'
DETAIL = '検証詳細.html'
ALL = '全25条件の比較.html'
SYMBOLS = ('TOPIX', 'NK225')
SOURCES = {}


def read(path):
    """
    機能: 保存済みJSONを読み、公開資料の入力指紋を記録する。
    引数: path (Path) は通常又は圧縮JSONのパス。
    返り値: dict又はlist の復元資料。
    """
    raw = path.read_bytes()
    SOURCES[str(path.relative_to(ROOT)).replace('\\', '/')] = hashlib.sha256(raw).hexdigest()
    return json.loads(gzip.decompress(raw) if path.suffix == '.gz' else raw)


def save(path, value):
    """
    機能: 日本語と有限数値でJSONを保存する。
    引数: path (Path)、value (dict又はlist)。
    返り値: None。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + '\n', encoding='utf-8')


def verify_result(result, fixed, model):
    """
    機能: 30場の会計・数量・親組と部分返済の一致を検査する。
    引数: result/fixed (dict)、model (str)。
    返り値: None。不一致は公開前に例外として止める。
    """
    assert result['model'] == model
    rows = result['rows']
    names = fixed['全30']
    assert result['run']['model'] == model and result['run']['delay'] == 0
    assert result['run']['sessions'] == names
    assert len(rows) == 60
    assert {(r['session'], r['symbol']) for r in rows} == {(n, s) for n in names for s in SYMBOLS}
    fields = ('profit', 'loss', 'net', 'gross', 'fees', 'winning_lots', 'losing_lots', 'flat_lots',
              'new_lots', 'exit_lots', 'campaign_profit', 'campaign_loss', 'campaigns',
              'campaign_wins', 'campaign_losses')
    for row in rows:
        initial = 5 if row['symbol'] == 'TOPIX' else 10
        assert row['max_long'] <= initial and row['max_short'] <= initial
        assert row['max_gross'] <= initial
        assert row['residual_long'] == row['residual_short'] == 0
        assert row['new_lots'] == row['exit_lots'] == row['settled_lots']
        assert abs(row['profit'] - row['loss'] - row['net']) < 1e-6
        assert abs(row['campaign_profit'] - row['campaign_loss'] - row['net']) < 1e-6
        assert abs(row['gross'] - row['fees'] - row['net']) < 1e-6
    for period, selected in [('前16', fixed['前16']), ('後14', fixed['後14']), ('全30', names)]:
        for symbol in SYMBOLS:
            subset = [r for r in rows if r['symbol'] == symbol and r['session'] in selected]
            account = result['periods'][period][symbol]
            for key in fields:
                assert abs(sum(r[key] for r in subset) - account[key]) < 1e-6, (result['config']['id'], period, symbol, key)
            assert account['positive_sessions'] == sum(r['net'] > 0 for r in subset)
            assert account['no_trade_sessions'] == sum(r['campaigns'] == 0 for r in subset)
            total = account['campaign_profit'] + account['campaign_loss']
            expected = account['campaign_profit'] / total if total else None
            assert account['cycle_profit_share'] == expected
    assert result['periods']['対象'] == result['periods']['全30']


# ----------------------------------------
def describe(config):
    """
    機能: 原E01と今回の部品の違いを入口・途中・出口へ分ける。
    引数: config (dict) は事前固定した条件。
    返り値: dict の平易な説明。
    """
    parts = config['parts']
    entry = '両市場のEMA15/60の主方向が一致し、短期の板中値が支持したら待機。0.25ATRの反発で買い、反落で売る。'
    if 'G' in parts:
        entry += '【G】待機中も両市場のEMA開始条件を再要求し、古い方向だけでの準備を抑える。'
    during = '2ATR順行で一部利確。通常影が1.5ATR進んだ後、新しい短期逆行で残す枠を一度半減する。追加・復元はしない。'
    if 'D' in parts:
        during += '【D】まだ1.5ATRへ進まず0.25ATR逆行し、両市場の新しい短期悪化が一致した時にも半減する。半減枠は元の処理と共用。'
    exit_text = '初期損失枠0.75ATR。1.5ATRから幅3ATRで追跡し、3ATR順行後は幅0.75ATRへ縮める。最長360分・場内返済を維持。'
    if 'P' in parts:
        exit_text += '【P】実組の料金後評価が1.5Rへ届いた後、最高利益の半分まで戻したら残玉を返済する。'
    restart = '早期返済後も通常影の終了＋5分まで次の入口を待つ。'
    if 'C' in parts:
        restart += '【C】同方向で2組連敗したらその方向を停止。停止後に両市場のEMA開始条件が崩れ、新しい資料で再成立した後に再開する。'
    suffix = config.get('time_mode', '')
    if suffix in ('J', 'U', 'JU'):
        windows = {'J': '日本開始後08:45〜09:15', 'U': '米国現物開始の前後15分',
                   'JU': '日本開始後08:45〜09:15と米国現物開始の前後15分'}
        entry += '【時間見送り】' + windows[suffix] + 'は新規を止める。'
        exit_text += '対象時間の開始以降、最初の有効観測の現在値で保有玉も返済する。'
        restart += '時間帯が終わっても古い待機は使わず、通常影の時計を保ったまま新しい準備を待つ。'
    return dict(entry=entry, during=during, exit=exit_text, restart=restart,
                short='追加部品なし' if not parts else '・'.join(parts))


def old_comparison(results):
    """
    機能: 前作業28場と今回の同一範囲、追加2場の収支を分ける。
    引数: results (dict) はモデル別・条件別の今回結果。
    返り値: list[dict] の旧範囲との接続表。
    """
    values = []
    for model in ('observed', 'specified'):
        for identifier, old_id in [('E01', 'E01'), ('E01_G', 'R01')]:
            old = read(ROOT / 'work/wave_v67' / model / (old_id + '.json.gz'))
            old_names = {r['session'] for r in old['rows']}
            current = results[model][identifier]
            for symbol in SYMBOLS:
                before = sum(r['net'] for r in old['rows'] if r['symbol'] == symbol)
                same = sum(r['net'] for r in current['rows'] if r['symbol'] == symbol and r['session'] in old_names)
                added = sum(r['net'] for r in current['rows'] if r['symbol'] == symbol and r['session'] not in old_names)
                assert abs(before - same) < 1e-5, (model, identifier, symbol, before, same)
                values.append(dict(model=model, id=identifier, symbol=symbol, previous=before,
                                   same28=same, added2=added, total=current['periods']['全30'][symbol]['net']))
    return values


def collect():
    """
    機能: 全50保存結果を検査し、描画に必要な資料を集める。
    引数: なし。
    返り値: dict の描画資料。
    """
    fixed = read(WORK / 'results/事前固定.json')
    assert len(fixed['catalog']) == 25
    results = {}
    for model in ('observed', 'specified'):
        results[model] = {}
        for config in fixed['catalog']:
            current = read(WORK / model / 'results' / (config['id'] + '.json'))
            assert current['config'] == config
            verify_result(current, fixed, model)
            results[model][config['id']] = current
    conclusion_path = HERE / '結論文.json'
    conclusion = read(conclusion_path) if conclusion_path.exists() else {
        '要旨': '原E01・入口再確認・4部品統合を、結果で差し替えず比較しました。指定された時間見送りも同条件で比べています。',
        '補足': '改修が有効かは両商品と前後期間を分けて評価します。過去30場はすべて既知です。'}
    components = read(WORK / 'analysis/4部品の有無比較.json')
    selected = [r for r in components['summaries']
                if r['model'] == 'observed' and r['period'] == '全30' and r['部品'] in ('P', 'D')]
    assert len(selected) == 4 and all(r['収支悪化数'] == 8 for r in selected)
    return dict(fixed={key: fixed[key] for key in ('catalog', 'primary', '全30', '前16', '後14', 'catalog_specification')},
                results=results, descriptions={c['id']: describe(c) for c in fixed['catalog']},
                old_comparison=old_comparison(results), conclusion=conclusion,
                parts_evidence={'対象': components['対象'], 'summaries': components['summaries']})


def render(template_name, script_name, destination, data):
    """
    機能: 自己完結した暗色HTMLへ資料と表示コードを埋め込む。
    引数: template_name/script_name (str)、destination (Path)、data (dict)。
    返り値: None。
    """
    text = (HERE / template_name).read_text(encoding='utf-8')
    replacements = {'__STYLE__': (HERE / 'style.css').read_text(encoding='utf-8'),
                    '__COMMON__': (HERE / 'common.js').read_text(encoding='utf-8'),
                    '__SCRIPT__': (HERE / script_name).read_text(encoding='utf-8'),
                    '__DATA__': json.dumps(data, ensure_ascii=False, allow_nan=False).replace('</', '<\\/'),
                    '__MAIN__': DETAIL, '__ALL__': ALL}
    for key, value in replacements.items():
        text = text.replace(key, value)
    if destination.name == DETAIL:
        text = text.replace('<body><main>', '<body><main><p class="links"><a href="' + MAIN + '">短い結論へ戻る</a></p>', 1)
    assert not any(key in text for key in replacements)
    destination.write_text(text, encoding='utf-8')


def main():
    """
    機能: 短い結論・検証詳細・全比較の3HTMLと入力指紋を保存する。
    引数: なし。
    返り値: None。
    """
    data = collect()
    PUBLIC.mkdir(parents=True, exist_ok=True)
    save(HERE / '描画資料.json', data)
    render('template.html', 'main.js', PUBLIC / DETAIL, data)
    render('all_template.html', 'all.js', PUBLIC / ALL, data)
    spec = importlib.util.spec_from_file_location('wave85_brief_report', HERE / 'brief.py')
    brief = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(brief)
    brief.main()
    proof = dict(全50結果の会計検査=True, 旧28場の原E01とR01収支一致=True,
                 入力SHA256=SOURCES,
                 公開SHA256={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (PUBLIC / MAIN, PUBLIC / DETAIL, PUBLIC / ALL)})
    save(HERE / '生成結果.json', proof)
    print(json.dumps(proof['公開SHA256'], ensure_ascii=False))


if __name__ == '__main__':
    main()
