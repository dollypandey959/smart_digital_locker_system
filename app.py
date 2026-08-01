import bcrypt
from flask import Flask, Response, render_template, request, redirect, send_from_directory, session, url_for, flash, jsonify
from flask_mysqldb import MySQL
import re
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
import webbrowser
import os
from functools import wraps
from datetime import datetime, timedelta
import hashlib
from flask_mail import Mail, Message
from functools import wraps
from flask import session, redirect, url_for, flash
from flask import request

import logging




UPLOAD_FOLDER = 'static/uploads'


from config import Config

app = Flask(__name__)
app.config.from_object(Config)

# Add caching headers for static files
@app.after_request
def add_header(response):
    if 'Cache-Control' not in response.headers:
        response.headers['Cache-Control'] = 'public, max-age=86400'
    return response

mysql = MySQL(app)




# ================= DECORATORS =================
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please login to continue', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

from functools import wraps

def hr_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):

        role = session.get('role')

        # ❌ Not logged in
        if not role:
            flash('Please login first.', 'warning')
            return redirect(url_for('login'))

        # 🔥 Normalize role
        if role.strip().upper() != 'HR':
            flash('Access denied. HR only.', 'danger')
            return redirect(url_for('login'))

        return f(*args, **kwargs)

    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'admin' not in session:
            flash('Admin access required', 'danger')
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function


