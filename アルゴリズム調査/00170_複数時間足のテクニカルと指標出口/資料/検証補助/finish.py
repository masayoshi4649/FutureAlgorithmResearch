"""全結果の短い入口と再現手順、表示監査の参照だけを永続化する。"""
import hashlib
import json
import shutil
from pathlib import Path
from urllib.parse import urlencode


def money(x):
    """
    機能: 符号付き金額を表示。引数:x(float)。返り値:str。
    """
    return f'{x:+,.0f}'


def sha(path):
    """
    機能: 資料の指紋を計測。引数:path(Path)。返り値:str。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    """
    機能: 完了済みの成績と小容量資料の参照をまとめる。引数:なし。返り値:None。
    """
    here=Path(__file__).resolve().parent;root=here.parents[1]
    study=root/'アルゴリズム調査/00170_複数時間足のテクニカルと指標出口'
    groups=json.loads((here/'validation.json').read_text(encoding='utf-8'))['groups']
    fixed=json.loads((study/'選定固定.json').read_text(encoding='utf-8'))
    assert sha(here/'rootselection.json')==fixed['selection_sha256']
    assert sha(here/'summary.json')==fixed['source_sha256']
    names={'F09A_I':'BB突破失敗からの反発、指標で返済','F10B_I':'DMI交差とADX上昇に追随、支持低下で返済',
           'F09B_F':'BB突破失敗からの反発、指標返済＋利益床','F03B_F':'方向が弱い時のRSI回復、指標返済＋利益床'}
    lines=['# 複数時間足のテクニカルと指標出口','','**今回の72条件から、セッションごとに安定して利益を出せる手法は確認できなかった。** 前半の相対上位4枠を固定すると、後半は3枠が赤字。残るTOPIX日中も12場で新規1回だけであり、有望と認定しない。','','過去の手法・成績を方式設計へ使わず、MA・RSI・MACD・ボリンジャーバンド・DMIの12仮説を新規に定義した。1/3/5分と1/5/15分、指標出口・トレール対照・早期利益床を比較した。日経225mini10枚、TOPIXmini10枚、手数料0。正常な気配差を含む。','','| 固定候補 | 対象 | 検討収支 | 確認収支 | 全利益 | 全損失 | 全収支 | 赤字場 / 全場 | 無取引場 |','|---|---|---:|---:|---:|---:|---:|---:|---:|']
    for g in groups:
        e=g['evaluations'][g['method_id']];a=e['全完全場'];t=e['検討'];v=e['確認'];symbol='日経' if g['symbol']=='NK225' else 'TOPIX';kind='日中' if g['kind']=='Day' else '夜間'
        lines.append(f"| [{g['algorithm_id']}](損益/{symbol}_{g['method_id']}.md) | {kind} | {money(t['net'])} | {money(v['net'])} | {a['profit']:,.0f} | {a['loss']:,.0f} | {money(a['net'])} | {a['negative']} / {a['sessions']} | {a['no_trade']} |")
    lines.extend(['','金額は円。利益・損失は新規から全返済までの決済損益を正負に分けた合計で、損失は正数。無取引を勝ちに数えない。候補は各銘柄の前34場だけで選び、後23場の結果では選び直していない。この順位規則が無取引の多い候補を上位にしたことも今回の問題として残す。既存保存データなので完全未見の検証とは称さない。','','| 手法 | 簡単な内容 |','|---|---|'])
    for g in groups:lines.append(f"| {g['algorithm_id']} | {names[g['method_id']]} |")
    lines.extend(['','入口・継続・通常返済・ドテンは確定した指標で判定し、利益追尾と非常停止は原板の更新ごとに監視する。I/FとTは同じ入口式でも、その後の保有時間が変わるので全取引の入口時刻まで一致する比較ではない。','','## 確認できたこと','','- 指標を増やすだけでは安定しなかった。検討黒字だったI/Fの18区分中、確認でも黒字は2区分。テクニカル一般の不可能性を証明した結果ではない。','- 利益を早く守る部品には局所効果があった。日経10月16日日中の同入口では、I/Tの−20万円に対しFは0円。ただし後からその日だけFへ切り替えるのは不可。','- 指標出口も常に改善ではない。日経夜間の固定候補は、初回入口が一致する25場でIが−39万円、Tが−28万円。TOPIX夜間の11場ではFが＋1万円、Iが−8.5万円、Tが−15万円。入口を揃えた範囲で効果が異なる。','- 0.01%の利益床は利益の保証ではない。判断後の次の正常気配までに戻され、0円返済になる例もあった。','','## 見る資料','','- [全72条件の比較と、各手法の全57セッション損益](全候補と損益.md)','- [SessionViewer用のリンク列挙](比較.resources.json)：固定4枠とI/T対照、計285リソース。既存原板と実約定JSONLだけを参照。','- [具体的な損失時刻・原行と同入口の出口比較](損失経路の確認.md)','- [原板で確認した具体例](原板で確認した具体例.md)','- [12仮説の確認結果](指標仮説の確認結果.md)','- [方式の機械条件](方式仮説.md) ／ [固定計画](計画.json) ／ [結果監査](結果監査.json)','','Viewerを起動し、「サーバー上の一覧ファイル」に次を指定する。日付・手法・raw/1/5/15分を画面で選べる。','','```text',str(study/'比較.resources.json'),'```','','## 検証・保存範囲','','2026-09-21日中～2026-10-29日中、各銘柄57場、全114原板・16,793,047行を物理行順に再生した。新規判断より後の正常行の買いはSell1、売りはBuy1で約定し、同時計でも原行順を保存。予定終了10分前から新規停止、6分前に場内返済を判断した。今回の全8208結果で残玉ゼロ、最終未約定ゼロ、EOF代理返済ゼロ。','','「完全場」は終了前6分以内の価格観測を確認した意味で、中間が無欠測という意味ではない。価格時計の最大間隔は1127秒。出来高時計nullを約定の証拠にせず、異常気配を約定へ使わない。完全なmini板や実約定待ち行列を再現した研究ではない。ラージのBBOによる共通執行モデルである。','','実装の人工テスト、Go静的検査、572,975項目の会計・件数監査、選定285結果の詳細再生一致、Viewerの数値/画像3組の指紋と最終会計を照合した。運用アプリ・ルール・distは変更していない。','','原板・全tickの保有/損益・画像は研究フォルダへ複製しない。Markdownに全損益を残し、Viewerは約定JSONLから復元する。スプレッドシートは新規作成しない。','','指標の出典：[マネックスの指標一覧](https://info.monex.co.jp/technical-analysis/indicators/)。条件や参加者心理の説明は本研究の仮説であり、同社が収益性を保証したものではない。',''])
    text='\n'.join(lines).replace('既存原板と実約定JSONL','既存原板と研究の模擬約定JSONL')
    text=text.replace('正常な気配差を含む。','正常な気配差を含む。執行はラージのBBOをmini倍率で評価する共通モデルで、実際のmini板の流動性は未検証。価格感応度はラージ1枚＝mini10枚相当だが、商品の板は同一ではない。')
    text=text.replace('初回入口が一致する25場でIが','初回入口が一致する25場の各初回取引だけではIが').replace('TOPIX夜間の11場ではFが','TOPIX夜間の11場の各初回取引だけではFが')
    (study/'README.md').write_text(text,encoding='utf-8')
    # ----------------------------------------
    # 画像本体・派生全状態は保存せず、同じViewer要求と指紋だけ残します。
    checks=json.loads((here/'visual-checks.json').read_text(encoding='utf-8'))
    (study/'表示確認.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (study/'確認集計.json').write_text((here/'validation.json').read_text(encoding='utf-8'),encoding='utf-8')
    # ----------------------------------------
    # 未完が一場もない今回に限り、未使用の含み列を明細から省きます。
    audit=json.loads((study/'結果監査.json').read_text(encoding='utf-8'))
    if not audit['未完場']:
        for detail in (study/'損益').glob('*.md'):
            text=detail.read_text(encoding='utf-8');lines=[]
            for line in text.splitlines():
                if line.startswith('|'):
                    cells=line.split('|')[1:-1]
                    if len(cells)==6:line='|'+'|'.join(cells[:4])+'|'
                if line.startswith('0は実際のゼロ、欠測は値なし。'):
                    line='0は実際のゼロ。利益・損失は正数、収支は利益−損失。全57場は終端観測と全返済を確認済み。'
                lines.append(line)
            detail.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    supplement=study/'資料/検証補助';supplement.mkdir(exist_ok=True)
    for filename in ['select_once.py','result_audit.py','family_review.py','diagnose.py','fetch_visual.py','raw_examples.py','viewer_audit.py','activity_audit.py','finish.py']:
        if (here/filename).exists():shutil.copyfile(here/filename,supplement/filename)
    (study/'再現手順.md').write_text('''# 再現手順

`資料/`はR170_001固定時のGo実装・テスト・選択/帳票スクリプトの正本。`資料/検証補助/`は実行後の監査・表示資料作成コードであり、入口・出口を変更しない。

1. リポジトリ内`work/research170`へ固定正本を展開する。原板は入力目録のパスを参照する。固定計画の入力サイズ・更新時刻が違えば、同じ検証と称さず中止する。
2. `go test ./...`、`go vet ./...`。
3. `go run . -mode run -output summary.json`。実装と目録のSHA256を計画と照合してから全原行を再生する。
4. 元の選択を再現する場合は、`analyze.py select`の出力を既存選定へ上書きせず別ファイルへ保存し、`選定固定.json`内のIDと比較する。新規実験の初回選定は`検証補助/select_once.py`を用い、後半確認前の指紋を保存する。
5. `analyze.py validate`と`report.py`でMarkdownを作り、`go run . -mode details -output details-summary.json`で固定4枠と対照の約定だけを出力する。詳細再生の会計は初回集計と一致すること。
6. SessionViewerで`比較.resources.json`を開く。AIは`/api/chart`→返された`data_url/png_url`を取得し、同じdata_sha256を確認する。

結果用のsummary.json・details-summary.json、派生画像、数値API応答は作業領域だけに置く。原板コピーと毎tick状態JSONLは作らない。全結果の永続正本は損益Markdown、選定経路は約定JSONL・監査・固定計画で辿る。

構造検査の今回結果は完全。しかし固定時freeze.pyの停止条件は旧キー名を見ており、不完全時を強制停止できない実装だった。今回の`仕様検査.json`と独立監査で完全を確認済み。次回の新ID作成では`proposal_complete is True`と不完全理由の空配列を明示検査すること。旧巨大台帳との類似照合は未実施であり、重複なしとは扱わない。

方式仮説の同時成立フラグ記載に対し、今回の約定正本は優先理由1つを保存する。別条件が同時に成立しなかった証拠には使わない。計画・固定実装・この制限を揃えて読む。
''',encoding='utf-8')
    if (here/'activity_audit.py').exists():
        from activity_audit import update_reports
        update_reports()
    print(json.dumps({'概要':str(study/'README.md'),'選定指紋':'一致','スプレッドシート':'新規作成なし'},ensure_ascii=False))


if __name__=='__main__':main()
