with open('rais-growth-engine/backend/app/seed_data/seed.py', 'r', encoding='utf-8') as f:
    text = f.read()

old_block = '''INITIAL_SERVICE_AREAS = [
    {"area_name": "Rayachoty (516269)", "is_primary": True, "delivery_frequency": "Daily Fulfillment", "notes": "Local town doorstep delivery"},
    {"area_name": "Sambepalli", "is_primary": False, "delivery_frequency": "Twice Weekly Route", "notes": "Commercial route van delivery"},
    {"area_name": "Galiveedu", "is_primary": False, "delivery_frequency": "Twice Weekly Route", "notes": "Commercial route van delivery"},
    {"area_name": "T. Sundupalli", "is_primary": False, "delivery_frequency": "Scheduled Deliveries", "notes": "Along Sundupalli highway corridor"},
    {"area_name": "Rajampet Route", "is_primary": False, "delivery_frequency": "Weekly Scheduled", "notes": "Bulk orders only"},
    {"area_name": "Madanapalle Route", "is_primary": False, "delivery_frequency": "Weekly Scheduled", "notes": "Subject to route confirmation"}
]'''

new_block = '''INITIAL_SERVICE_AREAS = [
    {"area_name": "Rayachoty (516269)", "is_primary": True, "delivery_frequency": "Daily Fulfillment", "notes": "Local town doorstep delivery and depot pickup"},
    {"area_name": "Sundupalli", "is_primary": True, "delivery_frequency": "Daily Route", "notes": "Along Sundupalli highway commercial corridor"},
    {"area_name": "Galiveedu", "is_primary": True, "delivery_frequency": "Daily / Alternate Day", "notes": "Fast food centers and restaurant supply"},
    {"area_name": "Kadiri", "is_primary": False, "delivery_frequency": "Scheduled Route", "notes": "Commercial food kitchens and cafes"},
    {"area_name": "Chinnamandem", "is_primary": True, "delivery_frequency": "Daily Route", "notes": "Direct kitchen drops"},
    {"area_name": "Kalakada", "is_primary": False, "delivery_frequency": "Scheduled Deliveries", "notes": "Bakeries and fast food centers"},
    {"area_name": "Mahal", "is_primary": False, "delivery_frequency": "Scheduled Deliveries", "notes": "Mahal Cross and regional eateries"},
    {"area_name": "Madanapalle Route", "is_primary": False, "delivery_frequency": "Scheduled Route", "notes": "Bulk frozen cartons and pizza packaging"},
    {"area_name": "Kadapa Corridor", "is_primary": False, "delivery_frequency": "Scheduled Route", "notes": "Direct supply for QSRs and dining"},
    {"area_name": "Rajampet Sector", "is_primary": False, "delivery_frequency": "Scheduled Route", "notes": "Food packaging and catering supply"}
]'''

text = text.replace('\r\n', '\n')
old_block = old_block.replace('\r\n', '\n')
new_block = new_block.replace('\r\n', '\n')

assert old_block in text, "old_block not found in seed.py"
text = text.replace(old_block, new_block, 1)

with open('rais-growth-engine/backend/app/seed_data/seed.py', 'w', encoding='utf-8') as f:
    f.write(text)

print("Updated INITIAL_SERVICE_AREAS successfully in seed.py!")
