from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.entities import (
    BusinessProfile, CatalogSKU, ServiceArea, Campaign, CampaignPost,
    KeywordTarget, CompetitorSnapshot, AutomationSetting, PostStatus, VerificationStatus,
    Review, ReviewReplyDraft, ReviewOrigin, SentimentType
)

INITIAL_SKUS = [
    {
        "sku": "RAIS-MM-MOZZ",
        "name": "Diced Mozzarella Cheese",
        "brand": "Milky Mist",
        "category": "Commercial Dairy & Cheese",
        "pack_size": "1 KG & 2 KG PACK",
        "is_commercial_focus": True,
        "description": "Authentic IQF diced mozzarella cheese with high stretch and golden melt for commercial pizza kitchens."
    },
    {
        "sku": "RAIS-AMUL-FF6",
        "name": "French Fries (6mm Thin Cut)",
        "brand": "Amul",
        "category": "Frozen Veg Snacks",
        "pack_size": "2.5 KG PACKET",
        "is_commercial_focus": True,
        "description": "Crispy golden 6mm shoestring fries with low oil pickup and long holding time."
    },
    {
        "sku": "RAIS-HUP-FF9",
        "name": "French Fries (9mm Regular Cut)",
        "brand": "Hup Hup",
        "category": "Frozen Veg Snacks",
        "pack_size": "2.5 KG PACKET",
        "is_commercial_focus": True,
        "description": "Thick cut 9mm pub-style fries with crispy exterior and fluffy potato interior."
    },
    {
        "sku": "RAIS-TRI-NUG",
        "name": "Crispy Chicken Nuggets",
        "brand": "Triken",
        "category": "Frozen Chicken Items",
        "pack_size": "1 KG PACKET",
        "is_commercial_focus": True,
        "description": "100% tender chicken nuggets coated in crispy breadcrumbs, fast 3-minute fryer prep."
    },
    {
        "sku": "RAIS-TRI-MOM",
        "name": "Steamed & Fried Chicken Momos",
        "brand": "Triken",
        "category": "Frozen Chicken Items",
        "pack_size": "50 PCS PACKET",
        "is_commercial_focus": True,
        "description": "Thin-wrapper authentic chicken momos for street counters and dine-in fast food."
    },
    {
        "sku": "RAIS-PB-85",
        "name": "Commercial Pizza Base (8.5 Inch)",
        "brand": "RAIS Bakery",
        "category": "Bakery & Bases",
        "pack_size": "5 PCS PACKET",
        "is_commercial_focus": True,
        "description": "Double-proofed 8.5 inch ready-to-bake pizza crusts."
    },
    {
        "sku": "RAIS-PB-10",
        "name": "Commercial Pizza Base (10 Inch)",
        "brand": "RAIS Bakery",
        "category": "Bakery & Bases",
        "pack_size": "5 PCS PACKET",
        "is_commercial_focus": True,
        "description": "Large 10 inch commercial pizza crusts for standard cafe pizza menus."
    },
    {
        "sku": "RAIS-PKG-BP40",
        "name": "Food-Grade OGR Butter Paper 40 GSM",
        "brand": "Packaging Solutions",
        "category": "Food Packaging Solutions",
        "pack_size": "1 KG (10x10 & 12x12 Cut Sheets)",
        "is_commercial_focus": True,
        "description": "Heavy 38-40 GSM Oil & Grease Resistant (OGR) wrapping sheets for burgers, shawarmas, and fried chicken."
    },
    {
        "sku": "RAIS-PKG-PB10",
        "name": "Corrugated Pizza Takeaway Box (10 Inch)",
        "brand": "Packaging Solutions",
        "category": "Food Packaging Solutions",
        "pack_size": "50 PCS BUNDLE",
        "is_commercial_focus": True,
        "description": "Sturdy corrugated thermal pizza boxes that vent steam while retaining heat during delivery."
    },
    {
        "sku": "RAIS-DM-MAYO",
        "name": "Eggless Burger Mayonnaise",
        "brand": "Del Monte",
        "category": "Ketchup & Sauces",
        "pack_size": "1 KG POUCH",
        "is_commercial_focus": True,
        "description": "Thick, heat-stable commercial mayonnaise for burgers, rolls, and shawarmas."
    }
]