logging.basicConfig(
    filename="activity.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

def add_activity(user_id, action):
    try:
        ip = request.headers.get('X-Forwarded-For')

        if ip:
            ip = ip.split(',')[0].strip()
        else:
            ip = request.remote_addr or "Unknown"

        ip = str(ip)[:45]
        action = str(action)[:255]

        cur = mysql.connection.cursor()
        cur.execute(
            "INSERT INTO activity_log (user_id, action, ip_address) VALUES (%s, %s, %s)",
            (user_id, action, ip)
        )
        mysql.connection.commit()
        cur.close()

        # ✅ SAFE (NO PRINT)
        logging.info(f"{user_id} | {action} | {ip}")

    except Exception as e:
        logging.error(f"Create User Error: {str(e)}")
# ================= INDEX =================
@app.route('/')
@app.route('/index')
def index():
    cursor = mysql.connection.cursor()

    # USERS COUNT
    cursor.execute("SELECT COUNT(*) FROM user")
    users_count = cursor.fetchone()[0]

    # DOCUMENTS COUNT
    cursor.execute("SELECT COUNT(*) FROM document")
    documents_count = cursor.fetchone()[0]

    # STORAGE USED (TOTAL FILE SIZE)
    cursor.execute("SELECT SUM(file_size) FROM document")
    total_size = cursor.fetchone()[0] or 0   # NULL handle

    # MAX STORAGE (example: 100 MB)
    max_storage = 100000000  

    # PERCENT CALCULATION
    storage_used = round((total_size / max_storage) * 100, 2) if max_storage else 0

    # UPTIME
    uptime = 99

    cursor.close()

    return render_template(
        'index.html',
        users_count=users_count,
        documents_count=documents_count,
        uptime=uptime,
        storage_used=storage_used
    )






# ================= Admin Login =================
@app.route('/admin_login', methods=['GET','POST'])
def admin_login():
    if request.method == "POST":
        username = request.form['username']
        password = request.form['password']
        
        # Hardcoded admin credentials (in production, use database)
        if username == "admin" and password == "admin123":
            session['admin'] = True
            session['admin_name'] = 'Administrator'
            flash('Welcome back, Admin!', 'success')
            return redirect(url_for('admin_dashboard'))
        else:
            flash("Invalid Admin Credentials", "danger")
            return redirect(url_for('admin_login'))

    return render_template('admin/admin_login.html')
# ================= EDIT USER =================
@app.route('/edit_user/<int:id>', methods=['GET', 'POST'])
@admin_required
def edit_user(id):
    cur = mysql.connection.cursor()

    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        role = request.form['role']

        cur.execute("""
            UPDATE user 
            SET name=%s, email=%s, role=%s 
            WHERE id=%s
        """, (name, email, role, id))

        mysql.connection.commit()

        add_activity(session['user_id'], f"Updated user ID: {id}")

        cur.close()

        flash("User updated successfully!", "success")
        return redirect(url_for('admin_dashboard'))

    cur.execute("SELECT id, name, email, role FROM user WHERE id=%s", (id,))
    user = cur.fetchone()
    cur.close()

    return render_template('admin/edit_user.html', user=user)
# ================= ADMIN DASHBOARD =================
@app.route('/admin_dashboard')
@admin_required
def admin_dashboard():
    cur = mysql.connection.cursor()

    # Counts
    cur.execute("SELECT COUNT(*) FROM user WHERE role='HR'")
    total_hr = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM user WHERE role='Employee'")
    total_emp = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM user WHERE status='Pending'")
    pending = cur.fetchone()[0]

    #  Pending users list (NEW)
    cur.execute("SELECT id, name, login_id FROM user WHERE status='Pending'")
    pending_users = cur.fetchall()

    # Recent users
    cur.execute("SELECT * FROM user ORDER BY id DESC LIMIT 5")
    users = cur.fetchall()

    cur.close()

    return render_template('admin/admin_dashboard.html',
        total_hr=total_hr,
        total_emp=total_emp,
        pending=pending,
        pending_users=pending_users,   
        users=users,
        active_page='dashboard'
    )
# ================= Approve User =================
@app.route('/approve_user/<int:id>')
@admin_required
def approve_user(id):
    cur = mysql.connection.cursor()

    # update user status
    cur.execute("UPDATE user SET status='Approved' WHERE id=%s", (id,))
    mysql.connection.commit()

    # 🔥 SAFE ACTIVITY LOG 
    add_activity(0, f"Admin approved user ID: {id}")

    cur.close()

    flash(f"User ID {id} has been approved successfully", "success")
    return redirect(url_for('admin_dashboard'))
# ================= Create User =================
@app.route('/create_user', methods=['GET', 'POST'])
@admin_required
def create_user():

    if request.method == 'POST':

        try:
            # ================= SAFE INPUT =================
            name = request.form.get('full_name', '').strip()
            email = request.form.get('email', '').strip()
            phone = request.form.get('phone', '').strip()
            login_id = request.form.get('login_id', '').strip()
            password = request.form.get('password', '')
            confirm = request.form.get('confirm_password', '')
            role = request.form.get('role', '').strip()
            department = request.form.get('department', '').strip()
            designation = request.form.get('designation', '').strip()
            address = request.form.get('address', '').strip()

            # ================= VALIDATION START =================

            # 1. Name
            if not name:
                flash("Name is required", "danger")
                return redirect(url_for('create_user'))

            if not re.match(r'^[A-Za-z ]{3,50}$', name):
                flash("Name must contain only letters (3-50 chars)", "danger")
                return redirect(url_for('create_user'))

            # 2. Email
            if not email:
                flash("Email is required", "danger")
                return redirect(url_for('create_user'))

            if not re.match(r'^[\w\.-]+@[\w\.-]+\.\w+$', email):
                flash("Invalid email format", "danger")
                return redirect(url_for('create_user'))

            # 3. Phone (optional)
            if phone and not re.match(r'^[0-9]{10}$', phone):
                flash("Phone must be 10 digits", "danger")
                return redirect(url_for('create_user'))

            # 4. Login ID
            if not login_id:
                flash("Login ID is required", "danger")
                return redirect(url_for('create_user'))

            if not re.match(r'^[A-Za-z0-9]{4,20}$', login_id):
                flash("Login ID must be 4-20 letters/numbers only", "danger")
                return redirect(url_for('create_user'))

            # 5. Role validation
            if role not in ['Employee', 'HR']:
                flash("Please select valid role", "danger")
                return redirect(url_for('create_user'))

            # 6. Password required
            if not password:
                flash("Password is required", "danger")
                return redirect(url_for('create_user'))

            # 7. Password match
            if password != confirm:
                flash("Passwords do not match", "danger")
                return redirect(url_for('create_user'))

            # 8. Strong password
            if not re.match(r'(?=.*[A-Z])(?=.*[0-9])(?=.*[\W]).{8,}', password):
                flash("Weak Password (8+ chars, 1 uppercase, 1 number, 1 special char)", "danger")
                return redirect(url_for('create_user'))

            # ================= DATABASE CHECK =================
            cur = mysql.connection.cursor()

            cur.execute("""
                SELECT id FROM user 
                WHERE login_id=%s OR email=%s
            """, (login_id, email))

            if cur.fetchone():
                flash("Login ID or Email already exists!", "danger")
                cur.close()
                return redirect(url_for('create_user'))

            # ================= INSERT USER =================
            hashed_password = generate_password_hash(password)

            cur.execute("""
                INSERT INTO user 
                (name, email, phone, login_id, password, role, status, is_password_changed, department, designation, address)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                name,
                email,
                phone,
                login_id,
                hashed_password,
                role,
                'Pending',
                0,
                department,
                designation,
                address
            ))

            mysql.connection.commit()

            # ================= ACTIVITY LOG =================
            if session.get('user_id'):
                add_activity(0, f"Admin created user: {name}")

            cur.close()

            flash("User created successfully!", "success")
            return redirect(url_for('admin_dashboard'))

        except Exception as e:
            print("ERROR:", e)
            flash("Something went wrong while creating user", "danger")
            return redirect(url_for('create_user'))

    return render_template('admin/create_user.html')
# ================= Reject User =================
@app.route('/reject_user/<int:id>')
@admin_required
def reject_user(id):
    cur = mysql.connection.cursor()

    cur.execute("UPDATE user SET status='Rejected' WHERE id=%s", (id,))
    mysql.connection.commit()

    # 🔥 SAFE LOG
    add_activity(0, f"Admin rejected user ID: {id}")

    cur.close()

    flash("User has been rejected", "danger")
    return redirect(url_for('admin_dashboard'))

# ================= PENDING REQUESTS =================
@app.route('/pending_requests')
@admin_required
def pending_requests():
    cur = mysql.connection.cursor()

    # 📌 1. Pending users list
    cur.execute("""
        SELECT id, name, login_id, email, role, department, designation, created_at 
        FROM user 
        WHERE status='Pending' 
        ORDER BY id DESC
    """)
    users = cur.fetchall()

    # 📊 2. Pending count
    cur.execute("SELECT COUNT(*) FROM user WHERE status='Pending'")
    pending_count = cur.fetchone()[0]

    # 📊 3. Approved TODAY users
    cur.execute("""
        SELECT COUNT(*) 
        FROM user 
        WHERE status='Approved' 
        AND DATE(created_at)=CURDATE()
    """)
    approved_today = cur.fetchone()[0]

    # 📊 4. Rejected users
    cur.execute("SELECT COUNT(*) FROM user WHERE status='Rejected'")
    rejected_count = cur.fetchone()[0]

    # 📊 5. TOTAL approved users (IMPORTANT FIX)
    cur.execute("SELECT COUNT(*) FROM user WHERE status='Approved'")
    total_approved = cur.fetchone()[0]

    # 📊 6. TOTAL users
    cur.execute("SELECT COUNT(*) FROM user")
    total_users = cur.fetchone()[0]

    cur.close()

    return render_template(
        "admin/pending_requests.html",
        users=users,

        # header stats
        header_pending_count=pending_count,
        header_approved_count=approved_today,

        # cards stats (clear naming)
        stat_pending=pending_count,
        stat_approved_today=approved_today,
        stat_approved=total_approved,
        stat_rejected=rejected_count,
        stat_total_users=total_users,

        active_page='pending'
    )
#==================LOGIN =================
@app.route('/login', methods=['GET','POST'])
def login():

    if request.method == 'POST':
        login_id = request.form['login_id']
        password = request.form['password']

        cur = mysql.connection.cursor()
        cur.execute("SELECT * FROM user WHERE login_id=%s", (login_id,))
        user = cur.fetchone()
        cur.close()

        if not user:
            flash("Invalid Login ID", "danger")
            return redirect(url_for('login'))

        # 🔴 FORCE FORGOT PASSWORD FIRST
        if user[10] == 0:
            flash("⚠ First reset your password!", "warning")
            return redirect(url_for('forgot_password'))

        # 🔐 password check
        if not check_password_hash(user[4], password):
            flash("Wrong password", "danger")
            return redirect(url_for('login'))

        # 🔴 ADMIN APPROVAL
        if user[6] != 'Approved':
            flash("⛔ Waiting for admin approval", "danger")
            return redirect(url_for('login'))

        # ✅ LOGIN SUCCESS
        session['user_id'] = user[0]
        session['name'] = user[1]
        session['role'] = user[5]

        # 🔥 ADD THIS
        add_activity(user[0], "User Logged In")

        if user[5] == 'HR':
            return redirect(url_for('hr_dashboard'))
        else:
            return redirect(url_for('emp_dashboard'))

    return render_template('login.html')

# ================= EMPLOYEE DASHBOARD =================
@app.route('/emp_dashboard')
@login_required
def emp_dashboard():
    if session.get('role') != 'Employee':
        return redirect(url_for('hr_dashboard'))

    cur = mysql.connection.cursor()
    user_id = session['user_id']

    # 🔍 SEARCH VALUE
    search = request.args.get('search')

    # 📊 TOTAL
    cur.execute("SELECT COUNT(*) FROM Document WHERE uploaded_by=%s", (user_id,))
    total_docs = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM Document WHERE uploaded_by=%s AND status='Verified'", (user_id,))
    verified_docs = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM Document WHERE uploaded_by=%s AND status='Pending'", (user_id,))
    pending_docs = cur.fetchone()[0]

    # 📦 STORAGE
    cur.execute("SELECT COALESCE(SUM(file_size),0) FROM Document WHERE uploaded_by=%s", (user_id,))
    total_storage = cur.fetchone()[0]
    total_storage_mb = round(total_storage / (1024 * 1024), 2)

    # =========================
    # 📄 MY DOCUMENTS (SEARCH)
    # =========================
    my_query = """
        SELECT id, title, file_name, file_type, upload_date, status, category
        FROM Document
        WHERE uploaded_by=%s
    """
    my_params = [user_id]

    if search:
        my_query += """
            AND (
                title LIKE %s OR
                file_name LIKE %s OR
                category LIKE %s OR
                status LIKE %s
            )
        """
        like = f"%{search}%"
        my_params.extend([like, like, like, like])

    my_query += " ORDER BY upload_date DESC LIMIT 10"

    cur.execute(my_query, tuple(my_params))
    my_documents = cur.fetchall()

    # =========================
    # 🔔 RECENT ACTIVITY (SEARCH)
    # =========================
    activity_query = """
        SELECT 
            d.id,
            d.title,
            d.file_name,
            d.file_type,
            d.upload_date,
            d.status,
            u.name
        FROM Document d
        JOIN user u ON d.uploaded_by = u.id
        WHERE d.user_id=%s AND d.uploaded_by!=%s
    """
    activity_params = [user_id, user_id]

    if search:
        activity_query += """
            AND (
                d.title LIKE %s OR
                d.file_name LIKE %s OR
                d.status LIKE %s OR
                u.name LIKE %s
            )
        """
        like = f"%{search}%"
        activity_params.extend([like, like, like, like])

    activity_query += " ORDER BY d.upload_date DESC"

    cur.execute(activity_query, tuple(activity_params))
    recent_activity = cur.fetchall()

    cur.close()

    return render_template(
        'EMP/emp_dashboard.html',
        total_docs=total_docs,
        verified_docs=verified_docs,
        pending_docs=pending_docs,
        total_storage=total_storage_mb,
        my_documents=my_documents,
        recent_activity=recent_activity,
        search=search
    )
# ================= MY DOCUMENTS =================
@app.route('/my_documents')
@login_required
def my_document():
    cur = mysql.connection.cursor()
    user_id = session['user_id']

    search = request.args.get('search')  # 👈 GET se search value

    query = """
        SELECT 
            d.id,
            u.name,
            d.title,
            d.category,
            d.upload_date,
            d.status,
            d.file_name
        FROM Document d
        JOIN user u ON d.uploaded_by = u.id
        WHERE d.uploaded_by = %s
    """

    params = [user_id]

    # 🔍 SAME SEARCH LOGIC (HR jaisa)
    if search:
        query += """
            AND (
                u.name LIKE %s OR
                d.title LIKE %s OR
                d.category LIKE %s OR
                d.status LIKE %s OR
                d.file_name LIKE %s
            )
        """
        like = f"%{search}%"
        params.extend([like, like, like, like, like])

    query += " ORDER BY d.upload_date DESC"

    cur.execute(query, params)
    documents = cur.fetchall()
    cur.close()

    return render_template(
        'EMP/my_document.html',
        documents=documents,
        search=search
    )
# ================= UPLOAD DOCUMENT =================
@app.route('/upload_document', methods=['GET', 'POST'])
@login_required
def upload_document():

    cur = mysql.connection.cursor()

    role = session.get('role')
    current_user = session.get('user_id')

    # 🔥 HR → employees list
    if role == 'HR':
        cur.execute("SELECT id, name FROM user WHERE role='Employee'")
        users = cur.fetchall()

    # 🔥 Employee → HR list
    else:
        cur.execute("SELECT id, name FROM user WHERE role='HR'")
        users = cur.fetchall()

    if request.method == 'POST':

        title = request.form.get('title')
        category = request.form.get('category')
        description = request.form.get('description')
        file = request.files.get('file')
        receiver_id = request.form.get('receiver_id')

        if not file:
            flash("Select file!", "danger")
            return redirect(request.url)

        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)

        file_type = filename.split('.')[-1]
        file_size = os.path.getsize(file_path)

        # 🔥 INSERT DOCUMENT
        cur.execute("""
        INSERT INTO Document
        (user_id, uploaded_by, title, file_name, file_type,
         file_size, category, description, status, is_private)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            receiver_id,
            current_user,
            title,
            filename,
            file_type,
            file_size,
            category,
            description,
            "Pending",
            0
        ))

        mysql.connection.commit()

        # 🔥 BOTH SIDE ACTIVITY LOG
        add_activity(current_user, f"You uploaded document '{title}'")
        add_activity(receiver_id, f"New document '{title}' received")

        flash("Document sent successfully!", "success")

        # 🔥 ROLE BASED REDIRECT
        if role == 'HR':
            return redirect(url_for('hr_dashboard'))
        else:
            return redirect(url_for('emp_dashboard'))

    cur.close()

    return render_template('EMP/upload_document.html', users=users)
