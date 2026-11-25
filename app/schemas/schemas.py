from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, HttpUrl, ConfigDict
from app.models.entities import VerificationStatus, PostStatus, SentimentType, LeadStatus, ReviewOrigin, ReplyStatus

# ================= Business Profile Schemas =================
class BusinessProfileBase(BaseModel):
    business_name: str
    tagline: Optional[str] = None
    address: str
    city: str
    state: str
    pin_code: str
    primary_phone: str
    secondary_phone: Optional[str] = None
    whatsapp_number: str
    website_url: str
    catalogue_url: str
    google_maps_url: Optional[str] = None
    primary_category: str
    secondary_categories: str
    description: Optional[str] = None

class BusinessProfileUpdate(BaseModel):
    business_name: Optional[str] = None
    tagline: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    pin_code: Optional[str] = None
    primary_phone: Optional[str] = None
    secondary_phone: Optional[str] = None
    whatsapp_number: Optional[str] = None
    website_url: Optional[str] = None
    catalogue_url: Optional[str] = None
    google_maps_url: Optional[str] = None
    primary_category: Optional[str] = None
    secondary_categories: Optional[str] = None
    description: Optional[str] = None

class BusinessProfileRead(BusinessProfileBase):
    id: int
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)

# ================= Catalog SKU Schemas =================
class CatalogSKUBase(BaseModel):
    sku: str
    name: str
    brand: str
    category: str
    pack_size: str
    hsn_code: Optional[str] = None
    in_stock: bool = True
    is_commercial_focus: bool = False
    description: Optional[str] = None
    verification_status: VerificationStatus = VerificationStatus.VERIFIED

class CatalogSKUUpdate(BaseModel):
    name: Optional[str] = None
    brand: Optional[str] = None
    category: Optional[str] = None
    pack_size: Optional[str] = None
    in_stock: Optional[bool] = None
    is_commercial_focus: Optional[bool] = None
    description: Optional[str] = None
    verification_status: Optional[VerificationStatus] = None

class CatalogSKURead(CatalogSKUBase):
    id: int
    source: str

    model_config = ConfigDict(from_attributes=True)

# ================= Service Area Schemas =================
class ServiceAreaBase(BaseModel):
    area_name: str
    is_primary: bool = False
    delivery_frequency: str = "Daily"
    directions_url: Optional[str] = None
    notes: Optional[str] = None

class ServiceAreaRead(ServiceAreaBase):
    id: int
    verification_status: VerificationStatus

    model_config = ConfigDict(from_attributes=True)

# ================= Campaign & Post Schemas =================
class CampaignPostBase(BaseModel):
    headline: str
    content_english: str
    content_telugu: Optional[str] = None
    call_to_action: str = "CALL_NOW"
    target_product_sku: Optional[str] = None
    media_url: Optional[str] = None
    day_number: Optional[int] = None

class CampaignPostCreate(CampaignPostBase):
    campaign_id: Optional[int] = None
    scheduled_for: Optional[datetime] = None

class CampaignPostUpdate(BaseModel):
    headline: Optional[str] = None
    content_english: Optional[str] = None
    content_telugu: Optional[str] = None
    call_to_action: Optional[str] = None
    target_product_sku: Optional[str] = None
    media_url: Optional[str] = None
    scheduled_for: Optional[datetime] = None
    status: Optional[PostStatus] = None

class CampaignPostRead(CampaignPostBase):
    id: int
    campaign_id: Optional[int] = None
    status: PostStatus
    scheduled_for: Optional[datetime] = None
    published_at: Optional[datetime] = None
    idempotency_key: Optional[str] = None
    verification_status: VerificationStatus
    validation_flags: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

class CampaignCreate(BaseModel):
    title: str
    objective: str = "B2B Customer Acquisition"
    theme: Optional[str] = None
    posts: List[CampaignPostCreate] = []

class CampaignRead(BaseModel):
    id: int
    title: str
    objective: str
    theme: Optional[str] = None
    status: PostStatus
    is_approved_by_user: bool
    approved_at: Optional[datetime] = None
    created_at: datetime
    posts: List[CampaignPostRead] = []

    model_config = ConfigDict(from_attributes=True)

# ================= Review Schemas =================
class ReviewReplyDraftRead(BaseModel):
    id: int
    review_id: int
    reply_english: str
    reply_telugu: Optional[str] = None
    is_approved: bool
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    published_at: Optional[datetime] = None
    status: str

    model_config = ConfigDict(from_attributes=True)

class ReviewRead(BaseModel):
    id: int
    google_review_id: str
    author_name: str
    author_photo_url: Optional[str] = None
    rating: int
    comment: Optional[str] = None
    create_time: datetime
    sentiment: SentimentType
    is_complaint: bool
    has_replied: bool
    origin: ReviewOrigin = ReviewOrigin.LOCAL_DIRECT
    reply_drafts: List[ReviewReplyDraftRead] = []

    model_config = ConfigDict(from_attributes=True)

class ReviewReplyApproval(BaseModel):
    reply_text: str
    approver_name: str = "Administrator"

# ================= SEO & Competitor Schemas =================
class KeywordTargetRead(BaseModel):
    id: int
    keyword: str
    intent: str
    relevance_score: int
    is_target: bool
    language: str

    model_config = ConfigDict(from_attributes=True)

