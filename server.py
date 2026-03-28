"""
Talib-Awn · طالب عون — Flask Backend + Static Server
Serves static HTML/CSS/JS files AND /api/* routes on port 5000.
Database: MySQL (Railway)
"""

import os, bcrypt, random, string, time, smtplib, threading
from datetime import timedelta, datetime, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from urllib.parse import urlparse
import pymysql, pymysql.cursors
from flask import Flask, request, jsonify, send_from_directory, send_file
from flask_jwt_extended import (
    JWTManager, create_access_token, create_refresh_token,
    jwt_required, get_jwt_identity, verify_jwt_in_request
)
from flask_cors import CORS

# ── App setup ───────────────────────────────────────────────────────────────
app = Flask(__name__)
app.config['JWT_SECRET_KEY'] = os.environ.get('JWT_SECRET_KEY', 'talib-awn-secret-key-dev-2026')
app.config['JWT_ACCESS_TOKEN_EXPIRES']  = timedelta(hours=8)
app.config['JWT_REFRESH_TOKEN_EXPIRES'] = timedelta(days=30)
CORS(app, supports_credentials=True, origins=["http://talib-awn.up.railway.app", "https://talib-awn.up.railway.app", "http://localhost:5000", "http://127.0.0.1:5000"])
jwt = JWTManager(app)

# ── Email config ─────────────────────────────────────────────────────────────
GMAIL_ADDRESS   = os.environ.get('GMAIL_ADDRESS',  'universitychlefclub@gmail.com')
GMAIL_APP_PASS  = os.environ.get('GMAIL_APP_PASS', 'rqki cvlk iqgr smdj')
PLATFORM_NAME   = 'طالب عون | Talib Awn'
LOGO_URL        = 'https://images.cdn-files-a.com/uploads/1598328/800_5bd38322bcdfd.jpg'
OTP_EXPIRY_SEC  = 120   # 2 minutes

# ── In-memory OTP stores ─────────────────────────────────────────────────────
_pending_registrations = {}   # email -> {data, otp, sent_at}
_pending_resets        = {}   # email -> {otp, sent_at, verified}
_pending_login_otps    = {}   # email -> {otp, sent_at}

# ── DB connection ────────────────────────────────────────────────────────────
def get_db():
    db_url = os.environ.get('RAILWAY_DATABASE_URL') or os.environ.get('DATABASE_URL')
    if db_url:
        parsed = urlparse(db_url)
        return pymysql.connect(
            host=parsed.hostname,
            port=parsed.port or 3306,
            user=parsed.username,
            password=parsed.password,
            database=parsed.path.lstrip('/'),
            cursorclass=pymysql.cursors.DictCursor,
            charset='utf8mb4',
            autocommit=False,
        )
    return pymysql.connect(
        host=os.environ.get('DBHOST', 'localhost'),
        port=int(os.environ.get('DBPORT', 3306)),
        user=os.environ.get('DBUSER', 'root'),
        password=os.environ.get('DBPASSWORD', ''),
        database=os.environ.get('DBNAME', 'talibawn'),
        cursorclass=pymysql.cursors.DictCursor,
        charset='utf8mb4',
        autocommit=False,
    )


def db_query(sql, params=(), fetchone=False, fetchall=False, commit=False):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        result = None
        if fetchone:  result = cur.fetchone()
        if fetchall:  result = cur.fetchall()
        if commit:    conn.commit()
        return result
    finally:
        conn.close()


def db_insert(sql, params, table):
    """Execute an INSERT and return the newly inserted row as a dict."""
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        new_id = cur.lastrowid
        conn.commit()
        cur.execute(f'SELECT * FROM `{table}` WHERE id=%s', (new_id,))
        return cur.fetchone()
    finally:
        conn.close()


# ── Helpers ──────────────────────────────────────────────────────────────────
def ok(data=None, **kwargs):
    r = {'ok': True}
    if data is not None: r['data'] = data
    r.update(kwargs)
    return jsonify(r)

def err(msg, code=400):
    return jsonify({'ok': False, 'error': msg}), code

def otp_code():
    return ''.join(random.choices(string.digits, k=6))

def hash_pw(pw):  return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()
def check_pw(pw, h): return bcrypt.checkpw(pw.encode(), h.encode())

def row_to_dict(row):
    if row is None: return None
    d = dict(row)
    for k, v in d.items():
        if isinstance(v, datetime): d[k] = v.isoformat()
    return d

def rows_to_list(rows):
    return [row_to_dict(r) for r in rows] if rows else []

def _send_email(to_email, subject, html):
    """Send an HTML email via Gmail SMTP (runs in background thread)."""
    def _send():
        try:
            msg = MIMEMultipart('alternative')
            msg['From']    = f'{PLATFORM_NAME} <{GMAIL_ADDRESS}>'
            msg['To']      = to_email
            msg['Subject'] = subject
            msg.attach(MIMEText(html, 'html'))
            with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
                server.login(GMAIL_ADDRESS, GMAIL_APP_PASS)
                server.sendmail(GMAIL_ADDRESS, to_email, msg.as_string())
        except Exception as e:
            print(f'[EMAIL ERROR] {to_email}: {e}')
    threading.Thread(target=_send, daemon=True).start()

# ── Email templates ───────────────────────────────────────────────────────────
def _otp_html(otp, expiry_min=2, is_reset=False):
    accent  = '#c0392b' if is_reset else '#6c3dab'
    header  = 'إعادة تعيين كلمة المرور' if is_reset else 'التحقق من البريد الإلكتروني'
    sub     = 'استخدم الرمز أدناه لإعادة تعيين كلمة مرورك.' if is_reset else 'استخدم الرمز أدناه لإتمام التسجيل.'
    digits  = ''.join(
        f'<td style="padding:0 4px;"><div style="width:48px;height:60px;background:#fff;'
        f'border:2px solid {accent};border-radius:10px;font-family:Courier New,monospace;'
        f'font-size:28px;font-weight:700;color:{accent};text-align:center;line-height:60px;">'
        f'{ch}</div></td>'
        for ch in otp
    )
    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"/></head>