# ================= ACTIVITY LOG =================
@app.route('/activity_log')
@admin_required
def activity_log():
    search = request.args.get('search', '')

    cur = mysql.connection.cursor()

    if search:
        query = """
            SELECT u.name, a.action, a.created_at
            FROM activity_log a
            JOIN user u ON a.user_id = u.id
            WHERE u.name LIKE %s 
               OR a.action LIKE %s 
               OR a.created_at LIKE %s
            ORDER BY a.created_at DESC
        """
        like = f"%{search}%"
        cur.execute(query, (like, like, like))
    else:
        cur.execute("""
            SELECT u.name, a.action, a.created_at
            FROM activity_log a
            JOIN user u ON a.user_id = u.id
            ORDER BY a.created_at DESC
        """)

    logs = cur.fetchall()
    cur.close()

    return render_template('admin/activity_log.html', logs=logs)
# ================= DOWNLOAD =================
@app.route('/download/<int:doc_id>')
@login_required
def download(doc_id):
    cur = mysql.connection.cursor()

    if session.get('role') == 'HR':
        cur.execute("SELECT file_name FROM Document WHERE id=%s AND is_private=FALSE", (doc_id,))
    else:
        cur.execute("SELECT file_name FROM Document WHERE id=%s AND user_id=%s",
                    (doc_id, session['user_id']))

    Document = cur.fetchone()
    cur.close()

    if Document:
        return send_from_directory(app.config['UPLOAD_FOLDER'], Document[0], as_attachment=True)
    else:
        flash("File not found or access denied!", "danger")
        return redirect(url_for('my_document' if session.get('role') != 'HR' else 'hr_dashboard'))