class CompetitorSnapshotCreate(BaseModel):
    competitor_name: str
    location_area: str
    public_category: Optional[str] = None
    rating: Optional[float] = None
    review_count: int = 0
    notes: Optional[str] = None
    source: str = "Manual Field Observation"

class CompetitorSnapshotRead(BaseModel):
    id: int
    competitor_name: str
    location_area: str
    public_category: Optional[str] = None
    rating: Optional[float] = None
    review_count: int
    verified_status: VerificationStatus
    notes: Optional[str] = None
    source: str

    model_config = ConfigDict(from_attributes=True)

# ================= B2B Lead Schemas =================
class B2BLeadCreate(BaseModel):
    business_name: str
    contact_person: Optional[str] = None
    phone: str
    business_type: str = "Cafe"
    location: str = "Rayachoty"
    product_interest: Optional[str] = None
    lead_source: str = "Google Business Profile"
    notes: Optional[str] = None

class B2BLeadUpdate(BaseModel):
    status: LeadStatus
    notes: Optional[str] = None
    contact_person: Optional[str] = None
    product_interest: Optional[str] = None

class B2BLeadRead(B2BLeadCreate):
    id: int
    status: LeadStatus
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

# ================= Automation Settings Schemas =================
class AutomationSettingUpdate(BaseModel):
    scheduled_publishing_enabled: Optional[bool] = None
    emergency_kill_switch: Optional[bool] = None
    posting_frequency_days: Optional[str] = None
    preferred_post_time: Optional[str] = None

class AutomationSettingRead(BaseModel):
    id: int
    scheduled_publishing_enabled: bool
    emergency_kill_switch: bool
    posting_frequency_days: str
    preferred_post_time: str
    auto_generate_drafts: bool
    require_explicit_campaign_approval: bool
    require_explicit_review_approval: bool
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)

# ================= Scheduler & Google Connection Schemas =================
class PublishCycleResponse(BaseModel):
    status: str
    published_count: int = 0
    simulated_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    message: Optional[str] = None

class GoogleAuthorizeResponse(BaseModel):
    authorization_url: str
    state: str

class GoogleStatusResponse(BaseModel):
    status: str
    connected: bool
    mode: str
    is_verified: bool
    is_live: bool
    is_simulated: bool
    account_id: Optional[str] = None
    location_id: Optional[str] = None
    account_email: Optional[str] = None
    location_name: Optional[str] = None
    primary_category: Optional[str] = None
    scopes_granted: List[str] = []
    message: Optional[str] = None
    actionable_instruction: Optional[str] = None

# ================= YouTube & Google Drive Automation Schemas =================
class YouTubeQueueItemRead(BaseModel):
    id: int
    drive_file_id: Optional[str] = None
    file_name: str
    product_sku: Optional[str] = None
    product_name: Optional[str] = None
    video_title: str
    description: str
    tags: Optional[str] = None
    status: str
    scheduled_for: Optional[datetime] = None
    published_at: Optional[datetime] = None
    youtube_video_id: Optional[str] = None
    youtube_url: Optional[str] = None
    ig_status: Optional[str] = "PENDING"
    ig_media_id: Optional[str] = None
    ig_url: Optional[str] = None
    ig_published_at: Optional[datetime] = None
    ig_error: Optional[str] = None
    fb_status: Optional[str] = "PENDING"
    fb_video_id: Optional[str] = None
    fb_url: Optional[str] = None
    fb_published_at: Optional[datetime] = None
    fb_error: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)

class YouTubeQueueItemCreate(BaseModel):
    file_name: str
    drive_file_id: Optional[str] = None
    product_sku: Optional[str] = None
    product_name: Optional[str] = None
    video_title: str
    description: str
    tags: Optional[str] = None
    scheduled_for: Optional[datetime] = None

class YouTubeDriveSettingRead(BaseModel):
    id: int
    folder_id: Optional[str] = None
    folder_name: str
    auto_publish_daily: bool
    auto_publish_instagram: bool = True
    auto_publish_facebook: bool = True
    daily_publish_hour: int
    is_connected: bool
    oauth_connected: bool = False
    last_synced_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)

class YouTubeDriveSettingUpdate(BaseModel):
    folder_id: Optional[str] = None
    folder_name: Optional[str] = "RAIS_Daily_Promotion_Videos"
    auto_publish_daily: Optional[bool] = True
    auto_publish_instagram: Optional[bool] = True
    auto_publish_facebook: Optional[bool] = True
    daily_publish_hour: Optional[int] = 10

class YouTubeSyncResult(BaseModel):
    status: str
    new_videos_found: int
    total_queued: int
    message: str

class YouTubePublishResult(BaseModel):
    status: str
    video_id: Optional[int] = None
    youtube_video_id: Optional[str] = None
    youtube_url: Optional[str] = None
    video_title: Optional[str] = None
    message: str

# ================= Meta Graph API (Instagram & Facebook) Schemas =================
class MetaConnectRequest(BaseModel):
    access_token: str
    page_id: Optional[str] = None
    ig_user_id: Optional[str] = None

class MetaStatusResponse(BaseModel):
    status: str  # NOT_CONNECTED | CONNECTED | TOKEN_INVALID
    connected: bool
    page_id: Optional[str] = None
    page_name: Optional[str] = None
    ig_user_id: Optional[str] = None
    ig_username: Optional[str] = None
    source: str  # env | database | none
    message: str
    token_verified_at: Optional[datetime] = None

class MetaPublishRequest(BaseModel):
    platforms: List[str] = ["instagram", "facebook"]
