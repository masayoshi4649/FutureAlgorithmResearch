"""最終応答と本物のtrailerの分離だけを、旧Falseを残して独立再確認する。"""

import json
from pathlib import Path

from range_engine_check import load,digest


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]


def run() -> None:
    """
    機能: 取得器のHTTP100/最終200境界を人工だけで再確認する。
    引数: なし。現API、現Night、金融及び入力抽出は呼ばない。
    返り値: None。元16口座180検査へ件数を合算しない別のsource追記証跡。
    """
    source=ROOT/'work/wave_v106/current_capture/capture.py';before=digest(source)
    module=load('独立現capture最終応答分離',source);old=HERE/'current_100後の通常Complete人工.txt'
    try:module.headers(old,'TOPIX')
    except AssertionError:old_rejected=True
    else:raise AssertionError('旧header偽Completeがまだ通る')
    original=old.read_bytes().decode('ascii');ordinary=original.split('HTTP/1.1 200 OK',1)[1]
    ordinary='HTTP/1.1 200 OK'+ordinary.replace('X-History-Complete: true\r\n','')
    examples={'単一200真trailer':(ordinary+'X-History-Complete: true\r\n',True),
        '100後の200真trailer':('HTTP/1.1 100 Continue\r\n\r\n'+ordinary+'X-History-Complete: true\r\n',True),
        '100後の200false':('HTTP/1.1 100 Continue\r\n\r\n'+ordinary+'X-History-Complete: false\r\n',False),
        '100後の200trailer欠落':('HTTP/1.1 100 Continue\r\n\r\n'+ordinary,False),
        '100側に偽Completeかつ200trailer欠落':('HTTP/1.1 100 Continue\r\nX-History-Complete: true\r\n\r\n'+ordinary,False),
        '100後の200trailer二重':('HTTP/1.1 100 Continue\r\n\r\n'+ordinary+'X-History-Complete: true\r\nX-History-Complete: true\r\n',False)}
    checked={}
    for name,(text,accepted) in examples.items():
        path=HERE/('current_capture_'+name+'.txt');assert not path.exists();path.write_bytes(text.encode('ascii'))
        try:module.headers(path,'TOPIX');actual=True
        except AssertionError:actual=False
        assert actual==accepted,name;checked[name]=dict(受理=actual,SHA256=digest(path))
    assert before==digest(source)
    target=HERE/'current_取得器修正の独立source追記.json';assert not target.exists()
    target.write_text(json.dumps(dict(全合格=True,scope='旧入力/数学/3条件の新金融検証ではなくHTTP完結guardのみの人工source追記',
        旧False拒否=old_rejected,検査=checked,source_SHA256={str(source.relative_to(ROOT)):before},
        旧False_SHA256=digest(HERE/'current_通常ヘッダーをtrailerと誤認するFalse.json'),
        部分会計180の元証跡_SHA256=digest(HERE/'current_固定入力と途中会計の独立人工.json'),
        部分会計180の再実行=0,現Night内容=0,API=0,金融=0,レビューsource_SHA256=digest(Path(__file__))),ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print('HTTP最終応答の旧False拒否と6人工が独立合格',flush=True)


if __name__=='__main__':run()