# ================= DELETE DOCUMENT =================
@app.route('/delete/<int:doc_id>')
@login_required
def delete_document(doc_id):
    cur = mysql.connection.cursor()
    cur.execute("SELECT file_name FROM Document WHERE id=%s AND user_id=%s",
                (doc_id, session['user_id']))
    file = cur.fetchone()

    if file:
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], file[0])
        if os.path.exists(file_path):
            os.remove(file_path)

        cur.execute("DELETE FROM Document WHERE id=%s AND user_id=%s", (doc_id, session['user_id']))
        mysql.connection.commit()
        add_activity(session['user_id'], f"Deleted document: {file[0]}")
        flash("Document deleted successfully!", "success")
    else:
        flash("Document not found!", "danger")

    cur.close()
    return redirect(url_for('my_document'))


# ================= HR DASHBOARD =================
@app.route('/hr_dashboard')
@hr_required
def hr_dashboard():

    cur = mysql.connection.cursor()
    hr_id = session['user_id']
    search = request.args.get('search')

    # 👥 TOTAL EMPLOYEES (GLOBAL - OK)
    cur.execute("SELECT COUNT(*) FROM user WHERE role='Employee'")
    total_employees = cur.fetchone()[0]

    # 📄 TOTAL DOCUMENTS (ONLY THIS HR)
    cur.execute("""
        SELECT COUNT(*) 
        FROM Document 
        WHERE uploaded_by = %s
    """, (hr_id,))
    total_documents = cur.fetchone()[0]

    # 📊 STATUS COUNT (ONLY THIS HR)
    cur.execute("""
        SELECT status, COUNT(*) 
        FROM Document 
        WHERE uploaded_by = %s
        GROUP BY status
    """, (hr_id,))
    status_data = dict(cur.fetchall())

    verified_documents = status_data.get('Verified', 0)
    pending_documents = status_data.get('Pending', 0)
    rejected_documents = status_data.get('Rejected', 0)

    # 🔥 RECENT DOCUMENTS (ONLY THIS HR)
    query = """
        SELECT 
            d.id,
            u.name,
            d.title,
            d.category,
            d.upload_date,
            d.status
        FROM Document d
        JOIN user u ON d.uploaded_by = u.id
        WHERE d.uploaded_by = %s
    """

    params = [hr_id]

    # 🔍 SEARCH FILTER
    if search:
        query += """
            AND (
                u.name LIKE %s OR
                d.title LIKE %s OR
                d.category LIKE %s OR
                d.status LIKE %s
            )
        """
        like = f"%{search}%"
        params.extend([like, like, like, like])

    query += " ORDER BY d.upload_date DESC LIMIT 10"

    cur.execute(query, params)
    recent_documents = cur.fetchall()

    # 🔔 NOTIFICATIONS (ONLY THIS HR)
    query2 = """
        SELECT d.id, u.name, d.title, d.upload_date
        FROM Document d
        JOIN user u ON d.uploaded_by = u.id
        WHERE d.uploaded_by = %s
        AND d.status = 'Pending'
    """

    params2 = [hr_id]

    if search:
        query2 += """
            AND (
                u.name LIKE %s OR
                d.title LIKE %s
            )
        """
        like = f"%{search}%"
        params2.extend([like, like])

    query2 += " ORDER BY d.upload_date DESC LIMIT 5"

    cur.execute(query2, params2)
    notifications = cur.fetchall()

    # 🔔 UNREAD MESSAGES
    cur.execute("""
        SELECT COUNT(*) 
        FROM support_messages
        WHERE hr_id = %s
        AND reply IS NULL
        AND is_seen = FALSE
    """, (hr_id,))

    unread = cur.fetchone()[0]

    cur.close()

    return render_template(
        "HR/hr_dashboard.html",
        total_employees=total_employees,
        total_documents=total_documents,
        verified_documents=verified_documents,
        pending_documents=pending_documents,
        rejected_documents=rejected_documents,
        recent_documents=recent_documents,
        notifications=notifications,
        unread=unread
    )
