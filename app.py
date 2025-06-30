from flask import Flask, request, jsonify, session, send_from_directory
import psycopg2
import hashlib
from datetime import datetime, timedelta
from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
from flask_cors import CORS
import os
import pandas as pd
import unicodedata

app = Flask(__name__)
app.secret_key = 'sua_chave_secreta_aqui'  # Troque por uma chave forte
CORS(app, supports_credentials=True)
app.config['SESSION_COOKIE_SAMESITE'] = 'None'
app.config['SESSION_COOKIE_SECURE'] = True

# Controle de tentativas de login
login_attempts = {}
LOCKOUT_TIME = 300  # segundos
MAX_ATTEMPTS = 3

def get_db_conn():
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD
    )

def hash_password(senha):
    return hashlib.sha256(senha.encode()).hexdigest()

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    if not data:
        return jsonify({'erro': 'Dados inválidos'}), 400
    usuario = data.get('usuario')
    senha = data.get('senha')
    ip = request.remote_addr
    now = datetime.now()
    key = f'{usuario}_{ip}'

    # Bloqueio por tentativas
    if key in login_attempts:
        attempts, last_time = login_attempts[key]
        if attempts >= MAX_ATTEMPTS and (now - last_time).total_seconds() < LOCKOUT_TIME:
            return jsonify({'erro': f'Conta bloqueada. Tente novamente em {LOCKOUT_TIME - int((now - last_time).total_seconds())} segundos.'}), 403
        elif (now - last_time).total_seconds() >= LOCKOUT_TIME:
            login_attempts[key] = (0, now)

    try:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute('SELECT usuario, senha, nome, cargo FROM usuarios WHERE usuario = %s', (usuario,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row:
            senha_hash = row[1]
            if senha_hash == senha or senha_hash == hash_password(senha):
                session['usuario'] = usuario
                session['nome'] = row[2]
                session['cargo'] = row[3]
                login_attempts[key] = (0, now)
                return jsonify({'mensagem': 'Login realizado', 'nome': row[2], 'cargo': row[3]})
        # Falha
        if key in login_attempts:
            login_attempts[key] = (login_attempts[key][0]+1, now)
        else:
            login_attempts[key] = (1, now)
        return jsonify({'erro': 'Usuário ou senha inválidos.'}), 401
    except Exception as e:
        return jsonify({'erro': f'Erro no login: {str(e)}'}), 500

@app.route('/api/resumo_os', methods=['GET'])
def resumo_os():
    if 'usuario' not in session:
        return jsonify({'erro': 'Não autenticado'}), 401
    try:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute('SELECT "Cliente", "Modelo", "OS", "Entrada", "Valor", "Saída", "Técnico", id FROM os_cadastros ORDER BY id DESC LIMIT 20')
        rows = cur.fetchall()
        cur.close()
        conn.close()
        resultado = [
            {
                'Cliente': r[0],
                'Modelo': r[1],
                'OS': r[2],
                'Entrada': r[3],
                'Valor': r[4],
                'Saida': r[5],
                'Tecnico': r[6],
                'id': r[7]
            } for r in rows
        ]
        return jsonify(resultado)
    except Exception as e:
        return jsonify({'erro': f'Erro ao buscar OS: {str(e)}'}), 500

@app.route('/api/abrir_os', methods=['POST'])
def abrir_os():
    if 'usuario' not in session:
        return jsonify({'erro': 'Não autenticado'}), 401
    data = request.json
    if not data:
        return jsonify({'erro': 'Dados inválidos'}), 400
    cliente = data.get('Cliente')
    modelo = data.get('Modelo')
    os_num = data.get('OS')
    entrada = data.get('Entrada')
    valor = data.get('Valor')
    saida = data.get('Saida')
    tecnico = data.get('Tecnico')
    try:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute('INSERT INTO os_cadastros ("Cliente", "Modelo", "OS", "Entrada", "Valor", "Saída", "Técnico") VALUES (%s, %s, %s, %s, %s, %s, %s)',
                    (cliente, modelo, os_num, entrada, valor, saida, tecnico))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'mensagem': 'OS aberta com sucesso!'})
    except Exception as e:
        return jsonify({'erro': f'Erro ao abrir OS: {str(e)}'}), 500

@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'mensagem': 'Logout realizado'})

@app.route('/api/os_todos', methods=['GET'])
def os_todos():
    if 'usuario' not in session:
        return jsonify({'erro': 'Não autenticado'}), 401
    try:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute('SELECT * FROM os_cadastros ORDER BY id DESC')
        colnames = [desc[0] for desc in cur.description]
        rows = cur.fetchall()
        cur.close()
        conn.close()
        resultado = [dict(zip(colnames, r)) for r in rows]
        return jsonify(resultado)
    except Exception as e:
        return jsonify({'erro': f'Erro ao buscar OS: {str(e)}'}), 500

@app.route('/api/os_detalhe/<int:os_id>', methods=['GET'])
def os_detalhe(os_id):
    if 'usuario' not in session:
        return jsonify({'erro': 'Não autenticado'}), 401
    try:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute('SELECT * FROM os_cadastros WHERE id = %s', (os_id,))
        colnames = [desc[0] for desc in cur.description]
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row:
            return jsonify(dict(zip(colnames, row)))
        else:
            return jsonify({'erro': 'OS não encontrada'}), 404
    except Exception as e:
        return jsonify({'erro': f'Erro ao buscar detalhes da OS: {str(e)}'}), 500