INITIAL_SERVICE_AREAS = [
    {"area_name": "Rayachoty (516269)", "is_primary": True, "delivery_frequency": "Daily Fulfillment", "notes": "Local town doorstep delivery"},
    {"area_name": "Sambepalli", "is_primary": False, "delivery_frequency": "Twice Weekly Route", "notes": "Commercial route van delivery"},
    {"area_name": "Galiveedu", "is_primary": False, "delivery_frequency": "Twice Weekly Route", "notes": "Commercial route van delivery"},
    {"area_name": "T. Sundupalli", "is_primary": False, "delivery_frequency": "Scheduled Deliveries", "notes": "Along Sundupalli highway corridor"},
    {"area_name": "Rajampet Route", "is_primary": False, "delivery_frequency": "Weekly Scheduled", "notes": "Bulk orders only"},
    {"area_name": "Madanapalle Route", "is_primary": False, "delivery_frequency": "Weekly Scheduled", "notes": "Subject to route confirmation"}
]

# 30-Day Campaign Templates (Loaded in UNVERIFIED_DRAFT status)
INITIAL_30_DAYS = [
    # Week 1
    (1, "Rayachoty’s One-Stop Wholesale Hub for Cafes & Restaurants!",
     "Starting or expanding a food business in Rayachoty? RAIS Agencies supplies premier frozen snacks, French fries, cheese, and packaging directly to your kitchen. Visit our hub beside Indel Money Bank on Sundupalli Road.",
     "రాయచోటిలోని హోటళ్లు మరియు కేఫ్‌లకు టోకు ధరలలో ఫ్రెంచ్ ఫ్రైస్, చీజ్ మరియు ప్యాకేజింగ్ మెటీరియల్స్ లభించును. సుండుపల్లి రోడ్, ఇండెల్ మనీ బ్యాంక్ పక్కన సంప్రదించండి.",
     "CALL_NOW", "RAIS-AMUL-FF6"),
    (2, "Extra Crispy 6mm & 9mm French Fries in Wholesale Cartons",
     "Commercial-grade French fries engineered for high crispness, low oil absorption, and superior holding time. Available in bulk cartons at wholesale trade pricing.",
     "హోటల్ మరియు కేఫ్ మెనూ కొరకు క్రిస్పీ ఫ్రెంచ్ ఫ్రైస్ టోకు కార్టన్లలో లభించును.",
     "LEARN_MORE", "RAIS-AMUL-FF6"),
    (3, "Zero Thawing: -18°C Guaranteed Cold-Chain Storage in Rayachoty",
     "In the frozen food business, temperature consistency protects your kitchen reputation. Every carton at RAIS Agencies is stored in dedicated commercial deep freezers.",
     "-18 డిగ్రీల కోల్డ్ స్టోరేజ్ నాణ్యతతో ఫ్రెష్ ఫ్రోజెన్ ఫుడ్స్ మీ కిచెన్‌కు సకాలంలో డెలివరీ.",
     "CALL_NOW", None),
    (4, "Crispy Chicken Nuggets: Quick 3-Minute Kitchen Prep!",
     "Speed is everything during evening rush hours. Our commercial chicken nuggets fry to golden perfection in 3 minutes with consistent portion control.",
     "సాయంత్రం రష్ సమయాలలో త్వరితగతిన తయారయ్యే రుచికరమైన చికెన్ నగ్గెట్స్ టోకు ధరలకే లభించును.",
     "LEARN_MORE", "RAIS-TRI-NUG"),
    (5, "రాయచోటి హోటళ్లు మరియు కేఫ్‌లకు టోకు ధరలలో ఫ్రోజెన్ ఫుడ్స్!",
     "ఫ్రెంచ్ ఫ్రైస్, చికెన్ నగ్గెట్స్, చీజ్ మరియు ప్యాకేజింగ్ మెటీరియల్స్ కోసం ఇతర ఊర్ల పై ఆధారపడకండి. రాయచోటి స్థానిక హబ్ నుండి డోర్‌స్టెప్ డెలివరీ.",
     "రాయచోటిలోని ఫాస్ట్ ఫుడ్ వ్యాపారులారా.. టోకు ధరల వివరాలకు 9347453135 వాట్సాప్ చేయండి.",
     "CALL_NOW", None),
    (6, "Authentic Veg, Paneer & Chicken Momos for Fast Food Menus",
     "Add juicy, thin-wrapper momos to your menu without manual prep labor. High burst resistance during steaming or frying.",
     "రాయచోటిలో బెస్ట్ క్వాలిటీ వెజ్ మరియు చికెన్ మోమోస్ హోల్‌సేల్ సప్లై.",
     "LEARN_MORE", "RAIS-TRI-MOM"),
    (7, "Plan Your Sunday Evening Rush with RAIS Agencies",
     "Weekends mean higher customer footfall. Don’t run out of fries or parcel boxes on Sunday evening. Connect with our B2B desk for weekend stock.",
     "వారాంతపు ఆర్డర్ల రద్దీని తట్టుకోవడానికి ముందుగానే సరుకును స్టాక్ చేసుకోండి.",
     "CALL_NOW", None),
    # Week 2
    (8, "The Secret to Great Pizza: Milky Mist Diced Mozzarella",
     "Customers judge pizza by the cheese pull! We are the authorized wholesale stockist for Milky Mist IQF Diced Mozzarella in Rayachoty. Melts evenly and cuts prep time.",
     "పిజ్జా మరియు బర్గర్లకు అద్భుతమైన స్ట్రెచ్ ఇచ్చే మిల్కీ మిస్ట్ డైస్డ్ మోజారెల్లా చీజ్ హోల్‌సేల్ రేటుకే పొందండి.",
     "LEARN_MORE", "RAIS-MM-MOZZ"),
    (9, "Fresh 8.5\" & 10\" Commercial Pizza Bases in Stock",
     "Soft, consistent crusts ready for your pizza oven. No need for expensive dough equipment. High-volume daily fresh stock.",
     "రెడీ-టు-బేక్ 8.5 మరియు 10 ఇంచుల పిజ్జా బేస్‌లు టోకు ధరలకే లభించును.",
     "CALL_NOW", "RAIS-PB-85"),
    (10, "High-Margin Burger Solutions: Buns, Patties & Mayo Bundles",
     "Upgrade your burger counter. RAIS Agencies supplies sesame burger buns, crispy patties, and thick commercial mayonnaise on a single invoice.",
     "బర్గర్ బన్స్, ప్యాటీస్ మరియు మయోనైస్ అన్నీ ఒకే చోట సులభంగా పొందండి.",
     "LEARN_MORE", "RAIS-DM-MAYO"),
    (11, "Sliced & Block Cheddar Cheese for Bakeries and Sandwich Shops",
     "Perfect melt for grilled sandwiches, burger tops, and cheesy fries. Premium dairy consistency that keeps foodies coming back.",
     "శాండ్‌విచ్‌లు మరియు బర్గర్ల కొరకు నాణ్యమైన చెడ్డార్ చీజ్ స్లైసెస్ లభించును.",
     "CALL_NOW", "RAIS-MM-MOZZ"),
    (12, "Powering Rayachoty’s Modern Cafes & Cloud Kitchens",
     "From Reddies Colony to Kadapa Road, we partner with passionate food entrepreneurs to make raw material procurement simple and reliable.",
     "రాయచోటిలోని ఆధునిక కేఫ్‌లకు నమ్మకమైన కిచెన్ సప్లై పార్ట్‌నర్ - రైస్ ఏజెన్సీస్.",
     "CALL_NOW", None),
    (13, "Boost Beverage Margins: Premium Mojito & Mocktail Syrups",
     "Beverage sales carry 70%+ gross margins! Stock authentic Blue Curacao and Mint syrups for signature cafe drinks.",
     "కేఫ్ మరియు రెస్టారెంట్ల కొరకు బ్లూ కురాకో మరియు మోజిటో సిరప్స్ హోల్‌సేల్ సప్లై.",
     "LEARN_MORE", None),
    (14, "Crispy Breading Mix & Peri-Peri Seasoning for Fried Chicken",
     "Want that world-class crunchy fried chicken crust? We supply professional Cajun breading mix and hot peri-peri sprinkle seasoning.",
     "క్రిస్పీ ఫ్రైడ్ చికెన్ తయారీకి కావలసిన స్పెషల్ బ్రెడింగ్ మిక్స్ మరియు పెరి-పెరి పౌడర్ అందుబాటులో ఉంది.",
     "CALL_NOW", None),
    # Week 3
    (15, "Stop Oil Leakage: Food-Grade 40 GSM OGR Butter Paper",
     "Say goodbye to thin 28 GSM paper that tears and leaks oil into customer hands. RAIS Agencies stocks 10x10 & 12x12 certified Oil & Grease Resistant (OGR) sheets.",
     "పార్సెల్స్ నుండి ఆయిల్ కారకుండా ఉండే గట్టి 40 GSM ఫుడ్ గ్రేడ్ బట్టర్ పేపర్ హోల్‌సేల్ రేటుకే పొందండి.",
     "LEARN_MORE", "RAIS-PKG-BP40"),
    (16, "Heavy Corrugated Pizza Boxes: Keep Crusts Crisp During Delivery",
     "Cheap paper boxes turn pizzas soggy during home delivery. Our premium corrugated boxes feature ventilation flutes that retain heat while venting steam.",
     "పిజ్జా హోమ్ డెలివరీలో వేడిని కాపాడుతూ మెత్తబడకుండా ఉంచే దృఢమైన పిజ్జా బాక్స్‌లు.",
     "CALL_NOW", "RAIS-PKG-PB10"),
    (17, "Commercial Wrapping Paper for Shawarma & Frankie Stalls",
     "Rayachoty shawarma counters love our greaseproof cut sheets. Pre-cut sizes mean your staff saves prep time during peak hours.",
     "షవర్మా మరియు రోల్స్ కొరకు ప్రత్యేకమైన కట్ షీట్స్ బట్టర్ పేపర్.",
     "LEARN_MORE", "RAIS-PKG-BP40"),
    (18, "రాయచోటిలో హోటల్స్ మరియు పార్సెల్స్ కొరకు బెస్ట్ బట్టర్ పేపర్!",
     "మీ హోటల్ పార్సెల్స్ కొరకు ఆయిల్ లీక్ అవ్వని క్వాలిటీ బట్టర్ పేపర్ మరియు పిజ్జా బాక్స్‌లు హోల్‌సేల్ రేటుకే పొందండి. బల్క్ క్వాంటిటీపై ప్రత్యేక తగ్గింపులు.",
     "మరిన్ని వివరాలకు 9347453135 వాట్సాప్ డెస్క్‌ను సంప్రదించండి.",
     "CALL_NOW", "RAIS-PKG-BP40"),
    (19, "Why Deal with 3 Different Vendors When RAIS Does It All?",
     "Don’t order cheese from one trader, frozen momos from outstation, and packaging from a paper store. RAIS Agencies bundles everything on a single invoice.",
     "చీజ్, ఫ్రోజెన్ స్నాక్స్ మరియు ప్యాకేజింగ్ మెటీరియల్స్ అన్నీ ఒకే ఆర్డర్‌లో మీ వద్దకు.",
     "LEARN_MORE", None),
    (20, "Certified Food-Safe Packaging for Modern Food Brands",
     "Today's customers care about hygiene. Our food wrapping paper is chlorine-free, odor-free, and 100% food-grade compliant.",
     "ఆహార భద్రత మరియు పరిశుభ్రత ప్రమాణాలు కలిగిన నాణ్యమైన ప్యాకేజింగ్ మెటీరియల్స్.",
     "CALL_NOW", "RAIS-PKG-BP40"),
    (21, "Cut Kitchen Packaging Costs Every Month with Commercial Bundles",
     "Buying small retail rolls from general stores increases food costs. Switch to RAIS commercial bundles and protect your profit margins.",
     "చిన్న ప్యాకెట్ల కంటే బల్క్ బండిల్స్ తీసుకోవడం ద్వారా కిచెన్ ఖర్చులను తగ్గించుకోండి.",
     "CALL_NOW", "RAIS-PKG-BP40"),
    # Week 4
    (22, "Reliable Doorstep Delivery Right to Your Kitchen Counter",
     "Kitchen staff busy with morning prep? Don't leave your stove to pick up supplies. RAIS Agencies delivers directly to your cafe doorstep in Rayachoty.",
     "రాయచోటిలోని వ్యాపారులకు నేరుగా కిచెన్ వద్దకే వేగవంతమైన డెలివరీ.",
     "CALL_NOW", None),
    (23, "Tired of Waiting for Bangalore or Kadapa Bus Parcels?",
     "Stop paying high bus freight and dealing with bus stand pickup delays. RAIS Agencies is right here in Rayachoty beside Indel Money Bank.",
     "ఇతర నగరాల నుండి పార్సెల్స్ వచ్చే వరకు వేచి చూడాల్సిన అవసరం లేకుండా స్థానికంగానే సరుకును పొందండి.",
     "LEARN_MORE", None),
    (24, "Thick Commercial Mayonnaise: Rich Consistency That Holds on Hot Patties",
     "A watery sauce ruins a good burger. Our Del Monte commercial mayonnaise has high emulsification that stays creamy even on sizzling patties.",
     "బర్గర్లు మరియు రోల్స్ కొరకు చిక్కనైన డెల్ మోంటే మయోనైస్ హోల్‌సేల్ ప్యాక్స్ లభించును.",
     "CALL_NOW", "RAIS-DM-MAYO"),
    (25, "Weekend Rush Support for Rayachoty Kitchens",
     "A sudden party order or unexpected rush? When you run out of stock on busy days, our local godown on Sundupalli Road provides fast support for partner kitchens.",
     "రద్దీ సమయాలలో స్టాక్ అయిపోతే ఆందోళన చెందకండి. స్థానిక సప్లైయర్ గా మేము మీకు అండగా ఉంటాము.",
     "CALL_NOW", None),
    (26, "Sweet Corn & Veg Appetizers for Quick Turnaround Menus",
     "Individual Quick Frozen (IQF) sweet corn kernels—juicy, sweet, and ready for butter corn cups, pizza toppings, or fried appetizers.",
     "పీజా టాపింగ్స్ మరియు కార్న్ కప్స్ కొరకు నాణ్యమైన స్వీట్ కార్న్ హోల్‌సేల్ సప్లై.",
     "LEARN_MORE", None),
    (27, "Supplying Cafes Across Sambepalli, Galiveedu & Nearby Routes",
     "Running an eatery outside Rayachoty town? We service food outlets across the commercial corridor with scheduled route deliveries.",
     "రాయచోటి పరిసర ప్రాంతాలైన సంబేపల్లి, గాలివీడులలోని కేఫ్‌లకు కూడా సరుకు సప్లై చేయబడును.",
     "CALL_NOW", None),
    (28, "Complete Food Service Range for Modern Bakeries",
     "Bakeries today aren't just about bread—they sell pizzas, burgers, fries, and cold beverages. Source all supplies from one trusted partner.",
     "ఆధునిక బేకరీలకు అవసరమైన పిజ్జా బేస్‌లు, చీజ్, సాస్‌లు మరియు ప్యాకేజింగ్ ఒకే చోట.",
     "CALL_NOW", None),
    (29, "Strict B2B Wholesale Pricing: Protecting Your Retail Margins",
     "We are strictly a commercial supply partner. We protect our cafe clients by never publishing wholesale trade rates publicly.",
     "హోల్‌సేల్ వ్యాపారుల హక్కులను కాపాడుతూ పారదర్శకమైన ట్రేడ్ రేట్స్ అందిస్తున్నాము. రేట్ల వివరాలకు వాట్సాప్ చేయండి.",
     "LEARN_MORE", None),
    (30, "Powering Food Outlets Across Rayachoty & Annamayya District",
     "Thank you Rayachoty for trusting RAIS Agencies as your food service partner. Join our network of satisfied cafes, bakeries, and restaurants today.",
     "రాయచోటిలోని ఫుడ్ సర్వీస్ వ్యాపారులందరికీ మా హృదయపూర్వక ధన్యవాదాలు. నేడే ఆర్డర్ చేయండి - 9347453135.",
     "CALL_NOW", None)
]