# ================= HR ALL DOCUMENTS =================
@app.route('/hr_all_documents')
@hr_required
def hr_all_documents():
    cur = mysql.connection.cursor()

    search = request.args.get('search')  # 👈 GET se value le

    query = """
        SELECT 
            d.id, 
            u.name,
            d.title, 
            d.category, 
            d.upload_date, 
            d.status, 
            d.file_name
        FROM Document d
        JOIN user u ON d.uploaded_by = u.id
        WHERE d.user_id = %s
        AND d.uploaded_by != %s
    """

    params = [session['user_id'], session['user_id']]

    # 🔍 SEARCH FILTER
    if search:
        query += """
            AND (
                u.name LIKE %s OR
                u.email LIKE %s OR
                u.department LIKE %s OR
                d.title LIKE %s OR
                d.category LIKE %s
            )
        """
        like = f"%{search}%"
        params.extend([like, like, like, like, like])

    query += " ORDER BY d.upload_date DESC"

    cur.execute(query, params)
    documents = cur.fetchall()
    cur.close()

    return render_template('HR/hr_all_documents.html', documents=documents)
# ================= HR EMPLOYEES =================
@app.route('/hr_employees')
@hr_required
def hr_employees():
    employee_id = request.args.get('employee_id')
    search = request.args.get('search', '')

    cur = mysql.connection.cursor()

    # ---------------------------
    # EMPLOYEES LIST (FIXED QUERY)
    # ---------------------------
    query = """
        SELECT 
            u.id,
            u.name,
            u.email,
            u.login_id,
            u.department,
            u.phone,
            u.designation,
            COUNT(d.id) AS total_docs,
            SUM(CASE WHEN d.status='Verified' THEN 1 ELSE 0 END) AS verified_docs,
            SUM(CASE WHEN d.status='Pending' THEN 1 ELSE 0 END) AS pending_docs
        FROM user u
        LEFT JOIN Document d ON u.id = d.user_id
        WHERE u.role='Employee'
    """

    params = []

    # ---------------------------
    # SEARCH FILTER
    # ---------------------------
    if search:
        query += """
            AND (
                u.name LIKE %s OR
                u.email LIKE %s OR
                u.department LIKE %s OR
                u.login_id LIKE %s
            )
        """
        like = f"%{search}%"
        params.extend([like, like, like, like])

    query += " GROUP BY u.id ORDER BY u.name"

    cur.execute(query, params)
    employees = cur.fetchall()

    # ---------------------------
    # SELECTED EMPLOYEE DOCUMENTS
    # ---------------------------
    selected_employee = None
    documents = []

    total_documents = 0
    verified_documents = 0
    pending_documents = 0
    rejected_documents = 0

    if employee_id:
        cur.execute("""
            SELECT id, name, email, login_id, department, phone
            FROM user
            WHERE id=%s
        """, (employee_id,))
        selected_employee = cur.fetchone()

        cur.execute("""
            SELECT id, file_name, category, upload_date, status
            FROM Document
            WHERE user_id=%s
        """, (employee_id,))
        documents = cur.fetchall()

        total_documents = len(documents)
        verified_documents = len([d for d in documents if d[4] == 'Verified'])
        pending_documents = len([d for d in documents if d[4] == 'Pending'])
        rejected_documents = len([d for d in documents if d[4] == 'Rejected'])

    cur.close()

    return render_template(
        "HR/hr_employees.html",
        employees=employees,
        selected_employee=selected_employee,
        documents=documents,
        total_documents=total_documents,
        verified_documents=verified_documents,
        pending_documents=pending_documents,
        rejected_documents=rejected_documents
    )

