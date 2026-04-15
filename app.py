from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import json, os, requests
from functools import wraps
from datetime import timedelta

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'halla-encom-credit-2026')
app.permanent_session_lifetime = timedelta(hours=8)

USERS_FILE = 'users.json'
GOOGLE_API_KEY = os.environ.get('GOOGLE_API_KEY', '')
GEMINI_URL = 'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent'

# ─── 사용자 관리 ───────────────────────────────────────────
def load_users():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, encoding='utf-8') as f:
            return json.load(f)
    default = {"admin": {"password": "admin1234", "role": "admin", "name": "관리자"}}
    save_users(default)
    return default

def save_users(users):
    with open(USERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(users, f, ensure_ascii=False, indent=2)

# ─── 인증 데코레이터 ───────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'username' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'username' not in session:
            return jsonify({'error': '로그인이 필요합니다'}), 401
        users = load_users()
        if users.get(session['username'], {}).get('role') != 'admin':
            return jsonify({'error': '관리자 권한이 필요합니다'}), 403
        return f(*args, **kwargs)
    return decorated

# ─── 인증 라우트 ───────────────────────────────────────────
@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'username' in session:
        return redirect(url_for('index'))
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        users = load_users()
        if username in users and users[username]['password'] == password:
            session.permanent = True
            session['username'] = username
            session['name'] = users[username].get('name', username)
            session['role'] = users[username].get('role', 'user')
            return redirect(url_for('index'))
        error = '아이디 또는 비밀번호가 올바르지 않습니다.'
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    return render_template('index.html',
        username=session.get('username'),
        name=session.get('name'),
        role=session.get('role'))

# ─── AI 분석 API (Gemini 2.5 Flash) ───────────────────────
@app.route('/api/analyze', methods=['POST'])
@login_required
def analyze():
    if not GOOGLE_API_KEY:
        return jsonify({'error': '서버에 Google API 키가 설정되지 않았습니다. 관리자에게 문의하세요.'}), 500

    data = request.json
    pdf_base64 = data.get('pdf_base64')
    prompt = data.get('prompt', '')

    if not pdf_base64:
        return jsonify({'error': 'PDF 데이터가 없습니다.'}), 400

    try:
        resp = requests.post(
            f'{GEMINI_URL}?key={GOOGLE_API_KEY}',
            headers={'Content-Type': 'application/json'},
            json={
                'contents': [{
                    'parts': [
                        {
                            'inline_data': {
                                'mime_type': 'application/pdf',
                                'data': pdf_base64
                            }
                        },
                        {
                            'text': prompt
                        }
                    ]
                }],
                'generationConfig': {
                    'temperature': 0.1,
                    'maxOutputTokens': 2000
                }
            },
            timeout=120
        )

        result = resp.json()

        if 'error' in result:
            msg = result['error'].get('message', 'Gemini API 오류')
            return jsonify({'error': msg}), 500

        text = result['candidates'][0]['content']['parts'][0]['text']
        return jsonify({'text': text})

    except requests.Timeout:
        return jsonify({'error': '분석 시간이 초과되었습니다. 다시 시도해주세요.'}), 504
    except Exception as e:
        return jsonify({'error': f'분석 중 오류: {str(e)}'}), 500

# ─── 사용자 관리 API (관리자 전용) ────────────────────────
@app.route('/api/users', methods=['GET'])
@admin_required
def get_users():
    users = load_users()
    result = [{'username': k, 'name': v.get('name', k), 'role': v.get('role', 'user')}
              for k, v in users.items()]
    return jsonify(result)

@app.route('/api/users', methods=['POST'])
@admin_required
def add_user():
    data = request.json
    username = data.get('username', '').strip()
    if not username:
        return jsonify({'error': '아이디를 입력하세요.'}), 400
    users = load_users()
    if username in users:
        return jsonify({'error': '이미 존재하는 아이디입니다.'}), 400
    users[username] = {
        'password': data.get('password', 'pass1234'),
        'name': data.get('name', username),
        'role': data.get('role', 'user')
    }
    save_users(users)
    return jsonify({'success': True})

@app.route('/api/users/<username>', methods=['DELETE'])
@admin_required
def delete_user(username):
    if username == 'admin':
        return jsonify({'error': '기본 관리자 계정은 삭제할 수 없습니다.'}), 400
    if username == session.get('username'):
        return jsonify({'error': '본인 계정은 삭제할 수 없습니다.'}), 400
    users = load_users()
    if username in users:
        del users[username]
        save_users(users)
    return jsonify({'success': True})

@app.route('/api/users/<username>/password', methods=['PUT'])
@admin_required
def change_password(username):
    data = request.json
    new_pw = data.get('password', '').strip()
    if len(new_pw) < 4:
        return jsonify({'error': '비밀번호는 4자 이상이어야 합니다.'}), 400
    users = load_users()
    if username in users:
        users[username]['password'] = new_pw
        save_users(users)
    return jsonify({'success': True})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)
