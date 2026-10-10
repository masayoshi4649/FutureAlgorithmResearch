"""研究実装と保存モデルを読み取り、独立した因果性レビューの証跡を保存する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import numpy as np


OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(OUT))
import research


ML_CHECK = r'''
import sys,json
from pathlib import Path
import numpy as np
sys.dont_write_bytecode=True
sys.path.insert(0,'work/wave_v7')
import ml_models as model
path=Path('work/wave_v7')
data=model.load_data(path/'dataset.npz')
sequence=model.sequence_rows(data)
rows=np.flatnonzero(sequence[:,0]>=0)
assert (data['time_ns'][sequence[rows]]<=data['time_ns'][rows,None]).all()
assert (data['session_idx'][sequence[rows]]==data['session_idx'][rows,None]).all()
assert (data['symbol_idx'][sequence[rows]]==data['symbol_idx'][rows,None]).all()
checks=[]
for fold in (2,3,4,None):
    for column,horizon in enumerate(model.HORIZONS):
        mask=data['valid'] & ((data['age']-45)%5==0) & np.isfinite(data['future_returns'][:,column]) & (data['future_returns'][:,column]!=0)
        scope='final' if fold is None else 'fold'+str(fold)
        if fold is not None:
            first=data['time_ns'][data['session_idx']==fold].min()
            mask &= (data['session_idx']<fold) & (data['label_end_ns'][:,column]<first)
        selected=np.flatnonzero(mask)
        lstm_rows=selected[sequence[selected,0]>=0]
        scaler_rows=np.unique(np.concatenate((selected,sequence[lstm_rows].ravel())))
        if fold is not None:
            assert (data['session_idx'][scaler_rows]<fold).all()
            assert (data['time_ns'][scaler_rows]<first).all()
        scaler=model.fit_scaler(data['X'][scaler_rows])
        with np.load(path/'models'/f'{scope}_{horizon}_scaler.npz',allow_pickle=False) as saved:
            for key in ('median','mean','scale'):
                np.testing.assert_array_equal(scaler[key],saved[key])
        checks.append(dict(分割=scope,予測先分=horizon,学習行数=len(selected),標準化入力行数=len(scaler_rows),係数完全一致=True))
with np.load(path/'ml_predictions.npz',allow_pickle=False) as prediction:
    for key in ('time_ns','session_idx','symbol_idx'):
        np.testing.assert_array_equal(prediction[key],data[key])
    for horizon in model.HORIZONS:
        assert not np.isfinite(prediction['logistic_'+str(horizon)][data['session_idx']<2]).any()
        assert not np.isfinite(prediction['lstm_'+str(horizon)][data['session_idx']<2]).any()
mask=data['session_idx']==4
part={key:(value[mask] if value.ndim>0 and len(value)==len(mask) else value) for key,value in data.items()}
original=model.predict_arrays(part,path/'models',scope='fold4')
cutoff=np.median(np.unique(part['time_ns']))
changed={key:value.copy() for key,value in part.items() if key not in ('future_returns','label_end_ns')}
changed['X'][changed['time_ns']>cutoff]=99999
altered=model.predict_arrays(changed,path/'models',scope='fold4')
before=part['time_ns']<=cutoff
prediction_checks=[]
for key in original:
    np.testing.assert_allclose(original[key][before],altered[key][before],rtol=0,atol=0,equal_nan=True)
    prediction_checks.append(dict(予測配列=key,有限値比較数=int(np.isfinite(original[key][before]).sum()),完全一致=True))
record=json.loads((path/'ml_training_record.json').read_text(encoding='utf-8'))
assert record['再推論']['入力SHA256']==model.digest_file(path/'dataset.npz')
assert record['再推論']['予測SHA256']==model.digest_file(path/'ml_predictions.npz')
assert record['再推論']['モデル変更'] is False
print(json.dumps(dict(系列照合数=len(rows),スケーラー照合=checks,行ID一致=True,初期２セッション予測なし=True,
    教師削除と未来改変の照合=prediction_checks,旧学習入力SHA256=record['入力SHA256'],現再推論入力SHA256=record['再推論']['入力SHA256'],再推論記録整合=True),ensure_ascii=False))
'''


def digest(path: Path) -> str:
    """機能: 読み取った監査対象の内容をハッシュで特定する。

    引数: path (Path) はファイル。
    返り値: SHA256 (str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    """機能: 修正点・ラベル満了・ML隔離を再確認し日本語の証跡を保存する。

    引数: なし。
    返り値: なし (None)。原本・モデル・予測・既存監査は変更しない。
    """
    data = dict(np.load(OUT / 'dataset.npz', allow_pickle=False))
    assert data['age'][data['valid']].min() == 43
    assert research.config(17).family == 17
    assert research.config(17).stop_loss == 2.5
    assert research.config(17).take_profit == 0
    synthetic = []
    for method, count, score in [('機械01/元4ATR', 0, 0), ('機械02/元4ATR', 1, -2)]:
        for session in research.SESSIONS[:2]:
            for symbol in research.SYMBOLS:
                synthetic.append(dict(方式=method, セッション=session, 銘柄=symbol, 取引数=count, 費用倍ATR収支=score))
    synthetic[-1].update(取引数=0, 費用倍ATR収支=0)
    assert research.select_rule(synthetic, research.SESSIONS[:2])['採用']['方式'] == '機械02/元4ATR'
    source = (OUT / 'research.py').read_text(encoding='utf-8')
    assert 'assert np.array_equal(ml[field], dataset[field])' in source
    assert 'config(family)' in source

    # ----------------------------------------
    # 将来ラベルは評価対象として作られるが、学習締切を越えてはいけない。
    label_checks = []
    for column, horizon in enumerate(research.HORIZONS):
        known = np.isfinite(data['future_returns'][:, column])
        assert (data['label_end_ns'][known, column] >= data['time_ns'][known] + horizon * 60 * 10**9).all()
        label_checks.append(dict(予測先分=horizon, ラベル数=int(known.sum()), 満了時刻一致=True))
    for fold in (2, 3, 4):
        train = data['session_idx'] < fold
        first = data['time_ns'][data['session_idx'] == fold].min()
        known = train[:, None] & (data['label_end_ns'] >= 0)
        assert (data['label_end_ns'][known] < first).all()

    # ----------------------------------------
    # ML専用環境では読み取りと予測だけ実行し、再学習は行わない。
    ml_process = subprocess.run([str(OUT / 'ml_gpu_env' / 'Scripts' / 'python.exe'), '-X', 'utf8', '-c', ML_CHECK],
                                cwd=ROOT, capture_output=True, text=True, encoding='utf-8', check=True)
    ml_result = json.loads(ml_process.stdout)
    causal = json.loads((OUT / '因果性監査.json').read_text(encoding='utf-8'))
    result = dict(
        判定='合格', 新データ取得=False, 原本変更=False, 再学習=False,
        範囲='入口因果性の保存済み監査・時間順研究コード・ML学習/標準化/系列/保存モデル推論。利益の将来優位の証明ではない。',
        修正確認={
            '無取引優勝の防止': '両銘柄の学習期間内累計取引数が１以上の候補のみ選択。全不適格の合成例でも無取引候補は除外。',
            '設定識別子': '機械XXはfamilyXX、ConfigV5表示は損切2.5・利確0。v6は固定利確を置かずExitRuleで出口を制御。',
            '新規判断開始': 'validのage43＋２分参照遅延＝45分。MLと機械の受付開始を統一。学習抽出はage45から５分間隔を維持。',
            '予測の行対応': 'time_ns/session_idx/symbol_idxの完全一致assertをresearch.evaluateへ追加済み。実保存配列も一致。'},
        既存入口の元足因果性={
            '照合ファイル数': len(causal['保存足照合']),
            '元足削除と未来改変時刻数': causal['比較仕様']['未来削除と改変の監査時刻数'],
            '特徴比較総行数': causal['比較仕様']['特徴比較総行数'],
            '独立逐次比較行数': causal['比較仕様']['逐次比較総行数'],
            '最大ATR絶対誤差': max(row['独立逐次ATR最大絶対誤差'] for row in causal['各セッション']),
            '参照': '因果性監査.json'},
        ラベル照合=label_checks, 全学習ラベルの次セッション前満了=True,
        ML独立監査=ml_result,
        読取所見=[
            '機械方向と注文再生はfuture_returns/label_end_nsを参照しない。取引評価に元入口固定anchorsを渡していない。',
            '学習foldは過去セッションのみ、さらにラベル満了を評価開始より前に制限する。',
            '標準化は学習行と学習LSTMの過去系列入力だけ。単方向LSTMは30分系列を独立に処理し、隠れ状態を次の標本へ持ち越さない。',
            'predict_arraysは教師列を使わず保存モデルと保存補完・標準化係数で予測する。',
            '初期２セッションのML予測なしは未評価であり、無取引で利益ゼロの成功例とはしない。',
            '旧学習入力hashを維持したまま、valid変更後の入力・予測hashを再推論項目へ追記している。',
            '既知期間の時間順再評価は真の未使用期間ではない。多数候補からの事後比較、実配信遅延、約定実現性は別の論点。'],
        対象SHA256={path.name: digest(path) for path in (OUT / 'research.py', OUT / 'ml_models.py', OUT / 'dataset.npz',
                    OUT / 'ml_predictions.npz', OUT / 'ml_training_record.json', OUT / '因果性監査.json', Path(__file__))},
    )
    (OUT / '独立レビュー.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ['# 未来参照を防ぐ検証の独立レビュー', '',
             '**判定: 合格。** 手法の機械実行、時間順の学習隔離、保存モデルによる教師不要の予測を確認した。将来の予測優位や収益性を保証する判定ではない。', '',
             '修正した３点を確認した。無取引候補は選択不可、機械系統の識別子と実効損切りの表示を整合、新規判断の開始を機械・MLともセッション開始45分へ合わせた。予測の時刻・セッション・銘柄ID完全一致のassertも追加済みで、実配列が一致した。', '',
             '| 監査 | 件数 | 結果 |', '|---|---:|---|',
             '| 保存足のハッシュ | 20ファイル | 保存時と一致 |',
             '| 元足を打切り・未来OHLCを改変 | 240時刻、延べ67,305行 | 過去特徴と方向が一致 |',
             '| 独立オンラインATR/CUSUM | 5,590行 | 方向完全一致、ATR最大誤差1.42e-14 |',
             '| 30/60/120分のラベル満了 | 5,017 / 4,740 / 4,149件 | 判断時刻＋対象時間以降 |',
             '| 学習ラベルの隔離 | ３分割 | 全件が次セッション前に満了 |',
             f"| LSTM過去系列 | {ml_result['系列照合数']:,}件 | 同一銘柄・セッション、未来行なし |",
             '| 保存スケーラーの独立再計算 | 12組 | 中央値・平均・標準偏差が完全一致 |',
             '| 教師削除＋未来特徴99999への改変 | 15予測配列 | 過去予測が完全一致 |', '',
             'MLの初期２セッションには予測がなく、評価対象は後半３セッション。学習データの前処理は各foldの過去入力だけを使い、早期終了や良いseedの選別は行わない。予測ではfuture_returns・label_end_nsの列そのものを削除しても動作した。', '',
             'age45から43への変更は推論可能な最初の２分を追加したもの。学習抽出はage45から５分間隔のため変わらない。初回学習時の入力SHA256はそのまま保持し、現在入力と予測のSHA256はml_training_record.jsonの「再推論」に記録してある。', '',
             '元足の因果性監査は価格CUSUMの入口が対象であり、全板特徴を一括合格としてはいない。機械48条件とMLは既知の５セッションを再評価しており、この確認から将来予測の優位を結論しない。', '',
             '再現用コードは [independent_review.py](independent_review.py)。プロジェクトルートから次を実行する。原本・保存モデル・予測は読み取り専用で、独立レビューの２ファイルだけを書き出す。', '',
             '```powershell', 'python -X utf8 work/wave_v7/independent_review.py', '```', '',
             '詳細・個別件数・対象SHA256は [独立レビュー.json](独立レビュー.json)、元足の再構築検査は [因果性監査.json](因果性監査.json) を参照。']
    (OUT / '独立レビュー.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('独立レビュー: 修正３点・行対応・学習隔離・12スケーラー・15予測配列の不変性を確認')


if __name__ == '__main__':
    main()