@app.route('/api/os_arquivos/<cliente>/<os_num>', methods=['GET'])
def os_arquivos(cliente, os_num):
    if 'usuario' not in session:
        return jsonify({'erro': 'Não autenticado'}), 401
    def normalizar(s):
        return unicodedata.normalize('NFKD', s).encode('ASCII', 'ignore').decode('ASCII').replace(' ', '').lower()
    base_dir = 'C:/OS'
    # Busca tolerante para cliente
    cliente_dirs = [d for d in os.listdir(base_dir) if os.path.isdir(os.path.join(base_dir, d))]
    cliente_norm = normalizar(cliente)
    cliente_match = next((d for d in cliente_dirs if normalizar(d) == cliente_norm), None)
    if not cliente_match:
        return jsonify({'arquivos': []})
    cliente_path = os.path.join(base_dir, cliente_match)
    # Busca tolerante para OS
    os_dirs = [d for d in os.listdir(cliente_path) if os.path.isdir(os.path.join(cliente_path, d))]
    os_norm = normalizar(os_num)
    os_match = next((d for d in os_dirs if normalizar(d) == os_norm), None)
    if not os_match:
        return jsonify({'arquivos': []})
    base_path = os.path.join(cliente_path, os_match)
    arquivos = []
    for nome in os.listdir(base_path):
        if nome.lower().endswith(('.xlsx', '.pdf')):
            arquivos.append(nome)
    return jsonify({'arquivos': arquivos})

@app.route('/api/download_arquivo/<cliente>/<os_num>/<nome_arquivo>', methods=['GET'])
def download_arquivo(cliente, os_num, nome_arquivo):
    if 'usuario' not in session:
        return jsonify({'erro': 'Não autenticado'}), 401
    base_path = os.path.join('C:/OS', cliente, os_num)
    if not os.path.isdir(base_path):
        return jsonify({'erro': 'Arquivo não encontrado'}), 404
    try:
        return send_from_directory(base_path, nome_arquivo, as_attachment=True)
    except Exception as e:
        return jsonify({'erro': f'Erro ao baixar arquivo: {str(e)}'}), 500

@app.route('/api/grafico_mensal/<int:ano>', methods=['GET'])
def grafico_mensal(ano):
    if 'usuario' not in session:
        return jsonify({'erro': 'Não autenticado'}), 401
    try:
        conn = get_db_conn()
        df = pd.read_sql('SELECT "Saída equip.", "Valor" FROM os_cadastros', conn)
        conn.close()
        df = df.dropna(subset=["Saída equip.", "Valor"])  # Remove linhas sem data ou valor
        df['saida'] = pd.to_datetime(df['Saída equip.'], dayfirst=True, errors='coerce')
        df = df.dropna(subset=['saida'])
        if df.empty:
            meses = [str(m).zfill(2) for m in range(1, 13)]
            valores = [0.0 for _ in range(1, 13)]
            return jsonify({'meses': meses, 'valores': valores})
        df['Valor'] = df['Valor'].fillna('0')
        df['valor_num'] = pd.to_numeric(df['Valor'].astype(str).str.replace('R$', '').str.replace('.', '').str.replace(',', '.'), errors='coerce')
        df['valor_num'] = df['valor_num'].fillna(0)
        df_year = df[df['saida'].dt.year == ano]
        mensal = df_year.groupby(df_year['saida'].dt.month)['valor_num'].sum().to_dict()
        meses = [str(m).zfill(2) for m in range(1, 13)]
        valores = [float(mensal.get(m, 0.0)) for m in range(1, 13)]
        return jsonify({'meses': meses, 'valores': valores})
    except Exception as e:
        return jsonify({'erro': str(e)}), 500

@app.route('/api/grafico_comparativo/<int:ano1>/<int:ano2>', methods=['GET'])
def grafico_comparativo(ano1, ano2):
    if 'usuario' not in session:
        return jsonify({'erro': 'Não autenticado'}), 401
    try:
        conn = get_db_conn()
        df = pd.read_sql('SELECT "Saída equip.", "Valor" FROM os_cadastros', conn)
        conn.close()
        df = df.dropna(subset=["Saída equip.", "Valor"])  # Remove linhas sem data ou valor
        df['saida'] = pd.to_datetime(df['Saída equip.'], dayfirst=True, errors='coerce')
        df = df.dropna(subset=['saida'])
        if df.empty:
            meses = [str(m).zfill(2) for m in range(1, 13)]
            valores1 = [0.0 for _ in range(1, 13)]
            valores2 = [0.0 for _ in range(1, 13)]
            return jsonify({'meses': meses, 'ano1': ano1, 'ano2': ano2, 'valores1': valores1, 'valores2': valores2})
        df['Valor'] = df['Valor'].fillna('0')
        df['valor_num'] = pd.to_numeric(df['Valor'].astype(str).str.replace('R$', '').str.replace('.', '').str.replace(',', '.'), errors='coerce')
        df['valor_num'] = df['valor_num'].fillna(0)
        m1 = df[df['saida'].dt.year == ano1].groupby(df['saida'].dt.month)['valor_num'].sum().to_dict()
        m2 = df[df['saida'].dt.year == ano2].groupby(df['saida'].dt.month)['valor_num'].sum().to_dict()
        meses = [str(m).zfill(2) for m in range(1, 13)]
        valores1 = [float(m1.get(m, 0.0)) for m in range(1, 13)]
        valores2 = [float(m2.get(m, 0.0)) for m in range(1, 13)]
        return jsonify({'meses': meses, 'ano1': ano1, 'ano2': ano2, 'valores1': valores1, 'valores2': valores2})
    except Exception as e:
        return jsonify({'erro': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)