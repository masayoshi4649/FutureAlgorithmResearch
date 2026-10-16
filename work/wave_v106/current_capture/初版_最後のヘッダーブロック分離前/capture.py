"""現ナイトの二つの固定スナップショットを各一回だけ取得し、完結トレーラーを検査する。"""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess


HERE=Path(__file__).resolve().parent
SESSION='2026-10-13_Night'
JAPAN=timezone(timedelta(hours=9))


def now() -> str:
    """
    機能: 取得処理の実際の日本時間を記録する。
    引数: なし。
    返り値: strはタイムゾーン付きISO時刻。保存板の価格時計とは区別する。
    """
    return datetime.now(JAPAN).isoformat()


def save(path: Path, value: dict) -> None:
    """
    機能: 取得証跡を未存在ファイルへ保存する。
    引数: path(Path)、value(dict)は所有域の位置と資料。
    返り値: None。既取得の板や証跡へ上書きしない。
    """
    assert path.resolve().is_relative_to(HERE) and not path.exists(),path
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8',newline='\n')


def headers(path: Path, symbol: str) -> dict:
    """
    機能: curlが保存した通常ヘッダーと本文後トレーラーから完結を確認する。
    引数: path(Path)、symbol(str)は全ヘッダーの保存先と期待商品。
    返り値: dictは固定上限と完結状態。不足、誤セッション、未完結は拒否する。
    """
    text=path.read_bytes().decode('iso-8859-1')
    lines=text.splitlines();status=[line for line in lines if line.startswith('HTTP/')]
    assert status and re.match(r'^HTTP/\S+\s+200(?:\s|$)',status[-1]),status
    fields={}
    for line in lines:
        if ':' in line:
            key,value=line.split(':',1);fields.setdefault(key.lower().strip(),[]).append(value.strip())
    required=('session-id','generation','code','as-of','sequence','complete')
    selected={key:fields.get('x-history-'+key,[]) for key in required}
    assert all(len(values)==1 for values in selected.values()),selected
    selected={key:values[0] for key,values in selected.items()}
    assert selected['complete'].lower()=='true','本文の完結トレーラーがありません'
    assert selected['session-id']==SESSION and selected['code']==symbol,selected
    assert selected['generation'] and int(selected['sequence'])>0
    assert datetime.fromisoformat(selected['as-of'].replace('Z','+00:00')).tzinfo is not None
    # ----------------------------------------
    # Completeを通常ヘッダーへ置いた人工救済は認めず、最終ヘッダー空行より後を確認する。
    first_end=text.find('\r\n\r\n')
    if first_end<0:first_end=text.find('\n\n')
    assert first_end>=0 and 'x-history-complete:' in text[first_end:].lower()
    return selected


def download(base: str, symbol: str, folder: Path) -> dict:
    """
    機能: 一商品へ一回のHTTP取得を行い、本文を表示せず直接ファイルへ保存する。
    引数: base(str)、symbol(str)、folder(Path)は接続先、商品、未存在の所有保存域。
    返り値: dictは実取得時刻、ヘッダー及びサイズ。本文再取得や自動再試行はしない。
    """
    assert symbol in ('TOPIX','NK225') and folder.resolve().is_relative_to(HERE)
    folder.mkdir(parents=True,exist_ok=True)
    book=folder/f'{symbol}.jsonl';header=folder/f'{symbol}_headers.txt'
    assert not book.exists() and not header.exists()
    executable=shutil.which('curl.exe' if os.name=='nt' else 'curl');assert executable
    url=base.rstrip('/')+'/api/v1/history/'+symbol+'/book'
    command=[executable,'--silent','--show-error','--fail','--connect-timeout','15','--max-time','600',
        '--noproxy','*','--dump-header',str(header),'--output',str(book),url]
    started=now()
    process=subprocess.run(command,capture_output=True,text=True,encoding='utf8',errors='replace',
        creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    value=dict(symbol=symbol,取得開始=started,取得完了=now(),HTTP要求回数=1,自動再試行=0,
        curl終了コード=process.returncode,標準エラー=process.stderr,
        原本位置=str(book),ヘッダー位置=str(header),bytes=book.stat().st_size if book.exists() else 0)
    assert process.returncode==0,value
    value['snapshot']=headers(header,symbol);assert value['bytes']>0
    return value


def run() -> None:
    """
    機能: 固定済み三対照のために現場二商品を一回取得し、失敗も再試行せず残す。
    引数: なし。根の実行フラグでのみ開始する。
    返り値: None。注文APIとcandles及びstatusは取得しない。金融再生は別の登録後に行う。
    """
    assert not (HERE/'取得開始.json').exists()
    save(HERE/'取得開始.json',dict(session=SESSION,時刻=now(),目的='未見の現ナイト接頭で一回の答え合わせ',
        固定対照=['AUTO_ER40_M2_LIMIT','R_ONLY_ER40_M2_LIMIT','C_ONLY_B2_ER40_B4'],
        解釈='終端未到来の接頭。未返済を架空清算せず実現と返済費込み時価を分ける。条件再選定に使わない。',
        book_HTTP各商品回数=1,自動再試行=0,実注文=0))
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            jobs={symbol:executor.submit(download,'http://10.10.100.1:8080',symbol,HERE/'snapshot') for symbol in ('TOPIX','NK225')}
            values={symbol:job.result() for symbol,job in jobs.items()}
        save(HERE/'取得完了.json',dict(全合格=True,session=SESSION,時刻=now(),symbols=values,
            HTTP要求合計=2,現セッション取得回数=1,新金融再生=0,実注文=0,
            注意='二商品は各HTTP開始時の固定上限。保存原行に実受信時計は追加されず、取得時刻は各原行の受信時刻を表さない。'))
        print('現ナイトを二商品各一回取得し、本文後の完結トレーラーを確認しました。金融0・実注文0。',flush=True)
    except BaseException as error:
        save(HERE/'取得停止.json',dict(全合格=False,時刻=now(),例外=repr(error),自動再試行=0,実注文=0))
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='現ナイトの一回だけの未見データ取得')
    parser.add_argument('--root-current-read-approved',action='store_true',required=True)
    parser.parse_args();run()
