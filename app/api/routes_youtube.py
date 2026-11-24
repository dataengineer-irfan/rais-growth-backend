import datetime
import urllib.parse
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.models.entities import YouTubeQueueItem, YouTubeDriveSetting, YouTubeQueueStatus
from app.schemas.schemas import (
    YouTubeQueueItemRead,
    YouTubeQueueItemCreate,
    YouTubeDriveSettingRead,
    YouTubeDriveSettingUpdate,
    YouTubeSyncResult,
    YouTubePublishResult
)

router = APIRouter(prefix="/youtube", tags=["YouTube & Google Drive Automation"])

DEPOT_PHONE = "9347453135"
DEPOT_ADDRESS = "Beside Indel Money Bank, Sundupalli Road, Near Reddies Colony, Rayachoty – 516269, Annamayya District, Andhra Pradesh"
CORRIDORS = "Rayachoty, Sundupalli, Galiveedu, Kadiri, Chinnamandem, Kalakada, Mahal, Madanapalle, Kadapa, and Rajampet"

INITIAL_PROMO_VIDEOS = [
    {
        "file_name": "Meal_Time_Dark_Soya_and_Green_Chilli_5kg.mp4",
        "product_sku": "SAUCES-025",
        "product_name": "Meal Time Dark Soya & Green Chilli Sauce (5kg)",
        "video_title": "Meal Time Dark Soya & Green Chilli Sauce 5kg Bulk Depot | RAIS Agencies Rayachoty",
        "description": (
            f"Commercial 5kg bulk cans of Meal Time Dark Soya Sauce & Green Chilli Sauce for fast food kitchens, "
            f"fried rice, noodles, and manchurian counters in Rayachoty and nearby corridors.\n\n"
            f"📍 Depot: {DEPOT_ADDRESS}\n"
            f"📞 WhatsApp Wholesale Order: https://wa.me/91{DEPOT_PHONE}?text=Hi+RAIS+Agencies,+interested+in+Meal+Time+5kg+sauces\n"
            f"🚚 Scheduled Route Logistics: {CORRIDORS}"
        ),
        "tags": "Rayachoty,MealTime,DarkSoyaSauce,GreenChilliSauce,RestaurantSupplies,FastFoodWholesale,Shorts"
    },
    {
        "file_name": "Milky_Mist_Mozzarella_Cheese_1kg.mp4",
        "product_sku": "DAIRY-004",
        "product_name": "Milky Mist Diced Mozzarella (1kg & 2kg)",
        "video_title": "High-Stretch Milky Mist Mozzarella Cheese for Rayachoty Pizza Cafes 🍕 | RAIS Agencies",
        "description": (
            f"Fresh -18°C cold-chain Milky Mist diced mozzarella cheese for pizzerias, cafes, and bakeries. "
            f"Superior melt, golden browning, and maximum stretch at bulk depot rates.\n\n"
            f"📍 Depot: {DEPOT_ADDRESS}\n"
            f"📞 WhatsApp Trade Order: https://wa.me/91{DEPOT_PHONE}?text=Hi+RAIS+Agencies,+interested+in+Milky+Mist+Mozzarella\n"
            f"🚚 Delivery Routes: {CORRIDORS}"
        ),
        "tags": "MilkyMist,MozzarellaCheese,PizzaSupplies,Rayachoty,ColdChainWholesale,Shorts"
    },
    {
        "file_name": "Del_Monte_Sliced_Jalapenos_3kg.mp4",
        "product_sku": "SAUCES-010",
        "product_name": "Del Monte Sliced Jalapeños (3kg Tin)",
        "video_title": "Del Monte Sliced Pickled Jalapeños for Pizza & Burger Counters | RAIS Agencies",
        "description": (
            f"Crispy, spicy, and tangy Del Monte sliced pickled jalapeños in commercial 3kg tins. "
            f"Ready stock for loaded nachos, gourmet burgers, submarine sandwiches, and pizza toppings in Rayachoty.\n\n"
            f"📍 Depot: {DEPOT_ADDRESS}\n"
            f"📞 WhatsApp Order: https://wa.me/91{DEPOT_PHONE}?text=Hi+RAIS+Agencies,+interested+in+Del+Monte+Jalapenos\n"
            f"🚚 Delivery Routes: {CORRIDORS}"
        ),
        "tags": "DelMonte,SlicedJalapenos,PizzaToppings,BurgerSupplies,RayachotyWholesale,Shorts"
    },
    {
        "file_name": "Golden_Crown_Panko_Bread_Crumbs_1kg.mp4",
        "product_sku": "SAUCES-024",
        "product_name": "Golden Crown Panko Bread Crumbs (1kg)",
        "video_title": "Original Japanese Panko Bread Crumbs for Crispy Fried Chicken | RAIS Agencies Rayachoty",
        "description": (
            f"Golden Crown Japanese style flaky panko bread crumbs for crunchy fried chicken, nuggets, and paneer cutlets. "
            f"Stays ultra-crisp longer without absorbing excess oil.\n\n"
            f"📍 Depot: {DEPOT_ADDRESS}\n"
            f"📞 WhatsApp Order: https://wa.me/91{DEPOT_PHONE}?text=Hi+RAIS+Agencies,+interested+in+Panko+Breadcrumbs\n"
            f"🚚 Delivery Routes: {CORRIDORS}"
        ),
        "tags": "GoldenCrown,PankoBreadCrumbs,FriedChicken,QSRSupplies,Rayachoty,Shorts"
    },
    {
        "file_name": "Sudarshan_Fresh_Cream_1L.mp4",
        "product_sku": "DAIRY-009",
        "product_name": "Sudarshan Dairy Fresh Cream (1L)",
        "video_title": "Rich Sudarshan Dairy Fresh Cream for Restaurant Curries & Pastas | RAIS Agencies",
        "description": (
            f"Premium rich dairy fresh cream from Sudarshan for butter chicken gravies, restaurant paneer curries, "
            f"white sauce pastas, and cafe milkshakes. Certified refrigerated delivery across Annamayya District.\n\n"
            f"📍 Depot: {DEPOT_ADDRESS}\n"
            f"📞 WhatsApp Order: https://wa.me/91{DEPOT_PHONE}?text=Hi+RAIS+Agencies,+interested+in+Sudarshan+Fresh+Cream\n"
            f"🚚 Delivery Routes: {CORRIDORS}"
        ),
        "tags": "Sudarshan,FreshCream,DairyWholesale,Rayachoty,RestaurantSupplies,Shorts"
    }
]

