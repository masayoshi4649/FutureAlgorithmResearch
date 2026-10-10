"""数量調整の比較と、全条件の週・セッション損益を短いダークHTMLにする。"""

from __future__ import annotations

import argparse
from html import escape
import sys

import partial_runner as runner
import partial_assessment as assessment

sys.path.insert(0, str(runner.HERE.parent/'wave_v35'))
import report_conditional as previous
import deterioration_signals

HERE, ROOT = runner.HERE, runner.ROOT
TITLE = '悪化時の部分減量と回復後の数量復元'
OUT = ROOT/'アルゴリズム調査'/('00032_'+TITLE)
style = previous.style
CONDITIONS = {r['id']: r['name'] for r in deterioration_signals.catalog()}
LABELS = {'A0': '元の数量を維持', 'CORE50': '最初から固定コア', 'SMALL50': '最初から少枚数・半分利確',
    'B06_NONE_F50': '悪化で減量したまま', 'B06_T120_F50_N1': '悪化で減量・120秒で復元',
    runner.design.PRIMARY_POLICY: '悪化で減量・回復で復元（主案）'}


def description(spec: dict) -> str:
    """機能: 固定条件を簡潔な日本語へ変換する。

    引数: spec (dict)。返り値: 説明 (str)。
    """
    p = spec['policy']
    if p['kind'] == 'baseline':
        text = '初回TOPIX5枚／NK10枚を元の返済条件まで保つ。'
    elif p['kind'] in ('static_core', 'static_split'):
        quantity = 'TOPIX4枚／NK8枚' if p['reduce_fraction'] == .25 else 'TOPIX3枚／NK5枚'
        text = '初回から'+quantity+'。元の退出価格を共用し、'
        text += '元の後半保有枠を優先して残す。' if p['kind'] == 'static_core' else '最初の利確では実初回の半分を返済する。'
    else:
        text = CONDITIONS[p['bad_id']]+'が保有と反対になれば、生存枠の'+str(round(p['reduce_fraction']*100))+'%を減らす（整数丸め・最低1枚を残す）。'
        if p['restore_mode'] == 'none': text += '復元しない。'
        elif p['restore_mode'] == 'timer': text += '減量後120秒以降の新しい有効な自市場公開で元の数量へ戻す。'
        else: text += '減量後に新しく公開された'+CONDITIONS[p['good_id']]+'が保有方向を肯定したら戻す。'
        text += f'減量は元の取引1組につき{p["max_reductions"]}回まで。元の利確で終了した枠は復元しない。'
    text += '入口'+spec['signal_id']+'。'
    if spec['variant_id'] != 'V000':
        text += f'診断：入口時間×{spec["entry_scale"]:g}、悪化窓×{spec["bad_scale"]:g}、回復窓×{spec["good_scale"]:g}。'
    if spec['observed_fill']: text += 'この診断は観測価格で約定。'
    if spec['random_seed'] is not None: text += '回復だけ公開イベントごとの固定乱数符号で変える補助対照。'
    return text


def money_tables(rows: list[dict], identifier: str, sessions: list[str]) -> str:
    """機能: 全期間・各週・各セッションの金額と延べ返済枚数を示す。

    引数: rows (list[dict])、identifier (str)、sessions (list[str])。返り値: HTML (str)。
    """
    body = []
    for symbol in runner.SYMBOLS:
        part = sorted((r for r in rows if r['symbol'] == symbol), key=lambda r: r['session'])
        assert len(part) == 13
        output = [style.money_row(label, style.totals([r for r in part if r['session'] in names]))
            for label, names in (('全13', sessions), ('共通後半7', sessions[6:]),
                ('9/21開始週', [s for s in sessions if s < '2026-09-28']),
                ('9/28開始週・途中', [s for s in sessions if s >= '2026-09-28']))]
        output += [style.money_row(r['session'], r) for r in part]
        body += ['<h3>'+symbol+'</h3>', style.table(
            ['区間', '利益 円', '損失 円', '収支 円', '利益枚数', '損失枚数', '同値枚数', '勝ち−負け枚数'],
            output, f'data-id="{identifier}" data-symbol="{symbol}"')]
    return ''.join(body)


