import enum
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, Boolean, Float, DateTime, ForeignKey, Enum as SQLEnum, Index, UniqueConstraint
from sqlalchemy.orm import relationship
from app.core.database import Base

class VerificationStatus(str, enum.Enum):
    VERIFIED = "VERIFIED"
    UNVERIFIED_CLAIM = "UNVERIFIED_CLAIM"
    UNVERIFIED_DRAFT = "UNVERIFIED_DRAFT"
    CONFLICTING = "CONFLICTING"

class PostStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    SCHEDULED = "SCHEDULED"
    PUBLISHING = "PUBLISHING"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"
    PAUSED = "PAUSED"

class SentimentType(str, enum.Enum):
    POSITIVE = "POSITIVE"
    NEUTRAL = "NEUTRAL"
    NEGATIVE = "NEGATIVE"

class ReviewOrigin(str, enum.Enum):
    GOOGLE_AUTHENTIC = "GOOGLE_AUTHENTIC"
    LOCAL_DIRECT = "LOCAL_DIRECT"
    SIMULATED_DEMO = "SIMULATED_DEMO"

class ReplyStatus(str, enum.Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED_NOT_PUBLISHED = "APPROVED_NOT_PUBLISHED"
    SIMULATED_DEMO_APPROVAL = "SIMULATED_DEMO_APPROVAL"
    PUBLISHED_TO_GOOGLE = "PUBLISHED_TO_GOOGLE"
    PUBLICATION_FAILED = "PUBLICATION_FAILED"

class LeadStatus(str, enum.Enum):
    NEW = "NEW"
    QUALIFIED = "QUALIFIED"
    CONTACTED = "CONTACTED"
    INTERESTED = "INTERESTED"
    QUOTATION_REQUESTED = "QUOTATION_REQUESTED"
    QUOTED = "QUOTED"
    CONVERTED = "CONVERTED"
    NOT_INTERESTED = "NOT_INTERESTED"
    FOLLOW_UP_REQUIRED = "FOLLOW_UP_REQUIRED"
    LOST = "LOST"

class YouTubeQueueStatus(str, enum.Enum):
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"

# ==================== Business Info & Catalog Models ====================

class BusinessProfile(Base):
    __tablename__ = "business_profiles"

    id = Column(Integer, primary_key=True)
    business_name = Column(String(200), default="RAIS Agencies", nullable=False)
    tagline = Column(String(255), default="Wholesale Frozen Food Products & Packaging Solutions")
    address = Column(String(300), default="Beside Indel Money Bank, Sundupalli Road, Near Reddies Colony, Rayachoty – 516269")
    city = Column(String(100), default="Rayachoty")
    state = Column(String(100), default="Andhra Pradesh")
    pin_code = Column(String(20), default="516269")
    primary_phone = Column(String(20), default="9347453135", nullable=False)
    secondary_phone = Column(String(20), nullable=True)  # Kept optional, excluded unless verified
    whatsapp_number = Column(String(20), default="919347453135")
    website_url = Column(String(255), default="https://dataengineer-irfan.github.io/RAIS-AGENCIES/")
    catalogue_url = Column(String(255), default="https://dataengineer-irfan.github.io/RAIS-AGENCIES/catalogue.html")
    google_maps_url = Column(String(500), nullable=True)
    latitude = Column(Float, default=14.0583)
    longitude = Column(Float, default=78.7523)
    primary_category = Column(String(100), default="Wholesale food store")
    secondary_categories = Column(Text, default="Frozen food store, Restaurant supply store, Packaging supply store, Food products supplier")
    description = Column(Text, nullable=True)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

class CatalogSKU(Base):
    __tablename__ = "catalog_skus"

    id = Column(Integer, primary_key=True)
    sku = Column(String(50), unique=True, index=True, nullable=False)
    name = Column(String(200), nullable=False)
    brand = Column(String(100), nullable=False)
    category = Column(String(100), nullable=False, index=True)
    pack_size = Column(String(100), nullable=False)
    hsn_code = Column(String(50), nullable=True)
    in_stock = Column(Boolean, default=True)
    is_commercial_focus = Column(Boolean, default=False)
    description = Column(Text, nullable=True)
    source = Column(String(100), default="RAIS Master Catalog")
    verification_status = Column(SQLEnum(VerificationStatus), default=VerificationStatus.VERIFIED)
    selling_price = Column(Float, nullable=True)
    price_unit = Column(String(40), nullable=True)
    stock_quantity = Column(Integer, nullable=True)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

class ServiceArea(Base):
    __tablename__ = "service_areas"

    id = Column(Integer, primary_key=True)
    area_name = Column(String(100), unique=True, nullable=False)
    is_primary = Column(Boolean, default=False)
    delivery_frequency = Column(String(100), default="Daily")
    directions_url = Column(String(500), nullable=True)
    notes = Column(Text, nullable=True)
    verification_status = Column(SQLEnum(VerificationStatus), default=VerificationStatus.VERIFIED)

# ==================== Google API Connection & Location Models ====================

class GoogleConnection(Base):
    __tablename__ = "google_connections"

    id = Column(Integer, primary_key=True)
    account_email = Column(String(200), nullable=True)
    encrypted_access_token = Column(Text, nullable=True)
    encrypted_refresh_token = Column(Text, nullable=True)
    token_expiry = Column(DateTime(timezone=True), nullable=True)
    is_connected = Column(Boolean, default=False)
    is_mock = Column(Boolean, default=True)
    account_id = Column(String(100), nullable=True)
    account_name = Column(String(200), nullable=True)
    location_id = Column(String(100), nullable=True)
    location_name = Column(String(200), nullable=True)
    scopes_granted = Column(Text, nullable=True)
    last_sync = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

class OAuthState(Base):
    __tablename__ = "oauth_states"

    id = Column(Integer, primary_key=True)
    state = Column(String(128), unique=True, index=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    expires_at = Column(DateTime(timezone=True), nullable=False)
    is_used = Column(Boolean, default=False)

class BusinessLocation(Base):
    __tablename__ = "business_locations"

    id = Column(Integer, primary_key=True)
    location_id = Column(String(100), unique=True, index=True, nullable=False)
    location_name = Column(String(200), default="RAIS Agencies")
    address_line = Column(String(300), default="Beside Indel Money Bank, Sundupalli Road, Near Reddies Colony")
    city = Column(String(100), default="Rayachoty")
    phone = Column(String(20), default="9347453135")
    primary_category = Column(String(100), default="Wholesale food store")
    is_verified = Column(Boolean, default=False)
    total_reviews = Column(Integer, default=0)
    average_rating = Column(Float, default=0.0)

# ==================== Campaigns & Publishing Models ====================

class Campaign(Base):
    __tablename__ = "campaigns"

    id = Column(Integer, primary_key=True)
    title = Column(String(200), nullable=False)
    objective = Column(String(100), default="B2B Acquisition")
    theme = Column(String(100), nullable=True)
    status = Column(SQLEnum(PostStatus), default=PostStatus.DRAFT, index=True)
    is_approved_by_user = Column(Boolean, default=False)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    posts = relationship("CampaignPost", back_populates="campaign", cascade="all, delete-orphan")

class CampaignPost(Base):
    __tablename__ = "campaign_posts"

    id = Column(Integer, primary_key=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=True)
    day_number = Column(Integer, nullable=True)
    headline = Column(String(255), nullable=False)
    content_english = Column(Text, nullable=False)
    content_telugu = Column(Text, nullable=True)
    call_to_action = Column(String(50), default="CALL_NOW")
    target_product_sku = Column(String(50), nullable=True)
    media_url = Column(String(500), nullable=True)
    status = Column(SQLEnum(PostStatus), default=PostStatus.DRAFT, index=True)
    scheduled_for = Column(DateTime(timezone=True), nullable=True, index=True)
    published_at = Column(DateTime(timezone=True), nullable=True)
    idempotency_key = Column(String(100), unique=True, index=True, nullable=True)
    google_post_id = Column(String(100), nullable=True)
    verification_status = Column(SQLEnum(VerificationStatus), default=VerificationStatus.UNVERIFIED_DRAFT)
    validation_flags = Column(Text, nullable=True)  # JSON string of passed/failed deterministic checks

    campaign = relationship("Campaign", back_populates="posts")
    publishing_jobs = relationship("PublishingJob", back_populates="post", cascade="all, delete-orphan")

class PublishingJob(Base):
    __tablename__ = "publishing_jobs"

    id = Column(Integer, primary_key=True)
    post_id = Column(Integer, ForeignKey("campaign_posts.id"), nullable=False)
    scheduled_time = Column(DateTime(timezone=True), nullable=False, index=True)
    status = Column(SQLEnum(PostStatus), default=PostStatus.SCHEDULED, index=True)
    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=3)
    last_error = Column(Text, nullable=True)
    published_time = Column(DateTime(timezone=True), nullable=True)
    idempotency_token = Column(String(100), unique=True, nullable=False)

    post = relationship("CampaignPost", back_populates="publishing_jobs")

# ==================== Reviews & Approvals ====================

class Review(Base):
    __tablename__ = "reviews"

    id = Column(Integer, primary_key=True)
    google_review_id = Column(String(100), unique=True, index=True, nullable=False)
    author_name = Column(String(150), nullable=False)
    author_photo_url = Column(String(500), nullable=True)
    rating = Column(Integer, nullable=False, index=True)
    comment = Column(Text, nullable=True)
    create_time = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    sentiment = Column(SQLEnum(SentimentType), default=SentimentType.POSITIVE)
    is_complaint = Column(Boolean, default=False)
    has_replied = Column(Boolean, default=False)
    origin = Column(SQLEnum(ReviewOrigin), default=ReviewOrigin.LOCAL_DIRECT, nullable=False)

    reply_drafts = relationship("ReviewReplyDraft", back_populates="review", cascade="all, delete-orphan")

class ReviewReplyDraft(Base):
    __tablename__ = "review_reply_drafts"

    id = Column(Integer, primary_key=True)
    review_id = Column(Integer, ForeignKey("reviews.id"), nullable=False)
    reply_english = Column(Text, nullable=False)
    reply_telugu = Column(Text, nullable=True)
    is_approved = Column(Boolean, default=False, nullable=False)  # Explicit human approval requirement
    approved_by = Column(String(100), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    published_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(50), default="PENDING_APPROVAL")

    review = relationship("Review", back_populates="reply_drafts")

# ==================== SEO & Competitor Intelligence ====================

class KeywordTarget(Base):
    __tablename__ = "keyword_targets"

    id = Column(Integer, primary_key=True)
    keyword = Column(String(150), unique=True, index=True, nullable=False)
    intent = Column(String(50), default="Commercial B2B")
    relevance_score = Column(Integer, default=90)
    is_target = Column(Boolean, default=True)
    language = Column(String(20), default="en")

class CompetitorSnapshot(Base):
    __tablename__ = "competitor_snapshots"

    id = Column(Integer, primary_key=True)
    competitor_name = Column(String(200), nullable=False)
    location_area = Column(String(150), nullable=False)
    public_category = Column(String(100), nullable=True)
    rating = Column(Float, nullable=True)
    review_count = Column(Integer, default=0)
    verified_status = Column(SQLEnum(VerificationStatus), default=VerificationStatus.UNVERIFIED_CLAIM)
    notes = Column(Text, nullable=True)
    source = Column(String(100), default="Public Directory Observation")
    website_url = Column(String(500), nullable=True)
    public_offers = Column(Text, nullable=True)
    last_checked_at = Column(DateTime(timezone=True), nullable=True)
    change_history_json = Column(Text, nullable=True)
    confidence = Column(String(30), default="MANUAL")

# ==================== B2B Leads ====================

class B2BLead(Base):
    __tablename__ = "b2b_leads"

    id = Column(Integer, primary_key=True)
    business_name = Column(String(200), nullable=False)
    contact_person = Column(String(100), nullable=True)
    phone = Column(String(20), nullable=False, index=True)
    business_type = Column(String(50), default="Cafe")  # Cafe, Restaurant, Bakery, Shawarma, Hotel, QSR
    location = Column(String(150), default="Rayachoty")
    product_interest = Column(String(255), nullable=True)
    status = Column(SQLEnum(LeadStatus), default=LeadStatus.NEW, index=True)
    lead_source = Column(String(100), default="Google Business Profile")
    notes = Column(Text, nullable=True)
    assigned_owner = Column(String(100), default="Depot Sales Lead")
    lead_score = Column(Integer, default=50)
    segment = Column(String(50), default="General B2B")
    last_interaction_at = Column(DateTime(timezone=True), nullable=True)
    next_followup_at = Column(DateTime(timezone=True), nullable=True)
    preferences_json = Column(Text, nullable=True)
    opted_out_whatsapp = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

# ==================== Media Assets ====================

class MediaAsset(Base):
    __tablename__ = "media_assets"

    id = Column(Integer, primary_key=True)
    title = Column(String(200), nullable=False)
    filename = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    category = Column(String(100), default="Snacks")
    caption = Column(Text, nullable=True)
    media_type = Column(String(30), default="image")  # image, video, thumbnail, brand
    tags = Column(String(300), nullable=True)
    sku = Column(String(50), nullable=True)
    campaign_id = Column(Integer, nullable=True)
    file_hash = Column(String(64), nullable=True, index=True)
    usage_count = Column(Integer, default=0)
    thumbnail_url = Column(String(500), nullable=True)
    is_verified_real_shop_photo = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

# ==================== Automation Control Settings ====================

class AutomationSetting(Base):
    __tablename__ = "automation_settings"

    id = Column(Integer, primary_key=True)
    scheduled_publishing_enabled = Column(Boolean, default=True)
    emergency_kill_switch = Column(Boolean, default=False)  # Immediately blocks all publishing jobs
    posting_frequency_days = Column(String(100), default="Mon,Wed,Fri,Sun")
    preferred_post_time = Column(String(10), default="10:30")
    auto_generate_drafts = Column(Boolean, default=True)
    require_explicit_campaign_approval = Column(Boolean, default=True)
    require_explicit_review_approval = Column(Boolean, default=True)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

# ==================== YouTube & Google Drive Automation ====================

class YouTubeQueueItem(Base):
    __tablename__ = "youtube_queue_items"

    id = Column(Integer, primary_key=True)
    drive_file_id = Column(String(100), unique=True, index=True)
    file_name = Column(String(255), nullable=False)
    product_sku = Column(String(50), nullable=True)
    product_name = Column(String(200), nullable=True)
    video_title = Column(String(150), nullable=False)
    description = Column(Text, nullable=False)
    tags = Column(String(500), nullable=True)
    status = Column(SQLEnum(YouTubeQueueStatus), default=YouTubeQueueStatus.QUEUED)
    scheduled_for = Column(DateTime(timezone=True), nullable=True)
    published_at = Column(DateTime(timezone=True), nullable=True)
    youtube_video_id = Column(String(100), nullable=True)
    youtube_url = Column(String(255), nullable=True)
    # Cross-platform Meta (Instagram Reels & Facebook Page) tracking
    ig_status = Column(String(50), default="PENDING")
    ig_media_id = Column(String(100), nullable=True)
    ig_url = Column(String(255), nullable=True)
    ig_published_at = Column(DateTime(timezone=True), nullable=True)
    ig_error = Column(Text, nullable=True)
    fb_status = Column(String(50), default="PENDING")
    fb_video_id = Column(String(100), nullable=True)
    fb_url = Column(String(255), nullable=True)
    fb_published_at = Column(DateTime(timezone=True), nullable=True)
    fb_error = Column(Text, nullable=True)
    first_comment = Column(Text, nullable=True)
    ig_comment_id = Column(String(100), nullable=True)
    fb_comment_id = Column(String(100), nullable=True)
    ai_analyzed = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class YouTubeDriveSetting(Base):
    __tablename__ = "youtube_drive_settings"

    id = Column(Integer, primary_key=True)
    folder_id = Column(String(100), nullable=True)
    folder_name = Column(String(150), default="RAIS_Daily_Promotion_Videos")
    auto_publish_daily = Column(Boolean, default=True)
    auto_publish_instagram = Column(Boolean, default=True)
    auto_publish_facebook = Column(Boolean, default=True)
    auto_post_immediately = Column(Boolean, default=True)
    auto_first_comment = Column(Boolean, default=True)
    encrypted_gemini_api_key = Column(Text, nullable=True)
    daily_publish_hour = Column(Integer, default=10)  # 10:00 AM IST
    is_connected = Column(Boolean, default=False)
    last_synced_at = Column(DateTime(timezone=True), nullable=True)

class MetaConnection(Base):
    __tablename__ = "meta_connections"

    id = Column(Integer, primary_key=True)
    page_id = Column(String(100), nullable=True)
    page_name = Column(String(200), nullable=True)
    ig_user_id = Column(String(100), nullable=True)
    ig_username = Column(String(150), nullable=True)
    encrypted_page_token = Column(Text, nullable=True)
    is_connected = Column(Boolean, default=False)
    token_verified_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class AdminAccount(Base):
    __tablename__ = "admin_accounts"

    id = Column(Integer, primary_key=True)
    username = Column(String(100), unique=True, nullable=False, default="admin")
    hashed_passkey = Column(String(255), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class AnalyticsEvent(Base):
    __tablename__ = "analytics_events"

    id = Column(Integer, primary_key=True)
    event_type = Column(String(50), nullable=False, index=True)
    path = Column(String(255), default="/")
    source = Column(String(80), default="Google / Direct", index=True)
    sku = Column(String(80), nullable=True)
    product_name = Column(String(200), nullable=True)
    visitor_id = Column(String(120), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)


# ==================== Central Automation & Workflow Engine ====================

class WorkflowExecutionStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    RETRYING = "RETRYING"


class ReelAssetStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    SCHEDULED = "SCHEDULED"
    PUBLISHING = "PUBLISHING"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"


class WorkflowDefinition(Base):
    __tablename__ = "workflow_definitions"

    id = Column(Integer, primary_key=True)
    slug = Column(String(100), unique=True, index=True, nullable=False)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    trigger_type = Column(String(60), nullable=False, index=True)
    conditions_json = Column(Text, default="[]")
    actions_json = Column(Text, default="[]")
    retry_policy_json = Column(Text, default='{"max_attempts": 3, "backoff_seconds": 30}')
    approval_required = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True, index=True)
    is_paused = Column(Boolean, default=False)
    schedule_cron = Column(String(100), nullable=True)
    last_run_at = Column(DateTime(timezone=True), nullable=True)
    next_run_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    executions = relationship("WorkflowExecution", back_populates="workflow", cascade="all, delete-orphan")


class WorkflowExecution(Base):
    __tablename__ = "workflow_executions"

    id = Column(Integer, primary_key=True)
    execution_uid = Column(String(64), unique=True, index=True, nullable=False)
    workflow_id = Column(Integer, ForeignKey("workflow_definitions.id"), nullable=False, index=True)
    trigger_type = Column(String(60), nullable=False)
    status = Column(SQLEnum(WorkflowExecutionStatus), default=WorkflowExecutionStatus.PENDING, index=True)
    idempotency_key = Column(String(150), unique=True, index=True, nullable=True)
    lock_token = Column(String(64), nullable=True)
    input_json = Column(Text, default="{}")
    output_json = Column(Text, default="{}")
    error_message = Column(Text, nullable=True)
    attempt_count = Column(Integer, default=0)
    max_attempts = Column(Integer, default=3)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)

    workflow = relationship("WorkflowDefinition", back_populates="executions")
    steps = relationship("WorkflowExecutionStep", back_populates="execution", cascade="all, delete-orphan")
    approvals = relationship("AutomationApproval", back_populates="execution", cascade="all, delete-orphan")


