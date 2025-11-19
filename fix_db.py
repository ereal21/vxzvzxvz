import sqlite3

# Replace with your real database filename if different
db_path = 'database.db'

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Add the missing column
try:
    cursor.execute('ALTER TABLE unfinished_operations ADD COLUMN message_id INTEGER;')
    print("✅ Column 'message_id' added successfully.")
except sqlite3.OperationalError as e:
    print(f"⚠️ Error: {e}")

# Add lottery tickets column
try:
    cursor.execute("ALTER TABLE users ADD COLUMN lottery_tickets INTEGER DEFAULT 0;")
    print("✅ Column 'lottery_tickets' added successfully.")
except sqlite3.OperationalError as e:
    print(f"⚠️ Error: {e}")

# Add streak tracking columns
try:
    cursor.execute("ALTER TABLE users ADD COLUMN purchase_streak INTEGER DEFAULT 0;")
    print("✅ Column 'purchase_streak' added successfully.")
except sqlite3.OperationalError as e:
    print(f"⚠️ Error: {e}")

try:
    cursor.execute("ALTER TABLE users ADD COLUMN last_purchase_date TEXT;")
    print("✅ Column 'last_purchase_date' added successfully.")
except sqlite3.OperationalError as e:
    print(f"⚠️ Error: {e}")

try:
    cursor.execute("ALTER TABLE users ADD COLUMN streak_discount INTEGER DEFAULT 0;")
    print("✅ Column 'streak_discount' added successfully.")
except sqlite3.OperationalError as e:
    print(f"⚠️ Error: {e}")

# Add promo code applicable items column
try:
    cursor.execute("ALTER TABLE promo_codes ADD COLUMN applicable_items TEXT;")
    print("✅ Column 'applicable_items' added successfully.")
except sqlite3.OperationalError as e:
    print(f"⚠️ Error: {e}")

# Ensure category titles column
try:
    cursor.execute("ALTER TABLE categories ADD COLUMN title TEXT DEFAULT '';")
    print("✅ Column 'title' added to categories.")
    cursor.execute("UPDATE categories SET title = name WHERE IFNULL(title, '') = '';")
    print("✅ Existing category titles populated.")
except sqlite3.OperationalError as e:
    print(f"⚠️ Error: {e}")

# Ensure achievements tables
try:
    cursor.execute("CREATE TABLE IF NOT EXISTS achievements (code TEXT PRIMARY KEY);")
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS user_achievements (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, achievement_code TEXT, achieved_at TEXT);"
    )
    cursor.execute(
        "INSERT OR IGNORE INTO achievements (code) VALUES "
        "('start'), ('first_purchase'), ('first_topup'), "
        "('first_blackjack'), ('first_coinflip'), ('gift_sent'), "
        "('first_referral'), ('five_purchases'), ('streak_three'), "
        "('ten_referrals');"
    )
    print("✅ Achievements tables ensured.")
except sqlite3.OperationalError as e:
    print(f"⚠️ Error: {e}")

# Ensure stock notifications table
try:
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS stock_notifications (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, item_name TEXT);"
    )
    print("✅ Stock notifications table ensured.")
except sqlite3.OperationalError as e:
    print(f"⚠️ Error: {e}")

# Add lottery tickets column
try:
    cursor.execute("ALTER TABLE users ADD COLUMN lottery_tickets INTEGER DEFAULT 0;")
    print("✅ Column 'lottery_tickets' added successfully.")
except sqlite3.OperationalError as e:
    print(f"⚠️ Error: {e}")

# Add streak tracking columns
try:
    cursor.execute("ALTER TABLE users ADD COLUMN purchase_streak INTEGER DEFAULT 0;")
    print("✅ Column 'purchase_streak' added successfully.")
except sqlite3.OperationalError as e:
    print(f"⚠️ Error: {e}")

try:
    cursor.execute("ALTER TABLE users ADD COLUMN last_purchase_date TEXT;")
    print("✅ Column 'last_purchase_date' added successfully.")
except sqlite3.OperationalError as e:
    print(f"⚠️ Error: {e}")

try:
    cursor.execute("ALTER TABLE users ADD COLUMN streak_discount INTEGER DEFAULT 0;")
    print("✅ Column 'streak_discount' added successfully.")
except sqlite3.OperationalError as e:
    print(f"⚠️ Error: {e}")

# Ensure achievements tables
try:
    cursor.execute("CREATE TABLE IF NOT EXISTS achievements (code TEXT PRIMARY KEY);")
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS user_achievements (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, achievement_code TEXT, achieved_at TEXT);"
    )
    cursor.execute(
        "INSERT OR IGNORE INTO achievements (code) VALUES "
        "('start'), ('first_purchase'), ('first_topup'), "
        "('first_blackjack'), ('first_coinflip'), ('gift_sent'), "
        "('first_referral'), ('five_purchases'), ('streak_three'), "
        "('ten_referrals');"

        "INSERT OR IGNORE INTO achievements (code) VALUES ('start'), ('first_purchase');"
    )
    print("✅ Achievements tables ensured.")
except sqlite3.OperationalError as e:
    print(f"⚠️ Error: {e}")

# Ensure stock notifications table
try:
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS stock_notifications (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, item_name TEXT);"
    )
    print("✅ Stock notifications table ensured.")
except sqlite3.OperationalError as e:
    print(f"⚠️ Error: {e}")

conn.commit()
conn.close()
