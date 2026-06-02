from __future__ import annotations

import hashlib
import hmac
import json
import mimetypes
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlparse

import httpx


@dataclass(frozen=True)
class SavedGameRecord:
    session_id: str
    title: str
    prompt: str | None
    template: str | None
    controls: dict[str, str]
    assets: list[dict]
    web_rel: str
    saved_at: str

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "title": self.title,
            "prompt": self.prompt,
            "template": self.template,
            "controls": self.controls,
            "assets": self.assets,
            "web_rel": self.web_rel,
            "saved_at": self.saved_at,
        }


class LocalSaveStore:
    def __init__(self, index_path: Path):
        self.index_path = index_path
        self.index_path.parent.mkdir(parents=True, exist_ok=True)

    def list(self) -> list[SavedGameRecord]:
        records = []
        for item in self._read().values():
            if not isinstance(item, dict):
                continue
            try:
                records.append(SavedGameRecord(**item))
            except TypeError:
                continue
        records.sort(key=lambda item: item.saved_at, reverse=True)
        return records

    def upsert(self, record: SavedGameRecord) -> SavedGameRecord:
        data = self._read()
        data[record.session_id] = record.to_dict()
        tmp = self.index_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True))
        tmp.replace(self.index_path)
        return record

    def delete(self, session_id: str) -> bool:
        data = self._read()
        existed = session_id in data
        data.pop(session_id, None)
        tmp = self.index_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True))
        tmp.replace(self.index_path)
        return existed

    def _read(self) -> dict[str, dict]:
        if not self.index_path.exists():
            return {}
        try:
            data = json.loads(self.index_path.read_text())
        except json.JSONDecodeError:
            return {}
        if not isinstance(data, dict):
            return {}
        return {str(k): v for k, v in data.items() if isinstance(v, dict)}