# ================= ANALYTICS =================
@app.route('/HR/analytics_page')
def analytics_page():
    cur = mysql.connection.cursor()

    cur.execute("""
        SELECT u.name, d.category, d.file_name
        FROM user u
        JOIN document d ON u.id = d.user_id
        WHERE u.role='Employee'
    """)

    data = cur.fetchall()
    cur.close()

    from collections import defaultdict

    categories = ["Personal", "Office", "Education", "Finance"]

    emp_files = defaultdict(lambda: {cat: [] for cat in categories})

    for name, category, file_name in data:
        if category in categories:
            emp_files[name][category].append(file_name)

    names = list(emp_files.keys())
    

    # 👉 counts for graph
    dataset = {cat: [] for cat in categories}

    for name in names:
        for cat in categories:
            dataset[cat].append(len(emp_files[name][cat]))

    # 🔥 INSIGHTS LOGIC START

    # 📊 Total per category
    category_totals = {cat: sum(dataset[cat]) for cat in categories}

    # 🥇 Top category
    top_category = max(category_totals, key=category_totals.get) if category_totals else "N/A"

    # 📁 Total documents
    total_docs = sum(category_totals.values())

    # 👤 Most active employee
    emp_total = {name: sum(emp_files[name][cat] and len(emp_files[name][cat]) or 0 for cat in categories) for name in names}
    top_employee = max(emp_total, key=emp_total.get) if emp_total else "N/A"

    return render_template(
        'HR/analytics_page.html',
        names=names,
        dataset=dataset,
        emp_files=emp_files,
        top_category=top_category,
        total_docs=total_docs,
        top_employee=top_employee
    )
