# server/app.py
from flask import Flask, request, render_template, redirect, url_for, session, jsonify
from pymongo import MongoClient
from functools import wraps
from dotenv import load_dotenv
import os, datetime, requests, re
from bson.objectid import ObjectId

load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "super_secret_key")

MONGO_URI = os.getenv("MONGO_URI")
client = MongoClient(MONGO_URI) if MONGO_URI else MongoClient()
db = client.get_database(os.getenv("MONGO_DBNAME", "clou2"))
links_collection = db.links
settings_collection = db.settings

# Simple admin check (keeps compatibility with original project)
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

@app.route('/login', methods=['GET', 'POST'])
def login():
    # very simple login page (preserve original behaviour)
    if request.method == 'POST':
        user = request.form.get('username')
        pwd = request.form.get('password')
        if user == os.getenv('ADMIN_USER') and pwd == os.getenv('ADMIN_PASS'):
            session['logged_in'] = True
            return redirect(url_for('dashboard'))
        return render_template('login.html', error='Invalid credentials')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/')
def index():
    return redirect(url_for('dashboard'))

@app.route('/dashboard')
@login_required
def dashboard():
    # show links that are not deleted
    all_links = list(links_collection.find({'deleted': {'$ne': True}}).sort('added_at', -1))
    return render_template('dashboard.html', links=all_links)

@app.route('/deleted')
@login_required
def deleted():
    # show soft-deleted links
    dead = list(links_collection.find({'deleted': True}).sort('added_at', -1))
    return render_template('deleted.html', links=dead)

@app.route('/restore/<link_id>', methods=['POST'])
@login_required
def restore_link(link_id):
    links_collection.update_one({'_id': ObjectId(link_id)}, {'$set': {'deleted': False}})
    return redirect(url_for('deleted'))

@app.route('/api/add_link', methods=['POST'])
def api_add_link():
    try:
        data = request.get_json()
        url = data.get('url')
        filename = data.get('filename') or None
        if not url:
            return jsonify({'status':'error','message':'No URL provided'}),400

        # basic filename extraction if not provided
        if not filename:
            try:
                # try Content-Disposition
                h = requests.head(url, allow_redirects=True, timeout=5)
                cd = h.headers.get('content-disposition')
                if cd:
                    m = re.search(r'filename\*=UTF-8\'\'([^;]+)|filename=\"?([^\";]+)\"?', cd)
                    if m:
                        filename = m.group(1) or m.group(2)
            except Exception:
                filename = None

        if not filename:
            filename = url.split('/')[-1] or 'File'

        # detect google drive file id if present
        file_id = None
        m = re.search(r'/d/([a-zA-Z0-9_-]+)', url)
        if not m:
            m = re.search(r'id=([a-zA-Z0-9_-]+)', url)
        if m:
            file_id = m.group(1)

        link_doc = {
            'original_url': url,
            'filename': filename,
            'file_id': file_id,
            'added_at': datetime.datetime.utcnow(),
            'deleted': False
        }
        res = links_collection.insert_one(link_doc)
        link_doc['_id'] = str(res.inserted_id)
        return jsonify({'status':'success','link':{'_id':str(res.inserted_id),'filename':filename}})
    except Exception as e:
        return jsonify({'status':'error','message':str(e)}),500

@app.route('/delete/<link_id>', methods=['POST'])
@login_required
def delete_link(link_id):
    # soft delete
    links_collection.update_one({'_id': ObjectId(link_id)}, {'$set': {'deleted': True}})
    return redirect(url_for('dashboard'))

@app.route('/download/<link_id>')
def download_page(link_id):
    try:
        link_info = links_collection.find_one({'_id': ObjectId(link_id)})
        if not link_info:
            return '❌ লিঙ্কটি খুঁজে পাওয়া যায়নি।', 404

        # prepare final link
        if link_info.get('file_id'):
            final_download_link = f"https://drive.google.com/uc?export=download&id={link_info['file_id']}"
        else:
            final_download_link = link_info.get('original_url')

        ads = settings_collection.find_one() or {}
        current_year = datetime.datetime.utcnow().year
        return render_template('file.html', link_info=link_info, ads=ads, final_download_link=final_download_link, current_year=current_year)
    except Exception as e:
        return f"An error occurred: {e}", 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 10000)))