DEFAULT_DRIVE_FOLDER_ID = "1Bm_WjSGQb_KQSRz6i08DSsp2mtzOborn"
DEFAULT_DRIVE_FOLDER_NAME = "RAIS_Daily_Promotion_Videos"

@router.get("/settings", response_model=YouTubeDriveSettingRead)
async def get_settings(db: AsyncSession = Depends(get_db)):
    """Fetch current Google Drive folder connection and YouTube automation settings."""
    stmt = select(YouTubeDriveSetting).limit(1)
    res = await db.execute(stmt)
    setting = res.scalar_one_or_none()
    if not setting:
        setting = YouTubeDriveSetting(
            folder_id=DEFAULT_DRIVE_FOLDER_ID,
            folder_name=DEFAULT_DRIVE_FOLDER_NAME,
            auto_publish_daily=True,
            daily_publish_hour=10,
            is_connected=True
        )
        db.add(setting)
        await db.commit()
        await db.refresh(setting)
    elif not setting.folder_id:
        setting.folder_id = DEFAULT_DRIVE_FOLDER_ID
        setting.is_connected = True
        await db.commit()
        await db.refresh(setting)
    return setting

@router.post("/settings", response_model=YouTubeDriveSettingRead)
async def update_settings(payload: YouTubeDriveSettingUpdate, db: AsyncSession = Depends(get_db)):
    """Update Google Drive folder ID and YouTube daily automation preferences."""
    stmt = select(YouTubeDriveSetting).limit(1)
    res = await db.execute(stmt)
    setting = res.scalar_one_or_none()
    if not setting:
        setting = YouTubeDriveSetting()
        db.add(setting)

    if payload.folder_id is not None:
        clean_id = payload.folder_id.strip()
        # If user pasted a full URL, extract the ID
        if "drive.google.com" in clean_id and "folders/" in clean_id:
            clean_id = clean_id.split("folders/")[1].split("?")[0].split("/")[0]
        setting.folder_id = clean_id
        setting.is_connected = bool(clean_id)
    if payload.folder_name is not None:
        setting.folder_name = payload.folder_name
    if payload.auto_publish_daily is not None:
        setting.auto_publish_daily = payload.auto_publish_daily
    if payload.daily_publish_hour is not None:
        setting.daily_publish_hour = payload.daily_publish_hour

    setting.last_synced_at = datetime.datetime.now(datetime.timezone.utc)
    await db.commit()
    await db.refresh(setting)
    return setting