def all_results(items: list[dict], sessions: list[str], preview: bool) -> None:
    """機能: 全427条件を個別選択できる章として出力する。

    引数: items (list[dict])、sessions (list[str])、preview (bool)。返り値: なし (None)。
    """
    primary = runner.design.PRIMARY_ID
    body = [f'<p><a href="{TITLE}.html">比較へ</a></p><h1>全条件の損益</h1>',
        '<p>主309・診断54・補助64。数量は延べ返済枚数です。勝ち−負け枚数は数量差であり、損益額でも現在の保有数でもありません。</p>',
        '<label>手法<select id="method-filter">'+''.join(f'<option value="{r["id"]}"'+
            (' selected' if r['id'] == primary else '')+'>'+escape(r['id'])+'</option>' for r in items)+'</select></label>']
    for item in items:
        identifier, spec = item['id'], item['spec']
        destination = 'supplementary' if spec['role'] == 'supplementary' else ''
        rows = runner.read(HERE/destination/'sessions'/(identifier+'.json.gz'))
        body += [f'<section class="method" id="{identifier}"'+(' hidden' if identifier != primary else '')+'>',
            '<h2>'+escape(identifier)+'</h2><p>'+escape(description(spec))+'</p>',
            money_tables(rows, identifier, sessions), '</section>']
    if preview: body.insert(1, '<p><strong>独立監査中の暫定表示。</strong></p>')
    script = '''/**
 * 選択した固定手法の表示だけを切り替える。
 * @param {Event|undefined} event - 選択操作。
 * @returns {undefined} 返り値なし。売買条件には触れない。
 */
function filter(event){const value=document.getElementById('method-filter').value;document.querySelectorAll('.method').forEach(e=>e.hidden=e.id!==value)}const choice=document.getElementById('method-filter');const requested=decodeURIComponent(location.hash.slice(1));if(Array.from(choice.options).some(o=>o.value===requested))choice.value=requested;choice.addEventListener('change',filter);filter();'''
    (OUT/'全条件損益.html').write_text(style.page('全条件の損益', body, script), encoding='utf-8')


