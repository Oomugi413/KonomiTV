
import anyio
import asyncio
import os
import psutil
import signal
import sys
import threading
from fastapi import APIRouter, Depends, Request, status
from fastapi.exceptions import HTTPException
from fastapi.security import OAuth2PasswordBearer
from typing import Any, Annotated, Coroutine

from app import logging
from app import schemas
from app.config import Config
from app.constants import RESTART_REQUIRED_LOCK_PATH, THUMBNAILS_DIR
from app.metadata.KeyFrameAnalyzer import KeyFrameAnalyzer
from app.metadata.RecordedScanTask import RecordedScanTask
from app.metadata.ThumbnailGenerator import ThumbnailGenerator
from app.models.Channel import Channel
from app.models.Program import Program
from app.models.RecordedProgram import RecordedProgram
from app.models.RecordedVideo import RecordedVideo
from app.models.TwitterAccount import TwitterAccount
from app.models.User import User
from app.routers.UsersRouter import GetCurrentAdminUser, GetCurrentUser


# ルーター
router = APIRouter(
    tags = ['Maintenance'],
    prefix = '/api/maintenance',
)

# 録画フォルダの一括スキャン・バックグラウンド解析タスクの asyncio.Task インスタンス
batch_scan_task: asyncio.Task[None] | None = None
background_analysis_task: asyncio.Task[None] | None = None


async def GetCurrentAdminUserOrLocal(
    request: Request,
    token: Annotated[str | None, Depends(OAuth2PasswordBearer(tokenUrl='users/token', auto_error=False))],
) -> User | None:
    """
    現在管理者ユーザーでログインしているか、http://127.0.0.77:7010 からのアクセスであるかを確認する
    KonomiTV の Windows サービスからサーバーをシャットダウンするために必要
    """

    # HTTP リクエストの Host ヘッダーが 127.0.0.77:7010 である場合、Windows サービスプロセスからのアクセスと見なす
    ## 通常アクセス時の Host ヘッダーは 192-168-1-11.local.konomi.tv:7000 のような形式になる
    valid_host = f'127.0.0.77:{Config().server.port + 10}'
    if request.headers.get('host', '').strip() == valid_host:
        return None

    # それ以外である場合、管理者ユーザーでログインしているかを確認する
    if token is None:
        logging.error('[MaintenanceRouter][GetCurrentAdminUserOrLocal] Not authenticated')
        raise HTTPException(
            status_code = status.HTTP_401_UNAUTHORIZED,
            detail = 'Not authenticated',
            headers = {'WWW-Authenticate': 'Bearer'},
        )
    return await GetCurrentAdminUser(await GetCurrentUser(token))


@router.post(
    '/update-database',
    summary = 'データベース更新 API',
    status_code = status.HTTP_204_NO_CONTENT,
)
async def UpdateDatabaseAPI(
    current_user: Annotated[User, Depends(GetCurrentAdminUser)],
):
    """
    データベースに保存されている、チャンネル情報・番組情報・Twitter アカウント情報などの外部 API に依存するデータをすべて更新する。<br>
    即座に外部 API からのデータ更新を反映させたい場合に利用する。<br>
    JWT エンコードされたアクセストークンがリクエストの Authorization: Bearer に設定されていて、かつ管理者アカウントでないとアクセスできない。
    """

    await Channel.update()
    await Channel.updateJikkyoStatus()
    await Program.update(multiprocess=True)
    await TwitterAccount.updateAccountsInformation()


@router.post(
    '/run-batch-scan',
    summary = '録画フォルダ一括スキャン API',
    status_code = status.HTTP_204_NO_CONTENT,
)
async def BatchScanAPI():
    """
    録画フォルダ内の全 TS ファイルをスキャンし、メタデータを解析して DB に永続化する。<br>
    追加・変更があったファイルのみメタデータを解析し、DB に永続化する。<br>
    存在しない録画ファイルに対応するレコードを一括削除する。<br>
    """

    global batch_scan_task

    # 録画フォルダ監視タスクのインスタンスを取得
    recorded_scan_task = RecordedScanTask()

    # タスクが実行中でない場合、新しくタスクを作成して実行
    ## asyncio.create_task() で実行することで、API への HTTP コネクションが切断されてもタスクが継続される
    if batch_scan_task is None:
        batch_scan_task = asyncio.create_task(recorded_scan_task.runBatchScan())
        # タスクの実行が完了するまで待機
        await batch_scan_task
    else:
        raise HTTPException(
            status_code = status.HTTP_429_TOO_MANY_REQUESTS,
            detail = 'Batch scan of recording folders is already running',
        )