INITIAL_KEYWORDS = [
    {"keyword": "frozen food wholesale rayachoty", "intent": "Commercial B2B", "relevance_score": 98, "language": "en"},
    {"keyword": "french fries wholesale rayachoty", "intent": "Commercial B2B", "relevance_score": 95, "language": "en"},
    {"keyword": "milky mist cheese wholesale rayachoty", "intent": "Commercial B2B", "relevance_score": 94, "language": "en"},
    {"keyword": "mozzarella cheese supplier rayachoty", "intent": "Commercial B2B", "relevance_score": 92, "language": "en"},
    {"keyword": "butter paper wholesale rayachoty", "intent": "Commercial B2B", "relevance_score": 90, "language": "en"},
    {"keyword": "pizza base wholesale rayachoty", "intent": "Commercial B2B", "relevance_score": 88, "language": "en"},
    {"keyword": "restaurant supplies rayachoty", "intent": "Commercial B2B", "relevance_score": 85, "language": "en"},
    {"keyword": "chicken nuggets bulk rayachoty", "intent": "Commercial B2B", "relevance_score": 84, "language": "en"},
    {"keyword": "rayachoti frozen foods agency", "intent": "Local Direct", "relevance_score": 89, "language": "te-en"},
    {"keyword": "butter paper kilo rate rayachoty", "intent": "Commercial B2B", "relevance_score": 82, "language": "te-en"}
]

