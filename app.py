from flask import (Flask, request, jsonify, redirect, url_for,
                    session, flash, get_flashed_messages)
from web3 import Web3
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import time, random, string, sqlite3, os, threading

app = Flask(__name__)

CONTRACT_ADDRESS = '0x42DFD77a8f94087feD2344507B915D703779A08d'
PRIVATE_KEY      = '24c5360cd677c935a71ea5b502dcce165d14b0704500da29b3b3441ef56bc28d'
SEPAY_TOKEN      = os.environ.get('SEPAY_TOKEN', '')
app.secret_key   = os.environ.get('SECRET_KEY', 'fundy-dev-secret-doi-khi-deploy-thuc')

w3 = Web3(Web3.HTTPProvider('https://rpc-amoy.polygon.technology'))
account_address = w3.eth.account.from_key(PRIVATE_KEY).address

contract_abi = [
    {"inputs":[{"internalType":"string","name":"_fundId","type":"string"},{"internalType":"string","name":"_fundName","type":"string"},{"internalType":"bool","name":"_isPrivate","type":"bool"}],"name":"createFund","outputs":[],"stateMutability":"nonpayable","type":"function"},
    {"inputs":[{"internalType":"string","name":"_fundId","type":"string"}],"name":"getFundLedger","outputs":[{"components":[{"internalType":"string","name":"bankTxId","type":"string"},{"internalType":"uint256","name":"amount","type":"uint256"},{"internalType":"string","name":"description","type":"string"},{"internalType":"bool","name":"isIncome","type":"bool"},{"internalType":"uint256","name":"timestamp","type":"uint256"}],"internalType":"struct MultiFundLedger.Transaction[]","name":"","type":"tuple[]"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"internalType":"string","name":"_fundId","type":"string"},{"internalType":"string","name":"_bankTxId","type":"string"},{"internalType":"uint256","name":"_amount","type":"uint256"},{"internalType":"string","name":"_description","type":"string"},{"internalType":"bool","name":"_isIncome","type":"bool"}],"name":"recordTransaction","outputs":[],"stateMutability":"nonpayable","type":"function"}
]
contract = w3.eth.contract(address=w3.to_checksum_address(CONTRACT_ADDRESS), abi=contract_abi)

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fundy.db')

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        created_at INTEGER NOT NULL
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS funds (
        fund_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        bank TEXT NOT NULL,
        stk TEXT NOT NULL,
        created_at INTEGER NOT NULL,
        owner_id INTEGER,
        is_public INTEGER DEFAULT 0
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS fund_members (
        fund_id TEXT NOT NULL,
        user_id INTEGER NOT NULL,
        PRIMARY KEY (fund_id, user_id)
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS expenses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fund_id TEXT NOT NULL,
        amount INTEGER NOT NULL,
        desc TEXT NOT NULL,
        to_fund TEXT,
        created_at INTEGER NOT NULL,
        created_by INTEGER
    )''')
    for col, coltype in [('owner_id', 'INTEGER'), ('is_public', 'INTEGER DEFAULT 0')]:
        try:
            conn.execute(f'ALTER TABLE funds ADD COLUMN {col} {coltype}')
        except sqlite3.OperationalError:
            pass
    conn.commit()
    conn.close()

def create_user(username, password):
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.execute('INSERT INTO users (username, password_hash, created_at) VALUES (?,?,?)',
            (username, generate_password_hash(password), int(time.time())))
        conn.commit()
        return cur.lastrowid
    except sqlite3.IntegrityError:
        return None
    finally:
        conn.close()

def get_user_by_username(username):
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute('SELECT id, username, password_hash FROM users WHERE username=?', (username,)).fetchone()
    conn.close()
    return {"id": row[0], "username": row[1], "password_hash": row[2]} if row else None

def get_user_by_id(user_id):
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute('SELECT id, username FROM users WHERE id=?', (user_id,)).fetchone()
    conn.close()
    return {"id": row[0], "username": row[1]} if row else None

def verify_user(username, password):
    user = get_user_by_username(username)
    if user and check_password_hash(user['password_hash'], password):
        return user
    return None

def save_fund(fund_id, name, bank, stk, owner_id, is_public):
    conn = sqlite3.connect(DB_PATH)
    conn.execute('INSERT INTO funds (fund_id, name, bank, stk, created_at, owner_id, is_public) VALUES (?,?,?,?,?,?,?)',
        (fund_id, name, bank, stk, int(time.time()), owner_id, 1 if is_public else 0))
    conn.commit()
    conn.close()

def _row_to_fund(row):
    if not row: return None
    return {"fund_id": row[0], "name": row[1], "bank": row[2], "stk": row[3],
            "created_at": row[4], "owner_id": row[5], "is_public": bool(row[6])}

FUND_COLS = "fund_id, name, bank, stk, created_at, owner_id, is_public"

def get_fund(fund_id):
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(f'SELECT {FUND_COLS} FROM funds WHERE fund_id=?', (fund_id,)).fetchone()
    conn.close()
    return _row_to_fund(row)

def get_fund_by_stk(stk):
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(f'SELECT {FUND_COLS} FROM funds WHERE stk=?', (stk,)).fetchone()
    conn.close()
    return _row_to_fund(row)

def get_latest_fund():
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(f'SELECT {FUND_COLS} FROM funds ORDER BY created_at DESC LIMIT 1').fetchone()
    conn.close()
    return _row_to_fund(row)

def get_public_funds():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(f'SELECT {FUND_COLS} FROM funds WHERE is_public=1 ORDER BY created_at DESC').fetchall()
    conn.close()
    return [_row_to_fund(r) for r in rows]

def get_funds_by_owner(user_id):
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(f'SELECT {FUND_COLS} FROM funds WHERE owner_id=? ORDER BY created_at DESC', (user_id,)).fetchall()
    conn.close()
    return [_row_to_fund(r) for r in rows]

def get_funds_shared_with(user_id):
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(f'SELECT {FUND_COLS} FROM funds WHERE fund_id IN (SELECT fund_id FROM fund_members WHERE user_id=?) ORDER BY created_at DESC', (user_id,)).fetchall()
    conn.close()
    return [_row_to_fund(r) for r in rows]

def add_expense(fund_id, amount, desc, to_fund, user_id):
    conn = sqlite3.connect(DB_PATH)
    conn.execute('INSERT INTO expenses (fund_id, amount, desc, to_fund, created_at, created_by) VALUES (?,?,?,?,?,?)',
        (fund_id, amount, desc, to_fund, int(time.time()), user_id))
    conn.commit()
    conn.close()

def get_expenses(fund_id):
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute('SELECT id, amount, desc, to_fund, created_at FROM expenses WHERE fund_id=? ORDER BY created_at DESC', (fund_id,)).fetchall()
    conn.close()
    return [{"id":r[0], "amount":r[1], "desc":r[2], "to_fund":r[3],
             "time": time.strftime('%d/%m %H:%M', time.localtime(r[4]))} for r in rows]

def add_fund_member(fund_id, user_id):
    conn = sqlite3.connect(DB_PATH)
    conn.execute('INSERT OR IGNORE INTO fund_members (fund_id, user_id) VALUES (?,?)', (fund_id, user_id))
    conn.commit()
    conn.close()

def get_fund_members(fund_id):
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute('SELECT users.id, users.username FROM fund_members JOIN users ON users.id = fund_members.user_id WHERE fund_members.fund_id=?', (fund_id,)).fetchall()
    conn.close()
    return [{"id": r[0], "username": r[1]} for r in rows]

init_db()

# =========================================================================
# I18N — tiếng Việt / English
# =========================================================================
TRANSLATIONS = {
    "vi": {
        "nav_home":       "Trang chủ",
        "nav_community":  "Quỹ cộng đồng",
        "nav_mine":       "Quỹ của tôi",
        "nav_login":      "Đăng nhập",
        "nav_register":   "Đăng ký",
        "nav_logout":     "Đăng xuất",
        "nav_about":      "Giới thiệu",
        "nav_guide":      "Hướng dẫn",
        "intro_about":    "Về Fundy",
        "intro_faq":      "Hỏi đáp",
        "intro_terms":    "Điều khoản",
        "intro_privacy":  "Chính sách bảo mật",
        "hero_tag":       "Powered by Polygon Blockchain",
        "hero_h1a":       "Thu Quỹ",
        "hero_h1b":       "Minh Bạch",
        "hero_h1c":       "không thể gian lận",
        "hero_sub":       "Mọi giao dịch chuyển khoản được đóng dấu bất tử lên blockchain — không ai có thể sửa hay xóa, kể cả bạn.",
        "about_title":    "Fundy là gì?",
        "about_body":     "Nền tảng thu quỹ cho lớp học, hội nhóm, chung cư và hoạt động từ thiện. Mọi giao dịch tự động ghi bất biến lên blockchain — ai cũng tra cứu sao kê thời gian thực.",
        "form_title":     "Tạo quỹ mới",
        "f_name":         "Tên quỹ",
        "f_name_ph":      "Ví dụ: Quỹ Lớp 12A1 — Hội Trường 2025",
        "f_bank":         "Ngân hàng",
        "f_bank_ph":      "— Chọn —",
        "f_stk":          "Số tài khoản",
        "f_stk_ph":       "STK nhận tiền",
        "f_type":         "Loại quỹ",
        "f_public":       "Quỹ công khai",
        "f_public_desc":  'Hiển thị trong "Quỹ cộng đồng" — ai cũng xem được.<br>Bỏ trống = quỹ riêng tư, chỉ vào qua link hoặc được mời.',
        "f_acct_label":   "Tạo tài khoản nhanh (không bắt buộc)",
        "f_username_ph":  "Tên đăng nhập",
        "f_password_ph":  "Mật khẩu",
        "f_hint_guest":   "Để trống → tạo quỹ ẩn danh (Guest). Đã có tài khoản?",
        "f_login_link":   "Đăng nhập",
        "f_hint_before":  "trước.",
        "f_submit":       "Khởi tạo quỹ →",
        "feat1_title":    "Tức thì",
        "feat1_desc":     "QR tự sinh, chuyển khoản ngay qua app ngân hàng",
        "feat2_title":    "Bất biến",
        "feat2_desc":     "Sổ cái Polygon blockchain — không ai sửa được",
        "feat3_title":    "Minh bạch",
        "feat3_desc":     "Link tra cứu public — chia sẻ cho cả nhóm",
        "community_tag":  "Cộng đồng",
        "community_h1":   "Quỹ cộng đồng",
        "community_sub":  "Tất cả quỹ công khai — ai cũng có thể theo dõi sao kê thời gian thực.",
        "community_active":"Đang hoạt động",
        "community_empty":"Chưa có quỹ công khai nào.",
        "mine_h1":        "Quỹ của tôi",
        "mine_sub":       "Quản lý quỹ bạn đã tạo và được chia sẻ.",
        "mine_yours":     "Quỹ của bạn",
        "mine_shared":    "Được chia sẻ với bạn",
        "mine_empty":     "Bạn chưa tạo quỹ nào.",
        "btn_view":       "Xem →",
        "badge_public":   "🌐 Công khai",
        "badge_private":  "🔒 Riêng tư",
        "badge_live":     "Blockchain live",
        "badge_err":      "⚠ Blockchain lỗi",
        "stat_total":     "Tổng thu được",
        "stat_count":     "Lượt đóng",
        "link_public":    "Link công khai",
        "link_private":   "Link chia sẻ (riêng tư)",
        "qr_title":       "📲 Quét để đóng quỹ",
        "qr_sub":         "Dùng app ngân hàng bất kỳ quét mã — tiền vào tài khoản chủ quỹ tự động.",
        "ledger_title":   "Nhật ký giao dịch",
        "ledger_all":     "Xem toàn bộ trên Polygonscan ↗",
        "ledger_empty":   "Chưa có giao dịch nào. Hãy chia sẻ mã QR để bắt đầu!",
        "th_time":        "Thời gian",
        "th_txid":        "Mã GD ngân hàng",
        "th_amount":      "Số tiền",
        "th_desc":        "Nội dung",
        "th_verify":      "Kiểm chứng",
        "notice_pending": "Giao dịch mới hiện sau ~15–30 giây khi blockchain xác nhận.",
        "invite_title":   "🔒 Mời thành viên xem quỹ này",
        "invite_ph":      "Tên đăng nhập",
        "invite_btn":     "Mời",
        "copy_btn":       "Sao chép",
        "copy_done":      "✓ Đã sao chép",
        "footer_note":    "Sổ cái bất tử · Polygon Amoy · Python + Web3.py",
        "reg_tag":        "Tài khoản Fundy",
        "reg_h1":         "Tạo tài khoản",
        "reg_sub":        "Chỉ cần tên đăng nhập và mật khẩu — không cần email.",
        "reg_username":   "Tên đăng nhập",
        "reg_password":   "Mật khẩu",
        "reg_confirm":    "Nhập lại mật khẩu",
        "reg_submit":     "Tạo tài khoản →",
        "reg_have_acct":  "Đã có tài khoản?",
        "login_h1":       "Đăng nhập",
        "login_sub":      "Truy cập quỹ của bạn và quỹ được chia sẻ.",
        "login_submit":   "Đăng nhập →",
        "login_no_acct":  "Chưa có tài khoản?",
        "modal_title":    "🔍 Kiểm chứng giao dịch này trên Blockchain",
        "modal_intro_b":  "Blockchain là gì?",
        "modal_intro":    "Hãy hình dung đây như một cuốn sổ cái công khai dán ở quảng trường — ai cũng đọc được, không ai xoá được, kể cả Fundy. Mọi giao dịch đều được ghi lại vĩnh viễn ở đó. Bạn có thể tự kiểm tra mà không cần tin tưởng riêng website này.",
        "step1_title":    "Mở Polygonscan",
        "step1_desc":     "Polygonscan là trang tra cứu blockchain Polygon độc lập — không thuộc sở hữu của Fundy, không do ai kiểm soát.",
        "step1_link":     "Mở Polygonscan ↗",
        "step2_title":    "Kiểm tra đây đúng là giao dịch của quỹ",
        "step2_desc":     'Trên trang Polygonscan vừa mở, cuộn xuống phần <strong style="color:var(--text)">"Logs"</strong>, bạn sẽ thấy các thông tin sau — so sánh với những gì Fundy hiển thị:',
        "step2_contract": "Contract Address (địa chỉ smart contract Fundy)",
        "step2_fundid":   "Fund ID (mã quỹ)",
        "step2_amount":   "Số tiền (amount) — đơn vị VNĐ",
        "step2_desc2":    "Nội dung chuyển khoản",
        "step3_title":    "Xác nhận không ai có thể chỉnh sửa được",
        "step3_desc":     'Nếu tất cả thông tin khớp → giao dịch này <strong style="color:var(--green)">hoàn toàn xác thực</strong>. Blockchain Polygon là mạng phi tập trung với hàng nghìn máy chủ trên toàn thế giới — để sửa một dòng dữ liệu, kẻ gian cần kiểm soát hơn 51% toàn bộ mạng đó cùng một lúc. Điều này là <strong style="color:var(--green)">bất khả thi</strong> trong thực tế.',
        "modal_open":     "Mở Polygonscan để kiểm chứng ↗",
        "modal_close":    "Đóng",
        "verify_btn":     "Kiểm chứng",
        "logged_in_as":   "Quỹ sẽ lưu vào tài khoản",
        "records":        "bản ghi",
        "funds":          "quỹ",
    },
    "en": {
        "nav_home":       "Home",
        "nav_community":  "Community Funds",
        "nav_mine":       "My Funds",
        "nav_login":      "Log in",
        "nav_register":   "Sign up",
        "nav_logout":     "Log out",
        "nav_about":      "About",
        "nav_guide":      "Guide",
        "intro_about":    "About Fundy",
        "intro_faq":      "FAQ",
        "intro_terms":    "Terms",
        "intro_privacy":  "Privacy Policy",
        "hero_tag":       "Powered by Polygon Blockchain",
        "hero_h1a":       "Community funds,",
        "hero_h1b":       "provably honest",
        "hero_h1c":       "— tamper-proof",
        "hero_sub":       "Every bank transfer is automatically recorded on the blockchain — immutable, public, verifiable by anyone. Not just trusted: provable.",
        "about_title":    "What is Fundy?",
        "about_body":     "A fund management platform for class funds, friend groups, community organizations and charities. Every transfer is automatically recorded on Polygon blockchain — real-time, public, independently verifiable.",
        "form_title":     "Create a new fund",
        "f_name":         "Fund name",
        "f_name_ph":      "e.g. Class 12A1 — Year-End Party 2025",
        "f_bank":         "Bank",
        "f_bank_ph":      "— Select —",
        "f_stk":          "Account number",
        "f_stk_ph":       "Receiving account number",
        "f_type":         "Visibility",
        "f_public":       "Public fund",
        "f_public_desc":  'Appears in "Community Funds" — anyone can view. Leave off = private fund, accessible only via link or invitation.',
        "f_acct_label":   "Create an account (optional)",
        "f_username_ph":  "Username",
        "f_password_ph":  "Password",
        "f_hint_guest":   "Leave blank to create anonymously (Guest). Already have an account?",
        "f_login_link":   "Log in",
        "f_hint_before":  "first.",
        "f_submit":       "Create fund →",
        "feat1_title":    "Instant",
        "feat1_desc":     "Auto-generated QR — pay via any bank app",
        "feat2_title":    "Immutable",
        "feat2_desc":     "Polygon blockchain ledger — no one can edit it",
        "feat3_title":    "Transparent",
        "feat3_desc":     "Public link — share with the whole group",
        "community_tag":  "Community",
        "community_h1":   "Community Funds",
        "community_sub":  "All public funds — anyone can follow the real-time ledger.",
        "community_active":"Active",
        "community_empty":"No public funds yet.",
        "mine_h1":        "My Funds",
        "mine_sub":       "Manage funds you created and funds shared with you.",
        "mine_yours":     "Your funds",
        "mine_shared":    "Shared with you",
        "mine_empty":     "You haven\'t created any funds yet.",
        "btn_view":       "View →",
        "badge_public":   "🌐 Public",
        "badge_private":  "🔒 Private",
        "badge_live":     "Blockchain live",
        "badge_err":      "⚠ Blockchain error",
        "stat_total":     "Total collected",
        "stat_count":     "Contributions",
        "link_public":    "Public link",
        "link_private":   "Share link (private)",
        "qr_title":       "📲 Scan to contribute",
        "qr_sub":         "Scan with any bank app — money goes directly to the fund owner.",
        "ledger_title":   "Transaction log",
        "ledger_all":     "View all on Polygonscan ↗",
        "ledger_empty":   "No transactions yet. Share the QR code to get started!",
        "th_time":        "Time",
        "th_txid":        "Bank TX ID",
        "th_amount":      "Amount",
        "th_desc":        "Description",
        "th_verify":      "Verify",
        "notice_pending": "New transactions appear ~15–30 seconds after blockchain confirmation.",
        "invite_title":   "🔒 Invite members to view this private fund",
        "invite_ph":      "Username",
        "invite_btn":     "Invite",
        "copy_btn":       "Copy",
        "copy_done":      "✓ Copied",
        "footer_note":    "Immutable ledger · Polygon Amoy · Python + Web3.py",
        "reg_tag":        "Fundy account",
        "reg_h1":         "Create account",
        "reg_sub":        "Just a username and password — no email needed.",
        "reg_username":   "Username",
        "reg_password":   "Password",
        "reg_confirm":    "Confirm password",
        "reg_submit":     "Create account →",
        "reg_have_acct":  "Already have an account?",
        "login_h1":       "Log in",
        "login_sub":      "Access your funds and funds shared with you.",
        "login_submit":   "Log in →",
        "login_no_acct":  "Don\'t have an account?",
        "modal_title":    "🔍 Verify this transaction on Blockchain",
        "modal_intro_b":  "What is a blockchain?",
        "modal_intro":    "Think of it as a public ledger posted in the town square — anyone can read it, no one can erase it, not even Fundy. Every transaction is written there permanently. You can check it yourself without trusting this website.",
        "step1_title":    "Open Polygonscan",
        "step1_desc":     "Polygonscan is an independent Polygon blockchain explorer — not owned by Fundy, not controlled by anyone.",
        "step1_link":     "Open Polygonscan ↗",
        "step2_title":    "Confirm this is the right transaction",
        "step2_desc":     'On Polygonscan, scroll down to the <strong style="color:var(--text)">"Logs"</strong> tab. You should see the following — compare with what Fundy displays:',
        "step2_contract": "Contract Address (Fundy smart contract)",
        "step2_fundid":   "Fund ID",
        "step2_amount":   "Amount (in VND)",
        "step2_desc2":    "Transfer description",
        "step3_title":    "Confirm no one can alter it",
        "step3_desc":     'If all fields match → this transaction is <strong style="color:var(--green)">fully verified</strong>. Polygon is a decentralized network with thousands of nodes worldwide — altering a single record would require controlling more than 51% of the entire network simultaneously. This is <strong style="color:var(--green)">practically impossible</strong>.',
        "modal_open":     "Open Polygonscan to verify ↗",
        "modal_close":    "Close",
        "verify_btn":     "Verify",
        "logged_in_as":   "Fund will be saved to account",
        "records":        "records",
        "funds":          "funds",
    }
}

def T(key, lang=None):
    """Return translated string. Uses session lang if lang not provided."""
    if lang is None:
        try:
            lang = session.get("lang", "vi")
        except RuntimeError:
            lang = "vi"
    return TRANSLATIONS.get(lang, TRANSLATIONS["vi"]).get(key, key)



def get_lang():
    """Return current language from session or cookie. Default: vi."""
    return session.get("lang", request.cookies.get("lang", "vi"))

def current_user():
    uid = session.get('user_id')
    return get_user_by_id(uid) if uid else None

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Bạn cần đăng nhập để xem trang này.', 'error')
            return redirect(url_for('login_page'))
        return f(*args, **kwargs)
    return decorated

def send_create_fund(fund_id, fund_name, is_private):
    try:
        nonce = w3.eth.get_transaction_count(account_address)
        tx = contract.functions.createFund(fund_id, fund_name, is_private).build_transaction({
            'chainId': 80002, 'gas': 200000,
            'maxPriorityFeePerGas': w3.to_wei(30, 'gwei'),
            'maxFeePerGas': w3.to_wei(35, 'gwei'), 'nonce': nonce,
        })
        signed = w3.eth.account.sign_transaction(tx, private_key=PRIVATE_KEY)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        print(f"✅ createFund [{fund_id}] tx: {tx_hash.hex()}")
    except Exception as e:
        print(f"❌ createFund error: {e}")

def send_record_tx(fund_id, bank_tx_id, amount, content):
    try:
        nonce = w3.eth.get_transaction_count(account_address)
        tx = contract.functions.recordTransaction(fund_id, bank_tx_id, amount, content, True).build_transaction({
            'chainId': 80002, 'gas': 250000,
            'maxPriorityFeePerGas': w3.to_wei(30, 'gwei'),
            'maxFeePerGas': w3.to_wei(35, 'gwei'), 'nonce': nonce,
        })
        signed = w3.eth.account.sign_transaction(tx, private_key=PRIVATE_KEY)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        print(f"✅ recordTx [{fund_id}] {amount}đ tx: {tx_hash.hex()}")
    except Exception as e:
        print(f"❌ recordTx error: {e}")

# =========================================================================
# NỘI DUNG GIỚI THIỆU — Về Fundy / Hỏi đáp / Điều khoản / Chính sách bảo mật
# =========================================================================
INTRO_CONTENT = {
    "about-fundy": {
        "vi": {
            "h1": "Về Fundy",
            "sub": "Nền tảng gây quỹ cộng đồng minh bạch trên Polygon Amoy Network",
            "sections": [
                ("Fundy là gì?",
                 "Fundy là một nền tảng phi tập trung (Web3 Beta) được xây dựng nhằm mục đích tối ưu hóa "
                 "tính minh bạch và độ tin cậy trong các hoạt động gây quỹ cộng đồng và thiện nguyện. Bằng "
                 "cách ứng dụng công nghệ chuỗi khối (Blockchain), mọi giao dịch quyên góp đều được ghi nhận "
                 "trực tiếp, không thể giả mạo hay xóa bỏ."),
                ("Sứ mệnh của chúng tôi",
                 "Chúng tôi hướng đến một thế giới nơi lòng tin của người quyên góp được bảo vệ tuyệt đối. "
                 "Từng đồng vốn đóng góp sẽ được chuyển đến đúng địa chỉ và đúng mục đích thông qua cơ chế "
                 "giám sát thông minh, trực quan và hiện đại."),
                ("Fundy chống gian lận, lừa đảo như thế nào?",
                 "Mọi khoản thu — chi của một quỹ đều được ghi lại thành giao dịch bất biến trên sổ cái "
                 "Polygon, kèm mã giao dịch ngân hàng, số tiền và nội dung. Không một cá nhân nào — kể cả "
                 "chủ quỹ hay đội ngũ Fundy — có thể chỉnh sửa hoặc xóa dữ liệu đã ghi. Bất kỳ ai có đường "
                 "link cũng có thể tự tra cứu, đối chiếu trực tiếp trên Polygonscan mà không cần tin tưởng "
                 "một mình Fundy."),
            ],
        },
        "en": {
            "h1": "About Fundy",
            "sub": "A transparent community fundraising platform on the Polygon Amoy Network",
            "sections": [
                ("What is Fundy?",
                 "Fundy is a decentralized platform (Web3 Beta) built to maximize transparency and "
                 "trustworthiness in community and charity fundraising. By using blockchain technology, "
                 "every contribution is recorded directly on-chain — it cannot be faked or deleted."),
                ("Our mission",
                 "We're working toward a world where a donor's trust is protected absolutely. Every "
                 "contribution is routed to the right recipient for the right purpose, through an "
                 "oversight mechanism that is intelligent, transparent, and modern."),
                ("How does Fundy prevent fraud and scams?",
                 "Every inflow and outflow of a fund is written as an immutable transaction on the "
                 "Polygon ledger, together with the bank transaction ID, amount, and description. No one "
                 "— not even the fund owner or the Fundy team — can edit or delete recorded data. Anyone "
                 "with the link can independently verify it on Polygonscan, without needing to trust "
                 "Fundy alone."),
            ],
        },
    },
    "faq": {
        "vi": {
            "h1": "Hỏi đáp (FAQ)",
            "sub": "Các câu hỏi thường gặp và giải đáp thắc mắc về hệ thống",
            "faq": [
                ("Làm thế nào để biết tiền quyên góp của tôi an toàn?",
                 "Hệ thống của Fundy vận hành trực tiếp trên mạng thử nghiệm Polygon Amoy. Mọi lịch sử ví, "
                 "số tiền chuyển đi và nhận về đều có thể tra cứu công khai 100% trên Explorer công cộng."),
                ("Phiên bản Beta này có sử dụng tiền thật không?",
                 "Không, hiện tại Fundy đang chạy thử nghiệm (Beta) nên tất cả các quỹ và giao dịch đều sử "
                 "dụng token thử nghiệm (Testnet), hoàn toàn miễn phí và không có giá trị tài chính thực tế."),
                ("Nếu chủ quỹ chi tiêu sai mục đích thì sao?",
                 "Mọi khoản chi đều phải được chủ quỹ tự ghi nhận công khai kèm mô tả, và hiển thị vĩnh viễn "
                 "trong nhật ký giao dịch của quỹ. Thành viên và người quyên góp có thể đối chiếu số dư, số "
                 "tiền vào/ra bất cứ lúc nào để phát hiện bất thường — dữ liệu không thể bị ẩn hay xóa."),
                ("Fundy có thu phí không?",
                 "Không. Trong giai đoạn Beta, Fundy hoàn toàn miễn phí. Nếu trong tương lai có thay đổi về "
                 "phí dịch vụ, thông tin sẽ được công bố rõ ràng trước khi áp dụng."),
                ("Quỹ riêng tư có bị công khai ngoài ý muốn không?",
                 "Quỹ riêng tư không hiển thị trong \"Quỹ cộng đồng\" và chỉ những người có link hoặc được "
                 "chủ quỹ mời mới xem được. Dữ liệu giao dịch vẫn được ghi trên blockchain công cộng để đảm "
                 "bảo minh bạch, nhưng đường dẫn truy cập không được Fundy chia sẻ cho bên thứ ba."),
                ("Fundy có dự định dùng tiền thật (Mainnet) không?",
                 "Có. Mục tiêu dài hạn của Fundy là triển khai lên mạng chính thức (Mainnet) sau khi hoàn "
                 "tất kiểm thử bảo mật. Người dùng sẽ luôn được thông báo trước khi bất kỳ quỹ nào chuyển "
                 "sang vận hành bằng tiền thật."),
            ],
        },
        "en": {
            "h1": "FAQ",
            "sub": "Frequently asked questions about how the system works",
            "faq": [
                ("How do I know my donation is safe?",
                 "Fundy runs directly on the Polygon Amoy test network. Every wallet's history, and every "
                 "amount sent or received, can be looked up publicly and in full on the public Explorer."),
                ("Does this Beta version use real money?",
                 "No. Fundy is currently running in Beta, so all funds and transactions use test tokens "
                 "(Testnet) — completely free and with no real financial value."),
                ("What if a fund owner spends money for the wrong purpose?",
                 "Every expense must be logged publicly by the fund owner along with a description, and it "
                 "stays permanently visible in the fund's transaction log. Members and donors can check "
                 "balances and inflows/outflows at any time to spot anything unusual — the data cannot be "
                 "hidden or deleted."),
                ("Does Fundy charge any fees?",
                 "No. During the Beta period Fundy is completely free. If service fees are introduced in "
                 "the future, this will be announced clearly before it takes effect."),
                ("Can a private fund be exposed publicly by accident?",
                 "Private funds don't appear in \"Community Funds\" and can only be viewed by people with "
                 "the link or those invited by the owner. Transaction data is still recorded on the public "
                 "blockchain for transparency, but Fundy does not share the access link with third parties."),
                ("Does Fundy plan to use real money (Mainnet)?",
                 "Yes. Fundy's long-term goal is to launch on the main network (Mainnet) once security "
                 "testing is complete. Users will always be notified before any fund switches to operating "
                 "with real money."),
            ],
        },
    },
    "terms": {
        "vi": {
            "h1": "Điều khoản sử dụng",
            "sub": "Cập nhật lần cuối: 20/07/2026 — vui lòng đọc kỹ trước khi sử dụng Fundy",
            "sections": [
                ("1. Chấp nhận điều khoản",
                 "Khi truy cập hoặc sử dụng Fundy, bạn đồng ý tuân thủ các điều khoản này. Nếu không đồng "
                 "ý, vui lòng ngừng sử dụng nền tảng."),
                ("2. Tính chất dịch vụ (Beta / Testnet)",
                 "Fundy hiện đang trong giai đoạn thử nghiệm (Beta), vận hành trên mạng thử nghiệm Polygon "
                 "Amoy. Mọi bản ghi trên blockchain trong giai đoạn này chỉ mang tính minh chứng công nghệ, "
                 "không có giá trị tài chính thực tế. Dòng tiền thật (nếu có) vẫn di chuyển qua tài khoản "
                 "ngân hàng do người dùng tự cung cấp, nằm ngoài phạm vi kiểm soát của Fundy."),
                ("3. Trách nhiệm của người dùng",
                 "Người tạo quỹ chịu trách nhiệm về tính chính xác của thông tin quỹ (tên, ngân hàng, số "
                 "tài khoản) và về việc sử dụng đúng mục đích số tiền đã quyên góp. Fundy không giữ, quản lý "
                 "hay có quyền truy cập vào tiền trong tài khoản ngân hàng của người dùng."),
                ("4. Hành vi bị nghiêm cấm",
                 "Nghiêm cấm sử dụng Fundy để gian lận, lừa đảo, rửa tiền, kêu gọi quyên góp giả mạo, cung "
                 "cấp thông tin sai sự thật, hoặc thực hiện bất kỳ hành vi vi phạm pháp luật hiện hành nào. "
                 "Fundy có quyền khóa tài khoản hoặc gỡ quỹ vi phạm mà không cần báo trước."),
                ("5. Tính bất biến của dữ liệu blockchain",
                 "Mọi giao dịch đã ghi lên blockchain là vĩnh viễn và không thể chỉnh sửa hay xóa bỏ — kể cả "
                 "bởi đội ngũ Fundy. Người dùng cần kiểm tra kỹ thông tin trước khi xác nhận giao dịch, vì "
                 "không có cơ chế \"hoàn tác\" trên sổ cái công khai."),
                ("6. Giới hạn trách nhiệm",
                 "Fundy được cung cấp \"nguyên trạng\", trong giai đoạn Beta có thể gián đoạn, lỗi kỹ thuật "
                 "hoặc chậm trễ đồng bộ với blockchain. Fundy không chịu trách nhiệm đối với tranh chấp phát "
                 "sinh giữa người quyên góp và chủ quỹ liên quan đến việc sử dụng tiền ngoài nền tảng."),
                ("7. Phí dịch vụ",
                 "Trong giai đoạn Beta, Fundy không thu bất kỳ khoản phí nào. Mọi thay đổi về phí trong "
                 "tương lai sẽ được công bố công khai trước khi áp dụng."),
                ("8. Thay đổi điều khoản",
                 "Fundy có thể cập nhật điều khoản này theo thời gian. Phiên bản mới nhất luôn được đăng "
                 "tại trang này; việc tiếp tục sử dụng dịch vụ đồng nghĩa bạn chấp nhận các thay đổi đó."),
                ("9. Liên hệ",
                 "Mọi thắc mắc về điều khoản sử dụng, vui lòng liên hệ đội ngũ Fundy qua kênh hỗ trợ chính "
                 "thức của nền tảng."),
            ],
        },
        "en": {
            "h1": "Terms of Service",
            "sub": "Last updated: 20 Jul 2026 — please read carefully before using Fundy",
            "sections": [
                ("1. Acceptance of terms",
                 "By accessing or using Fundy, you agree to comply with these terms. If you do not agree, "
                 "please discontinue use of the platform."),
                ("2. Nature of the service (Beta / Testnet)",
                 "Fundy is currently in Beta, running on the Polygon Amoy test network. All blockchain "
                 "records during this stage are proof-of-concept only and hold no real financial value. "
                 "Any real money still moves through bank accounts supplied by users themselves, which is "
                 "outside Fundy's control."),
                ("3. User responsibilities",
                 "Fund creators are responsible for the accuracy of their fund's information (name, bank, "
                 "account number) and for using donated money for its stated purpose. Fundy does not hold, "
                 "manage, or have access to money in users' bank accounts."),
                ("4. Prohibited conduct",
                 "You may not use Fundy to commit fraud, run scams, launder money, solicit fake donations, "
                 "provide false information, or engage in any conduct that violates applicable law. Fundy "
                 "reserves the right to suspend accounts or remove violating funds without prior notice."),
                ("5. Immutability of blockchain data",
                 "Every transaction written to the blockchain is permanent and cannot be edited or deleted "
                 "— not even by the Fundy team. Users should verify information carefully before confirming "
                 "a transaction, since there is no \"undo\" on a public ledger."),
                ("6. Limitation of liability",
                 "Fundy is provided \"as is.\" During Beta it may experience downtime, bugs, or delays "
                 "syncing with the blockchain. Fundy is not liable for disputes between donors and fund "
                 "owners regarding how money is used off-platform."),
                ("7. Fees",
                 "During the Beta period, Fundy charges no fees whatsoever. Any future fee changes will be "
                 "announced publicly before taking effect."),
                ("8. Changes to these terms",
                 "Fundy may update these terms from time to time. The latest version is always posted on "
                 "this page; continued use of the service means you accept those changes."),
                ("9. Contact",
                 "For questions about these terms, please contact the Fundy team through the platform's "
                 "official support channel."),
            ],
        },
    },
    "privacy": {
        "vi": {
            "h1": "Chính sách bảo mật",
            "sub": "Cập nhật lần cuối: 20/07/2026 — cách Fundy thu thập, sử dụng và bảo vệ dữ liệu của bạn",
            "sections": [
                ("1. Dữ liệu chúng tôi thu thập",
                 "Fundy chỉ thu thập tối thiểu: tên đăng nhập, mật khẩu (được mã hóa băm, không lưu dạng "
                 "văn bản thuần), tên quỹ, ngân hàng và số tài khoản nhận tiền do bạn tự nhập, cùng nội "
                 "dung/mô tả giao dịch. Chúng tôi không yêu cầu email, số điện thoại hay giấy tờ tùy thân."),
                ("2. Dữ liệu công khai trên blockchain",
                 "Số tiền, nội dung chuyển khoản, mã giao dịch ngân hàng và thời gian giao dịch của các quỹ "
                 "được ghi công khai và vĩnh viễn trên blockchain Polygon — bất kỳ ai cũng có thể xem được. "
                 "Vui lòng không đưa thông tin cá nhân nhạy cảm vào nội dung chuyển khoản."),
                ("3. Cookie & phiên đăng nhập",
                 "Fundy sử dụng cookie/session tối thiểu để ghi nhớ ngôn ngữ hiển thị (VI/EN) và duy trì "
                 "trạng thái đăng nhập. Fundy không dùng cookie quảng cáo hay theo dõi hành vi của bên "
                 "thứ ba."),
                ("4. Cách chúng tôi sử dụng dữ liệu",
                 "Dữ liệu chỉ được dùng để vận hành tài khoản, hiển thị quỹ và ghi nhận giao dịch minh bạch. "
                 "Fundy không bán, cho thuê hay chia sẻ dữ liệu cá nhân cho bên thứ ba vì mục đích quảng "
                 "cáo."),
                ("5. Lưu trữ & bảo mật",
                 "Mật khẩu được băm (hash) trước khi lưu trữ, không thể khôi phục ngược lại thành văn bản "
                 "gốc. Dữ liệu quỹ được lưu trong cơ sở dữ liệu nội bộ kết hợp với bản ghi bất biến trên "
                 "blockchain để đảm bảo tính toàn vẹn."),
                ("6. Quyền của bạn",
                 "Bạn có thể yêu cầu xóa tài khoản và dữ liệu định danh (tên đăng nhập, mật khẩu) khỏi cơ "
                 "sở dữ liệu của Fundy. Lưu ý: các giao dịch đã ghi lên blockchain là vĩnh viễn và không thể "
                 "xóa, do bản chất bất biến của công nghệ chuỗi khối."),
                ("7. Lưu ý giai đoạn Beta / Testnet",
                 "Vì đang chạy thử nghiệm, dữ liệu có thể được reset khi nâng cấp hệ thống. Fundy sẽ thông "
                 "báo trước nếu có kế hoạch reset ảnh hưởng đến tài khoản hoặc quỹ hiện có."),
                ("8. Liên hệ",
                 "Nếu có câu hỏi về chính sách bảo mật hoặc muốn thực hiện quyền của bạn đối với dữ liệu cá "
                 "nhân, vui lòng liên hệ đội ngũ Fundy qua kênh hỗ trợ chính thức."),
            ],
        },
        "en": {
            "h1": "Privacy Policy",
            "sub": "Last updated: 20 Jul 2026 — how Fundy collects, uses, and protects your data",
            "sections": [
                ("1. Data we collect",
                 "Fundy collects the minimum necessary: your username, password (stored as a salted hash, "
                 "never in plain text), fund name, bank, and receiving account number that you enter "
                 "yourself, plus transaction descriptions. We do not require an email, phone number, or ID."),
                ("2. Data made public on the blockchain",
                 "Amounts, transfer descriptions, bank transaction IDs, and timestamps for each fund are "
                 "written publicly and permanently to the Polygon blockchain — anyone can view them. Please "
                 "avoid putting sensitive personal information in a transfer description."),
                ("3. Cookies & session",
                 "Fundy uses a minimal cookie/session to remember your display language (VI/EN) and keep "
                 "you logged in. Fundy does not use advertising cookies or third-party behavioral tracking."),
                ("4. How we use data",
                 "Data is used only to operate your account, display funds, and record transactions "
                 "transparently. Fundy does not sell, rent, or share personal data with third parties for "
                 "advertising purposes."),
                ("5. Storage & security",
                 "Passwords are hashed before storage and cannot be reversed back into plain text. Fund "
                 "data is stored in an internal database alongside the immutable blockchain record to "
                 "preserve data integrity."),
                ("6. Your rights",
                 "You may request deletion of your account and identifying data (username, password) from "
                 "Fundy's database. Note: transactions already written to the blockchain are permanent and "
                 "cannot be deleted, due to the immutable nature of blockchain technology."),
                ("7. Beta / Testnet notice",
                 "Because Fundy is running in Beta, data may be reset during system upgrades. Fundy will "
                 "give advance notice before any reset that would affect existing accounts or funds."),
                ("8. Contact",
                 "If you have questions about this privacy policy or wish to exercise your rights over your "
                 "personal data, please contact the Fundy team through the official support channel."),
            ],
        },
    },
}

# =========================================================================
# HƯỚNG DẪN SỬ DỤNG — nội dung chi tiết theo từng bước
# =========================================================================
GUIDE_CONTENT = {
    "vi": {
        "h1": "Hướng dẫn sử dụng Fundy",
        "sub": "Từng bước tạo quỹ, quyên góp và tự kiểm chứng minh bạch — không cần tin ai, chỉ cần đối chiếu dữ liệu.",
        "toc": [
            ("tao-quy",    "1. Tạo quỹ"),
            ("quyen-gop",  "2. Quyên góp / chuyển tiền"),
            ("theo-doi",   "3. Theo dõi &amp; đối chiếu"),
            ("xac-minh",   "4. Xác minh trên Blockchain"),
            ("chi-tieu",   "5. Ghi nhận chi tiêu (chủ quỹ)"),
            ("moi-thanh-vien", "6. Mời thành viên xem quỹ"),
            ("an-toan",    "7. Nhận diện dấu hiệu gian lận"),
        ],
        "sections": [
            {
                "id": "tao-quy", "title": "1. Tạo quỹ mới",
                "intro": "Bất kỳ ai cũng có thể khởi tạo một quỹ trong vài giây, không bắt buộc phải đăng ký tài khoản.",
                "steps": [
                    ("Vào trang chủ", "Bấm mục \"Trang chủ\" trên thanh điều hướng, kéo tới khối \"Tạo quỹ mới\"."),
                    ("Điền thông tin quỹ", "Nhập Tên quỹ, Ngân hàng nhận tiền và Số tài khoản (STK) — đây là số tài khoản mà người quyên góp sẽ chuyển khoản tới."),
                    ("Chọn chế độ hiển thị", "Tích \"Công khai\" nếu muốn quỹ xuất hiện ở mục Quỹ cộng đồng để mọi người cùng thấy và giám sát; để trống nếu muốn quỹ ở chế độ riêng tư, chỉ ai có link mới xem được."),
                    ("Tạo tài khoản (tuỳ chọn)", "Nếu chưa đăng nhập, bạn có thể điền thêm Tên đăng nhập/Mật khẩu ngay trong form để vừa tạo quỹ vừa tạo tài khoản chủ quỹ — giúp quản lý quỹ về sau."),
                    ("Nhận đường dẫn quỹ", "Sau khi tạo, hệ thống trả về một trang quỹ riêng với đường dẫn duy nhất — lưu lại hoặc chia sẻ link này cho người quyên góp."),
                ],
            },
            {
                "id": "quyen-gop", "title": "2. Quyên góp / chuyển tiền vào quỹ",
                "intro": "Fundy không giữ tiền hộ — bạn chuyển khoản trực tiếp qua ngân hàng, hệ thống chỉ ghi nhận và đối chiếu minh bạch.",
                "steps": [
                    ("Mở trang quỹ", "Truy cập đường dẫn quỹ mà chủ quỹ chia sẻ, hoặc tìm quỹ công khai trong mục \"Quỹ cộng đồng\"."),
                    ("Lấy thông tin chuyển khoản", "Xem đúng Tên ngân hàng và Số tài khoản hiển thị trên trang quỹ."),
                    ("Ghi đúng nội dung chuyển khoản", "Khi chuyển khoản qua app ngân hàng, nên giữ nội dung rõ ràng (ví dụ tên người ủng hộ) để dễ đối chiếu sau này."),
                    ("Chờ hệ thống ghi nhận", "Sau khi ngân hàng báo có, giao dịch sẽ được đồng bộ tự động lên sổ cái Polygon trong ít phút — số dư và lịch sử quỹ sẽ tự cập nhật."),
                ],
            },
            {
                "id": "theo-doi", "title": "3. Theo dõi &amp; đối chiếu giao dịch",
                "intro": "Mọi khoản thu, chi của quỹ đều hiển thị công khai theo thời gian thực trên trang quỹ.",
                "steps": [
                    ("Xem nhật ký giao dịch", "Trang quỹ liệt kê đầy đủ từng giao dịch: số tiền, thời gian, nội dung, và đánh dấu là khoản thu hay khoản chi."),
                    ("Đối chiếu với sao kê ngân hàng", "So sánh số tiền và mã giao dịch ngân hàng (bankTxId) với sao kê tài khoản của chính bạn nếu bạn là người chuyển khoản."),
                    ("Theo dõi số dư quỹ", "Số dư hiện tại = tổng thu − tổng chi, được tính tự động và hiển thị ngay đầu trang quỹ."),
                ],
            },
            {
                "id": "xac-minh", "title": "4. Xác minh trên Blockchain (Polygonscan)",
                "intro": "Đây là bước quan trọng nhất để tự mình chống lừa đảo — không cần tin Fundy, chỉ cần tin vào dữ liệu công khai trên chuỗi khối.",
                "steps": [
                    ("Bấm nút \"Kiểm chứng\"", "Ở mỗi dòng giao dịch trong nhật ký quỹ, bấm biểu tượng/nút kiểm chứng để mở hộp thoại hướng dẫn xác minh."),
                    ("Mở Polygonscan (Amoy Explorer)", "Bấm liên kết trong hộp thoại để mở trực tiếp trang Explorer công khai — không cần đăng nhập, không cần cài đặt gì thêm."),
                    ("Đối chiếu địa chỉ hợp đồng &amp; mã quỹ", "Kiểm tra Địa chỉ hợp đồng thông minh và Fund ID hiển thị trong hộp thoại có trùng khớp với dữ liệu trên Explorer hay không."),
                    ("So khớp số tiền &amp; nội dung", "Đối chiếu số tiền và mô tả giao dịch trên Explorer với những gì hiển thị trên trang quỹ — nếu khớp 100%, giao dịch đó là thật và không thể bị chỉnh sửa."),
                ],
            },
            {
                "id": "chi-tieu", "title": "5. Ghi nhận chi tiêu (dành cho chủ quỹ)",
                "intro": "Chỉ chủ quỹ mới có quyền ghi chi tiêu, và mọi khoản chi đều vĩnh viễn hiển thị công khai để thành viên giám sát.",
                "steps": [
                    ("Đăng nhập bằng tài khoản chủ quỹ", "Chỉ tài khoản đã tạo quỹ (owner) mới thấy được form ghi chi tiêu trên trang quỹ."),
                    ("Nhập số tiền &amp; mô tả", "Điền chính xác số tiền đã chi và mô tả rõ ràng (mua gì, cho ai, mục đích gì)."),
                    ("Xác nhận ghi sổ", "Sau khi lưu, khoản chi được đồng bộ lên blockchain và không thể sửa hay xoá — kể cả bởi chủ quỹ hay đội ngũ Fundy."),
                ],
            },
            {
                "id": "moi-thanh-vien", "title": "6. Mời thành viên xem quỹ riêng tư",
                "intro": "Với quỹ riêng tư, chủ quỹ có thể mời thêm người xem để cùng giám sát mà không công khai toàn bộ cộng đồng.",
                "steps": [
                    ("Vào trang quỹ", "Đăng nhập với vai trò chủ quỹ và mở trang quỹ cần mời thêm người xem."),
                    ("Nhập tên đăng nhập người được mời", "Điền đúng tên đăng nhập Fundy của người bạn muốn mời vào ô mời thành viên."),
                    ("Xác nhận", "Sau khi mời thành công, người đó sẽ thấy quỹ này trong mục \"Quỹ của tôi\" và có thể theo dõi mọi giao dịch."),
                ],
            },
            {
                "id": "an-toan", "title": "7. Nhận diện dấu hiệu gian lận / lừa đảo",
                "intro": "Fundy giúp minh bạch hoá dữ liệu, nhưng bạn vẫn nên tự kiểm tra vài dấu hiệu sau trước khi quyên góp.",
                "steps": [
                    ("Số tài khoản không khớp", "Luôn đối chiếu Ngân hàng và Số tài khoản trên trang quỹ Fundy với số tài khoản người kêu gọi công bố ở nơi khác (Facebook, Zalo...) — nếu lệch, dừng lại và hỏi trực tiếp."),
                    ("Không thể tra cứu trên Explorer", "Nếu một giao dịch được quảng cáo là \"đã ghi lên blockchain\" nhưng không thể tìm thấy trên Polygonscan với đúng địa chỉ hợp đồng của Fundy, đó là dấu hiệu đáng ngờ."),
                    ("Chi tiêu không có mô tả rõ ràng", "Một quỹ minh bạch sẽ luôn có mô tả chi tiêu cụ thể; các khoản chi mập mờ, chung chung, lặp lại bất thường nên được đặt câu hỏi với chủ quỹ."),
                    ("Áp lực chuyển tiền gấp", "Cẩn trọng với những lời kêu gọi tạo cảm giác cấp bách, hối thúc chuyển tiền ngay mà không cho thời gian kiểm tra thông tin quỹ."),
                ],
            },
        ],
    },
    "en": {
        "h1": "How to use Fundy",
        "sub": "A step-by-step guide to creating a fund, donating, and verifying transparency yourself — trust the data, not a middleman.",
        "toc": [
            ("tao-quy",    "1. Create a fund"),
            ("quyen-gop",  "2. Donate / transfer money"),
            ("theo-doi",   "3. Track &amp; reconcile"),
            ("xac-minh",   "4. Verify on the blockchain"),
            ("chi-tieu",   "5. Record expenses (owner)"),
            ("moi-thanh-vien", "6. Invite viewers"),
            ("an-toan",    "7. Spot red flags"),
        ],
        "sections": [
            {
                "id": "tao-quy", "title": "1. Create a new fund",
                "intro": "Anyone can set up a fund in seconds — an account is not required.",
                "steps": [
                    ("Go to the homepage", "Click \"Home\" in the nav bar and scroll to the \"Create a new fund\" block."),
                    ("Fill in the fund details", "Enter the Fund name, receiving Bank, and Account number — this is the account donors will transfer money to."),
                    ("Choose visibility", "Check \"Public\" so the fund appears under Community Funds for everyone to see and monitor; leave it unchecked to keep the fund private, viewable only via its link."),
                    ("Create an account (optional)", "If you're not logged in, you can add a Username/Password right in the same form to create both the fund and your owner account at once — this makes managing the fund easier later."),
                    ("Get your fund link", "Once created, you'll land on a dedicated fund page with a unique URL — save it or share it with donors."),
                ],
            },
            {
                "id": "quyen-gop", "title": "2. Donate / transfer money into a fund",
                "intro": "Fundy never holds your money — you transfer directly through your bank, and the system records and reconciles it transparently.",
                "steps": [
                    ("Open the fund page", "Visit the link the fund owner shared, or find a public fund under \"Community Funds\"."),
                    ("Get the transfer details", "Check the exact Bank name and Account number shown on the fund page."),
                    ("Use a clear transfer note", "When transferring through your banking app, keep the description clear (e.g. your name) so it's easy to reconcile later."),
                    ("Wait for it to sync", "Once your bank confirms the transfer, it's synced onto the Polygon ledger within minutes — the fund's balance and history update automatically."),
                ],
            },
            {
                "id": "theo-doi", "title": "3. Track &amp; reconcile transactions",
                "intro": "Every inflow and outflow of a fund is shown publicly, in real time, on the fund page.",
                "steps": [
                    ("View the transaction log", "The fund page lists every transaction: amount, time, description, and whether it's income or an expense."),
                    ("Cross-check with your bank statement", "Compare the amount and bank transaction ID (bankTxId) against your own bank statement if you're the one who transferred."),
                    ("Watch the fund balance", "The current balance = total income − total expenses, calculated automatically and shown at the top of the fund page."),
                ],
            },
            {
                "id": "xac-minh", "title": "4. Verify on the blockchain (Polygonscan)",
                "intro": "This is the most important step for protecting yourself against fraud — you don't need to trust Fundy, only the public, on-chain data.",
                "steps": [
                    ("Click \"Verify\"", "On any transaction row in the fund's log, click the verify icon/button to open the verification guide dialog."),
                    ("Open Polygonscan (Amoy Explorer)", "Click the link in the dialog to open the public Explorer directly — no login or extra installs needed."),
                    ("Cross-check the contract address &amp; fund ID", "Confirm the Smart contract address and Fund ID shown in the dialog match what's on the Explorer."),
                    ("Match the amount &amp; description", "Compare the amount and transaction description on the Explorer with what's shown on the fund page — if they match exactly, the transaction is real and cannot have been altered."),
                ],
            },
            {
                "id": "chi-tieu", "title": "5. Record expenses (fund owners)",
                "intro": "Only the fund owner can log an expense, and every expense stays permanently visible so members can keep watch.",
                "steps": [
                    ("Log in as the fund owner", "Only the account that created the fund (the owner) sees the expense form on the fund page."),
                    ("Enter the amount &amp; description", "Fill in the exact amount spent and a clear description — what it was for, who it was for, and the purpose."),
                    ("Confirm the entry", "Once saved, the expense is written to the blockchain and can never be edited or deleted — not even by the owner or the Fundy team."),
                ],
            },
            {
                "id": "moi-thanh-vien", "title": "6. Invite viewers to a private fund",
                "intro": "For private funds, the owner can invite additional viewers to help monitor it without exposing it to the whole community.",
                "steps": [
                    ("Open the fund page", "Log in as the owner and open the fund you want to add a viewer to."),
                    ("Enter their username", "Type the exact Fundy username of the person you want to invite in the invite-member field."),
                    ("Confirm", "Once invited, that person will see this fund under \"My Funds\" and can follow every transaction."),
                ],
            },
            {
                "id": "an-toan", "title": "7. Spot signs of fraud or scams",
                "intro": "Fundy makes the data transparent, but you should still check a few things yourself before donating.",
                "steps": [
                    ("Mismatched account details", "Always compare the Bank and Account number on the Fundy page against what the organizer posted elsewhere (Facebook, messaging apps, etc.) — if they don't match, stop and ask directly."),
                    ("Can't be found on the Explorer", "If a transaction is advertised as \"recorded on the blockchain\" but can't be found on Polygonscan under Fundy's actual contract address, treat that as a red flag."),
                    ("Vague or missing expense descriptions", "A transparent fund always logs specific expense descriptions; vague, generic, or unusually repetitive entries deserve a direct question to the owner."),
                    ("Pressure to send money urgently", "Be wary of appeals that create urgency and push you to transfer immediately without giving you time to check the fund's information."),
                ],
            },
        ],
    },
}

# =========================================================================
# CSS — Redesign hoàn toàn
# =========================================================================
CSS = r"""


*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}

:root{
  --bg:       #0c0c10;
  --surface:  #141418;
  --surface2: #1c1c22;
  --border:   rgba(255,255,255,.07);
  --border2:  rgba(255,255,255,.13);
  --text:     #f0f0f5;
  --text2:    #8888a8;
  --text3:    #55556a;
  --green:    #22d4a0;
  --green2:   #1ab889;
  --gdim:     rgba(34,212,160,.08);
  --gborder:  rgba(34,212,160,.2);
  --blue:     #5b9cf6;
  --bdim:     rgba(91,156,246,.08);
  --bborder:  rgba(91,156,246,.2);
  --red:      #f06292;
  --rdim:     rgba(240,98,146,.08);
  --rborder:  rgba(240,98,146,.2);
  --gold:     #f5c842;
  --r:        14px;
  --rs:       10px;
  --shadow:   0 1px 3px rgba(0,0,0,.4), 0 8px 24px rgba(0,0,0,.25);
}

html{scroll-behavior:smooth}

body{
  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Helvetica Neue',Arial,sans-serif;
  background:var(--bg);
  color:var(--text);
  min-height:100vh;
  overflow-x:hidden;
  line-height:1.6;
  -webkit-font-smoothing:antialiased;
}

/* Subtle grid background */
body::before{
  content:'';
  position:fixed;inset:0;
  background-image:
    linear-gradient(rgba(255,255,255,.015) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,.015) 1px, transparent 1px);
  background-size:48px 48px;
  pointer-events:none;z-index:0;
}

/* Glow orbs */
body::after{
  content:'';
  position:fixed;
  top:-200px;left:50%;transform:translateX(-50%);
  width:800px;height:500px;
  background:radial-gradient(ellipse, rgba(91,156,246,.06) 0%, transparent 65%);
  pointer-events:none;z-index:0;
}

a{color:var(--blue);text-decoration:none;transition:color .15s}
a:hover{color:var(--text)}

/* ── NAV ─────────────────────────────────────────────────────── */
.nav{
  position:sticky;top:0;z-index:100;
  display:flex;align-items:center;justify-content:space-between;
  padding:0 28px;height:60px;
  background:rgba(12,12,16,.85);
  backdrop-filter:blur(20px);
  border-bottom:1px solid var(--border);
  gap:12px;flex-wrap:wrap;
}
.nav-left{display:flex;align-items:center;gap:28px}
.logo{
  font-size:15px;font-weight:700;letter-spacing:.05em;
  color:var(--text);white-space:nowrap;
}
.logo span{color:var(--green)}
.logo sup{
  font-size:8px;font-weight:600;letter-spacing:.1em;
  color:var(--text3);text-transform:uppercase;
  vertical-align:super;margin-left:2px;
}
.nav-links{display:flex;align-items:center;gap:4px}
.nav-link{
  display:inline-flex;align-items:center;
  height:34px;line-height:1;
  font-size:13px;font-weight:500;color:var(--text2);
  padding:0 12px;border-radius:8px;transition:all .15s;
  white-space:nowrap;box-sizing:border-box;
}
.nav-link:hover{color:var(--text);background:rgba(255,255,255,.06);text-decoration:none}
.nav-link.active{color:var(--green);background:var(--gdim)}
.nav-right{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.chain-pill{
  display:flex;align-items:center;gap:6px;
  font-family:'SFMono-Regular','Consolas','Liberation Mono',monospace;font-size:11px;
  color:var(--green);background:var(--gdim);
  border:1px solid var(--gborder);
  padding:4px 10px;border-radius:20px;white-space:nowrap;
}
.pulse{
  width:5px;height:5px;background:var(--green);
  border-radius:50%;flex-shrink:0;
  animation:pulse 2.5s ease-in-out infinite;
}
@keyframes pulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.4;transform:scale(.8)}}
.nav-user{
  font-size:12px;font-weight:500;color:var(--text2);
  font-family:'SFMono-Regular','Consolas','Liberation Mono',monospace;white-space:nowrap;
}
.nav-user strong{color:var(--text)}
.nav-btn{
  font-size:12px;font-weight:600;
  padding:7px 16px;border-radius:8px;
  border:1px solid var(--border2);color:var(--text2);
  transition:all .15s;white-space:nowrap;cursor:pointer;
}
.nav-btn:hover{border-color:var(--border2);color:var(--text);background:rgba(255,255,255,.06);text-decoration:none}
.nav-btn.primary{background:var(--green);color:#000;border-color:transparent;font-weight:700}
.nav-btn.primary:hover{background:var(--green2);color:#000}

/* ── NAV DROPDOWN (Giới thiệu) ──────────────────────────────────── */
.nav-dropdown{position:relative;display:flex;align-items:center}
.dropdown-toggle{
  display:inline-flex;align-items:center;gap:5px;
  height:34px;line-height:1;box-sizing:border-box;
  font-size:13px;font-weight:500;color:var(--text2);
  padding:0 12px;border-radius:8px;transition:all .15s;
  white-space:nowrap;background:none;border:none;cursor:pointer;font-family:inherit;
}
.dropdown-toggle:hover{color:var(--text);background:rgba(255,255,255,.06)}
.dropdown-toggle .caret{font-size:9px;transition:transform .15s}
.nav-dropdown.open .dropdown-toggle{color:var(--green);background:var(--gdim)}
.nav-dropdown.open .dropdown-toggle .caret{transform:rotate(180deg)}
.dropdown-panel{
  display:none;position:absolute;top:calc(100% + 8px);left:0;
  min-width:190px;background:var(--surface2);
  border:1px solid var(--border2);border-radius:12px;
  padding:8px;box-shadow:0 12px 32px rgba(0,0,0,.45);
  z-index:200;
}
.nav-dropdown.open .dropdown-panel{display:block}
.dropdown-handle{width:36px;height:4px;border-radius:2px;background:var(--border2);margin:2px auto 8px}
.dropdown-item{
  display:block;font-size:13px;color:var(--text2);
  padding:9px 12px;border-radius:8px;transition:all .15s;white-space:nowrap;
}
.dropdown-item:hover{color:var(--text);background:rgba(255,255,255,.06);text-decoration:none}
.dropdown-item.active{color:var(--green);background:var(--gdim)}

/* ── INTRO / ABOUT / FAQ / TERMS / PRIVACY PAGES ────────────────── */
.intro-layout{display:flex;align-items:flex-start;gap:24px}
.intro-side{width:210px;flex-shrink:0;display:flex;flex-direction:column;gap:2px;position:sticky;top:76px}
.intro-side a{
  font-size:13px;color:var(--text2);padding:10px 14px;border-radius:9px;
  transition:all .15s;white-space:nowrap;
}
.intro-side a:hover{color:var(--text);background:rgba(255,255,255,.06);text-decoration:none}
.intro-side a.active{color:var(--green);background:var(--gdim);font-weight:600}
.intro-content{flex:1;min-width:0}
.intro-content h1{font-size:24px;font-weight:700;letter-spacing:-.02em;margin-bottom:6px}
.intro-content .intro-sub{font-size:13px;color:var(--text3);margin-bottom:20px}
.intro-content h2{font-size:15px;font-weight:600;margin:22px 0 8px}
.intro-content h2:first-of-type{margin-top:4px}
.intro-content p{font-size:13.5px;color:var(--text2);line-height:1.85;margin-bottom:4px}
.intro-content .faq-item{
  background:var(--surface2);border:1px solid var(--border);
  border-radius:12px;padding:18px 20px;margin-bottom:14px;
}
.intro-content .faq-item .q{font-size:14px;font-weight:600;color:var(--text);margin-bottom:8px}
.intro-content .faq-item .a{font-size:13.5px;color:var(--text2);line-height:1.8}
@media(max-width:720px){
  .intro-layout{flex-direction:column}
  .intro-side{position:static;width:100%;flex-direction:row;flex-wrap:wrap;gap:6px}
}

/* ── LAYOUT ──────────────────────────────────────────────────── */
.wrap{
  position:relative;z-index:1;
  max-width:720px;margin:0 auto;
  padding:48px 20px 100px;
}
.wrap.narrow{max-width:420px;padding-top:32px}

/* ── HERO ────────────────────────────────────────────────────── */
.hero{text-align:center;padding:56px 0 40px}
.hero-eyebrow{
  display:inline-flex;align-items:center;gap:7px;
  font-family:'SFMono-Regular','Consolas','Liberation Mono',monospace;
  font-size:11px;letter-spacing:.12em;text-transform:uppercase;
  color:var(--blue);background:var(--bdim);
  border:1px solid var(--bborder);
  padding:5px 14px;border-radius:20px;margin-bottom:24px;
}
.hero h1{
  font-size:clamp(28px,5vw,52px);font-weight:700;
  line-height:1.05;letter-spacing:-.03em;
  margin-bottom:16px;
}
.hero h1 em{font-style:normal;color:var(--green)}
.hero p{
  font-size:15px;color:var(--text2);
  max-width:440px;margin:0 auto;line-height:1.8;
}

/* ── CARDS ───────────────────────────────────────────────────── */
.card{
  background:var(--surface);
  border:1px solid var(--border);
  border-radius:var(--r);
  padding:28px;
  margin-bottom:16px;
  box-shadow:var(--shadow);
  transition:border-color .2s;
}
.card:hover{border-color:var(--border2)}

/* ── SECTION HEADER ──────────────────────────────────────────── */
.sh{display:flex;align-items:center;justify-content:space-between;margin-bottom:20px;gap:8px;flex-wrap:wrap}
.sh-title{font-size:14px;font-weight:600;color:var(--text)}
.sh-meta{font-size:12px;color:var(--text3);font-family:'SFMono-Regular','Consolas','Liberation Mono',monospace}
.divider{height:1px;background:var(--border);margin:22px 0}

/* ── FORM ────────────────────────────────────────────────────── */
.fg{margin-bottom:16px}
.fg label{
  display:block;font-size:11px;font-weight:600;
  letter-spacing:.08em;text-transform:uppercase;
  color:var(--text2);margin-bottom:7px;
}
input,select{
  width:100%;
  background:var(--surface2);
  border:1px solid var(--border);
  border-radius:var(--rs);
  padding:12px 14px;
  color:var(--text);
  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;
  font-size:14px;font-weight:400;
  outline:none;
  transition:border-color .2s,box-shadow .2s;
  -webkit-appearance:none;
}
input:focus,select:focus{
  border-color:rgba(91,156,246,.5);
  box-shadow:0 0 0 3px rgba(91,156,246,.1);
}
select option{background:var(--surface2)}
input::placeholder{color:var(--text3)}
.fg-row{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.fg-hint{font-size:11px;color:var(--text3);margin-top:7px;line-height:1.65}

/* ── BUTTON ──────────────────────────────────────────────────── */
.btn{
  display:block;width:100%;
  padding:13px 20px;
  background:var(--green);color:#000;
  border:none;border-radius:var(--rs);
  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;
  font-size:14px;font-weight:700;
  letter-spacing:.01em;
  cursor:pointer;
  transition:background .15s,transform .12s,box-shadow .15s;
  text-align:center;text-decoration:none;
  margin-top:8px;
  box-shadow:0 0 20px rgba(34,212,160,.15);
}
.btn:hover{background:var(--green2);color:#000;transform:translateY(-1px);box-shadow:0 4px 20px rgba(34,212,160,.25);text-decoration:none}
.btn:active{transform:translateY(0)}
.btn.ghost{background:transparent;color:var(--text2);border:1px solid var(--border2);box-shadow:none}
.btn.ghost:hover{border-color:var(--border2);color:var(--text);background:rgba(255,255,255,.05);transform:none;box-shadow:none}
.btn-sm{display:inline-flex;align-items:center;width:auto;padding:8px 16px;font-size:12px;border-radius:8px;margin-top:0}

/* ── TOGGLE ──────────────────────────────────────────────────── */
.toggle-row{
  display:flex;align-items:flex-start;gap:14px;
  padding:14px 16px;
  background:var(--surface2);
  border:1px solid var(--border);
  border-radius:var(--rs);
  cursor:pointer;user-select:none;
}
.toggle-row input{display:none}
.toggle-row .toggle-title,.toggle-row .toggle-desc{text-transform:none!important;letter-spacing:normal!important}
.sw{
  flex-shrink:0;
  width:38px;height:22px;
  background:var(--surface2);
  border:1px solid var(--border2);
  border-radius:20px;position:relative;
  transition:.2s;margin-top:1px;
}
.sw::after{
  content:'';position:absolute;
  width:14px;height:14px;
  background:var(--text3);
  border-radius:50%;
  top:3px;left:3px;transition:.2s;
}
.toggle-row input:checked ~ .sw{background:var(--green);border-color:var(--green)}
.toggle-row input:checked ~ .sw::after{transform:translateX(16px);background:#000}
.toggle-body{display:flex;flex-direction:column;gap:3px}
.toggle-title{font-size:13px;font-weight:500;color:var(--text);text-transform:none;letter-spacing:normal}
.toggle-desc{font-size:11px;font-weight:400;color:var(--text3);line-height:1.65;text-transform:none;letter-spacing:normal}


/* ── STATS ───────────────────────────────────────────────────── */
.stats{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:16px}
.stat{
  background:var(--surface2);
  border:1px solid var(--border);
  border-radius:var(--rs);
  padding:18px 20px;
}
.stat-label{
  font-size:10px;font-weight:600;
  letter-spacing:.1em;text-transform:uppercase;
  color:var(--text3);margin-bottom:8px;
}
.stat-val{
  font-family:'SFMono-Regular','Consolas','Liberation Mono',monospace;
  font-size:28px;font-weight:500;
  color:var(--green);letter-spacing:-.02em;
}
.stat-val.blue{color:var(--blue)}
.stat-unit{font-size:13px;color:var(--text3);margin-left:2px}

/* ── QR ──────────────────────────────────────────────────────── */
.qr-section{
  background:var(--surface);
  border:1px solid var(--border);
  border-radius:var(--r);
  padding:32px 28px;
  text-align:center;
  margin-bottom:16px;
  box-shadow:var(--shadow);
}
.qr-frame{
  display:inline-flex;align-items:center;justify-content:center;
  background:#fff;border-radius:16px;padding:14px;
  margin:20px auto;
  box-shadow:0 4px 20px rgba(0,0,0,.3);
}
.qr-frame img{display:block;width:200px;height:200px;border-radius:6px}

/* ── SHARE BOX ───────────────────────────────────────────────── */
.share-box{
  display:flex;align-items:center;gap:8px;
  background:var(--surface2);
  border:1px solid var(--border);
  border-radius:var(--rs);
  padding:10px 14px;margin-top:8px;
}
.share-url{
  font-family:'SFMono-Regular','Consolas','Liberation Mono',monospace;
  font-size:12px;color:var(--blue);
  flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
}
.copy-btn{
  flex-shrink:0;
  background:transparent;
  border:1px solid var(--border2);color:var(--text3);
  padding:5px 12px;border-radius:6px;
  font-size:11px;font-weight:600;
  cursor:pointer;white-space:nowrap;
  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;
  transition:all .15s;
}
.copy-btn:hover{border-color:var(--green);color:var(--green)}

/* ── TABLE ───────────────────────────────────────────────────── */
.tbl-wrap{overflow-x:auto;margin:0 -2px}
table{width:100%;border-collapse:collapse}
thead tr{border-bottom:1px solid var(--border)}
th{
  font-size:10px;font-weight:600;
  letter-spacing:.08em;text-transform:uppercase;
  color:var(--text3);padding:10px 12px;
  text-align:left;white-space:nowrap;
}
td{
  padding:13px 12px;
  border-bottom:1px solid rgba(255,255,255,.04);
  font-size:13px;color:var(--text2);
  vertical-align:middle;
}
tr:last-child td{border-bottom:none}
tbody tr:hover td{background:rgba(255,255,255,.03)}
.tx-id{
  font-family:'SFMono-Regular','Consolas','Liberation Mono',monospace;
  font-size:11px;color:var(--text3);
}
.amount-in{
  font-family:'SFMono-Regular','Consolas','Liberation Mono',monospace;
  font-weight:600;color:var(--green);
}
.amount-out{
  font-family:'SFMono-Regular','Consolas','Liberation Mono',monospace;
  font-weight:600;color:var(--red);
}
.empty-state{
  text-align:center;padding:44px 20px;
  color:var(--text3);font-size:13px;
}
.empty-icon{font-size:30px;margin-bottom:10px;opacity:.5}
.proof-link{
  display:inline-flex;align-items:center;gap:4px;
  font-size:11px;font-weight:500;
  color:var(--text3);
  font-family:'SFMono-Regular','Consolas','Liberation Mono',monospace;
  border:1px solid var(--border);
  border-radius:5px;padding:3px 8px;
  transition:all .15s;white-space:nowrap;
}
.proof-link:hover{color:var(--green);border-color:var(--gborder);background:var(--gdim);text-decoration:none}
.proof-link svg{flex-shrink:0}

/* ── BADGES ──────────────────────────────────────────────────── */
.badge{
  display:inline-flex;align-items:center;gap:5px;
  font-size:11px;font-weight:600;
  padding:3px 9px;border-radius:20px;
  letter-spacing:.02em;white-space:nowrap;
}
.badge-green{color:var(--green);background:var(--gdim);border:1px solid var(--gborder)}
.badge-blue{color:var(--blue);background:var(--bdim);border:1px solid var(--bborder)}
.badge-gray{color:var(--text2);background:rgba(255,255,255,.06);border:1px solid var(--border)}
.badge-red{color:var(--red);background:var(--rdim);border:1px solid var(--rborder)}

/* ── ALERTS ──────────────────────────────────────────────────── */
.alert{
  display:flex;align-items:flex-start;gap:10px;
  padding:12px 16px;border-radius:var(--rs);
  font-size:13px;margin-bottom:14px;
}
.alert-success{background:var(--gdim);border:1px solid var(--gborder);color:var(--green)}
.alert-error{background:var(--rdim);border:1px solid var(--rborder);color:var(--red)}

/* ── FUND ROW (list) ─────────────────────────────────────────── */
.fund-list{display:flex;flex-direction:column;gap:8px}
.fund-row{
  display:flex;align-items:center;gap:14px;
  padding:14px 16px;
  background:var(--surface2);
  border:1px solid var(--border);
  border-radius:var(--rs);
  transition:border-color .15s,background .15s;
  flex-wrap:wrap;
}
.fund-row:hover{border-color:var(--border2);background:rgba(255,255,255,.03)}
.fund-avatar{
  width:40px;height:40px;
  background:var(--gdim);border:1px solid var(--gborder);
  border-radius:10px;
  display:flex;align-items:center;justify-content:center;
  font-size:16px;flex-shrink:0;
}
.fund-info{flex:1;min-width:140px}
.fund-name{font-size:14px;font-weight:600;color:var(--text);margin-bottom:2px}
.fund-meta{font-size:11px;color:var(--text3);font-family:'SFMono-Regular','Consolas','Liberation Mono',monospace}

/* ── INVITE BOX ──────────────────────────────────────────────── */
.invite-box{
  background:var(--surface2);border:1px solid var(--border);
  border-radius:var(--rs);padding:16px;margin-top:14px;
}
.invite-title{font-size:13px;font-weight:600;color:var(--text);margin-bottom:10px}
.invite-form{display:flex;gap:8px}
.invite-form input{flex:1}
.member-chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}
.chip{
  display:inline-flex;align-items:center;gap:4px;
  font-size:11px;font-family:'SFMono-Regular','Consolas','Liberation Mono',monospace;
  color:var(--text2);
  background:var(--surface);border:1px solid var(--border);
  border-radius:20px;padding:4px 10px;
}

/* ── NOTICE ──────────────────────────────────────────────────── */
.notice{
  display:flex;align-items:center;gap:8px;
  background:rgba(34,212,160,.05);
  border:1px solid rgba(34,212,160,.15);
  border-radius:var(--rs);
  padding:10px 14px;font-size:12px;color:var(--green);
  margin-top:14px;
}

/* ── ABOUT CARD ──────────────────────────────────────────────── */
.about-strip{
  background:linear-gradient(135deg,rgba(34,212,160,.06),rgba(91,156,246,.04));
  border:1px solid rgba(255,255,255,.08);
  border-radius:var(--r);
  padding:20px 24px;margin-bottom:20px;
  font-size:13px;color:var(--text2);line-height:1.75;
}
.about-strip strong{color:var(--text)}

/* ── FEATURE GRID ────────────────────────────────────────────── */
.feat{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-top:4px}
.feat-card{
  background:var(--surface2);border:1px solid var(--border);
  border-radius:var(--r);padding:20px 16px;text-align:center;
  transition:border-color .2s,transform .15s;
}
.feat-card:hover{border-color:var(--border2);transform:translateY(-2px)}
.feat-icon{font-size:20px;margin-bottom:10px;display:block}
.feat-title{font-size:12px;font-weight:700;color:var(--text);margin-bottom:4px;letter-spacing:.02em}
.feat-desc{font-size:11px;color:var(--text3);line-height:1.6}

/* ── ACCOUNT BOX ─────────────────────────────────────────────── */
.account-sep{
  border-top:1px solid var(--border);padding-top:18px;margin-top:6px;
}
.account-logged{
  display:flex;align-items:center;gap:10px;
  background:var(--surface2);border:1px solid var(--gborder);
  border-radius:var(--rs);padding:11px 14px;
  font-size:13px;color:var(--text2);
}
.account-logged strong{color:var(--green)}

/* ── SPINNER ─────────────────────────────────────────────────── */
.spin{
  display:inline-block;
  width:12px;height:12px;
  border:2px solid rgba(0,0,0,.2);
  border-top-color:#000;border-radius:50%;
  animation:spin .5s linear infinite;
  vertical-align:middle;margin-right:6px;
}
@keyframes spin{to{transform:rotate(360deg)}}

/* ── FOOTER TEXT ─────────────────────────────────────────────── */
.footer-note{
  text-align:center;font-size:11px;
  color:var(--text3);margin-top:24px;
  font-family:'SFMono-Regular','Consolas','Liberation Mono',monospace;
  letter-spacing:.03em;
}

/* ── VERIFY MODAL ────────────────────────────────────────────── */
.modal-backdrop{
  display:none;position:fixed;inset:0;z-index:200;
  background:rgba(0,0,0,.7);backdrop-filter:blur(6px);
  align-items:center;justify-content:center;padding:20px;
}
.modal-backdrop.open{display:flex}
.modal{
  background:var(--surface);border:1px solid var(--border2);
  border-radius:16px;width:100%;max-width:560px;
  max-height:90vh;overflow-y:auto;
  box-shadow:0 24px 64px rgba(0,0,0,.5);
}
.modal-head{
  display:flex;align-items:center;justify-content:space-between;
  padding:20px 24px 0;
}
.modal-title{font-size:15px;font-weight:700;color:var(--text)}
.modal-close{
  width:28px;height:28px;border-radius:8px;
  background:var(--surface2);border:1px solid var(--border);
  color:var(--text2);font-size:16px;line-height:1;
  cursor:pointer;display:flex;align-items:center;justify-content:center;
  transition:all .15s;flex-shrink:0;
}
.modal-close:hover{background:var(--rdim);border-color:var(--rborder);color:var(--red)}
.modal-body{padding:16px 24px 24px}
.modal-intro{
  font-size:13px;color:var(--text2);line-height:1.7;
  background:var(--surface2);border:1px solid var(--border);
  border-radius:var(--rs);padding:12px 14px;margin-bottom:18px;
}
.modal-intro strong{color:var(--text)}
/* Steps */
.steps{display:flex;flex-direction:column;gap:0}
.step{display:flex;gap:14px;padding:14px 0;border-bottom:1px solid var(--border)}
.step:last-child{border-bottom:none}
.step-num{
  flex-shrink:0;width:26px;height:26px;
  background:var(--gdim);border:1px solid var(--gborder);
  border-radius:50%;font-size:12px;font-weight:700;color:var(--green);
  display:flex;align-items:center;justify-content:center;margin-top:1px;
}
.step-body{flex:1;min-width:0}
.step-title{font-size:13px;font-weight:600;color:var(--text);margin-bottom:5px}
.step-desc{font-size:12px;color:var(--text2);line-height:1.65}
.step-code{
  display:inline-block;margin-top:6px;
  font-family:'SFMono-Regular','Consolas','Liberation Mono',monospace;
  font-size:11px;color:var(--green);
  background:var(--gdim);border:1px solid var(--gborder);
  border-radius:5px;padding:4px 8px;word-break:break-all;
}
.step-check{
  display:flex;flex-direction:column;gap:5px;margin-top:8px;
}
.check-item{
  display:flex;align-items:flex-start;gap:8px;
  font-size:12px;color:var(--text2);
}
.check-icon{color:var(--green);flex-shrink:0;font-size:13px;margin-top:1px}
.check-val{font-family:'SFMono-Regular','Consolas','Liberation Mono',monospace;
  color:var(--text);font-size:11px;word-break:break-all}
.modal-cta{
  margin-top:18px;display:flex;align-items:center;gap:10px;flex-wrap:wrap;
}
.modal-cta a{flex:1;min-width:160px}
.verify-btn{
  display:inline-flex;align-items:center;gap:6px;
  font-size:11px;font-weight:600;
  color:var(--text2);background:var(--surface2);
  border:1px solid var(--border2);border-radius:7px;
  padding:5px 10px;cursor:pointer;transition:all .15s;
  white-space:nowrap;
}
.verify-btn:hover{color:var(--green);border-color:var(--gborder);background:var(--gdim)}

/* ── AUTH PAGE ───────────────────────────────────────────────── */
.auth-hero{text-align:center;padding:20px 0 28px}
.auth-logo{font-size:22px;font-weight:700;margin-bottom:4px;letter-spacing:-.02em}
.auth-logo span{color:var(--green)}
.auth-sub{font-size:13px;color:var(--text3)}

/* ── GUIDE PAGE ──────────────────────────────────────────────── */
.guide-section{margin-bottom:8px;scroll-margin-top:88px}
.guide-section:not(:last-child){border-bottom:1px solid var(--border);padding-bottom:26px;margin-bottom:26px}
.guide-section-head{display:flex;align-items:center;gap:10px;margin-bottom:8px}
.guide-section-num{
  flex-shrink:0;width:28px;height:28px;border-radius:8px;
  background:var(--gdim);border:1px solid var(--gborder);color:var(--green);
  font-size:12px;font-weight:700;display:flex;align-items:center;justify-content:center;
}
.guide-section h2{font-size:16px;font-weight:700;color:var(--text)}
.guide-section-intro{font-size:13px;color:var(--text2);line-height:1.75;margin:6px 0 16px}
.guide-toc{
  display:flex;flex-wrap:wrap;gap:8px;margin-bottom:24px;
  padding:14px;background:var(--surface2);border:1px solid var(--border);border-radius:var(--rs);
}
.guide-toc a{
  font-size:12px;font-weight:600;color:var(--text2);
  background:var(--surface);border:1px solid var(--border2);border-radius:20px;
  padding:5px 12px;transition:all .15s;
}
.guide-toc a:hover{color:var(--green);border-color:var(--gborder);background:var(--gdim);text-decoration:none}

@media(max-width:520px){
  .stats,.feat,.fg-row{grid-template-columns:1fr}
  .hero{padding:36px 0 28px}
  .card{padding:20px}
  .nav{padding:0 16px}
  .invite-form{flex-direction:column}
  .wrap{padding:28px 16px 80px}
}
"""

# =========================================================================
# LAYOUT HELPERS
# =========================================================================
INTRO_KEYS = ('about-fundy', 'faq', 'terms', 'privacy')

def nav_html(active=''):
    lang = get_lang()
    def lnk(href, label, key):
        cls = 'nav-link active' if active == key else 'nav-link'
        return f'<a class="{cls}" href="{href}">{label}</a>'
    def ddlnk(href, label, key):
        cls = 'dropdown-item active' if active == key else 'dropdown-item'
        return f'<a class="{cls}" href="{href}">{label}</a>'

    dd_open = 'nav-dropdown open' if active in INTRO_KEYS else 'nav-dropdown'
    intro_dd = f"""<div class="{dd_open}" id="introDropdown">
      <button type="button" class="dropdown-toggle" onclick="fyToggleIntro(event)">{T('nav_about')} <span class="caret">▾</span></button>
      <div class="dropdown-panel">
        <div class="dropdown-handle"></div>
        {ddlnk('/ve-fundy', T('intro_about'), 'about-fundy')}
        {ddlnk('/hoi-dap', T('intro_faq'), 'faq')}
        {ddlnk('/dieu-khoan', T('intro_terms'), 'terms')}
        {ddlnk('/chinh-sach-bao-mat', T('intro_privacy'), 'privacy')}
      </div>
    </div>"""

    links = (lnk('/', T('nav_home'), 'home')
             + intro_dd
             + lnk('/huong-dan', T('nav_guide'), 'guide')
             + lnk('/quy-cong-dong', T('nav_community'), 'community'))
    user = current_user()
    if user:
        links += lnk('/quy-cua-toi', T('nav_mine'), 'mine')
        right = f"""
        <span class="nav-user">👤 <strong>{user['username']}</strong></span>
        <a class="nav-btn" href="/dang-xuat">{T('nav_logout')}</a>"""
    else:
        right = f"""
        <a class="nav-btn" href="/dang-nhap">{T('nav_login')}</a>
        <a class="nav-btn primary" href="/dang-ky">{T('nav_register')}</a>"""

    # Language switcher
    other_lang = 'en' if lang == 'vi' else 'vi'
    other_label = 'EN' if lang == 'vi' else 'VI'
    lang_sw = f'<a class="nav-btn" href="/set-lang/{other_lang}" title="Switch language" style="padding:7px 10px;font-size:11px;letter-spacing:.05em">{other_label}</a>'

    return f"""<nav class="nav">
  <div class="nav-left">
    <div class="logo">Fund<span>y</span><sup>beta</sup></div>
    <div class="nav-links">{links}</div>
  </div>
  <div class="nav-right">
    <div class="chain-pill"><span class="pulse"></span>Polygon Amoy</div>
    {lang_sw}
    {right}
  </div>
</nav>
<script>
  function fyToggleIntro(e){{
    e.stopPropagation();
    document.getElementById('introDropdown').classList.toggle('open');
  }}
  document.addEventListener('click', function(e){{
    var dd = document.getElementById('introDropdown');
    if (dd && !dd.contains(e.target)) dd.classList.remove('open');
  }});
  document.addEventListener('keydown', function(e){{
    if (e.key === 'Escape') {{
      var dd = document.getElementById('introDropdown');
      if (dd) dd.classList.remove('open');
    }}
  }});
</script>"""

def alerts_html():
    out = ''
    for cat, msg in get_flashed_messages(with_categories=True):
        icon = '✓' if cat == 'success' else '⚠'
        out += f'<div class="alert alert-{cat if cat in ("success","error") else "error"}">{icon} {msg}</div>'
    return out

def page(content, active='', narrow=False):
    return f"""<!DOCTYPE html>
<html lang="{get_lang()}">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Fundy — Thu quỹ minh bạch</title>
  <style>{CSS}</style>
</head>
<body>
  {nav_html(active)}
  <div class="wrap{'  narrow' if narrow else ''}">
    {alerts_html()}
    {content}
  </div>
  <script>
    function copyLink(text){{
      navigator.clipboard.writeText(text).then(()=>{{
        const b=event.target;const o=b.textContent;
        b.textContent='✓ Đã sao chép';b.style.color='var(--green)';b.style.borderColor='var(--green)';
        setTimeout(()=>{{b.textContent=o;b.style.color='';b.style.borderColor='';}},2000);
      }});
    }}

    /* ── Scroll reveal ───────────────────────────── */
    (function(){{
      const els=document.querySelectorAll('.reveal');
      if(!els.length)return;
      const io=new IntersectionObserver(entries=>{{
        entries.forEach(e=>{{if(e.isIntersecting){{e.target.classList.add('revealed');io.unobserve(e.target);}}}});
      }},{{threshold:.08}});
      els.forEach(el=>io.observe(el));
    }})();

    /* ── Page-load stagger for top cards ─────────── */
    (function(){{
      document.querySelectorAll('.anim-fade-up').forEach((el,i)=>{{
        el.style.animationDelay=(i*0.06)+'s';
      }});
    }})();

    /* ── Number count-up for stat values ─────────── */
    function animateCount(el, target, prefix, suffix){{
      let start=0, dur=800, step=16;
      const inc=target/(dur/step);
      const timer=setInterval(()=>{{
        start+=inc;
        if(start>=target){{start=target;clearInterval(timer);}}
        el.textContent=prefix+Math.floor(start).toLocaleString('vi-VN')+suffix;
      }},step);
    }}
    window.addEventListener('DOMContentLoaded',()=>{{
      document.querySelectorAll('[data-count]').forEach(el=>{{
        const v=parseInt(el.dataset.count)||0;
        const pre=el.dataset.prefix||'';
        const suf=el.dataset.suffix||'';
        animateCount(el,v,pre,suf);
      }});
    }});
  </script>
</body>
</html>"""

def intro_side_html(active):
    def item(href, label, key):
        cls = 'active' if active == key else ''
        return f'<a class="{cls}" href="{href}">{label}</a>'
    return f"""<div class="intro-side">
      {item('/ve-fundy', T('intro_about'), 'about-fundy')}
      {item('/hoi-dap', T('intro_faq'), 'faq')}
      {item('/dieu-khoan', T('intro_terms'), 'terms')}
      {item('/chinh-sach-bao-mat', T('intro_privacy'), 'privacy')}
    </div>"""

def intro_page(active):
    """Render the Về Fundy / Hỏi đáp / Điều khoản / Chính sách bảo mật pages.
    active is one of: 'about-fundy', 'faq', 'terms', 'privacy'"""
    lang = get_lang() if get_lang() in ('vi', 'en') else 'vi'
    data = INTRO_CONTENT[active][lang]

    if active == 'faq':
        body = ''.join(
            f"""<div class="faq-item"><div class="q">Q: {q}</div><div class="a">A: {a}</div></div>"""
            for q, a in data['faq']
        )
    else:
        body = ''.join(
            f"""<h2>{title}</h2><p>{text}</p>"""
            for title, text in data['sections']
        )

    content = f"""
    <div class="intro-layout">
      {intro_side_html(active)}
      <div class="intro-content">
        <h1>{data['h1']}</h1>
        <div class="intro-sub">{data['sub']}</div>
        <div class="card">{body}</div>
      </div>
    </div>"""
    return page(content, active=active)

@app.route('/ve-fundy')
def about_fundy_page():
    return intro_page('about-fundy')

@app.route('/hoi-dap')
def faq_page():
    return intro_page('faq')

@app.route('/dieu-khoan')
def terms_page():
    return intro_page('terms')

@app.route('/chinh-sach-bao-mat')
def privacy_page():
    return intro_page('privacy')

def guide_page():
    """Render trang Hướng dẫn sử dụng chi tiết, dễ tiếp cận từ nav bar."""
    lang = get_lang() if get_lang() in ('vi', 'en') else 'vi'
    data = GUIDE_CONTENT[lang]

    toc = ''.join(f'<a href="#{anchor}">{label}</a>' for anchor, label in data['toc'])

    sections = ''
    for i, sec in enumerate(data['sections'], start=1):
        steps_html = ''.join(
            f"""<div class="step">
              <div class="step-num">{j}</div>
              <div class="step-body">
                <div class="step-title">{title}</div>
                <div class="step-desc">{desc}</div>
              </div>
            </div>""" for j, (title, desc) in enumerate(sec['steps'], start=1)
        )
        sections += f"""<div class="guide-section" id="{sec['id']}">
          <div class="guide-section-head">
            <div class="guide-section-num">{i}</div>
            <h2>{sec['title'].split('. ', 1)[-1]}</h2>
          </div>
          <div class="guide-section-intro">{sec['intro']}</div>
          <div class="steps">{steps_html}</div>
        </div>"""

    content = f"""
    <h1 style="font-size:24px;font-weight:700;letter-spacing:-.02em;margin-bottom:6px">{data['h1']}</h1>
    <div style="font-size:13px;color:var(--text3);margin-bottom:20px">{data['sub']}</div>
    <div class="guide-toc">{toc}</div>
    <div class="card">{sections}</div>"""
    return page(content, active='guide')

@app.route('/huong-dan')
def guide_route():
    return guide_page()

# =========================================================================
# ROUTES
# =========================================================================

@app.route("/set-lang/<lang>")
def set_lang(lang):
    if lang not in ("vi", "en"):
        lang = "vi"
    session["lang"] = lang
    resp = redirect(request.referrer or url_for("index"))
    resp.set_cookie("lang", lang, max_age=60*60*24*365)
    return resp

@app.route('/', methods=['GET', 'POST'])
def index():
    lang = get_lang()
    if request.method == 'POST':
        name      = request.form.get('name', '').strip()
        bank      = request.form.get('bank', '').strip()
        stk       = request.form.get('stk', '').strip()
        is_public = request.form.get('is_public') == 'on'

        if not name or not bank or not stk:
            flash('Vui lòng điền đầy đủ thông tin quỹ.', 'error')
            return redirect(url_for('index'))

        user     = current_user()
        owner_id = None
        if user:
            owner_id = user['id']
        else:
            nu = request.form.get('new_username', '').strip()
            np = request.form.get('new_password', '')
            if nu and np:
                new_id = create_user(nu, np)
                if new_id is None:
                    flash(f'Tên "{nu}" đã tồn tại. Quỹ được tạo dạng Guest.', 'error')
                else:
                    owner_id = new_id
                    session['user_id'] = new_id
            elif nu or np:
                flash('Cần điền cả Tên đăng nhập và Mật khẩu. Quỹ được tạo dạng Guest.', 'error')

        fund_id = ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))
        save_fund(fund_id, name, bank, stk, owner_id, is_public)
        threading.Thread(target=send_create_fund, args=(fund_id, name, not is_public), daemon=True).start()
        return redirect(url_for('view_fund', fund_id=fund_id))

    user = current_user()
    if user:
        acct = f"""<div class="account-sep">
          <div class="fg"><div class="account-logged">
            <span>👤</span> {T('logged_in_as')}&nbsp;<strong>{user['username']}</strong>
          </div></div></div>"""
    else:
        acct = f"""<div class="account-sep">
          <div class="fg">
            <label>{T('f_acct_label')}</label>
            <div class="fg-row">
              <input type="text" name="new_username" placeholder="{T('f_username_ph')}">
              <input type="password" name="new_password" placeholder="{T('f_password_ph')}">
            </div>
            <p class="fg-hint">{T('f_hint_guest')}
              <a href="/dang-nhap">{T('f_login_link')}</a> {T('f_hint_before')}</p>
          </div></div>"""

    c = f"""
<div class="hero">
  <div class="hero-eyebrow">✦ {T('hero_tag')}</div>
  <h1>{T('hero_h1a')} <em>{T('hero_h1b')}</em><br>{T('hero_h1c')}</h1>
  <p>{T('hero_sub')}</p>
</div>

<div class="about-strip">
  <strong>{T('about_title')}</strong> &nbsp;{T('about_body')}
</div>

<div class="card">
  <div class="sh"><div class="sh-title">{T('form_title')}</div></div>
  <form method="POST">
    <div class="fg">
      <label>{T('f_name')}</label>
      <input type="text" name="name" placeholder="{T('f_name_ph')}" required>
    </div>
    <div class="fg-row" style="margin-bottom:16px">
      <div>
        <label>{T('f_bank')}</label>
        <select name="bank" required>
          <option value="">{T('f_bank_ph')}</option>
          <option value="ICB">VietinBank</option>
          <option value="VCB">Vietcombank</option>
          <option value="MB">MBBank</option>
          <option value="TCB">Techcombank</option>
          <option value="ACB">ACB</option>
          <option value="BIDV">BIDV</option>
          <option value="VPB">VPBank</option>
          <option value="TPB">TPBank</option>
        </select>
      </div>
      <div>
        <label>{T("f_stk")}</label>
        <input type="text" name="stk" placeholder="{T('f_stk_ph')}" required>
      </div>
    </div>
    <div class="fg">
      <div style="font-size:11px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--text2);margin-bottom:7px">{T('f_type')}</div>
      <div class="toggle-row" onclick="document.getElementById('is_public').click()">
        <input type="checkbox" name="is_public" id="is_public" onclick="event.stopPropagation()">
        <span class="sw"></span>
        <div class="toggle-body">
          <div class="toggle-title">{T('f_public')}</div>
          <div class="toggle-desc">{T('f_public_desc')}</div>
        </div>
      </div>
    </div>
    {acct}
    <button class="btn" type="submit">{T("f_submit")}</button>
  </form>
</div>

<div class="feat reveal">
  <div class="feat-card">
    <span class="feat-icon">⚡</span>
    <div class="feat-title">{T('feat1_title')}</div>
    <div class="feat-desc">{T('feat1_desc')}</div>
  </div>
  <div class="feat-card">
    <span class="feat-icon">🔒</span>
    <div class="feat-title">{T('feat2_title')}</div>
    <div class="feat-desc">{T('feat2_desc')}</div>
  </div>
  <div class="feat-card">
    <span class="feat-icon">🌐</span>
    <div class="feat-title">{T('feat3_title')}</div>
    <div class="feat-desc">{T('feat3_desc')}</div>
  </div>
</div>"""
    return page(c, active='home')


@app.route('/dang-ky', methods=['GET', 'POST'])
def register_page():
    lang = get_lang()
    if current_user(): return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        confirm  = request.form.get('confirm', '')
        if not username or not password:
            flash('Vui lòng điền đầy đủ thông tin.', 'error'); return redirect(url_for('register_page'))
        if password != confirm:
            flash('Mật khẩu nhập lại không khớp.', 'error'); return redirect(url_for('register_page'))
        new_id = create_user(username, password)
        if new_id is None:
            flash(f'Tên "{username}" đã được sử dụng.', 'error'); return redirect(url_for('register_page'))
        session['user_id'] = new_id
        flash(f'Chào mừng, {username}!', 'success')
        return redirect(url_for('index'))

    c = f"""
<div class="auth-hero">
  <div class="auth-logo">Fund<span>y</span></div>
  <div class="auth-sub">Tạo tài khoản miễn phí — không cần email</div>
</div>
<div class="card">
  <form method="POST">
    <div class="fg"><label>{T('reg_username')}</label>
      <input type="text" name="username" placeholder="vd: lop12a1" required autofocus></div>
    <div class="fg"><label>{T('reg_password')}</label>
      <input type="password" name="password" placeholder="••••••••" required></div>
    <div class="fg"><label>{T('reg_confirm')}</label>
      <input type="password" name="confirm" placeholder="••••••••" required></div>
    <button class="btn" type="submit">{T('reg_submit')}</button>
  </form>
  <p class="fg-hint" style="text-align:center;margin-top:14px">
    Đã có tài khoản? <a href="/dang-nhap">Đăng nhập</a></p>
</div>"""
    return page(c, narrow=True)


@app.route('/dang-nhap', methods=['GET', 'POST'])
def login_page():
    lang = get_lang()
    if current_user(): return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = verify_user(username, password)
        if not user:
            flash('Tên đăng nhập hoặc mật khẩu không đúng.', 'error')
            return redirect(url_for('login_page'))
        session['user_id'] = user['id']
        flash(f'Xin chào, {user["username"]}!', 'success')
        return redirect(url_for('index'))

    c = f"""
<div class="auth-hero">
  <div class="auth-logo">Fund<span>y</span></div>
  <div class="auth-sub">{T('login_sub')}</div>
</div>
<div class="card">
  <form method="POST">
    <div class="fg"><label>Tên đăng nhập</label>
      <input type="text" name="username" placeholder="Tên đăng nhập" required autofocus></div>
    <div class="fg"><label>Mật khẩu</label>
      <input type="password" name="password" placeholder="••••••••" required></div>
    <button class="btn" type="submit">{T('login_submit')}</button>
  </form>
  <p class="fg-hint" style="text-align:center;margin-top:14px">
    Chưa có tài khoản? <a href="/dang-ky">Đăng ký</a></p>
</div>"""
    return page(c, narrow=True)


@app.route('/dang-xuat')
def logout_page():
    session.pop('user_id', None)
    flash('Đã đăng xuất.', 'success')
    return redirect(url_for('index'))


def _fund_row(fund, badge=None):
    icons = {'ICB':'🏦','VCB':'🏦','MB':'📱','TCB':'💙','ACB':'🟠','BIDV':'🔵','VPB':'🟢','TPB':'🔴'}
    icon = icons.get(fund['bank'], '💰')
    lang = get_lang()
    b = ''
    if badge == 'public': b = f'<span class="badge badge-blue">{T("badge_public")}</span>'
    elif badge == 'private': b = f'<span class="badge badge-gray">{T("badge_private")}</span>'
    return f"""<div class="fund-row">
  <div class="fund-avatar">{icon}</div>
  <div class="fund-info">
    <div class="fund-name">{fund['name']}</div>
    <div class="fund-meta">{fund['bank']} · {fund['stk']}</div>
  </div>
  {b}
  <a class="btn btn-sm ghost" href="/quy/{fund['fund_id']}">{T('btn_view')}</a>
</div>"""


@app.route('/quy-cong-dong')
def community_funds():
    lang = get_lang()
    funds = get_public_funds()
    rows = ''.join(_fund_row(f) for f in funds) if funds else \
        f'<div class="empty-state"><div class="empty-icon">🌐</div>{T("empty_community")}</div>'
    c = f"""
<div class="hero" style="padding-top:24px">
  <div class="hero-eyebrow">✦ Cộng đồng</div>
  <h1>{T('community_h1')}</h1>
  <p>{T('community_sub')}</p>
</div>
<div class="card">
  <div class="sh">
    <div class="sh-title">{T('community_active')}</div>
    <span class="sh-meta">{len(funds)} quỹ</span>
  </div>
  <div class="fund-list">{rows}</div>
</div>"""
    return page(c, active='community')


@app.route('/quy-cua-toi')
@login_required
def my_funds():
    lang = get_lang()
    user   = current_user()
    owned  = get_funds_by_owner(user['id'])
    shared = get_funds_shared_with(user['id'])

    o_rows = ''.join(_fund_row(f, badge='public' if f['is_public'] else 'private') for f in owned) if owned \
        else '<div class="empty-state"><div class="empty-icon">📭</div>Bạn chưa tạo quỹ nào.</div>'

    s_block = ''
    if shared:
        s_rows = ''.join(_fund_row(f, badge='public' if f['is_public'] else 'private') for f in shared)
        s_block = f"""<div class="card">
  <div class="sh"><div class="sh-title">{T('mine_shared')}</div>
    <span class="sh-meta">{len(shared)} quỹ</span></div>
  <div class="fund-list">{s_rows}</div>
</div>"""

    c = f"""
<div class="hero" style="padding-top:24px">
  <div class="hero-eyebrow">👤 {user['username']}</div>
  <h1>{T('mine_h1')}</h1>
  <p>{T('mine_sub')}</p>
</div>
<div class="card">
  <div class="sh">
    <div class="sh-title">{T('mine_yours')}</div>
    <span class="sh-meta">{len(owned)} {T('funds')}</span>
  </div>
  <div class="fund-list">{o_rows}</div>
</div>
{s_block}"""
    return page(c, active='mine')


@app.route('/quy/<fund_id>')
def view_fund(fund_id):
    lang = get_lang()
    fund = get_fund(fund_id)
    if not fund:
        return page('<div class="card"><div class="empty-state"><div class="empty-icon">🔍</div>Quỹ không tồn tại hoặc đường link đã hết hạn.</div></div>'), 404

    qr_url     = f"https://api.vietqr.io/image/{fund['bank']}-{fund['stk']}-compact.jpg?accountName={fund['name'].replace(' ','%20')}&addInfo=QUY{fund_id.upper()}"
    share_link = request.url_root.rstrip('/') + '/quy/' + fund_id

    ledger, total, count, bc_ok = [], 0, 0, True
    try:
        raw = contract.functions.getFundLedger(fund_id).call({"from": account_address})
        # Lấy event logs để có tx_hash thực tế cho từng giao dịch
        tx_hashes = []
        try:
            event_filter = contract.events.TransactionRecorded.create_filter(
                from_block=0,
                argument_filters={"fundId": fund_id}
            )
            events = event_filter.get_all_entries()
            tx_hashes = [e['transactionHash'].hex() for e in events]
        except Exception:
            tx_hashes = []

        for i, tx in enumerate(reversed(raw)):
            if tx[3]: total += tx[1]; count += 1
            # Map tx_hash: events và raw đều theo thứ tự thời gian
            rev_idx = len(raw) - 1 - i
            tx_hash = tx_hashes[rev_idx] if rev_idx < len(tx_hashes) else None
            ledger.append({"tx_id": tx[0], "amount": tx[1], "desc": tx[2],
                           "income": tx[3], "time": time.strftime('%d/%m %H:%M', time.localtime(tx[4])),
                           "tx_hash": tx_hash})
    except Exception as e:
        bc_ok = False; print(f"Lỗi blockchain: {e}")

    bc_badge   = f'<span class="badge badge-green"><span class="pulse"></span>{T("badge_live")}</span>' if bc_ok \
                 else f'<span class="badge badge-red">{T("badge_err")}</span>'
    priv_badge = f'<span class="badge badge-blue">{T("badge_public")}</span>' if fund['is_public'] \
                 else f'<span class="badge badge-gray">{T("badge_private")}</span>'

    invite_block = ''
    user = current_user()
    if user and fund['owner_id'] == user['id'] and not fund['is_public']:
        members    = get_fund_members(fund_id)
        chips      = ''.join(f'<span class="chip">👤 {m["username"]}</span>' for m in members) or \
                     f'<span style="font-size:11px;color:var(--text3)">{T("invite_none")}</span>'
        invite_block = f"""<div class="invite-box">
  <div class="invite-title">{T('invite_title')}</div>
  <form class="invite-form" method="POST" action="/quy/{fund_id}/moi">
    <input type="text" name="username" placeholder="{T('invite_ph')}" required>
    <button class="btn btn-sm" type="submit">{T('invite_btn')}</button>
  </form>
  <div class="member-chips">{chips}</div>
</div>"""

    EXPLORER = "https://amoy.polygonscan.com"

    def proof_btn(t):
        """Nút mở modal verify cho từng giao dịch."""
        h = t.get('tx_hash') or ''
        # escape for JS string
        h_safe = h.replace("'", "\\'")
        amount_fmt = f"{'+' if t['income'] else '-'}{t['amount']:,}d"
        desc_safe  = (t['desc'] or '').replace("'", "\\'").replace('"', '&quot;')
        time_safe  = t['time'].replace("'", "\\'")
        txid_safe  = (t['tx_id'] or '').replace("'", "\\'")
        return (
            f"<button class='verify-btn' onclick=\"openVerify('{h_safe}','{amount_fmt}',"
            f"'{desc_safe}','{time_safe}','{txid_safe}')\">"
            "<svg width='11' height='11' viewBox='0 0 12 12' fill='none'>"
            "<path d='M6 1v5M6 9v1' stroke='currentColor' stroke-width='1.5' stroke-linecap='round'/>"
            "<circle cx='6' cy='6' r='5' stroke='currentColor' stroke-width='1.2' fill='none'/>"
            "</svg> " + T("verify_btn") + "</button>"
        )

    if ledger:
        rows = "".join(
            "<tr>"
            f"<td style='color:var(--text3);font-size:11px;white-space:nowrap'>{t['time']}</td>"
            f"<td><span class='tx-id'>{t['tx_id'] or '—'}</span></td>"
            f"<td class=\"{'amount-in' if t['income'] else 'amount-out'}\">{'+' if t['income'] else '−'}{t['amount']:,}đ</td>"
            f"<td style='color:var(--text2);font-size:12px;max-width:140px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap'>{t['desc']}</td>"
            f"<td>{proof_btn(t)}</td>"
            "</tr>"
            for t in ledger
        )
    else:
        rows = f'<tr><td colspan="5"><div class="empty-state"><div class="empty-icon">📭</div>{T("ledger_empty")}</div></td></tr>' 

    # ── Build Sankey data ─────────────────────────────────────────
    expenses = get_expenses(fund_id)
    total_expense = sum(e['amount'] for e in expenses)
    total_in      = total      # already computed
    net_balance   = total_in - total_expense

    # Detect cross-fund transfers from description (format: #fundid in desc)
    import re as _re
    fund_transfers = {}  # {to_fund_id: amount}
    for e in expenses:
        if e.get('to_fund'):
            fid = e['to_fund'].strip()
            fund_transfers[fid] = fund_transfers.get(fid, 0) + e['amount']

    # Build top senders from ledger (group by tx_id prefix as "person")
    sender_totals = {}
    for t in ledger:
        if t['income']:
            key = (t['tx_id'] or 'Ẩn danh')[:12] if t['tx_id'] else t['desc'][:14] or 'Ẩn danh'
            sender_totals[key] = sender_totals.get(key, 0) + t['amount']

    # JSON for Sankey — nodes + links
    import json as _json

    sankey_nodes = []
    sankey_links = []

    node_idx = {}
    def nidx(name):
        if name not in node_idx:
            node_idx[name] = len(sankey_nodes)
            sankey_nodes.append({"name": name})
        return node_idx[name]

    FUND_NODE = fund['name'][:28]
    nidx(FUND_NODE)

    for sender, amt in sorted(sender_totals.items(), key=lambda x: -x[1])[:8]:
        if amt > 0:
            label = sender if len(sender) <= 16 else sender[:14] + '…'
            sankey_links.append({"source": nidx(label), "target": nidx(FUND_NODE), "value": amt, "type": "income"})

    if total_expense > 0:
        EXPENSE_NODE = "Chi tiêu"
        for e in expenses[:6]:
            label = e['desc'][:16] + ('…' if len(e['desc']) > 16 else '')
            sankey_links.append({"source": nidx(FUND_NODE), "target": nidx(label + " "), "value": e['amount'], "type": "expense"})

    for to_fid, amt in fund_transfers.items():
        dest_fund = get_fund(to_fid)
        dest_name = (dest_fund['name'][:20] if dest_fund else f'Quỹ #{to_fid}') + ' →'
        sankey_links.append({"source": nidx(FUND_NODE), "target": nidx(dest_name), "value": amt, "type": "transfer"})

    sankey_data = _json.dumps({"nodes": sankey_nodes, "links": sankey_links})

    # ── Owner-only: public fund list for expense transfer target ───
    all_public_funds = [f for f in get_public_funds() if f['fund_id'] != fund_id] if (user and fund.get('owner_id') == (user['id'] if user else None)) else []

    # ── Expense form block (owner only) ────────────────────────────
    expense_block = ''
    if user and fund.get('owner_id') == user['id']:
        fund_opts = ''.join(f'<option value="{f["fund_id"]}">{f["name"][:30]}</option>' for f in all_public_funds)
        expense_block = f"""
<div class="expense-section reveal">
  <div class="sh">
    <div class="sh-title">💸 Ghi chi tiêu</div>
    <span class="sh-meta">{len(expenses)} khoản chi</span>
  </div>
  <form class="expense-form" method="POST" action="/quy/{fund_id}/chi">
    <div>
      <label>Số tiền (đ)</label>
      <input type="number" name="amount" placeholder="200000" min="1" required>
    </div>
    <div>
      <label>Mô tả chi tiêu</label>
      <input type="text" name="desc" placeholder="Mua vật phẩm, trang trí..." required>
    </div>
    <div>
      <label>Chuyển sang quỹ</label>
      <select name="to_fund">
        <option value="">— Không (chi tiêu thường) —</option>
        {fund_opts}
      </select>
    </div>
    <button class="btn" type="submit" style="align-self:end">Ghi →</button>
  </form>
  {'<div class="expense-list">' + ''.join(
    f'<div class="expense-row anim-slide-right"><span class="expense-amount">−{e["amount"]:,}đ</span>'
    f'<span class="expense-desc">{e["desc"]}</span>'
    + (f'<span class="expense-arrow">→ Quỹ #{e["to_fund"]}</span>' if e.get("to_fund") else '')
    + f'<span class="expense-time">{e["time"]}</span></div>'
    for e in expenses
  ) + '</div>' if expenses else '<p style="font-size:12px;color:var(--text3);margin-top:8px">Chưa có khoản chi nào.</p>'}
</div>"""

    c = f"""
<div class="card anim-fade-up">
  <div style="display:flex;align-items:flex-start;justify-content:space-between;flex-wrap:wrap;gap:10px;margin-bottom:16px">
    <div style="display:flex;gap:6px;flex-wrap:wrap">{bc_badge} {priv_badge}</div>
    <span style="font-family:'SFMono-Regular','Consolas','Liberation Mono',monospace;font-size:11px;color:var(--text3)">#{fund_id}</span>
  </div>
  <h2 style="font-size:22px;font-weight:700;letter-spacing:-.02em;margin-bottom:4px">{fund['name']}</h2>
  <p style="font-family:'SFMono-Regular','Consolas','Liberation Mono',monospace;font-size:12px;color:var(--text3);margin-bottom:20px">{fund['bank']} · {fund['stk']}</p>

  <div class="stats" style="grid-template-columns:repeat(3,1fr)">
    <div class="stat anim-count d1">
      <div class="stat-label">{T('stat_total')}</div>
      <div class="stat-val" data-count="{total}" data-suffix="đ">{total:,}<span class="stat-unit">đ</span></div>
    </div>
    <div class="stat anim-count d2">
      <div class="stat-label">Đã chi</div>
      <div class="stat-val" style="color:var(--red)" data-count="{total_expense}" data-suffix="đ">{total_expense:,}<span class="stat-unit">đ</span></div>
    </div>
    <div class="stat anim-count d3">
      <div class="stat-label">Còn lại</div>
      <div class="stat-val" style="color:{'var(--green)' if net_balance>=0 else 'var(--red)'}"
           data-count="{abs(net_balance)}" data-suffix="đ">{'−' if net_balance<0 else ''}{abs(net_balance):,}<span class="stat-unit">đ</span></div>
    </div>
  </div>

  <div class="divider"></div>

  <div class="fg" style="margin-bottom:0">
    <label>{T('link_public') if fund['is_public'] else T('link_private')}</label>
    <div class="share-box">
      <span class="share-url">{share_link}</span>
      <button class="copy-btn" onclick="copyLink('{share_link}')">{T('copy_btn')}</button>
    </div>
  </div>
  {invite_block}
  <div class="notice" style="margin-top:14px">
    <span>⏳</span> {T('notice_pending')}
  </div>
</div>


{expense_block}

<!-- SANKEY DIAGRAM -->
<div class="sankey-wrap reveal" id="sankeyWrap" style="display:{'none' if not sankey_links else 'block'}">
  <div class="sankey-title">📊 Sơ đồ dòng tiền</div>
  <div class="sankey-sub">Trực quan hoá luồng thu · chi · chuyển quỹ</div>
  <svg id="sankeyChart" height="260"></svg>
  <div class="sankey-legend">
    <span class="sankey-legend-item"><span class="sankey-dot" style="background:#22d4a0"></span>Tiền vào</span>
    <span class="sankey-legend-item"><span class="sankey-dot" style="background:#f06292"></span>Chi tiêu</span>
    <span class="sankey-legend-item"><span class="sankey-dot" style="background:#5b9cf6"></span>Chuyển quỹ</span>
  </div>
</div>
<div class="sankey-tooltip" id="sankeyTip"></div>

<script src="https://cdn.jsdelivr.net/npm/d3@7.8.5/dist/d3.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/d3-sankey@0.12.3/dist/d3-sankey.min.js"></script>
<script>
(function(){{
  var raw = {sankey_data};
  if(!raw.links || !raw.links.length) return;

  var container = document.getElementById('sankeyWrap');
  if(!container) return;

  var W = container.clientWidth - 40;
  var H = 260;
  var svg = d3.select('#sankeyChart').attr('viewBox','0 0 '+W+' '+H);
  var tip = document.getElementById('sankeyTip');

  var sankey = d3.sankey()
    .nodeWidth(14)
    .nodePadding(14)
    .extent([[10,10],[W-10,H-10]]);

  // Deep-copy to avoid mutation
  var graph = JSON.parse(JSON.stringify(raw));
  sankey(graph);

  var colorMap = {{
    income:   '#22d4a0',
    expense:  '#f06292',
    transfer: '#5b9cf6',
  }};

  // Draw links
  svg.append('g').selectAll('path')
    .data(graph.links).enter().append('path')
    .attr('d', d3.sankeyLinkHorizontal())
    .attr('fill','none')
    .attr('stroke', d => colorMap[d.type] || '#5b9cf6')
    .attr('stroke-width', d => Math.max(1.5, d.width))
    .attr('stroke-opacity', .32)
    .attr('class','sankey-link')
    .style('cursor','pointer')
    .on('mouseover', function(event, d){{
      d3.select(this).attr('stroke-opacity',.65);
      var fmt = new Intl.NumberFormat('vi-VN').format(d.value);
      tip.style.opacity=1;
      tip.innerHTML = '<strong>' + d.source.name + '</strong> → <strong>' + d.target.name + '</strong><br>' + fmt + 'đ';
    }})
    .on('mousemove', function(event){{
      tip.style.left=(event.clientX+12)+'px';
      tip.style.top=(event.clientY-36)+'px';
    }})
    .on('mouseout', function(){{
      d3.select(this).attr('stroke-opacity',.32);
      tip.style.opacity=0;
    }});

  // Draw nodes
  var nodeG = svg.append('g').selectAll('g')
    .data(graph.nodes).enter().append('g');

  nodeG.append('rect')
    .attr('x', d=>d.x0).attr('y', d=>d.y0)
    .attr('width', d=>d.x1-d.x0)
    .attr('height', d=>Math.max(4,d.y1-d.y0))
    .attr('rx',3).attr('ry',3)
    .attr('fill', d=>{{
      var isSource=graph.links.some(l=>l.target===d && l.type==='income');
      var isDest=graph.links.some(l=>l.source===d && l.type==='expense');
      var isTransfer=graph.links.some(l=>l.source===d && l.type==='transfer');
      if(isDest||isTransfer) return '#5b9cf6';
      if(isSource) return '#22d4a0';
      return '#f5c842';
    }})
    .attr('opacity',.9)
    .on('mouseover',function(event,d){{
      var fmt=new Intl.NumberFormat('vi-VN').format(d.value||0);
      tip.style.opacity=1;
      tip.innerHTML='<strong>'+d.name+'</strong><br>'+fmt+'đ';
    }})
    .on('mousemove',function(event){{tip.style.left=(event.clientX+12)+'px';tip.style.top=(event.clientY-36)+'px';}})
    .on('mouseout',function(){{tip.style.opacity=0;}});

  // Labels
  nodeG.append('text')
    .attr('x', d=> d.x0 < W/2 ? d.x1+6 : d.x0-6)
    .attr('y', d=> (d.y0+d.y1)/2)
    .attr('dy','0.35em')
    .attr('text-anchor', d=> d.x0 < W/2 ? 'start' : 'end')
    .attr('font-size','10px')
    .attr('font-family','system-ui,sans-serif')
    .attr('fill','#8888a8')
    .text(d=>d.name.length>18?d.name.slice(0,17)+'…':d.name);

  // Animate links on load
  svg.selectAll('.sankey-link')
    .attr('stroke-dasharray',function(){{return this.getTotalLength()+' '+this.getTotalLength();}} )
    .attr('stroke-dashoffset',function(){{return this.getTotalLength();}})
    .transition().duration(900).ease(d3.easeQuadOut)
    .attr('stroke-dashoffset',0)
    .attr('stroke-opacity',.32);
}})();
</script>

<div class="qr-section reveal">
  <div class="sh-title">{T('qr_title')}</div>
  <p style="font-size:13px;color:var(--text3);margin-top:6px">{T('qr_sub')}</p>
  <div class="qr-frame">
    <img src="{qr_url}" alt="VietQR"
      onerror="this.parentElement.innerHTML='<span style=color:#aaa;font-size:13px;padding:60px>QR không tải được</span>'">
  </div>
  <div style="font-family:'SFMono-Regular','Consolas','Liberation Mono',monospace;font-size:12px;color:var(--text3)">{fund['bank']} · {fund['stk']}</div>
</div>

<div class="card reveal">
  <div class="sh">
    <div class="sh-title">{T('ledger_title')}</div>
    <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
      <span class="sh-meta">{len(ledger)} {T('records')}</span>
      <a class="proof-link" href="https://amoy.polygonscan.com/address/{CONTRACT_ADDRESS}#events"
         target="_blank" rel="noopener" style="font-size:10px">
        <svg width="10" height="10" viewBox="0 0 12 12" fill="none">
          <path d="M2 10L10 2M10 2H5M10 2V7" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
        </svg>Xem toàn bộ trên Polygonscan ↗
      </a>
    </div>
  </div>
  <div class="tbl-wrap">
    <table>
      <thead><tr><th>{T('th_time')}</th><th>{T('th_txid')}</th><th>{T('th_amount')}</th><th>{T('th_desc')}</th><th>{T('th_verify')}</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </div>
</div>

<!-- MODAL KIỂM CHỨNG BLOCKCHAIN -->
<div class="modal-backdrop" id="verifyModal" onclick="if(event.target===this)closeVerify()">
  <div class="modal">
    <div class="modal-head">
      <div class="modal-title">{T('modal_title')}</div>
      <button class="modal-close" onclick="closeVerify()">✕</button>
    </div>
    <div class="modal-body">
      <div class="modal-intro">
        <strong>{T('modal_intro_b')}</strong> {T('modal_intro')}
      </div>

      <div class="steps">

        <div class="step">
          <div class="step-num">1</div>
          <div class="step-body">
            <div class="step-title">{T('step1_title')}</div>
            <div class="step-desc">{T('step1_desc')}</div>
            <div>
              <a id="modal-explorer-link" href="#" target="_blank" rel="noopener"
                 style="display:inline-flex;align-items:center;gap:5px;margin-top:8px;font-size:12px;font-weight:600;color:var(--blue)">
                <svg width="11" height="11" viewBox="0 0 12 12" fill="none">
                  <path d="M2 10L10 2M10 2H5M10 2V7" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
                </svg>{T('step1_link')}
              </a>
            </div>
          </div>
        </div>

        <div class="step">
          <div class="step-num">2</div>
          <div class="step-body">
            <div class="step-title">{T('step2_title')} <strong style="color:var(--text)">{fund['name']}</strong></div>
            <div class="step-desc">{T('step2_desc')}</div>
            <div class="step-check">
              <div class="check-item">
                <span class="check-icon">✓</span>
                <div>
                  <div style="font-size:11px;color:var(--text3);margin-bottom:2px">{T('step2_contract')}</div>
                  <span class="step-code">{CONTRACT_ADDRESS}</span>
                </div>
              </div>
              <div class="check-item">
                <span class="check-icon">✓</span>
                <div>
                  <div style="font-size:11px;color:var(--text3);margin-bottom:2px">{T('step2_fundid')}</div>
                  <span class="step-code">{fund_id}</span>
                </div>
              </div>
              <div class="check-item">
                <span class="check-icon">✓</span>
                <div>
                  <div style="font-size:11px;color:var(--text3);margin-bottom:2px">{T('step2_amount')}</div>
                  <span class="step-code" id="modal-amount"></span>
                </div>
              </div>
              <div class="check-item">
                <span class="check-icon">✓</span>
                <div>
                  <div style="font-size:11px;color:var(--text3);margin-bottom:2px">{T('step2_desc2')}</div>
                  <span class="step-code" id="modal-desc"></span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="step">
          <div class="step-num">3</div>
          <div class="step-body">
            <div class="step-title">{T('step3_title')}</div>
            <div class="step-desc">{T('step3_desc')}</div>
          </div>
        </div>

      </div><!-- /steps -->

      <div class="modal-cta">
        <a id="modal-cta-link" href="#" target="_blank" rel="noopener">
          <button class="btn btn-sm" style="width:100%;justify-content:center">
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none" style="margin-right:5px">
              <path d="M2 10L10 2M10 2H5M10 2V7" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
            </svg>{T('modal_open')}
          </button>
        </a>
        <button class="btn btn-sm ghost" onclick="closeVerify()" style="flex:0 0 auto">{T('modal_close')}</button>
      </div>
    </div>
  </div>
</div>

<script>
function openVerify(txHash, amount, desc, time, txId) {{
  var modal = document.getElementById('verifyModal');
  var EXPLORER = 'https://amoy.polygonscan.com';
  var CONTRACT = '{CONTRACT_ADDRESS}';
  var url = txHash ? (EXPLORER + '/tx/' + txHash) : (EXPLORER + '/address/' + CONTRACT + '#events');
  document.getElementById('modal-explorer-link').href = url;
  document.getElementById('modal-cta-link').href = url;
  document.getElementById('modal-amount').textContent = amount;
  document.getElementById('modal-desc').textContent = desc || '(không có nội dung)';
  modal.classList.add('open');
  document.body.style.overflow = 'hidden';
}}
function closeVerify() {{
  document.getElementById('verifyModal').classList.remove('open');
  document.body.style.overflow = '';
}}
document.addEventListener('keydown', function(e) {{
  if (e.key === 'Escape') closeVerify();
}});
</script>

<p class="footer-note">{T('footer_note')}</p>"""
    return page(c)


@app.route('/quy/<fund_id>/chi', methods=['POST'])
@login_required
def add_expense_route(fund_id):
    fund = get_fund(fund_id)
    user = current_user()
    if not fund or fund.get('owner_id') != user['id']:
        flash('Chỉ chủ quỹ mới có thể ghi chi tiêu.', 'error')
        return redirect(url_for('view_fund', fund_id=fund_id))
    try:
        amount  = int(request.form.get('amount', 0))
        desc    = request.form.get('desc', '').strip()
        to_fund = request.form.get('to_fund', '').strip() or None
        if amount <= 0 or not desc:
            flash('Vui lòng nhập đủ số tiền và mô tả.', 'error')
            return redirect(url_for('view_fund', fund_id=fund_id))
        add_expense(fund_id, amount, desc, to_fund, user['id'])
        flash(f'Đã ghi chi tiêu {amount:,}đ — {desc}.', 'success')
    except (ValueError, TypeError):
        flash('Số tiền không hợp lệ.', 'error')
    return redirect(url_for('view_fund', fund_id=fund_id))


@app.route('/quy/<fund_id>/moi', methods=['POST'])
@login_required
def invite_member(fund_id):
    fund = get_fund(fund_id)
    user = current_user()
    if not fund or fund['owner_id'] != user['id']:
        flash('Bạn không có quyền mời thành viên cho quỹ này.', 'error')
        return redirect(url_for('view_fund', fund_id=fund_id))
    username = request.form.get('username', '').strip()
    target   = get_user_by_username(username)
    if not target:
        flash(f'Không tìm thấy tài khoản "{username}".', 'error')
    else:
        add_fund_member(fund_id, target['id'])
        flash(f'Đã mời "{username}" xem quỹ này.', 'success')
    return redirect(url_for('view_fund', fund_id=fund_id))


@app.route('/webhook', methods=['POST'])
def webhook():
    if SEPAY_TOKEN:
        if request.headers.get('Authorization', '') != f'Apikey {SEPAY_TOKEN}':
            return jsonify({"status": "unauthorized"}), 401
    data = request.json
    if not data: return jsonify({"status": "error"}), 400

    amount     = int(data.get('transferAmount', 0))
    content    = data.get('content', '')
    bank_tx_id = data.get('referenceCode', '')
    to_stk     = data.get('toAccountNumber', data.get('accountNumber', ''))

    print(f"📨 Webhook: {amount}đ | STK: {to_stk} | {content}")

    fund = get_fund_by_stk(to_stk) if to_stk else None
    if not fund: fund = get_latest_fund()
    if not fund: return jsonify({"status": "no_fund"}), 200

    threading.Thread(target=send_record_tx, args=(fund['fund_id'], bank_tx_id, amount, content), daemon=True).start()
    return jsonify({"status": "success", "fund_id": fund['fund_id']}), 200


if __name__ == '__main__':
    print(f"🔗 Ví: {account_address}")
    print(f"📡 Polygon: {w3.is_connected()}")
    print(f"💾 DB: {DB_PATH}")
    app.run(port=5000, debug=True)