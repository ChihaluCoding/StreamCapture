# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path
from typing import Callable, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SCOPES = ["https://www.googleapis.com/auth/drive.file"]
DEFAULT_TOKEN_PATH = Path(__file__).resolve().with_name("gdrive_token.json")


def _emit(status_cb: Optional[Callable[[str], None]], message: str) -> None:
    if status_cb is not None:
        status_cb(message)


def _load_credentials(
    client_secret_path: str,
    token_path: Path,
    status_cb: Optional[Callable[[str], None]] = None,
) -> Optional[Credentials]:
    if not client_secret_path:
        _emit(status_cb, "Google Drive: 認証情報(JSON)が未設定です。")
        return None
    secret_path = Path(client_secret_path)
    if not secret_path.exists():
        _emit(status_cb, f"Google Drive: 認証情報が見つかりません: {secret_path}")
        return None

    creds: Optional[Credentials] = None
    if token_path.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        except Exception:
            creds = None

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception as exc:
            _emit(status_cb, f"Google Drive: トークン更新に失敗しました: {exc}")
            creds = None

    if not creds or not creds.valid:
        _emit(status_cb, "Google Drive: 認証を開始します（ブラウザが開きます）。")
        flow = InstalledAppFlow.from_client_secrets_file(str(secret_path), SCOPES)
        creds = flow.run_local_server(port=0)

    try:
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json(), encoding="utf-8")
    except Exception as exc:
        _emit(status_cb, f"Google Drive: トークン保存に失敗しました: {exc}")

    return creds


def upload_to_drive(
    file_path: Path,
    client_secret_path: str,
    folder_id: str,
    token_path: Optional[Path] = None,
    status_cb: Optional[Callable[[str], None]] = None,
) -> Optional[str]:
    target_path = Path(file_path)
    if not target_path.exists():
        _emit(status_cb, f"Google Drive: アップロード対象が見つかりません: {target_path}")
        return None
    if target_path.stat().st_size == 0:
        _emit(status_cb, f"Google Drive: 空ファイルのためアップロードを中止します: {target_path}")
        return None

    token_path = token_path or DEFAULT_TOKEN_PATH
    creds = _load_credentials(client_secret_path, token_path, status_cb=status_cb)
    if not creds:
        return None

    service = build("drive", "v3", credentials=creds)
    metadata = {"name": target_path.name}
    if folder_id:
        metadata["parents"] = [folder_id]

    _emit(status_cb, f"Google Drive: アップロード開始 {target_path.name}")
    media = MediaFileUpload(str(target_path), resumable=True)
    result = service.files().create(
        body=metadata,
        media_body=media,
        fields="id,name,webViewLink",
    ).execute()
    file_id = result.get("id")
    web_link = result.get("webViewLink")
    if web_link:
        _emit(status_cb, f"Google Drive: アップロード完了 {web_link}")
    elif file_id:
        _emit(status_cb, f"Google Drive: アップロード完了 (id={file_id})")
    else:
        _emit(status_cb, "Google Drive: アップロード完了")
    return file_id