class PostgresSaveStore:
    def __init__(self, database_url: str):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("psycopg is required when DATABASE_URL is set") from exc

        self._psycopg = psycopg
        self._dict_row = dict_row
        self.database_url = database_url
        self._ensure_schema()

    def list(self) -> list[SavedGameRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT session_id, title, prompt, template, controls, assets, web_rel, saved_at
                FROM saved_games
                ORDER BY saved_at DESC
                """
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def upsert(self, record: SavedGameRecord) -> SavedGameRecord:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO saved_games
                    (session_id, title, prompt, template, controls, assets, web_rel, saved_at)
                VALUES
                    (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s::timestamptz)
                ON CONFLICT (session_id) DO UPDATE SET
                    title = EXCLUDED.title,
                    prompt = EXCLUDED.prompt,
                    template = EXCLUDED.template,
                    controls = EXCLUDED.controls,
                    assets = EXCLUDED.assets,
                    web_rel = EXCLUDED.web_rel,
                    saved_at = EXCLUDED.saved_at
                """,
                (
                    record.session_id,
                    record.title,
                    record.prompt,
                    record.template,
                    json.dumps(record.controls),
                    json.dumps(record.assets),
                    record.web_rel,
                    record.saved_at,
                ),
            )
            conn.commit()
        return record

    def delete(self, session_id: str) -> bool:
        with self._connect() as conn:
            result = conn.execute("DELETE FROM saved_games WHERE session_id = %s", (session_id,))
            conn.commit()
        return (result.rowcount or 0) > 0

    def _connect(self):
        return self._psycopg.connect(self.database_url, row_factory=self._dict_row)

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS saved_games (
                    session_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    prompt TEXT,
                    template TEXT,
                    controls JSONB NOT NULL DEFAULT '{}'::jsonb,
                    assets JSONB NOT NULL DEFAULT '[]'::jsonb,
                    web_rel TEXT NOT NULL,
                    saved_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            conn.commit()

    @staticmethod
    def _row_to_record(row: dict) -> SavedGameRecord:
        saved_at = row["saved_at"]
        if isinstance(saved_at, datetime):
            saved_at = saved_at.isoformat()
        return SavedGameRecord(
            session_id=row["session_id"],
            title=row["title"],
            prompt=row["prompt"],
            template=row["template"],
            controls=row["controls"] or {},
            assets=row["assets"] or [],
            web_rel=row["web_rel"],
            saved_at=str(saved_at),
        )


class ObjectStorage:
    def __init__(
        self,
        endpoint_url: str,
        region: str,
        bucket: str,
        access_key: str,
        secret_key: str,
        public_base_url: str | None = None,
    ):
        self.endpoint_url = endpoint_url.rstrip("/")
        self.region = region
        self.bucket = bucket
        self.access_key = access_key
        self.secret_key = secret_key
        self.public_base_url = public_base_url.rstrip("/") if public_base_url else None

    @classmethod
    def from_env(cls) -> ObjectStorage | None:
        bucket = os.environ.get("SPACES_BUCKET") or os.environ.get("S3_BUCKET")
        access_key = os.environ.get("SPACES_ACCESS_KEY") or os.environ.get("AWS_ACCESS_KEY_ID")
        secret_key = os.environ.get("SPACES_SECRET_KEY") or os.environ.get("AWS_SECRET_ACCESS_KEY")
        if not (bucket and access_key and secret_key):
            return None

        region = os.environ.get("SPACES_REGION") or os.environ.get("AWS_REGION") or "nyc3"
        endpoint = (
            os.environ.get("SPACES_ENDPOINT_URL")
            or os.environ.get("S3_ENDPOINT_URL")
            or f"https://{region}.digitaloceanspaces.com"
        )
        public_base_url = os.environ.get("SPACES_PUBLIC_BASE_URL") or os.environ.get(
            "S3_PUBLIC_BASE_URL"
        )
        return cls(endpoint, region, bucket, access_key, secret_key, public_base_url)

    async def upload_web_build(self, web_dir: Path, session_id: str) -> str:
        index = web_dir / "index.html"
        if not index.exists():
            raise FileNotFoundError(f"{index} does not exist")

        prefix = f"games/{session_id}/web"
        for path in sorted(p for p in web_dir.rglob("*") if p.is_file()):
            rel = path.relative_to(web_dir).as_posix()
            key = f"{prefix}/{rel}"
            content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            await self._put_file(key, path, content_type)
        return self.public_url(f"{prefix}/index.html")

    def public_url(self, key: str) -> str:
        encoded = "/".join(quote(part) for part in key.split("/"))
        if self.public_base_url:
            return f"{self.public_base_url}/{encoded}"
        parsed = urlparse(self.endpoint_url)
        host = parsed.netloc
        if host.endswith("digitaloceanspaces.com"):
            return f"{parsed.scheme}://{self.bucket}.{host}/{encoded}"
        return f"{self.endpoint_url}/{self.bucket}/{encoded}"

    async def _put_file(self, key: str, path: Path, content_type: str) -> None:
        body = path.read_bytes()
        url = f"{self.endpoint_url}/{self.bucket}/{quote(key)}"
        headers = self._signed_headers("PUT", key, body, content_type)
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.put(url, content=body, headers=headers)
        response.raise_for_status()

    def _signed_headers(self, method: str, key: str, body: bytes, content_type: str) -> dict[str, str]:
        now = datetime.now(timezone.utc)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = now.strftime("%Y%m%d")
        payload_hash = hashlib.sha256(body).hexdigest()
        parsed = urlparse(self.endpoint_url)
        host = parsed.netloc
        canonical_uri = f"/{self.bucket}/" + "/".join(quote(part) for part in key.split("/"))
        signed_headers = "content-type;host;x-amz-content-sha256;x-amz-date"
        canonical_headers = (
            f"content-type:{content_type}\n"
            f"host:{host}\n"
            f"x-amz-content-sha256:{payload_hash}\n"
            f"x-amz-date:{amz_date}\n"
        )
        canonical_request = "\n".join(
            [method, canonical_uri, "", canonical_headers, signed_headers, payload_hash]
        )
        credential_scope = f"{date_stamp}/{self.region}/s3/aws4_request"
        string_to_sign = "\n".join(
            [
                "AWS4-HMAC-SHA256",
                amz_date,
                credential_scope,
                hashlib.sha256(canonical_request.encode()).hexdigest(),
            ]
        )
        signature = hmac.new(
            self._signing_key(date_stamp), string_to_sign.encode(), hashlib.sha256
        ).hexdigest()
        authorization = (
            "AWS4-HMAC-SHA256 "
            f"Credential={self.access_key}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )
        return {
            "Authorization": authorization,
            "Content-Type": content_type,
            "Host": host,
            "x-amz-content-sha256": payload_hash,
            "x-amz-date": amz_date,
        }

    def _signing_key(self, date_stamp: str) -> bytes:
        k_date = hmac.new(
            f"AWS4{self.secret_key}".encode(), date_stamp.encode(), hashlib.sha256
        ).digest()
        k_region = hmac.new(k_date, self.region.encode(), hashlib.sha256).digest()
        k_service = hmac.new(k_region, b"s3", hashlib.sha256).digest()
        return hmac.new(k_service, b"aws4_request", hashlib.sha256).digest()


def make_save_store(local_index_path: Path):
    database_url = os.environ.get("SAVE_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if database_url:
        return PostgresSaveStore(database_url)
    return LocalSaveStore(local_index_path)