#========= VERIFY DOCUMENT =================
@app.route('/verify_document/<int:id>')
@hr_required
def verify_document(id):
    cur = mysql.connection.cursor()
    cur.execute("UPDATE document SET status='Verified' WHERE id=%s", (id,))
    mysql.connection.commit()
    add_activity(session['user_id'], f"Verified document ID: {id}")
    cur.close()

    flash("Document verified successfully!", "success")
    return redirect(request.referrer or url_for('hr_dashboard'))

# ================= REJECT DOCUMENT =================
@app.route('/reject_document/<int:id>')
@hr_required
def reject_document(id):
    cur = mysql.connection.cursor()
    cur.execute("UPDATE document SET status='Rejected' WHERE id=%s", (id,))
    mysql.connection.commit()
    add_activity(session['user_id'], f"Rejected document ID: {id}")
    cur.close()

    flash("Document rejected!", "danger")
    return redirect(request.referrer or url_for('hr_dashboard'))


# =================  EMPLOYEE PROFILE =================
@app.route('/emp_profile', methods=['GET', 'POST'])
def emp_profile():
    user_id = session['user_id']
    cur = mysql.connection.cursor()

    if request.method == 'POST':
        name = request.form['name']
        department = request.form['department']
        designation = request.form['designation']
        phone = request.form['phone']

        cur.execute("""
            UPDATE user 
            SET name=%s, department=%s, designation=%s, phone=%s
            WHERE id=%s
        """, (name, department, designation, phone, user_id))

        mysql.connection.commit()
        mysql.connection.commit()

        add_activity(session['user_id'], "Updated profile")
        flash("Profile Updated Successfully!", "success")

    cur.execute("SELECT * FROM user WHERE id=%s", (user_id,))
    user = cur.fetchone()
    cur.close()

    return render_template('EMP/emp_profile.html', user=user)



# ================= HR PROFILE PAGE =================
@app.route('/hr_profile', methods=['GET', 'POST'])
@hr_required
def hr_profile():

    cur = mysql.connection.cursor()
    user_id = session['user_id']

    if request.method == 'POST':

        name = request.form.get('full_name')
        email = request.form.get('email')
        phone = request.form.get('phone')
        department = request.form.get('department')
        designation = request.form.get('designation')
        address = request.form.get('address')

        cur.execute("""
            UPDATE user SET
            name=%s,
            email=%s,
            phone=%s,
            department=%s,
            designation=%s,
            address=%s
            WHERE id=%s
        """, (name, email, phone, department, designation, address, user_id))

        mysql.connection.commit()

    cur.execute("SELECT * FROM user WHERE id=%s", (user_id,))
    user = cur.fetchone()
    cur.close()

    return render_template("HR/hr_profile.html", user=user)
# ================= LOGOUT =================
@app.route('/logout')
def logout():
    if 'user_id' in session:
        add_activity(session['user_id'], "User Logged Out")  # 👈

    session.clear()
    flash("You have been logged out", "info")
    return redirect(url_for('index'))

# ================= VIEW DOCUMENT =================

from flask import send_from_directory, abort
import os

UPLOAD_FOLDER = 'static/uploads'

@app.route('/view_document/<int:doc_id>')
def view_document(doc_id):
    cur = mysql.connection.cursor()
    cur.execute("SELECT file_name, file_type FROM Document WHERE id=%s", (doc_id,))
    result = cur.fetchone()

    if result:
        file_name, file_type = result
        file_path = os.path.join(UPLOAD_FOLDER, file_name)

        if os.path.exists(file_path):
            # Open in browser (inline) or force download with as_attachment=True
            return send_from_directory(UPLOAD_FOLDER, file_name)
        else:
            return "File not found", 404
    else:
        return "Document not found", 404
# ================= FORGOT PASSWORD =================
@app.route('/forgot_password', methods=['GET','POST'])
def forgot_password():

    if request.method == 'POST':
        login_id = request.form['login_id'].strip()

        cur = mysql.connection.cursor()
        cur.execute("SELECT * FROM user WHERE LOWER(login_id)=LOWER(%s)", (login_id,))
        user = cur.fetchone()
        cur.close()

        if not user:
            flash("Login ID not found!", "danger")
            return redirect(url_for('forgot_password'))

        # ✅ SAME SESSION
        session['reset_user_id'] = user[0]

        flash("Now set your new password", "success")
        return redirect(url_for('reset_password'))

    return render_template('forgot_password.html')
