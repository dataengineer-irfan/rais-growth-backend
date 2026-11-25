import asyncio
from datetime import datetime, timezone
import hashlib
import hmac
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import decrypt_token, encrypt_token
from app.models.entities import MetaConnection


class MetaService:
    """Service for verifying Meta Page Access Tokens and publishing Drive videos to Instagram Reels & Facebook Pages."""

    GRAPH_BASE = "https://graph.facebook.com/v21.0"
    GRAPH_VIDEO_BASE = "https://graph-video.facebook.com/v21.0"

    @classmethod
    def _signing_secret(cls) -> bytes:
        return (settings.SECRET_KEY or "rais-meta-stream-key").encode("utf-8")

    @classmethod
    def sign_media_url(cls, drive_file_id: str, exp_seconds: int = 900, base_url: Optional[str] = None) -> str:
        exp = int(time.time()) + exp_seconds
        payload = f"{drive_file_id}:{exp}".encode("utf-8")
        sig = hmac.new(cls._signing_secret(), payload, hashlib.sha256).hexdigest()
        root = (base_url or settings.BACKEND_PUBLIC_URL or "").rstrip("/")
        return f"{root}{settings.API_V1_STR}/meta/media-stream/{drive_file_id}?exp={exp}&sig={sig}"

    @classmethod
    def verify_media_signature(cls, drive_file_id: str, exp: int, sig: str) -> bool:
        if not drive_file_id or not sig or exp < int(time.time()):
            return False
        payload = f"{drive_file_id}:{exp}".encode("utf-8")
        expected = hmac.new(cls._signing_secret(), payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, sig)

    @classmethod
    async def get_credentials(cls, db: AsyncSession) -> Optional[Dict[str, Any]]:
        res = await db.execute(
            select(MetaConnection)
            .where(MetaConnection.is_connected == True)
            .order_by(MetaConnection.id.desc())
        )
        conn = res.scalars().first()
        if conn and conn.encrypted_page_token:
            token = decrypt_token(conn.encrypted_page_token)
            if token:
                return {
                    "access_token": token,
                    "page_id": conn.page_id,
                    "page_name": conn.page_name,
                    "ig_user_id": conn.ig_user_id,
                    "ig_username": conn.ig_username,
                    "source": "database",
                    "token_verified_at": conn.token_verified_at,
                }

        if settings.META_PAGE_ACCESS_TOKEN:
            return {
                "access_token": settings.META_PAGE_ACCESS_TOKEN,
                "page_id": settings.META_PAGE_ID or None,
                "page_name": None,
                "ig_user_id": settings.META_IG_USER_ID or None,
                "ig_username": None,
                "source": "env",
                "token_verified_at": None,
            }

        return None

    @classmethod
    async def get_status(cls, db: AsyncSession) -> Dict[str, Any]:
        creds = await cls.get_credentials(db)
        if not creds or not creds.get("access_token"):
            return {
                "status": "NOT_CONNECTED",
                "connected": False,
                "page_id": None,
                "page_name": None,
                "ig_user_id": None,
                "ig_username": None,
                "source": "none",
                "message": "Meta Page Access Token is not configured yet. Connect your linked Facebook Page & Instagram Business Account.",
                "token_verified_at": None,
            }

        ig_label = f" (@{creds['ig_username']})" if creds.get("ig_username") else ""
        page_label = creds.get("page_name") or creds.get("page_id") or "Facebook Page"
        return {
            "status": "CONNECTED",
            "connected": True,
            "page_id": creds.get("page_id"),
            "page_name": creds.get("page_name"),
            "ig_user_id": creds.get("ig_user_id"),
            "ig_username": creds.get("ig_username"),
            "source": creds.get("source", "database"),
            "message": f"Connected to {page_label}{ig_label} via {creds.get('source', 'database')} token.",
            "token_verified_at": creds.get("token_verified_at"),
        }

    @classmethod
    def _extract_graph_error(cls, resp: httpx.Response) -> str:
        try:
            body = resp.json()
            err = body.get("error") or {}
            return err.get("message") or resp.text[:300]
        except Exception:
            return resp.text[:300]

    @classmethod
    async def _discover_connection_details(
        cls,
        client: httpx.AsyncClient,
        token: str,
        preferred_page_id: Optional[str],
        preferred_ig_id: Optional[str],
    ) -> Dict[str, Optional[str]]:
        resolved_token = token
        resolved_page_id: Optional[str] = preferred_page_id
        resolved_page_name: Optional[str] = None
        resolved_ig_id: Optional[str] = preferred_ig_id
        resolved_ig_username: Optional[str] = None
        last_error = ""

        # 1. Try User/System-User /me/accounts (lists Pages & linked Instagram Business Accounts)
        acct_resp = await client.get(
            f"{cls.GRAPH_BASE}/me/accounts",
            params={
                "fields": "id,name,access_token,instagram_business_account{id,username}",
                "access_token": token,
            },
        )
        if acct_resp.status_code == 200:
            pages = acct_resp.json().get("data") or []
            if pages:
                selected = None
                if preferred_page_id:
                    selected = next((p for p in pages if p.get("id") == preferred_page_id), None)
                if not selected:
                    selected = next((p for p in pages if p.get("instagram_business_account")), pages[0])

                resolved_token = selected.get("access_token") or token
                resolved_page_id = selected.get("id") or resolved_page_id
                resolved_page_name = selected.get("name")
                ig_obj = selected.get("instagram_business_account") or {}
                resolved_ig_id = preferred_ig_id or ig_obj.get("id")
                resolved_ig_username = ig_obj.get("username")
        else:
            last_error = cls._extract_graph_error(acct_resp)

        # 2. If not resolved via /me/accounts, treat token as a Page Access Token via /me
        if not resolved_page_id or (not resolved_ig_id and not resolved_page_name):
            me_resp = await client.get(
                f"{cls.GRAPH_BASE}/me",
                params={
                    "fields": "id,name,instagram_business_account{id,username}",
                    "access_token": resolved_token,
                },
            )
            if me_resp.status_code == 200:
                me_data = me_resp.json()
                resolved_page_id = resolved_page_id or me_data.get("id")
                resolved_page_name = resolved_page_name or me_data.get("name")
                ig_obj = me_data.get("instagram_business_account") or {}
                resolved_ig_id = resolved_ig_id or ig_obj.get("id")
                resolved_ig_username = resolved_ig_username or ig_obj.get("username")
            elif not resolved_page_id:
                last_error = cls._extract_graph_error(me_resp) or last_error

        # 3. If page_id is known but IG link wasn't fetched yet, query page node directly
        if resolved_page_id and not resolved_ig_id:
            page_resp = await client.get(
                f"{cls.GRAPH_BASE}/{resolved_page_id}",
                params={
                    "fields": "id,name,instagram_business_account{id,username}",
                    "access_token": resolved_token,
                },
            )
            if page_resp.status_code == 200:
                p_data = page_resp.json()
                resolved_page_name = resolved_page_name or p_data.get("name")
                ig_obj = p_data.get("instagram_business_account") or {}
                resolved_ig_id = resolved_ig_id or ig_obj.get("id")
                resolved_ig_username = resolved_ig_username or ig_obj.get("username")

        # 4. If IG ID known without username, fetch IG username
        if resolved_ig_id and not resolved_ig_username:
            ig_resp = await client.get(
                f"{cls.GRAPH_BASE}/{resolved_ig_id}",
                params={"fields": "id,username", "access_token": resolved_token},
            )
            if ig_resp.status_code == 200:
                resolved_ig_username = ig_resp.json().get("username")

        if not resolved_page_id and not resolved_ig_id:
            detail = f" ({last_error})" if last_error else ""
            raise ValueError(
                f"Meta Graph API could not verify a Facebook Page or Instagram Business Account{detail}."
            )

        return {
            "access_token": resolved_token,
            "page_id": resolved_page_id,
            "page_name": resolved_page_name,
            "ig_user_id": resolved_ig_id,
            "ig_username": resolved_ig_username,
        }

    @classmethod
    async def verify_and_connect(
        cls,
        db: AsyncSession,
        access_token: str,
        page_id: Optional[str] = None,
        ig_user_id: Optional[str] = None,
        client: Optional[httpx.AsyncClient] = None,
    ) -> Dict[str, Any]:
        clean_token = (access_token or "").strip()
        if not clean_token:
            raise ValueError("Meta Page Access Token is required.")

        if client is not None:
            discovered = await cls._discover_connection_details(
                client, clean_token, page_id, ig_user_id
            )
        else:
            async with httpx.AsyncClient(timeout=30.0) as local_client:
                discovered = await cls._discover_connection_details(
                    local_client, clean_token, page_id, ig_user_id
                )

        await db.execute(delete(MetaConnection))
        conn = MetaConnection(
            page_id=discovered["page_id"],
            page_name=discovered["page_name"],
            ig_user_id=discovered["ig_user_id"],
            ig_username=discovered["ig_username"],
            encrypted_page_token=encrypt_token(discovered["access_token"] or clean_token),
            is_connected=True,
            token_verified_at=datetime.now(timezone.utc),
        )
        db.add(conn)
        await db.commit()
        return await cls.get_status(db)

    @classmethod
    async def disconnect(cls, db: AsyncSession) -> None:
        await db.execute(delete(MetaConnection))
        await db.commit()

    @classmethod
    async def publish_to_instagram(
        cls,
        creds: Dict[str, Any],
        video_url: str,
        caption: str,
        poll_interval: float = 4.0,
        max_polls: int = 20,
        client: Optional[httpx.AsyncClient] = None,
    ) -> Dict[str, str]:
        ig_user_id = creds.get("ig_user_id")
        token = creds.get("access_token")
        if not ig_user_id or not token:
            raise ValueError("Linked Instagram Business Account ID and Meta token are required.")

        async def _run(http: httpx.AsyncClient) -> Dict[str, str]:
            # 1. Create Reels media container
            create_resp = await http.post(
                f"{cls.GRAPH_BASE}/{ig_user_id}/media",
                data={
                    "media_type": "REELS",
                    "video_url": video_url,
                    "caption": caption[:2200],
                    "share_to_feed": "true",
                    "access_token": token,
                },
            )
            if create_resp.status_code != 200:
                raise ValueError(
                    f"Instagram container creation failed ({create_resp.status_code}): {cls._extract_graph_error(create_resp)}"
                )
            creation_id = create_resp.json().get("id")
            if not creation_id:
                raise ValueError("Instagram API did not return a container creation ID.")

            # 2. Poll until container video processing reaches FINISHED
            ready = False
            for _ in range(max_polls):
                status_resp = await http.get(
                    f"{cls.GRAPH_BASE}/{creation_id}",
                    params={"fields": "status_code,status", "access_token": token},
                )
                if status_resp.status_code == 200:
                    sdata = status_resp.json()
                    code = str(sdata.get("status_code") or "").upper()
                    if code == "FINISHED":
                        ready = True
                        break
                    if code in ("ERROR", "EXPIRED"):
                        raise ValueError(f"Instagram Reels processing failed: {sdata}")
                if poll_interval > 0:
                    await asyncio.sleep(poll_interval)

            if not ready:
                raise ValueError("Instagram Reels container processing timed out before publish.")

            # 3. Publish container
            pub_resp = await http.post(
                f"{cls.GRAPH_BASE}/{ig_user_id}/media_publish",
                data={"creation_id": creation_id, "access_token": token},
            )
            if pub_resp.status_code != 200:
                raise ValueError(
                    f"Instagram Reels publish failed ({pub_resp.status_code}): {cls._extract_graph_error(pub_resp)}"
                )
            media_id = pub_resp.json().get("id")
            if not media_id:
                raise ValueError("Instagram publish response missing media ID.")

            # 4. Fetch real permalink
            permalink = f"https://www.instagram.com/{creds.get('ig_username') or 'raisfrozenfoods'}/"
            link_resp = await http.get(
                f"{cls.GRAPH_BASE}/{media_id}",
                params={"fields": "permalink", "access_token": token},
            )
            if link_resp.status_code == 200 and link_resp.json().get("permalink"):
                permalink = link_resp.json()["permalink"]

            return {"media_id": str(media_id), "permalink": permalink}

        if client is not None:
            return await _run(client)
        async with httpx.AsyncClient(timeout=120.0) as local_client:
            return await _run(local_client)

    @classmethod
    async def publish_to_facebook(
        cls,
        creds: Dict[str, Any],
        video_bytes: bytes,
        filename: str,
        title: str,
        description: str,
        client: Optional[httpx.AsyncClient] = None,
    ) -> Dict[str, str]:
        page_id = creds.get("page_id")
        token = creds.get("access_token")
        if not page_id or not token:
            raise ValueError("Facebook Page ID and Meta Page Access Token are required.")

        async def _run(http: httpx.AsyncClient) -> Dict[str, str]:
            upload_resp = await http.post(
                f"{cls.GRAPH_VIDEO_BASE}/{page_id}/videos",
                data={
                    "title": (title or "RAIS Agencies Wholesale Update")[:255],
                    "description": (description or "")[:5000],
                    "access_token": token,
                },
                files={
                    "source": (filename or "rais_promo_video.mp4", video_bytes, "video/mp4")
                },
            )
            if upload_resp.status_code != 200:
                raise ValueError(
                    f"Facebook Page video upload failed ({upload_resp.status_code}): {cls._extract_graph_error(upload_resp)}"
                )
            video_id = upload_resp.json().get("id")
            if not video_id:
                raise ValueError("Facebook video upload response missing video ID.")

            fb_url = f"https://www.facebook.com/{page_id}/videos/{video_id}"
            link_resp = await http.get(
                f"{cls.GRAPH_BASE}/{video_id}",
                params={"fields": "permalink_url", "access_token": token},
            )
            if link_resp.status_code == 200 and link_resp.json().get("permalink_url"):
                p = link_resp.json()["permalink_url"]
                fb_url = f"https://www.facebook.com{p}" if p.startswith("/") else p

            return {"video_id": str(video_id), "url": fb_url}

        if client is not None:
            return await _run(client)
        async with httpx.AsyncClient(timeout=120.0) as local_client:
            return await _run(local_client)

    @classmethod
    def build_meta_caption(cls, item: Any) -> str:
        desc = (getattr(item, "description", "") or "").strip()
        title = (getattr(item, "video_title", "") or getattr(item, "product_name", "") or "").strip()
        if title and title.lower() not in desc.lower():
            base = f"{title}\n\n{desc}".strip()
        else:
            base = desc or title
        if "9347453135" not in base:
            base += "\n\nRAIS Agencies | Beside Indel Money Bank, Rayachoty | Wholesale WhatsApp: 9347453135"
        if "#RAISAgencies" not in base:
            base += "\n#RAISAgencies #Rayachoty #WholesaleFrozenFoods #CafeSupply"
        return base[:2200]

    @classmethod
    async def publish_queue_item(
        cls,
        db: AsyncSession,
        item: Any,
        platforms: List[str],
        download_bytes_fn: Callable[[str, AsyncSession], Awaitable[bytes]],
        base_url: Optional[str] = None,
        poll_interval: float = 4.0,
        client: Optional[httpx.AsyncClient] = None,
    ) -> Dict[str, Any]:
        creds = await cls.get_credentials(db)
        if not creds or not creds.get("access_token"):
            raise ValueError(
                "Meta Page Access Token is not configured. Connect your Facebook Page & Instagram Business Account first."
            )
        if not getattr(item, "drive_file_id", None):
            raise ValueError(
                "Queued item has no authentic Google Drive file ID. Sync directly from Drive first."
            )

        targets = [p.strip().lower() for p in platforms if p and p.strip()]
        if not targets:
            targets = ["instagram", "facebook"]

        caption = cls.build_meta_caption(item)
        now = datetime.now(timezone.utc)
        results: Dict[str, Any] = {}
        errors: List[str] = []

        if "instagram" in targets:
            try:
                signed_url = cls.sign_media_url(item.drive_file_id, base_url=base_url)
                ig_res = await cls.publish_to_instagram(
                    creds=creds,
                    video_url=signed_url,
                    caption=caption,
                    poll_interval=poll_interval,
                    client=client,
                )
                item.ig_status = "PUBLISHED"
                item.ig_media_id = ig_res["media_id"]
                item.ig_url = ig_res["permalink"]
                item.ig_published_at = now
                item.ig_error = None
                results["instagram"] = ig_res
            except Exception as exc:
                item.ig_status = "FAILED"
                item.ig_error = str(exc)
                errors.append(f"Instagram: {exc}")

        if "facebook" in targets:
            try:
                video_bytes = await download_bytes_fn(item.drive_file_id, db)
                fb_res = await cls.publish_to_facebook(
                    creds=creds,
                    video_bytes=video_bytes,
                    filename=getattr(item, "file_name", None) or "rais_reel.mp4",
                    title=getattr(item, "video_title", "RAIS Agencies Promo"),
                    description=caption,
                    client=client,
                )
                item.fb_status = "PUBLISHED"
                item.fb_video_id = fb_res["video_id"]
                item.fb_url = fb_res["url"]
                item.fb_published_at = now
                item.fb_error = None
                results["facebook"] = fb_res
            except Exception as exc:
                item.fb_status = "FAILED"
                item.fb_error = str(exc)
                errors.append(f"Facebook: {exc}")

        await db.commit()
        await db.refresh(item)

        if errors and not results:
            raise RuntimeError(" | ".join(errors))

        return {
            "status": "PARTIAL" if errors else "SUCCESS",
            "item_id": item.id,
            "results": results,
            "errors": errors,
        }

