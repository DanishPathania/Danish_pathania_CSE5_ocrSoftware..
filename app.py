

from flask import Flask, render_template, request, redirect, url_for, session, flash
import pytesseract
from PIL import Image
import os
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
from pymongo import MongoClient
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'

UPLOAD_FOLDER = 'static/uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# MongoDB setup
client = MongoClient("mongodb://localhost:27017/")
mongo_db = client['ocrApp']
users_collection = mongo_db['users']
admins_collection = mongo_db['admins']
extracted_data_collection = mongo_db['extractedData']  # Initialize extracted data collection

# --- AUTH ROUTES ---
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = generate_password_hash(request.form['password'])
        email = request.form['email']

        if users_collection.find_one({"username": username}):
            flash("Username already exists", "danger")
            return render_template('register.html')

        users_collection.insert_one({
            "username": username,
            "password": password,
            "email": email,
            "created_at": datetime.utcnow()
        })

        flash("Registration successful! Please log in.", "success")
        return redirect(url_for('login'))
    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password_input = request.form['password']

        user = users_collection.find_one({"username": username})
        if user and check_password_hash(user["password"], password_input):
            session['user_id'] = str(user["_id"])
            session['username'] = username
            return redirect(url_for('index'))
        else:
            flash("Invalid credentials", "danger")
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# --- MAIN APP ROUTES ---
@app.route('/', methods=['GET', 'POST'])
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    text = ''
    results = get_user_data(session['user_id'])

    if request.method == 'POST':
        file = request.files['image']
        if file:
            filepath = os.path.join(UPLOAD_FOLDER, file.filename)
            file.save(filepath)
            image = Image.open(filepath)
            text = pytesseract.image_to_string(image)
            return render_template('index.html', text=text, image=file.filename, saved_data=results)
    return render_template('index.html', text=text, saved_data=results)


@app.route('/save', methods=['POST'])
def save():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    number = request.form['number']
    text = request.form['text']
    user_id = session['user_id']

    with sqlite3.connect('database.db') as conn:
        conn.execute("INSERT INTO userdata (user_id, number, text) VALUES (?, ?, ?)", (user_id, number, text))
    return redirect(url_for('index'))

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return "No file part"
    
    file = request.files['file']
    
    if file.filename == '':
        return "No selected file"
    
    if file:
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
        file.save(filepath)
        
        # Perform OCR
        text = extract_text_from_image(filepath)
        
        # Save extracted data to MongoDB
        extracted_data_collection.insert_one({
            'username': session.get('user'),  # Assuming user is stored in session after login
            'filename': file.filename,
            'extracted_text': text,
            'timestamp': datetime.utcnow()
        })
        
        return render_template('result.html', extracted_text=text)

@app.route('/search', methods=['POST'])
def search():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    number = request.form.get('search_number', '')
    with sqlite3.connect('database.db') as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT text FROM userdata WHERE user_id = ? AND number = ?", (session['user_id'], number))
        result = cursor.fetchone()
    return render_template('index.html', result=result[0] if result else 'No data found!', saved_data=get_user_data(session['user_id']))

# --- Admin Setup (Create One-Time Admin Account if Needed) ---
def ensure_default_admin():
    if not admins_collection.find_one({"username": "Danish"}):
        admins_collection.insert_one({
            "username": "Danish",
            "password": generate_password_hash("Pathania12"),
            "role": "superadmin",
            "created_at": datetime.utcnow()
        })
ensure_default_admin()

# --- Admin Login ---
@app.route('/admin_login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        admin = admins_collection.find_one({'username': username, 'password': password})
        if admin:
            session['admin'] = username
            return redirect(url_for('admin_user_details'))  # Make sure this matches
        return "Invalid credentials"
    return render_template('admin_login.html')

@app.route('/admin_user_details')  # Must match above
def admin_user_details():
    if 'admin' not in session:
        return redirect(url_for('admin_login'))
    users = list(users_collection.find({}, {'_id': 0}))
    return render_template('admin_user_details.html', users=users)

# --- ADMIN DASHBOARD ---
@app.route('/admin')
def admin_dashboard():
    if session.get('admin'):
        all_users = list(users_collection.find())
        all_admins = list(admins_collection.find())
        return render_template('admin.html', users=all_users, admins=all_admins)
    return redirect(url_for('admin_login'))

@app.route('/admin-logout')
def admin_logout():
    session.pop('admin', None)
    session.pop('admin_user', None)
    return redirect(url_for('admin_login'))
# --- HELPER ---
def extract_text_from_image(filepath):
    """Extract text from an image file using pytesseract."""
    try:
        image = Image.open(filepath)
        return pytesseract.image_to_string(image)
    except Exception as e:
        return f"Error extracting text: {e}"


def get_user_data(user_id):
    with sqlite3.connect('database.db') as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT number, text FROM userdata WHERE user_id = ?", (user_id,))
        return dict(cursor.fetchall())

if __name__ == '__main__':
    app.run(debug=True)