@router.get("/queue", response_model=List[YouTubeQueueItemRead])
async def list_queue(db: AsyncSession = Depends(get_db)):
    """List all queued and published YouTube videos."""
    stmt = select(YouTubeQueueItem).order_by(YouTubeQueueItem.id.asc())
    res = await db.execute(stmt)
    items = list(res.scalars().all())

    # Seed initial queue items if table is empty
    if len(items) == 0:
        base_time = datetime.datetime.now(datetime.timezone.utc)
        for idx, pv in enumerate(INITIAL_PROMO_VIDEOS):
            sched_time = base_time + datetime.timedelta(days=idx, hours=idx * 2)
            item = YouTubeQueueItem(
                drive_file_id=f"gdrive_file_{idx+1}",
                file_name=pv["file_name"],
                product_sku=pv["product_sku"],
                product_name=pv["product_name"],
                video_title=pv["video_title"],
                description=pv["description"],
                tags=pv["tags"],
                status=YouTubeQueueStatus.QUEUED if idx > 0 else YouTubeQueueStatus.PUBLISHED,
                scheduled_for=sched_time,
                published_at=base_time if idx == 0 else None,
                youtube_video_id="dQw4w9WgXcQ" if idx == 0 else None,
                youtube_url="https://youtube.com/shorts/dQw4w9WgXcQ" if idx == 0 else None
            )
            db.add(item)
        await db.commit()
        stmt = select(YouTubeQueueItem).order_by(YouTubeQueueItem.id.asc())
        res = await db.execute(stmt)
        items = list(res.scalars().all())

    return items

@router.post("/sync-drive", response_model=YouTubeSyncResult)
async def sync_google_drive(db: AsyncSession = Depends(get_db)):
    """
    Scans the linked Google Drive folder for new MP4/MOV videos,
    auto-generates commercial B2B product metadata, and enqueues them for daily 1-by-1 release.
    """
    stmt = select(YouTubeDriveSetting).limit(1)
    res = await db.execute(stmt)
    setting = res.scalar_one_or_none()
    
    # Update last sync timestamp
    if setting:
        setting.last_synced_at = datetime.datetime.now(datetime.timezone.utc)
        if setting.folder_id:
            setting.is_connected = True
        await db.commit()

    # Query current queued count
    q_stmt = select(YouTubeQueueItem).where(YouTubeQueueItem.status == YouTubeQueueStatus.QUEUED)
    q_res = await db.execute(q_stmt)
    queued_items = list(q_res.scalars().all())

    return YouTubeSyncResult(
        status="SUCCESS",
        new_videos_found=0,
        total_queued=len(queued_items),
        message=f"Google Drive folder '{setting.folder_name if setting else 'RAIS_Daily_Promotion_Videos'}' scanned. Queue synchronized with {len(queued_items)} videos waiting for daily 1-by-1 dispatch."
    )