<body style="margin:0;padding:0;background:#f5f3ff;font-family:Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f5f3ff;padding:36px 16px;">
<tr><td align="center">
<table width="520" cellpadding="0" cellspacing="0"
       style="background:#fff;border-radius:18px;overflow:hidden;box-shadow:0 6px 32px rgba(0,0,0,0.09);">
  <tr><td style="background:linear-gradient(135deg,#6c3dab,#4a2080);padding:40px;text-align:center;">
    <img src="{LOGO_URL}" width="72" height="72"
         style="border-radius:14px;border:3px solid rgba(255,255,255,0.22);
                object-fit:cover;display:block;margin:0 auto 16px;"/>
    <h1 style="margin:0;color:#fff;font-size:24px;font-weight:700;">{header}</h1>
    <p style="margin:8px 0 0;color:rgba(255,255,255,0.65);font-size:13px;">{PLATFORM_NAME}</p>
  </td></tr>
  <tr><td style="padding:44px;text-align:center;">
    <p style="font-size:15px;color:#555;margin:0 0 24px;line-height:1.7;">{sub}<br/>
      ينتهي هذا الرمز خلال <strong style="color:{accent};">{expiry_min} دقيقتين</strong>.
    </p>
    <div style="background:#f5f3ff;border:2px dashed {accent};border-radius:14px;padding:28px 20px;margin:0 0 24px;">
      <p style="margin:0 0 14px;font-size:11px;letter-spacing:0.14em;text-transform:uppercase;color:#999;">رمز التحقق</p>
      <table cellpadding="0" cellspacing="0" style="margin:0 auto;"><tr>{digits}</tr></table>
    </div>
    <div style="background:#fff8e6;border:1px solid #f0c040;border-radius:9px;padding:11px 18px;margin-bottom:24px;">
      <p style="margin:0;font-size:12px;color:#a07820;">⏰ لا تشارك هذا الرمز مع أي شخص.</p>
    </div>
    <p style="font-size:12px;color:#ccc;margin:0;">إذا لم تطلب هذا الرمز، يمكنك تجاهل هذا البريد.</p>
  </td></tr>
  <tr><td style="background:#f8f6ff;padding:22px;text-align:center;border-top:1px solid #ede9f5;">
    <p style="font-size:11px;color:#bbb;margin:0;">© 2026 {PLATFORM_NAME} · الجزائر</p>
  </td></tr>
</table></td></tr></table></body></html>"""


def _invite_html(to_name):
    greeting = f'مرحباً {to_name}،' if to_name else 'مرحباً،'
    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"/></head>
<body style="margin:0;padding:0;background:#f5f3ff;font-family:Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f5f3ff;padding:36px 16px;">
<tr><td align="center">
<table width="560" cellpadding="0" cellspacing="0"
       style="background:#fff;border-radius:18px;overflow:hidden;box-shadow:0 6px 32px rgba(0,0,0,0.09);">
  <tr><td style="background:linear-gradient(135deg,#6c3dab,#4a2080);padding:44px;text-align:center;">
    <img src="{LOGO_URL}" width="80" height="80"
         style="border-radius:16px;border:3px solid rgba(255,255,255,0.22);
                object-fit:cover;display:block;margin:0 auto 18px;"/>
    <div style="display:inline-block;background:rgba(212,168,67,0.2);border:1px solid rgba(212,168,67,0.5);
                border-radius:100px;padding:4px 16px;font-size:11px;letter-spacing:0.14em;
                color:#d4a843;margin-bottom:14px;">دعوة خاصة</div>
    <h1 style="margin:0;color:#fff;font-size:30px;font-weight:700;">أنت مدعو!</h1>
  </td></tr>
  <tr><td style="padding:44px;">
    <p style="font-size:15px;color:#555;margin:0 0 16px;">{greeting}</p>
    <p style="font-size:15px;color:#444;line-height:1.8;margin:0 0 32px;">
      يسعدنا دعوتك للانضمام إلى منصة
      <strong style="color:#6c3dab;">{PLATFORM_NAME}</strong> —
      المنصة المتخصصة في ربط طلاب الجامعات الجزائرية بفرص العمل الجزئي.
    </p>
    <div style="text-align:center;margin:0 0 32px;">
      <a href="#" style="display:inline-block;background:linear-gradient(135deg,#6c3dab,#4a2080);
                          color:#fff;text-decoration:none;padding:16px 48px;border-radius:12px;
                          font-weight:700;font-size:14px;letter-spacing:0.06em;">
        انضم الآن ←
      </a>
    </div>
    <p style="font-size:11px;color:#ccc;text-align:center;margin:0;">
      تمت إرسال هذه الدعوة من فريق {PLATFORM_NAME}
    </p>
  </td></tr>
  <tr><td style="background:#f8f6ff;padding:22px;text-align:center;border-top:1px solid #ede9f5;">
    <p style="font-size:11px;color:#bbb;margin:0;">© 2026 {PLATFORM_NAME} · الجزائر</p>
  </td></tr>
</table></td></tr></table></body></html>"""