def main() -> None:
    """機能: 固定主案と単純対照の比較を、全損益と共に出力する。

    引数: --preview (bool)。返り値: なし (None)。正式版は独立完備監査を要求する。
    """
    parser = argparse.ArgumentParser(); parser.add_argument('--preview', action='store_true')
    preview = parser.parse_args().preview
    if not preview:
        proof = runner.read(HERE/'完備監査.json')
        assert proof['検証完了'] and proof['全条件数'] == 363 and proof['補助条件数'] == 64
        for name, sha in proof['参照資料SHA256'].items(): assert runner.digest(ROOT/name) == sha
    items = runner.read(HERE/'全条件の期間集計.json.gz')
    extras = runner.read(HERE/'supplementary/全条件の期間集計.json.gz')
    index = {r['id']: r for r in items+extras}
    sessions = runner.read(HERE/'探索条件の固定.json')['全セッション']
    verdict = runner.read(HERE/('暫定判定.json' if preview else '独立判定.json'))
    primary = index[runner.design.PRIMARY_ID]
    chosen = [(label, index['H019__'+policy+'__V000']) for policy, label in LABELS.items()]
    passed = verdict['既知比較の採用候補']
    outcome = '既知データ内の改善基準を通過しました。未知相場は未確認です。' if passed else '部分減量・復元で収支は改善。回復判断の優位は銘柄で異なります。'
    diagnosis = runner.read(HERE/'全格子の機序診断.json')
    body = ['<p><a href="../index.html">作業一覧</a></p><h1>'+TITLE+'</h1>',
        '<p class="lead"><strong>'+outcome+'</strong></p>',
        '<p>同じ入口から、減量のみ・回復で復元・時間で復元・少枚数を比較しました。主案は結果前にB06・50%減量・復元1回へ固定しています。</p>',
        '<p>主案の収支はTOPIX +546,500円、NK +264,900円。元の数量維持より+25,500円／+7,400円でした。NKの最大下落は減りましたが、TOPIXは3,500円増加。時間だけで戻す対照も改善しており、回復予測が利益の原因だとはまだ言えません。</p>',
        '<p><a class="button" href="全条件損益.html">週・セッション別の金額／枚数</a><a class="button" href="５分足と売買.html">５分足と売買</a></p>',
        '<h2>全13セッションの比較</h2>', previous.main_table(chosen, 'all_symbols'),
        '<p class="muted">TOPIXミニ換算／NKマイクロ換算。原本は先物価格。初回5／10枚、片方向上限10／20枚。費用0・指定価格約定・場内全返済。最大下落は含み損益込み。銘柄間の円額は単純比較しません。</p>',
        '<p class="muted">A0は今回の対照管理IDで、入口H019＋固定D273返済を意味します。少枚数の対照は初回TOPIX3枚／NK5枚です。</p>',
        '<details><summary>後半7セッション</summary>', previous.main_table(chosen, 'symbols'), '</details>',
        '<details><summary>売買条件</summary><p>入口H019：公開済み1分足EMA15/60の方向、60秒遅れの他銘柄、直近30秒の気配変化が一致したら新規を準備。0.25ATRの新規トレーリングを使います。</p>',
        '<p>主案B06：自市場と60秒遅れの相手市場で、直近2分と30秒の気配価格が同じ方向へ十分動いたことを確認。保有と反対なら半量を減らし、その後の新しい情報が保有方向へ揃ったら戻します。判断の次の有効観測行で執行します。</p>',
        '<p>元の条件は初回ATRで固定。1ATRの組損失予算、2ATRで元枠の半分利確、1.5ATR順行後3ATR追跡、最長360分。減量・復元の損失も組全体へ加算し、元の利益確定で終了した枠は再開しません。予算超過は次の観測や注文競合で起こり得ます。</p>',
        '<p>他の308管理では、単独の価格、板フロー、両銘柄の価格と板など8根拠を減量と回復へ別指定。25%/50%減量、1回/3回を比較しています。</p></details>',
        '<details><summary>減量と復元の作動</summary>', style.table(
            ['銘柄', '期間', '減量回数', '復元回数', '減量／復元枚数', '実予算予約後の返済超過 円', '予約後の最大遅延 秒'],
            [[symbol, '全13' if period == 'all_symbols' else '後7', str(primary[period][symbol]['reductions']),
                str(primary[period][symbol]['restorations']), f'{primary[period][symbol]["reduced_units"]}／{primary[period][symbol]["restored_units"]}',
                style.yen(primary[period][symbol]['budget_excess_yen']), f'{primary[period][symbol]["maximum_budget_latency_seconds"]:.2f}']
                for period in ('all_symbols', 'symbols') for symbol in runner.SYMBOLS]),
        '<p>上表の超過は実予算予約を経た返済だけです。元の予約注文で終了した場合を含む全組のR超過とは分けます。減量は純数量を減らす操作であり、同約定の両建てとは資産全体で同じ効果です。利確脚の多さを独立の利益源と数えません。</p></details>',
        '<details><summary>敵対検証と採否の内訳</summary>', style.table(['検査', '結果'],
            [[name, '通過' if value else '未通過'] for name, value in verdict['経済検査'].items()]),
        '<p>入口・悪化窓・回復窓を個別に±20%変更し、観測価格での約定も診断。回復だけを公開ごとの乱数符号へ変える64対照、最大勝ち除外、指定8波を確認します。詳細数値は<a href="../../work/wave_v37/独立判定.json">独立判定</a>。</p>',
        '<p>指定8波では正方向を20分以上保有できましたが、TOPIXの2波は各−3,000円でした。波への参加と利益化は別です。入口の時間を変えると黒字は残っても収支・最大下落が大きく悪化する例があり、強い頑健性までは示していません。</p>',
        '<p>全13は既知データで、後7も真の未知検証ではありません。初期6は祝日開始に偏ります。乱数対照は非0の公開機会を残すため、市場情報を完全に消した対照でも正式なp値でもありません。</p></details>',
        '<details><summary>何が利益を増やしたか</summary><p>主案のA0差は、TOPIXで減量中の差+10,500円・早い予算返済の差+15,000円、NKで+1,400円・+6,000円でした。復元後の利益をここへ重ねて足すと二重計上になります。</p>',
        '<p>回復符号を乱した64対照より、TOPIXは収支が全て上、NKは最大下落が全て小さい結果でした。ただしTOPIXは下落幅、NKは収支で中央値を上回れず、両指標の同時改善基準は未達です。</p>',
        '<p><a href="../../work/wave_v37/枠差の分解と解釈.md">全組対応の差額分解と損失予算超過</a></p></details>',
        '<details><summary>ほかの条件に有望なものはあったか</summary><p>主格子309条件は全て、両銘柄・全13/後7で黒字、平均の勝ち元組が負け元組を上回り、最大の勝ちを除いても非負でした。元の入口自体の好成績を、多数の独立した証拠とは数えません。</p>',
        '<p>そのうち'+str(len(diagnosis['A0同時改善IDs']))+'条件で、4区分すべての収支がA0以上、最大下落がA0以下になりました。同値も含みます。以下は追加検証の候補で、主案の事後差し替えではありません。</p>',
        style.table(['方式ID（詳細）', 'TOP収支 円', 'TOP最大下落 円', 'NK収支 円', 'NK最大下落 円'],
            [[f'<a href="全条件損益.html#{r["id"]}">{r["policy"]["id"]}</a>', style.yen(r['全期間']['TOPIX']['net_yen']), style.yen(r['全期間']['TOPIX']['drawdown_yen']),
              style.yen(r['全期間']['NK225']['net_yen']), style.yen(r['全期間']['NK225']['drawdown_yen'])]
             for r in diagnosis['全格子'] if r['A0比較']['同時改善']]),
        '<p>8条件中5条件は時計復元で、入口は共通です。独立した8件の成功とは数えません。主案と同じ感度・符号対照をまだ実施していないため、8条件すべてを次に反証します。</p></details>',
        '<p><a href="README.md">資料案内・再現手順</a></p>']
    if preview: body.insert(1, '<p><strong>独立監査中の暫定表示。</strong></p>')
    OUT.mkdir(exist_ok=True)
    (OUT/(TITLE+'.html')).write_text(style.page(TITLE, body), encoding='utf-8')
    all_results(items+extras, sessions, preview)
    print('比較と全427条件の週・セッション損益を出力。', flush=True)


if __name__ == '__main__':
    main()
