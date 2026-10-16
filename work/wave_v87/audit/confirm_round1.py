"""終了した計算ハンドルに依存せず、保存成果と固定指紋から第一改修の完了を確認する。"""

import hashlib
from diagnose import ROOT,HERE,read,save


def digest(path):
    """
    機能: 読取対象の内容指紋を再計算する。
    引数: path (Path)。
    返り値: str。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    """
    機能: 全24結果と台帳・全コードを独立会計時の指紋へ再照合する。
    引数: なし。
    返り値: None。計算をやり直さず、既存成果も変更しない。
    """
    work=ROOT/'work/wave_v87/round1';fixed=read(work/'事前固定.json')
    proof=read(HERE/'全12条件の独立会計と再参加条件.json')
    assert proof['全合格'] and proof['条件数']==24 and proof['口座数']==1440
    reports=[]
    for model in fixed['models']:
        for config in fixed['catalog']:
            ident=config['id'];path=work/model/'results'/f'{ident}.json';ledger=work/model/'ledgers'/f'{ident}.pkl'
            packet=read(path)
            prior=next(r for r in proof['条件別'] if r['モデル']==model and r['条件']==ident)
            assert digest(path)==prior['結果SHA256']
            assert digest(ledger)==prior['台帳SHA256']==packet['ledger_SHA256']
            assert packet['config']==config and len(packet['rows'])==60
            assert set(packet['periods'])=={'前16','後14','全30'}
            reports.append(dict(モデル=model,条件=ident,結果と台帳は独立会計時と同一=True))
    for name,expected in fixed['code_SHA256'].items():
        assert digest(ROOT/name)==expected,name
    save('第一改修の保存完了と指紋再確認.json',dict(全合格=True,確認結果数=len(reports),
        結果台帳の確認ファイル数=len(reports)*2,固定コード指紋確認数=len(fixed['code_SHA256']),
        独立会計済み口座数=proof['口座数'],確認=reports,
        判定='全24結果・台帳・固定コードは独立会計完了時と一致。以前のプロセスハンドルの有無に依存せず第一改修の保存完了を確認。'))
    print('第一改修完了確認',len(reports),len(fixed['code_SHA256']),flush=True)


if __name__=='__main__':
    main()