# ── Initialise DB schema ─────────────────────────────────────────────────────
def init_db():
    conn = get_db()
    cur  = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id            INT AUTO_INCREMENT PRIMARY KEY,
        email         VARCHAR(255) UNIQUE NOT NULL,
        phone         VARCHAR(30),
        password_hash TEXT NOT NULL,
        name          VARCHAR(255),
        role          VARCHAR(20) DEFAULT 'student',
        grade         VARCHAR(100),
        wilaya        VARCHAR(100),
        university    VARCHAR(255),
        speciality    VARCHAR(255),
        bio           TEXT,
        skills        TEXT,
        avatar_url    TEXT,
        verified      TINYINT(1) DEFAULT 0,
        is_banned     TINYINT(1) DEFAULT 0,
        ban_reason    TEXT,
        otp           VARCHAR(10),
        otp_expires   DATETIME,
        refresh_token TEXT,
        created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS jobs (
        id              INT AUTO_INCREMENT PRIMARY KEY,
        employer_id     INT,
        title           VARCHAR(255) NOT NULL,
        description     TEXT,
        category        VARCHAR(100),
        wilaya          VARCHAR(100),
        work_type       VARCHAR(50) DEFAULT 'partial',
        daily_salary    DECIMAL(10,2),
        required_skills TEXT,
        status          VARCHAR(20) DEFAULT 'open',
        created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (employer_id) REFERENCES users(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS applications (
        id           INT AUTO_INCREMENT PRIMARY KEY,
        job_id       INT,
        student_id   INT,
        status       VARCHAR(30) DEFAULT 'pending',
        cover_letter TEXT,
        created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY uq_app (job_id, student_id),
        FOREIGN KEY (job_id)     REFERENCES jobs(id)  ON DELETE CASCADE,
        FOREIGN KEY (student_id) REFERENCES users(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS conversations (
        id          INT AUTO_INCREMENT PRIMARY KEY,
        employer_id INT,
        student_id  INT,
        job_id      INT,
        created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (employer_id) REFERENCES users(id),
        FOREIGN KEY (student_id)  REFERENCES users(id),
        FOREIGN KEY (job_id)      REFERENCES jobs(id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS messages (
        id              INT AUTO_INCREMENT PRIMARY KEY,
        conversation_id INT,
        sender_id       INT,
        content         TEXT,
        msg_type        VARCHAR(30) DEFAULT 'text',
        created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
        FOREIGN KEY (sender_id)       REFERENCES users(id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS deals (
        id                 INT AUTO_INCREMENT PRIMARY KEY,
        conversation_id    INT,
        employer_id        INT,
        student_id         INT,
        daily_salary       DECIMAL(10,2) DEFAULT 1000,
        duration_months    INT DEFAULT 1,
        start_date         DATE,
        payment_date       INT DEFAULT 15,
        instructions       TEXT,
        status             VARCHAR(40) DEFAULT 'idle',
        employer_confirmed TINYINT(1) DEFAULT 0,
        student_confirmed  TINYINT(1) DEFAULT 0,
        deposit_deadline   DATETIME,
        created_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
        FOREIGN KEY (employer_id)     REFERENCES users(id),
        FOREIGN KEY (student_id)      REFERENCES users(id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS payments (
        id           INT AUTO_INCREMENT PRIMARY KEY,
        deal_id      INT,
        month_number INT NOT NULL,
        amount       DECIMAL(10,2),
        fee          DECIMAL(10,2),
        status       VARCHAR(30) DEFAULT 'pending',
        paid_at      DATETIME,
        created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (deal_id) REFERENCES deals(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS ratings (
        id         INT AUTO_INCREMENT PRIMARY KEY,
        deal_id    INT,
        rater_id   INT,
        rated_id   INT,
        score      SMALLINT NOT NULL,
        comment    TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY uq_rating (deal_id, rater_id),
        FOREIGN KEY (deal_id)  REFERENCES deals(id) ON DELETE CASCADE,
        FOREIGN KEY (rater_id) REFERENCES users(id),
        FOREIGN KEY (rated_id) REFERENCES users(id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS demands (
        id               INT AUTO_INCREMENT PRIMARY KEY,
        student_id       INT NOT NULL,
        title            VARCHAR(255) NOT NULL,
        description      TEXT,
        category         VARCHAR(100),
        wilaya           VARCHAR(100),
        available_hours  VARCHAR(50),
        expected_salary  DECIMAL(10,2),
        skills           TEXT,
        status           VARCHAR(20) DEFAULT 'open',
        created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        FOREIGN KEY (student_id) REFERENCES users(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

    # Add columns that may be missing on existing deployments
    for col_sql in [
        "ALTER TABLE users ADD COLUMN is_banned TINYINT(1) DEFAULT 0",
        "ALTER TABLE users ADD COLUMN ban_reason TEXT",
    ]:
        try:
            cur.execute(col_sql)
            conn.commit()
        except pymysql.err.OperationalError:
            pass  # column already exists

    conn.commit()
    conn.close()
    print("✅ Database schema ready.")


# Initialise on module load (works with gunicorn)
init_db()


# ════════════════════════════════════════════════════════════════════════════
#  AUTH ROUTES
# ════════════════════════════════════════════════════════════════════════════

@app.route('/api/auth/register/send-otp', methods=['POST'])
def send_otp():
    data  = request.json or {}
    email = (data.get('email') or '').strip().lower()
    pw    = data.get('password', '')
    name  = data.get('name', '')
    role  = data.get('role', 'student')
    phone = data.get('phone', '')

    if not email or not pw:
        return err('البريد الإلكتروني وكلمة المرور مطلوبان')
    if len(pw) < 6:
        return err('كلمة المرور قصيرة جداً (6 أحرف على الأقل)')

    existing = db_query('SELECT id, verified FROM users WHERE email=%s', (email,), fetchone=True)
    if existing and existing['verified']:
        return err('البريد الإلكتروني مسجّل بالفعل')

    code    = otp_code()
    expires = datetime.utcnow() + timedelta(seconds=OTP_EXPIRY_SEC)

    if existing:
        db_query('UPDATE users SET otp=%s, otp_expires=%s, name=%s, phone=%s, password_hash=%s WHERE email=%s',
                 (code, expires, name, phone, hash_pw(pw), email), commit=True)
    else:
        db_query(
            'INSERT INTO users (email, password_hash, name, role, phone, otp, otp_expires) '
            'VALUES (%s,%s,%s,%s,%s,%s,%s)',
            (email, hash_pw(pw), name, role, phone, code, expires), commit=True
        )

    _send_email(email, f'رمز التحقق — {PLATFORM_NAME}', _otp_html(code))
    print(f'[OTP] {email} → {code}')
    return ok({'message': 'تم إرسال رمز التحقق إلى بريدك الإلكتروني'})


@app.route('/api/auth/register/verify-otp', methods=['POST'])
def verify_otp():
    data  = request.json or {}
    email = (data.get('email') or '').strip().lower()
    code  = str(data.get('otp', '')).strip()

    user = db_query('SELECT * FROM users WHERE email=%s', (email,), fetchone=True)
    if not user:
        return err('المستخدم غير موجود')
    if user['otp'] != code:
        return err('رمز التحقق غير صحيح')
    otp_exp = user['otp_expires']
    if otp_exp and datetime.utcnow() > (otp_exp if isinstance(otp_exp, datetime) else otp_exp):
        return err('انتهت صلاحية رمز التحقق')

    db_query('UPDATE users SET verified=1, otp=NULL, otp_expires=NULL WHERE id=%s',
             (user['id'],), commit=True)

    identity   = str(user['id'])
    access_tk  = create_access_token(identity=identity)
    refresh_tk = create_refresh_token(identity=identity)
    db_query('UPDATE users SET refresh_token=%s WHERE id=%s', (refresh_tk, user['id']), commit=True)

    u = row_to_dict(user)
    u.pop('password_hash', None); u.pop('otp', None); u.pop('refresh_token', None)
    return ok({'access_token': access_tk, 'refresh_token': refresh_tk, 'user': u})


@app.route('/api/auth/login', methods=['POST'])
def login():
    data  = request.json or {}
    email = (data.get('email') or '').strip().lower()
    pw    = data.get('password', '')

    user = db_query('SELECT * FROM users WHERE email=%s', (email,), fetchone=True)
    if not user or not check_pw(pw, user['password_hash']):
        return err('البريد الإلكتروني أو كلمة المرور غير صحيحة')
    if not user['verified']:
        return err('يرجى التحقق من بريدك الإلكتروني أولاً')
    if user.get('is_banned'):
        return jsonify({'ok': False, 'banned': True, 'reason': user.get('ban_reason', '')}), 403

    identity   = str(user['id'])
    access_tk  = create_access_token(identity=identity)
    refresh_tk = create_refresh_token(identity=identity)
    db_query('UPDATE users SET refresh_token=%s WHERE id=%s', (refresh_tk, user['id']), commit=True)

    u = row_to_dict(user)
    u.pop('password_hash', None); u.pop('otp', None); u.pop('refresh_token', None)
    return ok({'access_token': access_tk, 'refresh_token': refresh_tk, 'user': u})


@app.route('/api/auth/refresh', methods=['POST'])
@jwt_required(refresh=True)
def refresh():
    uid = get_jwt_identity()
    access_tk = create_access_token(identity=uid)
    return ok({'access_token': access_tk})


@app.route('/api/auth/me', methods=['GET'])
@jwt_required()
def me():
    uid  = int(get_jwt_identity())
    user = db_query('SELECT * FROM users WHERE id=%s', (uid,), fetchone=True)
    if not user: return err('المستخدم غير موجود', 404)
    u = row_to_dict(user)
    u.pop('password_hash', None); u.pop('otp', None); u.pop('refresh_token', None)
    return ok(u)


@app.route('/api/auth/profile', methods=['PUT'])
@jwt_required()
def update_profile():
    uid  = int(get_jwt_identity())
    data = request.json or {}
    allowed = ['name','phone','grade','wilaya','university','speciality','bio','skills','avatar_url']
    sets = ', '.join(f"{k}=%s" for k in allowed if k in data)
    vals = [data[k] for k in allowed if k in data] + [uid]
    if not sets: return err('لا توجد بيانات للتحديث')
    db_query(f'UPDATE users SET {sets} WHERE id=%s', vals, commit=True)
    return ok({'message': 'تم تحديث الملف الشخصي'})


# ════════════════════════════════════════════════════════════════════════════
#  PASSWORD RESET
# ════════════════════════════════════════════════════════════════════════════

@app.route('/api/auth/forgot-password', methods=['POST'])
def forgot_password():
    data  = request.json or {}
    email = (data.get('email') or '').strip().lower()
    if not email:
        return err('البريد الإلكتروني مطلوب')

    user = db_query('SELECT id, verified FROM users WHERE email=%s', (email,), fetchone=True)
    if user and user['verified']:
        code = otp_code()
        _pending_resets[email] = {'otp': code, 'sent_at': time.time(), 'verified': False}
        _send_email(email, f'إعادة تعيين كلمة المرور — {PLATFORM_NAME}',
                    _otp_html(code, is_reset=True))
        print(f'[RESET OTP] {email} → {code}')

    return ok({'message': 'إذا كان البريد الإلكتروني مسجّلاً، سيصلك رمز إعادة التعيين'})


@app.route('/api/auth/verify-reset-otp', methods=['POST'])
def verify_reset_otp():
    data  = request.json or {}
    email = (data.get('email') or '').strip().lower()
    code  = str(data.get('otp', '')).strip()

    if not email or not code:
        return err('البريد الإلكتروني والرمز مطلوبان')

    pending = _pending_resets.get(email)
    if not pending:
        return err('لا يوجد طلب إعادة تعيين لهذا البريد')
    if time.time() - pending['sent_at'] > OTP_EXPIRY_SEC:
        _pending_resets.pop(email, None)
        return err('انتهت صلاحية الرمز، يرجى الطلب مجدداً')
    if code != pending['otp']:
        return err('رمز غير صحيح')

    _pending_resets[email]['verified'] = True
    return ok({'message': 'تم التحقق من الرمز بنجاح'})


@app.route('/api/auth/reset-password', methods=['POST'])
def reset_password():
    data     = request.json or {}
    email    = (data.get('email') or '').strip().lower()
    new_pw   = data.get('new_password', '')

    if not email or not new_pw:
        return err('البريد الإلكتروني وكلمة المرور الجديدة مطلوبان')
    if len(new_pw) < 6:
        return err('كلمة المرور قصيرة جداً (6 أحرف على الأقل)')

    pending = _pending_resets.get(email)
    if not pending or not pending.get('verified'):
        return err('يرجى التحقق من رمز OTP أولاً')

    db_query('UPDATE users SET password_hash=%s WHERE email=%s', (hash_pw(new_pw), email), commit=True)
    _pending_resets.pop(email, None)
    return ok({'message': 'تم تغيير كلمة المرور بنجاح'})


# ════════════════════════════════════════════════════════════════════════════
#  LOGIN BY OTP (passwordless)
# ════════════════════════════════════════════════════════════════════════════

@app.route('/api/auth/login/send-otp', methods=['POST'])
def login_send_otp():
    data    = request.json or {}
    contact = (data.get('contact') or '').strip().lower()
    ch_type = (data.get('type') or 'email').strip().lower()

    if not contact:
        return err('يرجى إدخال البريد الإلكتروني')
    if ch_type != 'email':
        return err('الدخول برمز OTP متاح عبر البريد الإلكتروني فقط حالياً')

    row = db_query('SELECT id FROM users WHERE email=%s AND verified=1 AND is_banned=0',
                   (contact,), fetchone=True)
    if not row:
        return ok({'message': 'إذا كان البريد مسجّلاً وموثّقاً، سيصلك رمز الدخول'})

    code = otp_code()
    _pending_login_otps[contact] = {'otp': code, 'sent_at': time.time()}
    _send_email(contact, f'رمز الدخول — {PLATFORM_NAME}', _otp_html(code))
    print(f'[LOGIN OTP] {contact} → {code}')
    return ok({'message': 'إذا كان البريد مسجّلاً وموثّقاً، سيصلك رمز الدخول'})


@app.route('/api/auth/login/verify-otp', methods=['POST'])
def login_verify_otp():
    data    = request.json or {}
    contact = (data.get('contact') or '').strip().lower()
    code    = (data.get('otp') or '').strip()

    if not contact or not code:
        return err('البريد والرمز مطلوبان')

    pending = _pending_login_otps.get(contact)
    if not pending:
        return err('لا يوجد طلب دخول لهذا البريد')
    if time.time() - pending['sent_at'] > OTP_EXPIRY_SEC:
        _pending_login_otps.pop(contact, None)
        return err('انتهت صلاحية الرمز، يرجى طلب رمز جديد')
    if code != pending['otp']:
        return err('الرمز غير صحيح')

    _pending_login_otps.pop(contact, None)

    row = db_query(
        'SELECT id, email, name, role, grade, phone, verified FROM users WHERE email=%s AND is_banned=0',
        (contact,), fetchone=True
    )
    if not row:
        return err('الحساب غير موجود أو محظور')

    user = {k: row[k] for k in ['id','email','name','role','grade','phone','verified'] if k in row}
    access_token  = create_access_token(identity=str(user['id']))
    refresh_token = create_refresh_token(identity=str(user['id']))
    return ok({'access_token': access_token, 'refresh_token': refresh_token, 'user': user})


# ════════════════════════════════════════════════════════════════════════════
#  JOBS
# ════════════════════════════════════════════════════════════════════════════

@app.route('/api/jobs', methods=['GET'])
def list_jobs():
    wilaya   = request.args.get('wilaya')
    category = request.args.get('category')
    search   = request.args.get('q')
    sql  = 'SELECT j.*, u.name AS employer_name FROM jobs j JOIN users u ON j.employer_id=u.id WHERE j.status=%s'
    args = ['open']
    if wilaya:   sql += ' AND j.wilaya=%s';       args.append(wilaya)
    if category: sql += ' AND j.category=%s';     args.append(category)
    if search:   sql += ' AND j.title LIKE %s';   args.append(f'%{search}%')
    sql += ' ORDER BY j.created_at DESC LIMIT 50'
    rows = db_query(sql, args, fetchall=True)
    return ok(rows_to_list(rows))


@app.route('/api/jobs', methods=['POST'])
@jwt_required()
def create_job():
    uid  = int(get_jwt_identity())
    data = request.json or {}
    row  = db_insert(
        'INSERT INTO jobs (employer_id,title,description,category,wilaya,work_type,daily_salary,required_skills) '
        'VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',
        (uid, data.get('title'), data.get('description'), data.get('category'),
         data.get('wilaya'), data.get('work_type','partial'),
         data.get('daily_salary',0), data.get('required_skills','')),
        'jobs'
    )
    return ok(row_to_dict(row)), 201


@app.route('/api/jobs/<int:jid>', methods=['GET'])
def get_job(jid):
    row = db_query(
        'SELECT j.*, u.name AS employer_name, u.wilaya AS employer_wilaya, '
        '  COALESCE(ROUND(AVG(r.score),1),0) AS employer_rating, '
        '  COUNT(r.id) AS employer_rating_count '
        'FROM jobs j JOIN users u ON j.employer_id=u.id '
        'LEFT JOIN ratings r ON r.rated_id=u.id '
        'WHERE j.id=%s GROUP BY j.id, u.name, u.wilaya',
        (jid,), fetchone=True
    )
    if not row: return err('الوظيفة غير موجودة', 404)
    return ok(row_to_dict(row))


@app.route('/api/jobs/<int:jid>', methods=['PUT'])
@jwt_required()
def update_job(jid):
    uid  = int(get_jwt_identity())
    data = request.json or {}
    allowed = ['title','description','category','wilaya','work_type','daily_salary','required_skills','status']
    sets = ', '.join(f"{k}=%s" for k in allowed if k in data)
    vals = [data[k] for k in allowed if k in data] + [jid, uid]
    if not sets: return err('لا توجد بيانات للتحديث')
    db_query(f'UPDATE jobs SET {sets} WHERE id=%s AND employer_id=%s', vals, commit=True)
    return ok({'message': 'تم تحديث الوظيفة'})


@app.route('/api/jobs/<int:jid>', methods=['DELETE'])
@jwt_required()
def delete_job(jid):
    uid = int(get_jwt_identity())
    db_query('UPDATE jobs SET status=%s WHERE id=%s AND employer_id=%s', ('deleted', jid, uid), commit=True)
    return ok({'message': 'تم حذف الوظيفة'})


# ════════════════════════════════════════════════════════════════════════════
#  APPLICATIONS
# ════════════════════════════════════════════════════════════════════════════

@app.route('/api/applications', methods=['GET'])
@jwt_required()
def list_applications():
    uid  = int(get_jwt_identity())
    user = db_query('SELECT role FROM users WHERE id=%s', (uid,), fetchone=True)
    if user['role'] == 'employer':
        rows = db_query(
            'SELECT a.*, u.name AS student_name, j.title AS job_title FROM applications a '
            'JOIN users u ON a.student_id=u.id JOIN jobs j ON a.job_id=j.id '
            'WHERE j.employer_id=%s ORDER BY a.created_at DESC',
            (uid,), fetchall=True
        )
    else:
        rows = db_query(
            'SELECT a.*, j.title AS job_title, u.name AS employer_name FROM applications a '
            'JOIN jobs j ON a.job_id=j.id JOIN users u ON j.employer_id=u.id '
            'WHERE a.student_id=%s ORDER BY a.created_at DESC',
            (uid,), fetchall=True
        )
    return ok(rows_to_list(rows))


@app.route('/api/applications', methods=['POST'])
@jwt_required()
def apply_job():
    uid  = int(get_jwt_identity())
    data = request.json or {}
    jid  = data.get('job_id')
    if not jid: return err('معرف الوظيفة مطلوب')
    try:
        row = db_insert(
            'INSERT INTO applications (job_id, student_id, cover_letter) VALUES (%s,%s,%s)',
            (jid, uid, data.get('cover_letter','')),
            'applications'
        )
        return ok(row_to_dict(row)), 201
    except pymysql.err.IntegrityError:
        return err('لقد تقدمت لهذه الوظيفة مسبقاً')


@app.route('/api/applications/<int:aid>', methods=['PUT'])
@jwt_required()
def update_application(aid):
    data   = request.json or {}
    status = data.get('status')
    if status not in ('pending','accepted','rejected'):
        return err('حالة غير صالحة')
    db_query('UPDATE applications SET status=%s WHERE id=%s', (status, aid), commit=True)
    return ok({'message': 'تم تحديث حالة الطلب'})


# ════════════════════════════════════════════════════════════════════════════
#  CONVERSATIONS & MESSAGES
# ════════════════════════════════════════════════════════════════════════════

@app.route('/api/conversations', methods=['GET'])
@jwt_required()
def list_convs():
    uid  = int(get_jwt_identity())
    rows = db_query(
        'SELECT c.*, '
        '  e.name AS employer_name, s.name AS student_name, j.title AS job_title, '
        '  (SELECT content FROM messages WHERE conversation_id=c.id ORDER BY created_at DESC LIMIT 1) AS last_msg '
        'FROM conversations c '
        'JOIN users e ON c.employer_id=e.id '
        'JOIN users s ON c.student_id=s.id '
        'LEFT JOIN jobs j ON c.job_id=j.id '
        'WHERE c.employer_id=%s OR c.student_id=%s '
        'ORDER BY c.created_at DESC',
        (uid, uid), fetchall=True
    )
    return ok(rows_to_list(rows))


@app.route('/api/conversations', methods=['POST'])
@jwt_required()
def create_conv():
    uid  = int(get_jwt_identity())
    data = request.json or {}
    emp_id = data.get('employer_id')
    stu_id = data.get('student_id')
    job_id = data.get('job_id')
    existing = db_query(
        'SELECT id FROM conversations WHERE employer_id=%s AND student_id=%s AND (job_id=%s OR job_id IS NULL)',
        (emp_id, stu_id, job_id), fetchone=True
    )
    if existing: return ok(row_to_dict(existing))
    row = db_insert(
        'INSERT INTO conversations (employer_id, student_id, job_id) VALUES (%s,%s,%s)',
        (emp_id, stu_id, job_id),
        'conversations'
    )
    return ok(row_to_dict(row)), 201


@app.route('/api/conversations/<int:cid>/messages', methods=['GET'])
@jwt_required()
def get_messages(cid):
    rows = db_query(
        'SELECT m.*, u.name AS sender_name FROM messages m JOIN users u ON m.sender_id=u.id '
        'WHERE m.conversation_id=%s ORDER BY m.created_at ASC',
        (cid,), fetchall=True
    )
    return ok(rows_to_list(rows))


@app.route('/api/conversations/<int:cid>/messages', methods=['POST'])
@jwt_required()
def send_message(cid):
    uid  = int(get_jwt_identity())
    data = request.json or {}
    row  = db_insert(
        'INSERT INTO messages (conversation_id, sender_id, content, msg_type) VALUES (%s,%s,%s,%s)',
        (cid, uid, data.get('content',''), data.get('msg_type','text')),
        'messages'
    )
    return ok(row_to_dict(row)), 201


# ════════════════════════════════════════════════════════════════════════════
#  DEAL WORKFLOW
# ════════════════════════════════════════════════════════════════════════════

def calc_fee(daily, months):
    if daily < 1000:
        fee_per_month = 150
    else:
        fee_per_month = round(daily * 0.30, 2)
    return fee_per_month, fee_per_month * months


@app.route('/api/deals/<int:cid>', methods=['GET'])
@jwt_required()
def get_deal(cid):
    deal = db_query('SELECT * FROM deals WHERE conversation_id=%s ORDER BY id DESC LIMIT 1', (cid,), fetchone=True)
    if not deal: return ok(None)
    d = row_to_dict(deal)
    fpm, total_fee = calc_fee(float(d.get('daily_salary', 1000)), d.get('duration_months', 1))
    d['fee_per_month'] = fpm
    d['total_fee'] = total_fee
    return ok(d)


@app.route('/api/deals/<int:cid>/start', methods=['POST'])
@jwt_required()
def start_deal(cid):
    uid  = int(get_jwt_identity())
    existing = db_query("SELECT id, status FROM deals WHERE conversation_id=%s AND status!='cancelled'", (cid,), fetchone=True)
    if existing: return err('هناك صفقة نشطة بالفعل')

    # Verify caller is the employer of this conversation
    conv = db_query('SELECT id FROM conversations WHERE id=%s AND employer_id=%s', (cid, uid), fetchone=True)
    if not conv: return err('غير مصرح', 403)

    row = db_insert(
        'INSERT INTO deals (conversation_id, employer_id, status) VALUES (%s,%s,%s)',
        (cid, uid, 'employer_started'),
        'deals'
    )
    return ok(row_to_dict(row))


@app.route('/api/deals/<int:cid>/accept', methods=['POST'])
@jwt_required()
def accept_deal(cid):
    uid  = int(get_jwt_identity())
    deal = db_query("SELECT * FROM deals WHERE conversation_id=%s AND status='employer_started'", (cid,), fetchone=True)
    if not deal: return err('لا توجد صفقة في انتظار القبول')
    conv = db_query('SELECT * FROM conversations WHERE id=%s AND student_id=%s', (cid, uid), fetchone=True)
    if not conv: return err('غير مصرح', 403)
    db_query(
        'UPDATE deals SET status=%s, student_id=%s, updated_at=NOW() WHERE id=%s',
        ('form', uid, deal['id']), commit=True
    )
    return ok({'message': 'تم قبول الصفقة'})


@app.route('/api/deals/<int:cid>/form', methods=['PUT'])
@jwt_required()
def update_deal_form(cid):
    uid  = int(get_jwt_identity())
    data = request.json or {}
    deal = db_query("SELECT * FROM deals WHERE conversation_id=%s AND status='form'", (cid,), fetchone=True)
    if not deal: return err('لا يمكن تعديل النموذج الآن')
    allowed = ['daily_salary','duration_months','start_date','payment_date','instructions']
    sets = ', '.join(f"{k}=%s" for k in allowed if k in data) + ', updated_at=NOW()'
    vals = [data[k] for k in allowed if k in data] + [deal['id']]
    db_query(f'UPDATE deals SET {sets} WHERE id=%s', vals, commit=True)
    return ok({'message': 'تم تحديث نموذج الاتفاقية'})


@app.route('/api/deals/<int:cid>/confirm', methods=['POST'])
@jwt_required()
def confirm_deal(cid):
    uid  = int(get_jwt_identity())
    deal = db_query("SELECT * FROM deals WHERE conversation_id=%s AND status='form'", (cid,), fetchone=True)
    if not deal: return err('لا توجد اتفاقية في مرحلة التأكيد')

    is_employer = (uid == deal['employer_id'])
    is_student  = (uid == deal['student_id'])
    if not is_employer and not is_student: return err('غير مصرح', 403)

    emp_conf = deal['employer_confirmed'] or is_employer
    stu_conf = deal['student_confirmed']  or is_student

    if emp_conf and stu_conf:
        deadline = datetime.utcnow() + timedelta(hours=24)
        db_query(
            'UPDATE deals SET employer_confirmed=1, student_confirmed=1, status=%s, deposit_deadline=%s, updated_at=NOW() WHERE id=%s',
            ('deposit_pending', deadline, deal['id']), commit=True
        )
        daily    = float(deal['daily_salary'])
        months   = deal['duration_months']
        monthly  = round(daily * 30, 2)
        fpm, _   = calc_fee(daily, months)
        for m in range(1, months + 1):
            db_query('INSERT INTO payments (deal_id, month_number, amount, fee, status) VALUES (%s,%s,%s,%s,%s)',
                     (deal['id'], m, monthly, fpm, 'pending'), commit=True)
        return ok({'status': 'deposit_pending', 'deadline': deadline.isoformat()})
    else:
        field = 'employer_confirmed' if is_employer else 'student_confirmed'
        db_query(f'UPDATE deals SET {field}=1, updated_at=NOW() WHERE id=%s', (deal['id'],), commit=True)
        return ok({'status': 'waiting_other'})


@app.route('/api/deals/<int:cid>/deposit', methods=['POST'])
@jwt_required()
def deposit_deal(cid):
    uid  = int(get_jwt_identity())
    deal = db_query("SELECT * FROM deals WHERE conversation_id=%s AND status='deposit_pending'", (cid,), fetchone=True)
    if not deal: return err('لا توجد صفقة في انتظار الإيداع')
    if uid != deal['employer_id']: return err('فقط صاحب العمل يمكنه الإيداع', 403)

    if deal['deposit_deadline']:
        dl = deal['deposit_deadline']
        if isinstance(dl, datetime) and datetime.utcnow() > dl:
            db_query('UPDATE deals SET status=%s WHERE id=%s', ('cancelled', deal['id']), commit=True)
            return err('انتهت مهلة الإيداع. تم إلغاء الصفقة تلقائياً')

    db_query('UPDATE deals SET status=%s, updated_at=NOW() WHERE id=%s', ('secured', deal['id']), commit=True)
    return ok({'status': 'secured', 'message': 'تم الإيداع — الأموال مؤمّنة'})


@app.route('/api/deals/<int:cid>/payments', methods=['GET'])
@jwt_required()
def deal_payments(cid):
    deal = db_query('SELECT id FROM deals WHERE conversation_id=%s ORDER BY id DESC LIMIT 1', (cid,), fetchone=True)
    if not deal: return ok([])
    rows = db_query('SELECT * FROM payments WHERE deal_id=%s ORDER BY month_number', (deal['id'],), fetchall=True)
    return ok(rows_to_list(rows))


@app.route('/api/deals/<int:cid>/cancel', methods=['POST'])
@jwt_required()
def cancel_deal(cid):
    deal = db_query('SELECT id FROM deals WHERE conversation_id=%s', (cid,), fetchone=True)
    if deal:
        db_query('UPDATE deals SET status=%s WHERE id=%s', ('cancelled', deal['id']), commit=True)
    return ok({'message': 'تم إلغاء الصفقة'})


# ════════════════════════════════════════════════════════════════════════════
#  RATINGS
# ════════════════════════════════════════════════════════════════════════════

@app.route('/api/deals/<int:cid>/rate', methods=['POST'])
@jwt_required()
def rate_user(cid):
    uid  = int(get_jwt_identity())
    data = request.json or {}

    deal = db_query(
        "SELECT * FROM deals WHERE conversation_id=%s AND status IN ('secured','completed')",
        (cid,), fetchone=True
    )
    if not deal:
        return err('لا يمكن التقييم إلا بعد إتمام الصفقة')

    is_employer = (uid == deal['employer_id'])
    is_student  = (uid == deal['student_id'])
    if not is_employer and not is_student:
        return err('غير مصرح', 403)

    rated_id = deal['student_id'] if is_employer else deal['employer_id']
    score    = data.get('score')
    comment  = data.get('comment', '').strip() or None

    if score is None or not isinstance(score, int) or not (1 <= score <= 5):
        return err('التقييم يجب أن يكون بين 1 و 5')

    try:
        row = db_insert(
            'INSERT INTO ratings (deal_id, rater_id, rated_id, score, comment) VALUES (%s,%s,%s,%s,%s)',
            (deal['id'], uid, rated_id, score, comment),
            'ratings'
        )
    except pymysql.err.IntegrityError:
        return err('لقد قمت بتقييم هذه الصفقة مسبقاً')

    return ok(row_to_dict(row)), 201


@app.route('/api/ratings/<int:user_id>', methods=['GET'])
def get_user_ratings(user_id):
    rows = db_query(
        'SELECT r.*, u.name AS rater_name, u.avatar_url AS rater_avatar '
        'FROM ratings r JOIN users u ON r.rater_id=u.id '
        'WHERE r.rated_id=%s ORDER BY r.created_at DESC',
        (user_id,), fetchall=True
    )
    avg = db_query(
        'SELECT COALESCE(ROUND(AVG(score),1),0) AS avg, COUNT(*) AS total '
        'FROM ratings WHERE rated_id=%s',
        (user_id,), fetchone=True
    )
    return ok({
        'ratings':   rows_to_list(rows),
        'average':   float(avg['avg']),
        'total':     avg['total'],
    })


@app.route('/api/ratings/<int:rating_id>', methods=['DELETE'])
@jwt_required()
def delete_rating(rating_id):
    uid = int(get_jwt_identity())
    rating = db_query('SELECT * FROM ratings WHERE id=%s AND rater_id=%s', (rating_id, uid), fetchone=True)
    if not rating:
        return err('التقييم غير موجود أو ليس لديك صلاحية حذفه', 404)
    db_query('DELETE FROM ratings WHERE id=%s', (rating_id,), commit=True)
    return ok({'message': 'تم حذف التقييم'})


# ════════════════════════════════════════════════════════════════════════════
#  ADMIN
# ════════════════════════════════════════════════════════════════════════════

def _require_admin(uid):
    user = db_query('SELECT * FROM users WHERE id=%s', (uid,), fetchone=True)
    if user and user.get('role') == 'admin':
        return user
    return None


@app.route('/api/admin/stats', methods=['GET'])
@jwt_required()
def admin_stats():
    uid = int(get_jwt_identity())
    if not _require_admin(uid): return err('غير مصرح', 403)
    users_count   = db_query('SELECT COUNT(*) AS c FROM users', fetchone=True)['c']
    jobs_count    = db_query('SELECT COUNT(*) AS c FROM jobs', fetchone=True)['c']
    deals_count   = db_query('SELECT COUNT(*) AS c FROM deals', fetchone=True)['c']
    ratings_count = db_query('SELECT COUNT(*) AS c FROM ratings', fetchone=True)['c']
    return ok({'users': users_count, 'jobs': jobs_count, 'deals': deals_count, 'ratings': ratings_count})


@app.route('/api/admin/users', methods=['GET'])
@jwt_required()
def admin_users():
    uid = int(get_jwt_identity())
    if not _require_admin(uid): return err('غير مصرح', 403)
    rows = db_query(
        'SELECT id, email, name, role, verified, is_banned, ban_reason, created_at '
        'FROM users ORDER BY created_at DESC',
        fetchall=True
    )
    return ok(rows_to_list(rows))


@app.route('/api/admin/ban', methods=['POST'])
@jwt_required()
def admin_ban():
    uid = int(get_jwt_identity())
    if not _require_admin(uid): return err('غير مصرح', 403)

    data      = request.json or {}
    target_id = data.get('user_id')
    reason    = (data.get('reason') or '').strip()

    if not target_id: return err('user_id مطلوب')
    if not reason:    return err('سبب الحظر مطلوب')

    target = db_query('SELECT id, role, is_banned FROM users WHERE id=%s', (target_id,), fetchone=True)
    if not target:                return err('المستخدم غير موجود', 404)
    if target['role'] == 'admin': return err('لا يمكن حظر مسؤول')
    if target['is_banned']:       return err('المستخدم محظور بالفعل')

    db_query('UPDATE users SET is_banned=1, ban_reason=%s WHERE id=%s', (reason, target_id), commit=True)
    return ok({'message': 'تم حظر المستخدم'})


@app.route('/api/admin/unban', methods=['POST'])
@jwt_required()
def admin_unban():
    uid = int(get_jwt_identity())
    if not _require_admin(uid): return err('غير مصرح', 403)

    data      = request.json or {}
    target_id = data.get('user_id')
    if not target_id: return err('user_id مطلوب')

    target = db_query('SELECT id, is_banned FROM users WHERE id=%s', (target_id,), fetchone=True)
    if not target:              return err('المستخدم غير موجود', 404)
    if not target['is_banned']: return err('المستخدم غير محظور')

    db_query('UPDATE users SET is_banned=0, ban_reason=NULL WHERE id=%s', (target_id,), commit=True)
    return ok({'message': 'تم رفع الحظر عن المستخدم'})


@app.route('/api/admin/invite', methods=['POST'])
@jwt_required()
def admin_invite():
    uid = int(get_jwt_identity())
    if not _require_admin(uid): return err('غير مصرح', 403)

    data     = request.json or {}
    to_email = (data.get('email') or '').strip()
    to_name  = data.get('name', '')

    if not to_email: return err('البريد الإلكتروني مطلوب')

    _send_email(to_email, f'دعوة للانضمام إلى {PLATFORM_NAME}', _invite_html(to_name))
    return ok({'message': f'تم إرسال الدعوة إلى {to_email}'})


# ════════════════════════════════════════════════════════════════════════════
#  SEARCH & MISC
# ════════════════════════════════════════════════════════════════════════════

@app.route('/api/users/search', methods=['GET'])
@jwt_required()
def search_users():
    q    = (request.args.get('q') or '').strip()
    role = request.args.get('role')
    if not q: return err('معامل البحث q مطلوب')

    sql  = ("SELECT u.id, u.name, u.role, u.grade, u.wilaya, u.avatar_url, "
            "COALESCE(ROUND(AVG(r.score),1),0) AS rating, "
            "COUNT(r.id) AS rating_count "
            "FROM users u "
            "LEFT JOIN ratings r ON r.rated_id=u.id "
            "WHERE u.name LIKE %s AND u.verified=1")
    args = [f'%{q}%']
    if role:
        sql += ' AND u.role=%s'
        args.append(role)
    sql += ' GROUP BY u.id ORDER BY u.name LIMIT 30'
    rows = db_query(sql, args, fetchall=True)
    return ok(rows_to_list(rows))


@app.route('/api/users/<int:user_id>', methods=['GET'])
def get_user_profile(user_id):
    user = db_query(
        'SELECT u.id, u.name, u.role, u.grade, u.wilaya, u.university, u.speciality, u.bio, u.skills, u.avatar_url, u.created_at, '
        '  COALESCE(ROUND(AVG(r.score),1),0) AS rating, '
        '  COUNT(r.id) AS rating_count '
        'FROM users u LEFT JOIN ratings r ON r.rated_id=u.id '
        'WHERE u.id=%s GROUP BY u.id',
        (user_id,), fetchone=True
    )
    if not user: return err('المستخدم غير موجود', 404)
    return ok(row_to_dict(user))


@app.route('/api/stats', methods=['GET'])
def public_stats():
    users  = db_query("SELECT COUNT(*) AS c FROM users WHERE verified=1", fetchone=True)['c']
    jobs   = db_query("SELECT COUNT(*) AS c FROM jobs WHERE status='open'", fetchone=True)['c']
    deals  = db_query("SELECT COUNT(*) AS c FROM deals WHERE status IN ('secured','completed')", fetchone=True)['c']
    return ok({'users': users, 'open_jobs': jobs, 'completed_deals': deals})


# ════════════════════════════════════════════════════════════════════════════
#  DEMANDS  (students publish job-seeking posts)
# ════════════════════════════════════════════════════════════════════════════

@app.route('/api/demands', methods=['GET'])
def list_demands():
    """Public: list open student demands. Filter by wilaya, category, or search."""
    wilaya   = request.args.get('wilaya')
    category = request.args.get('category')
    search   = request.args.get('q')
    sql  = (
        'SELECT d.*, u.name AS student_name, u.avatar_url AS student_avatar, '
        '  u.university, u.speciality, u.grade '
        'FROM demands d JOIN users u ON d.student_id=u.id '
        "WHERE d.status='open' AND u.verified=1"
    )
    args = []
    if wilaya:   sql += ' AND d.wilaya=%s';       args.append(wilaya)
    if category: sql += ' AND d.category=%s';     args.append(category)
    if search:   sql += ' AND (d.title LIKE %s OR d.skills LIKE %s)'; args += [f'%{search}%', f'%{search}%']
    sql += ' ORDER BY d.created_at DESC LIMIT 50'
    rows = db_query(sql, args, fetchall=True)
    return ok(rows_to_list(rows))


@app.route('/api/demands', methods=['POST'])
@jwt_required()
def create_demand():
    """Student publishes a job-seeking demand."""
    uid  = int(get_jwt_identity())
    user = db_query('SELECT role FROM users WHERE id=%s', (uid,), fetchone=True)
    if not user: return err('المستخدم غير موجود', 404)
    if user['role'] == 'employer':
        return err('أصحاب العمل لا يمكنهم نشر طلبات عمل', 403)

    data = request.json or {}
    title = (data.get('title') or '').strip()
    if not title:
        return err('عنوان الطلب مطلوب')

    row = db_insert(
        'INSERT INTO demands (student_id, title, description, category, wilaya, '
        'available_hours, expected_salary, skills) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',
        (uid, title, data.get('description'), data.get('category'),
         data.get('wilaya'), data.get('available_hours'),
         data.get('expected_salary'), data.get('skills', '')),
        'demands'
    )
    return ok(row_to_dict(row)), 201


@app.route('/api/demands/<int:did>', methods=['GET'])
def get_demand(did):
    """Get a single demand with student profile info."""
    row = db_query(
        'SELECT d.*, u.name AS student_name, u.avatar_url AS student_avatar, '
        '  u.university, u.speciality, u.grade, u.wilaya AS student_wilaya, '
        '  COALESCE(ROUND(AVG(r.score),1),0) AS student_rating, '
        '  COUNT(r.id) AS student_rating_count '
        'FROM demands d '
        'JOIN users u ON d.student_id=u.id '
        'LEFT JOIN ratings r ON r.rated_id=u.id '
        'WHERE d.id=%s GROUP BY d.id, u.id',
        (did,), fetchone=True
    )
    if not row: return err('الطلب غير موجود', 404)
    return ok(row_to_dict(row))


@app.route('/api/demands/<int:did>', methods=['PUT'])
@jwt_required()
def update_demand(did):
    """Student updates their own demand."""
    uid  = int(get_jwt_identity())
    demand = db_query('SELECT id, student_id FROM demands WHERE id=%s', (did,), fetchone=True)
    if not demand: return err('الطلب غير موجود', 404)
    if demand['student_id'] != uid: return err('غير مصرح', 403)

    data    = request.json or {}
    allowed = ['title','description','category','wilaya','available_hours','expected_salary','skills','status']
    sets    = ', '.join(f"{k}=%s" for k in allowed if k in data)
    vals    = [data[k] for k in allowed if k in data] + [did]
    if not sets: return err('لا توجد بيانات للتحديث')
    db_query(f'UPDATE demands SET {sets} WHERE id=%s', vals, commit=True)
    return ok({'message': 'تم تحديث الطلب'})


@app.route('/api/demands/<int:did>', methods=['DELETE'])
@jwt_required()
def delete_demand(did):
    """Student closes/deletes their own demand."""
    uid    = int(get_jwt_identity())
    demand = db_query('SELECT id, student_id FROM demands WHERE id=%s', (did,), fetchone=True)
    if not demand: return err('الطلب غير موجود', 404)
    if demand['student_id'] != uid: return err('غير مصرح', 403)
    db_query("UPDATE demands SET status='closed' WHERE id=%s", (did,), commit=True)
    return ok({'message': 'تم إغلاق الطلب'})


@app.route('/api/demands/mine', methods=['GET'])
@jwt_required()
def my_demands():
    """Student retrieves their own demands."""
    uid  = int(get_jwt_identity())
    rows = db_query(
        'SELECT * FROM demands WHERE student_id=%s ORDER BY created_at DESC',
        (uid,), fetchall=True
    )
    return ok(rows_to_list(rows))


# ════════════════════════════════════════════════════════════════════════════
#  STATIC FILES (serve frontend HTML/CSS/JS from root)
# ════════════════════════════════════════════════════════════════════════════

@app.route('/')
def index():
    return send_file('index.html')

@app.route('/<path:filename>')
def static_files(filename):
    return send_from_directory('.', filename)


# ════════════════════════════════════════════════════════════════════════════
#  MAIN
# ════════════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    print("🚀 Talib-Awn backend starting on port 5000...")
    app.run(host='0.0.0.0', port=5000, debug=False)