@router.post(
    '/run-background-analysis',
    summary = 'バックグラウンド解析タスク手動実行 API',
    status_code = status.HTTP_204_NO_CONTENT,
)
async def BackgroundAnalysisAPI():
    """
    キーフレーム情報が未解析の録画ファイルに対してキーフレーム情報を解析し、<br>
    サムネイルが未生成の録画ファイルに対してサムネイルを生成する。<br>
    """

    global background_analysis_task

    async def BackgroundAnalysis():
        global background_analysis_task
        logging.info('Manual background analysis has started.')

        # キーフレーム情報が未生成、またはサムネイルが未生成の録画ファイルを取得
        db_recorded_videos = await RecordedVideo.filter(status='Recorded')

        # 各録画ファイルに対して直列にバックグラウンド解析タスクを実行
        ## HDD は並列アクセスが遅いため、随時直列に実行していった方が結果的に早いことが多い
        for db_recorded_video in db_recorded_videos:
            file_path = anyio.Path(db_recorded_video.file_path)
            try:
                if not await file_path.is_file():
                    logging.warning(f'{file_path}: File not found. Skipping...')
                    continue

                # キーフレーム情報解析とサムネイル生成を同時に実行
                tasks: list[Coroutine[Any, Any, None]] = []

                # キーフレーム情報が未解析の場合、タスクに追加
                if not db_recorded_video.has_key_frames:
                    tasks.append(KeyFrameAnalyzer(file_path).analyze())

                # サムネイルが未生成の場合、タスクに追加
                thumbnail_path = anyio.Path(str(THUMBNAILS_DIR)) / f'{db_recorded_video.file_hash}.webp'
                if not await thumbnail_path.is_file():
                    # 録画番組情報を取得
                    db_recorded_program = await RecordedProgram.all() \
                        .select_related('recorded_video') \
                        .select_related('channel') \
                        .get_or_none(id=db_recorded_video.id)
                    if db_recorded_program is not None:
                        # RecordedProgram モデルを schemas.RecordedProgram に変換
                        recorded_program = schemas.RecordedProgram.model_validate(db_recorded_program, from_attributes=True)
                        tasks.append(ThumbnailGenerator.fromRecordedProgram(recorded_program).generate(skip_tile_if_exists=True))

                # タスクが存在する場合、同時実行
                if tasks:
                    await asyncio.gather(*tasks)

            except Exception as ex:
                logging.error(f'{file_path}: Error in background analysis:', exc_info=ex)
                continue

        # すべての録画ファイルのバックグラウンド解析が完了した
        logging.info('Manual background analysis has finished processing all recorded files.')
        background_analysis_task = None  # 再度新しいタスクを作成できるように None にする

    # タスクが実行中でない場合、新しくタスクを作成して実行
    ## asyncio.create_task() で実行することで、API への HTTP コネクションが切断されてもタスクが継続される
    if background_analysis_task is None:
        background_analysis_task = asyncio.create_task(BackgroundAnalysis())
        # タスクの実行が完了するまで待機
        await background_analysis_task
    else:
        raise HTTPException(
            status_code = status.HTTP_429_TOO_MANY_REQUESTS,
            detail = 'Background analysis task is already running',
        )


@router.post(
    '/restart',
    summary = 'サーバー再起動 API',
    status_code = status.HTTP_204_NO_CONTENT,
)
def ServerRestartAPI(
    current_user: Annotated[User | None, Depends(GetCurrentAdminUserOrLocal)],
):
    """
    KonomiTV サーバーを再起動する。<br>
    JWT エンコードされたアクセストークンがリクエストの Authorization: Bearer に設定されていて、かつ管理者アカウントでないとアクセスできない。
    """

    def Restart():

        # シグナルの送信対象の PID
        ## --reload フラグが付与されている場合のみ、Reloader の起動元である親プロセスの PID を利用する
        target_process: psutil.Process = psutil.Process(os.getpid())
        if '--reload' in sys.argv:
            target_process = target_process.parent()

        # 現在の Uvicorn サーバーを終了する
        if sys.platform == 'win32':
            target_process.send_signal(signal.CTRL_C_EVENT)
        else:
            target_process.send_signal(signal.SIGINT)

        # Uvicorn 終了後に再起動が必要であることを示すロックファイルを作成する
        # Uvicorn 終了後、KonomiTV.py でロックファイルの存在が確認され、もし存在していればサーバー再起動が行われる
        RESTART_REQUIRED_LOCK_PATH.touch(exist_ok=True)

    # バックグラウンドでサーバー再起動を開始
    threading.Thread(target=Restart).start()


@router.post(
    '/shutdown',
    summary = 'サーバー終了 API',
    status_code = status.HTTP_204_NO_CONTENT,
)
def ServerShutdownAPI(
    current_user: Annotated[User | None, Depends(GetCurrentAdminUserOrLocal)],
):
    """
    KonomiTV サーバーを終了する。<br>
    なお、PM2 環境 / Docker 環境ではサーバー終了後に自動的にプロセスが再起動されるため、事実上 /api/maintenance/restart と等価。<br>
    JWT エンコードされたアクセストークンがリクエストの Authorization: Bearer に設定されていて、かつ管理者アカウントでないとアクセスできない。
    """

    def Shutdown():

        # シグナルの送信対象の PID
        ## --reload フラグが付与されている場合のみ、Reloader の起動元である親プロセスの PID を利用する
        target_process: psutil.Process = psutil.Process(os.getpid())
        if '--reload' in sys.argv:
            target_process = target_process.parent()

        # 現在の Uvicorn サーバーを終了する
        if sys.platform == 'win32':
            target_process.send_signal(signal.CTRL_C_EVENT)
        else:
            target_process.send_signal(signal.SIGINT)

    # バックグラウンドでサーバー終了を開始
    threading.Thread(target=Shutdown).start()