class WorkflowExecutionStep(Base):
    __tablename__ = "workflow_execution_steps"

    id = Column(Integer, primary_key=True)
    execution_id = Column(Integer, ForeignKey("workflow_executions.id"), nullable=False, index=True)
    step_index = Column(Integer, nullable=False)
    step_name = Column(String(150), nullable=False)
    action_type = Column(String(80), nullable=False)
    status = Column(String(40), default="PENDING")
    input_json = Column(Text, default="{}")
    output_json = Column(Text, default="{}")
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    execution = relationship("WorkflowExecution", back_populates="steps")


class AutomationApproval(Base):
    __tablename__ = "automation_approvals"

    id = Column(Integer, primary_key=True)
    execution_id = Column(Integer, ForeignKey("workflow_executions.id"), nullable=False, index=True)
    step_id = Column(Integer, nullable=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    payload_json = Column(Text, default="{}")
    status = Column(String(30), default="PENDING", index=True)  # PENDING, APPROVED, REJECTED
    reviewed_by = Column(String(100), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    decision_notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    execution = relationship("WorkflowExecution", back_populates="approvals")


# ==================== Persistent Reels Video Studio ====================

class ReelsAsset(Base):
    __tablename__ = "reels_assets"

    id = Column(Integer, primary_key=True)
    drive_file_id = Column(String(120), unique=True, index=True, nullable=True)
    youtube_queue_item_id = Column(Integer, ForeignKey("youtube_queue_items.id"), nullable=True)
    title = Column(String(250), nullable=False)
    brand = Column(String(100), default="RAIS Agencies")
    product_sku = Column(String(60), nullable=True)
    product_name = Column(String(200), nullable=True)
    theme = Column(String(100), default="frozen_products")
    video_url = Column(String(500), nullable=True)
    thumbnail_url = Column(String(500), nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    resolution = Column(String(40), default="1080x1920")
    aspect_ratio = Column(String(20), default="9:16")
    platforms_json = Column(Text, default='["instagram", "facebook", "youtube"]')
    caption_english = Column(Text, nullable=True)
    caption_telugu = Column(Text, nullable=True)
    caption_hindi = Column(Text, nullable=True)
    hashtags = Column(String(500), nullable=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=True)
    scheduled_for = Column(DateTime(timezone=True), nullable=True, index=True)
    status = Column(SQLEnum(ReelAssetStatus), default=ReelAssetStatus.DRAFT, index=True)
    published_url = Column(String(500), nullable=True)
    platform_post_id = Column(String(150), nullable=True)
    error_history_json = Column(Text, default="[]")
    approved_by = Column(String(100), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


# ==================== Google Places Lead Discovery & CRM Enquiries ====================

class LeadDiscoveryResult(Base):
    __tablename__ = "lead_discovery_results"

    id = Column(Integer, primary_key=True)
    place_id = Column(String(150), unique=True, index=True, nullable=False)
    business_name = Column(String(200), nullable=False)
    address = Column(String(350), nullable=True)
    phone = Column(String(40), nullable=True)
    website = Column(String(300), nullable=True)
    maps_url = Column(String(500), nullable=True)
    category = Column(String(100), default="Restaurant")
    location_query = Column(String(120), default="Rayachoty")
    rating = Column(Float, nullable=True)
    user_ratings_total = Column(Integer, default=0)
    lead_score = Column(Integer, default=50)
    converted_lead_id = Column(Integer, ForeignKey("b2b_leads.id"), nullable=True)
    discovered_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    last_refreshed_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class CustomerEnquiry(Base):
    __tablename__ = "customer_enquiries"

    id = Column(Integer, primary_key=True)
    lead_id = Column(Integer, ForeignKey("b2b_leads.id"), nullable=True, index=True)
    channel = Column(String(40), default="WEBSITE", index=True)  # WHATSAPP, WEBSITE, CRM, SOCIAL, MANUAL
    customer_name = Column(String(150), nullable=False)
    phone = Column(String(30), nullable=False, index=True)
    product_sku = Column(String(60), nullable=True)
    product_name = Column(String(200), nullable=True)
    quantity_text = Column(String(120), nullable=True)
    notes = Column(Text, nullable=True)
    status = Column(String(40), default="NEW", index=True)  # NEW, QUOTED, FOLLOW_UP, CONVERTED, CLOSED
    assigned_owner = Column(String(100), default="Depot Sales Lead")
    prepared_response = Column(Text, nullable=True)
    quotation_json = Column(Text, nullable=True)
    requires_confirmation = Column(Boolean, default=True)
    confirmed_by = Column(String(100), nullable=True)
    linked_order_ref = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class CustomerInteraction(Base):
    __tablename__ = "customer_interactions"

    id = Column(Integer, primary_key=True)
    lead_id = Column(Integer, ForeignKey("b2b_leads.id"), nullable=False, index=True)
    channel = Column(String(40), default="CRM")
    direction = Column(String(20), default="OUTBOUND")
    summary = Column(Text, nullable=False)
    created_by = Column(String(100), default="admin")
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)


# ==================== WhatsApp Business Cloud API ====================

class WhatsAppConfig(Base):
    __tablename__ = "whatsapp_configs"

    id = Column(Integer, primary_key=True)
    phone_number_id = Column(String(100), nullable=True)
    waba_id = Column(String(100), nullable=True)
    encrypted_access_token = Column(Text, nullable=True)
    verify_token = Column(String(120), default="rais-wa-verify-2026")
    is_connected = Column(Boolean, default=False)
    last_verified_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class WhatsAppMessage(Base):
    __tablename__ = "whatsapp_messages"

    id = Column(Integer, primary_key=True)
    wa_message_id = Column(String(150), unique=True, index=True, nullable=True)
    lead_id = Column(Integer, ForeignKey("b2b_leads.id"), nullable=True, index=True)
    direction = Column(String(20), default="OUTBOUND")  # INBOUND, OUTBOUND
    phone = Column(String(30), nullable=False, index=True)
    message_type = Column(String(30), default="text")  # text, template
    body = Column(Text, nullable=False)
    template_name = Column(String(100), nullable=True)
    status = Column(String(40), default="QUEUED")  # RECEIVED, QUEUED, SENT, DELIVERED, READ, FAILED
    error_detail = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)


# ==================== Monitoring & AI Provenance Logs ====================

class IntegrationSyncLog(Base):
    __tablename__ = "integration_sync_logs"

    id = Column(Integer, primary_key=True)
    integration_name = Column(String(80), nullable=False, index=True)
    status = Column(String(40), nullable=False)  # CONNECTED, DISCONNECTED, AUTH_EXPIRED, PERMISSION_MISSING, RATE_LIMITED, UNAVAILABLE
    last_success_at = Column(DateTime(timezone=True), nullable=True)
    last_error = Column(Text, nullable=True)
    details_json = Column(Text, nullable=True)
    checked_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)


class AIGenerationLog(Base):
    __tablename__ = "ai_generation_logs"

    id = Column(Integer, primary_key=True)
    task_type = Column(String(60), nullable=False, index=True)
    provider = Column(String(50), nullable=False)  # gemini, template_engine
    model_used = Column(String(80), nullable=True)
    prompt_summary = Column(String(300), nullable=True)
    output_preview = Column(Text, nullable=True)
    fallback_used = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