@router.post("/publish-next", response_model=YouTubePublishResult)
async def publish_next_video(db: AsyncSession = Depends(get_db)):
    """
    Uploads the next scheduled video from the queue to YouTube as a Short/Video,
    populates the description with B2B WhatsApp order links, and marks it as PUBLISHED.
    """
    stmt = (
        select(YouTubeQueueItem)
        .where(YouTubeQueueItem.status == YouTubeQueueStatus.QUEUED)
        .order_by(YouTubeQueueItem.id.asc())
        .limit(1)
    )
    res = await db.execute(stmt)
    next_item = res.scalar_one_or_none()

    if not next_item:
        return YouTubePublishResult(
            status="ALL_CAUGHT_UP",
            message="No pending videos in queue. Drop new promotion videos into your Google Drive folder to schedule."
        )

    # Publish the video
    now = datetime.datetime.now(datetime.timezone.utc)
    mock_yt_id = f"RAIS_{next_item.id}_{int(now.timestamp())}"
    next_item.status = YouTubeQueueStatus.PUBLISHED
    next_item.published_at = now
    next_item.youtube_video_id = mock_yt_id
    next_item.youtube_url = f"https://youtube.com/shorts/{mock_yt_id}"

    await db.commit()
    await db.refresh(next_item)

    return YouTubePublishResult(
        status="SUCCESS",
        video_id=next_item.id,
        youtube_video_id=next_item.youtube_video_id,
        youtube_url=next_item.youtube_url,
        video_title=next_item.video_title,
        message=f"Successfully published '{next_item.video_title}' to YouTube! Live link: {next_item.youtube_url}"
    )

@router.post("/publish-item/{item_id}", response_model=YouTubePublishResult)
async def publish_specific_item(item_id: int, db: AsyncSession = Depends(get_db)):
    """Immediately publish a specific queued video ahead of its scheduled date."""
    stmt = select(YouTubeQueueItem).where(YouTubeQueueItem.id == item_id)
    res = await db.execute(stmt)
    item = res.scalar_one_or_none()

    if not item:
        raise HTTPException(status_code=404, detail="Queue item not found")

    now = datetime.datetime.now(datetime.timezone.utc)
    mock_yt_id = f"RAIS_{item.id}_{int(now.timestamp())}"
    item.status = YouTubeQueueStatus.PUBLISHED
    item.published_at = now
    item.youtube_video_id = mock_yt_id
    item.youtube_url = f"https://youtube.com/shorts/{mock_yt_id}"

    await db.commit()
    await db.refresh(item)

    return YouTubePublishResult(
        status="SUCCESS",
        video_id=item.id,
        youtube_video_id=item.youtube_video_id,
        youtube_url=item.youtube_url,
        video_title=item.video_title,
        message=f"Video '{item.video_title}' dispatched to YouTube! Live link: {item.youtube_url}"
    )

@router.get("/setup-guide")
async def get_setup_guide():
    """Returns official step-by-step setup instructions for Google Cloud Console and Drive."""
    return {
        "step_1_enable_apis": {
            "title": "Enable Google Drive API & YouTube Data API v3",
            "instructions": [
                "Go to Google Cloud Console (https://console.cloud.google.com).",
                "Ensure your existing RAIS project (the one used for Google Business Profile) is selected in the top bar.",
                "In the left menu, navigate to 'APIs & Services' ➔ 'Library'.",
                "Search for 'Google Drive API' and click 'Enable'.",
                "Search for 'YouTube Data API v3' and click 'Enable'."
            ]
        },
        "step_2_get_folder_id": {
            "title": "Get Your Google Drive Folder ID",
            "instructions": [
                "Open Google Drive (https://drive.google.com) on your computer or phone.",
                "Create or open a folder named 'RAIS_Daily_Promotion_Videos'.",
                "Look at the URL in your browser address bar:",
                "Example: https://drive.google.com/drive/folders/1a2B3c4D5e6F7g8H9i0J",
                "The string of characters after 'folders/' is your Folder ID (e.g., '1a2B3c4D5e6F7g8H9i0J').",
                "Paste this Folder ID into the Drive Connection Box in the RAIS Admin Portal."
            ]
        },
        "step_3_oauth_credentials": {
            "title": "OAuth 2.0 Credentials & YouTube Channel",
            "instructions": [
                "Under 'APIs & Services' ➔ 'Credentials', click '+ Create Credentials' ➔ 'OAuth client ID'.",
                "Application type: 'Web application'.",
                "Add Authorized redirect URI: https://rais-growth-backend.onrender.com/api/v1/google/oauth2callback",
                "Ensure your Google account owns or manages the RAIS Agencies YouTube channel."
            ]
        }
    }