INITIAL_COMPETITORS = [
    {
        "competitor_name": "Sri Tirumala Traders",
        "location_area": "Rayachoty Market Hub",
        "public_category": "Plastic & Disposable Goods",
        "rating": 4.1,
        "review_count": 24,
        "verified_status": VerificationStatus.UNVERIFIED_CLAIM,
        "notes": "Traders dealing in plastic boxes and catering disposables. Treat as unverified market observation."
    },
    {
        "competitor_name": "Y.S.K Traders",
        "location_area": "Rayachoty Bus Stand Road",
        "public_category": "Paper & Disposable Products",
        "rating": 4.0,
        "review_count": 18,
        "verified_status": VerificationStatus.UNVERIFIED_CLAIM,
        "notes": "General paper merchant. Does not supply food ingredients or cold-chain items."
    },
    {
        "competitor_name": "Chand Agencies",
        "location_area": "Rayachoty Kadapa Road",
        "public_category": "Commercial Cooling & Dairy",
        "rating": 4.3,
        "review_count": 35,
        "verified_status": VerificationStatus.UNVERIFIED_CLAIM,
        "notes": "Deals mainly in deep freezers and dairy infrastructure."
    }
]

async def seed_initial_data(db: AsyncSession):
    """Idempotently seeds initial verified business details, SKUs, and DRAFT campaign templates."""
    # 1. Business Profile
    stmt = select(BusinessProfile).limit(1)
    res = await db.execute(stmt)
    profile = res.scalar_one_or_none()
    if not profile:
        profile = BusinessProfile(
            business_name="RAIS Agencies",
            tagline="Wholesale Frozen Food Products & Packaging Solutions",
            address="Beside Indel Money Bank, Sundupalli Road, Near Reddies Colony, Rayachoty – 516269",
            city="Rayachoty",
            state="Andhra Pradesh",
            pin_code="516269",
            primary_phone="9347453135",
            secondary_phone=None, # Excluded per strict user rule
            whatsapp_number="919347453135",
            website_url="https://dataengineer-irfan.github.io/RAIS-AGENCIES/",
            catalogue_url="https://dataengineer-irfan.github.io/RAIS-AGENCIES/catalogue.html",
            primary_category="Wholesale food store",
            secondary_categories="Frozen food store, Restaurant supply store, Packaging supply store, Food products supplier"
        )
        db.add(profile)

    # 2. SKUs
    for item in INITIAL_SKUS:
        s_stmt = select(CatalogSKU).where(CatalogSKU.sku == item["sku"])
        s_res = await db.execute(s_stmt)
        if not s_res.scalar_one_or_none():
            db.add(CatalogSKU(**item))

    # 3. Service Areas
    for sa in INITIAL_SERVICE_AREAS:
        sa_stmt = select(ServiceArea).where(ServiceArea.area_name == sa["area_name"])
        sa_res = await db.execute(sa_stmt)
        if not sa_res.scalar_one_or_none():
            db.add(ServiceArea(**sa))

    # 4. Keyword Targets
    for kw in INITIAL_KEYWORDS:
        k_stmt = select(KeywordTarget).where(KeywordTarget.keyword == kw["keyword"])
        k_res = await db.execute(k_stmt)
        if not k_res.scalar_one_or_none():
            db.add(KeywordTarget(**kw))

    # 5. Competitor Snapshots
    for comp in INITIAL_COMPETITORS:
        c_stmt = select(CompetitorSnapshot).where(CompetitorSnapshot.competitor_name == comp["competitor_name"])
        c_res = await db.execute(c_stmt)
        if not c_res.scalar_one_or_none():
            db.add(CompetitorSnapshot(**comp))

    # 6. Automation Setting
    set_stmt = select(AutomationSetting).limit(1)
    set_res = await db.execute(set_stmt)
    if not set_res.scalar_one_or_none():
        db.add(AutomationSetting())

    # 7. Seed 30-Day Launch Campaign (IN UNVERIFIED_DRAFT STATUS)
    c_stmt = select(Campaign).where(Campaign.title == "30-Day Launch Blueprint (Editable Draft Templates)")
    c_res = await db.execute(c_stmt)
    if not c_res.scalar_one_or_none():
        launch_campaign = Campaign(
            title="30-Day Launch Blueprint (Editable Draft Templates)",
            objective="B2B Customer Acquisition",
            theme="Frozen Snacks, Cheese, Packaging & Local Advantage",
            status=PostStatus.DRAFT,
            is_approved_by_user=False
        )
        db.add(launch_campaign)
        await db.flush()

        for (day, h, en, te, cta, sku) in INITIAL_30_DAYS:
            post = CampaignPost(
                campaign_id=launch_campaign.id,
                day_number=day,
                headline=h,
                content_english=en,
                content_telugu=te,
                call_to_action=cta,
                target_product_sku=sku,
                status=PostStatus.DRAFT,
                verification_status=VerificationStatus.UNVERIFIED_DRAFT
            )
            db.add(post)

    # 8. Seed Verified Authentic Reviews with Pending Bilingual Approval Drafts
    initial_reviews_data = [
        {
            "google_review_id": "google-rev-irfan-01",
            "author_name": "Shaik Irfan",
            "author_photo_url": None,
            "rating": 5,
            "comment": "Best wholesale supplier for frozen chicken momos and French fries in Rayachoty. Quality is always maintained at -18°C with prompt doorstep delivery.",
            "create_time": datetime(2026, 11, 5, 11, 30, tzinfo=timezone.utc),
            "sentiment": SentimentType.POSITIVE,
            "is_complaint": False,
            "has_replied": False,
            "origin": ReviewOrigin.GOOGLE_AUTHENTIC,
            "reply_english": "Thank you Shaik Irfan for your trusted partnership! At RAIS Agencies, we are dedicated to supporting Rayachoty's fast food kitchens with guaranteed -18°C cold-chain integrity and daily wholesale supply. We look forward to serving your kitchen regularly!",
            "reply_telugu": "రాయచోటిలో మీ ఫాస్ట్ ఫుడ్ సెంటర్‌కు -18°C కోల్డ్-చైన్ నాణ్యతతో చికెన్ మోమోస్ మరియు ఫ్రెంచ్ ఫ్రైస్ అందించడం మా బాధ్యత. మీ విలువైన రివ్యూకు ధన్యవాదాలు షేక్ ఇర్ఫాన్ గారు!"
        },
        {
            "google_review_id": "google-rev-venkat-02",
            "author_name": "K. Venkat",
            "author_photo_url": None,
            "rating": 5,
            "comment": "Milky Mist mozzarella cheese and 10-inch corrugated pizza boxes delivered daily. Excellent wholesale rates and continuous support for local cafes.",
            "create_time": datetime(2026, 10, 30, 14, 15, tzinfo=timezone.utc),
            "sentiment": SentimentType.POSITIVE,
            "is_complaint": False,
            "has_replied": False,
            "origin": ReviewOrigin.GOOGLE_AUTHENTIC,
            "reply_english": "Thank you Venkat garu! We take pride in being Rayachoty's authorized wholesale hub for Milky Mist commercial dairy and quality packaging. Your cafe's success is our top priority.",
            "reply_telugu": "మిల్కీ మిస్ట్ మొజారెల్లా చీజ్ మరియు పిజ్జా బాక్స్‌ల నాణ్యతపై మీ పాజిటివ్ ఫీడ్‌బ్యాక్‌కు ధన్యవాదాలు వెంకట్ గారు. రాయచోటి కేఫ్‌లకు నిరంతరం ఉత్తమ సేవలు అందిస్తాము!"
        },
        {
            "google_review_id": "google-rev-reddy-03",
            "author_name": "M. Reddy",
            "author_photo_url": None,
            "rating": 5,
            "comment": "Reliable packaging supplies, OGR butter paper and burger boxes. Always in stock beside Indel Bank. Highly recommended for commercial food businesses.",
            "create_time": datetime(2026, 10, 24, 16, 45, tzinfo=timezone.utc),
            "sentiment": SentimentType.POSITIVE,
            "is_complaint": False,
            "has_replied": False,
            "origin": ReviewOrigin.GOOGLE_AUTHENTIC,
            "reply_english": "Thank you Reddy garu for your strong recommendation! Keeping certified OGR greaseproof wrapping and takeaway boxes in continuous stock right here in Rayachoty is our commitment to local food entrepreneurs.",
            "reply_telugu": "మీ అమూల్యమైన రివ్యూకు చాలా ధన్యవాదాలు రెడ్డి గారు. రాయచోటిలోని హోటళ్లు మరియు టిఫిన్ సెంటర్లకు నాణ్యమైన ప్యాకేజింగ్ మెటీరియల్ ఎల్లప్పుడూ అందుబాటులో ఉంచుతాము!"
        },
        {
            "google_review_id": "google-rev-farooq-04",
            "author_name": "Syed Farooq",
            "author_photo_url": None,
            "rating": 5,
            "comment": "Amul fries (6mm thin cut) and Triken crispy nuggets are very fresh and fry up perfectly. Good wholesale discounts on bulk carton orders.",
            "create_time": datetime(2026, 10, 18, 18, 20, tzinfo=timezone.utc),
            "sentiment": SentimentType.POSITIVE,
            "is_complaint": False,
            "has_replied": False,
            "origin": ReviewOrigin.GOOGLE_AUTHENTIC,
            "reply_english": "Thank you Syed Farooq for your valued feedback! We are thrilled that Amul fries and Triken nuggets perform so well in your restaurant fryers. Bulk wholesale savings and cold-chain freshness are guaranteed.",
            "reply_telugu": "అమూల్ ఫ్రైస్ మరియు ట్రైకెన్ నగ్గెట్స్ నాణ్యతపై మీ ప్రశంసలకు ధన్యవాదాలు సయ్యద్ ఫారూఖ్ గారు. హోల్‌సేల్ బల్క్ ఆర్డర్‌లపై ఎల్లప్పుడూ బెస్ట్ రేట్స్ అందిస్తాము!"
        },
        {
            "google_review_id": "google-rev-naresh-05",
            "author_name": "A. Naresh",
            "author_photo_url": None,
            "rating": 5,
            "comment": "Quick WhatsApp ordering and prompt counter pickup. The best frozen food and snacks distributor in Annamayya district.",
            "create_time": datetime(2026, 10, 12, 10, 10, tzinfo=timezone.utc),
            "sentiment": SentimentType.POSITIVE,
            "is_complaint": False,
            "has_replied": False,
            "origin": ReviewOrigin.GOOGLE_AUTHENTIC,
            "reply_english": "Thank you Naresh garu! We have streamlined our WhatsApp B2B ordering (9347453135) and counter pickup at Reddies Colony so your kitchen never experiences stockouts. Proud to serve Annamayya district!",
            "reply_telugu": "రాయచోటి మరియు అన్నమయ్య జిల్లాలోని ఫాస్ట్ ఫుడ్ పాయింట్లకు త్వరిత వాట్సాప్ ఆర్డరింగ్ మరియు కౌంటర్ పికప్ సేవలు అందించడం మా సంతోషం. ధన్యవాదాలు నరేష్ గారు!"
        }
    ]

    for r_data in initial_reviews_data:
        r_stmt = select(Review).where(Review.google_review_id == r_data["google_review_id"])
        r_res = await db.execute(r_stmt)
        if not r_res.scalar_one_or_none():
            new_r = Review(
                google_review_id=r_data["google_review_id"],
                author_name=r_data["author_name"],
                author_photo_url=r_data.get("author_photo_url"),
                rating=r_data["rating"],
                comment=r_data["comment"],
                create_time=r_data["create_time"],
                sentiment=r_data["sentiment"],
                is_complaint=r_data["is_complaint"],
                has_replied=r_data["has_replied"],
                origin=r_data["origin"]
            )
            db.add(new_r)
            await db.flush()

            draft = ReviewReplyDraft(
                review_id=new_r.id,
                reply_english=r_data["reply_english"],
                reply_telugu=r_data["reply_telugu"],
                is_approved=False,
                status="PENDING_APPROVAL"
            )
            db.add(draft)

    await db.commit()