#======== RESET PASSWORD =================
import re
from flask import request, flash, redirect, url_for, render_template

@app.route('/reset_password', methods=['GET', 'POST'])
def reset_password():
    if request.method == 'POST':
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')

        # 1. Match check
        if new_password != confirm_password:
            flash("❌ Passwords do not match", "danger")
            return redirect(url_for('reset_password'))

        # 2. Strong password check
        pattern = r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&]).{8,}$'
        if not re.match(pattern, new_password):
            flash("⚠️ Password must be strong (8+ chars, A-Z, a-z, number, special char)", "warning")
            return redirect(url_for('reset_password'))

        # 3. Hash password (IMPORTANT 🔐)
        from werkzeug.security import generate_password_hash
        hashed_password = generate_password_hash(new_password)

        # 4. Update DB
        cur = mysql.connection.cursor()
        cur.execute("UPDATE users SET password=%s WHERE id=%s", (hashed_password, session['user_id']))
        mysql.connection.commit()

        flash("✅ Password updated successfully!", "success")
        return redirect(url_for('login'))

    return render_template('reset_password.html')
# ===============================
# 📄 STATIC PAGES
# ===============================

@app.route('/privacy')
def privacy():
    return render_template('privacy.html')


@app.route('/terms')
def terms():
    return render_template('terms.html')


# ===============================
# About
# ===============================

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/help')
@login_required
def help_page():

    cur = mysql.connection.cursor()

    # 📩 Employee messages
    cur.execute("""
        SELECT * FROM support_messages 
        WHERE sender_id=%s 
        ORDER BY id DESC
    """, (session['user_id'],))
    messages = cur.fetchall()

    # 👨‍💼 HR list
    cur.execute("SELECT id, name FROM user WHERE role='HR'")
    hr_list = cur.fetchall()

    # 🔔 1. unread count FIRST  ✅
    cur.execute("""
        SELECT COUNT(*) FROM support_messages
        WHERE sender_id=%s 
        AND reply IS NOT NULL
        AND is_seen=FALSE
    """, (session['user_id'],))

    unread = cur.fetchone()[0]

    # 👀 2. THEN mark as seen ✅
    cur.execute("""
        UPDATE support_messages
        SET is_seen=TRUE
        WHERE sender_id=%s AND reply IS NOT NULL
    """, (session['user_id'],))

    mysql.connection.commit()
    cur.close()

    return render_template(
        "EMP/help.html",
        messages=messages,
        hr_list=hr_list,
        unread=unread
    )
@app.route('/send_message', methods=['POST'])
@login_required
def send_message():
    message = request.form['message'].strip()
    sender_id = session['user_id']
    hr_id = request.form['hr_id']

    cur = mysql.connection.cursor()

    cur.execute("""
    INSERT INTO support_messages (sender_id, hr_id, message, is_seen)
    VALUES (%s, %s, %s, FALSE)
""", (sender_id, hr_id, message))

    mysql.connection.commit()
    cur.close()

    return redirect(url_for('help_page'))
@app.route('/hr_messages')
@hr_required
def hr_messages():

    cur = mysql.connection.cursor()

    # 📩 Only messages for THIS HR ✅
    cur.execute("""
        SELECT * FROM support_messages
        WHERE hr_id=%s
        ORDER BY id DESC
    """, (session['user_id'],))
    messages = cur.fetchall()

    # 🔔 unread count
    cur.execute("""
        SELECT COUNT(*) FROM support_messages
        WHERE hr_id=%s 
        AND reply IS NULL
        AND is_seen=FALSE
    """, (session['user_id'],))
    unread = cur.fetchone()[0]

    # 👀 mark as seen
    cur.execute("""
        UPDATE support_messages
        SET is_seen=TRUE
        WHERE hr_id=%s AND reply IS NULL
    """, (session['user_id'],))

    mysql.connection.commit()
    cur.close()

    return render_template(
        "HR/hr_message.html",
        messages=messages,
        unread=unread
    )
@app.route('/hr_message/<int:id>', methods=['POST'])
@hr_required
def hr_message(id):

    reply = request.form.get('reply')

    cur = mysql.connection.cursor()

    cur.execute("""
        UPDATE support_messages
        SET reply=%s, status='Resolved', is_seen=FALSE
        WHERE id=%s
    """, (reply, id))

    mysql.connection.commit()
    cur.close()

    return redirect(url_for('hr_messages'))
# ================= RUN =================
if __name__ == "__main__":
    webbrowser.open("http://127.0.0.1:5000/")
    app.run(debug=True)