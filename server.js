const express = require('express');
const cors = require('cors');
const jwt = require('jsonwebtoken');
const bcrypt = require('bcryptjs');
const { Pool } = require('pg');
const path = require('path');
const fs = require('fs');
const crypto = require('crypto');

const app = express();
app.use(cors());
app.use(express.json());

const SECRET_KEY = 'sua_chave_secreta_super_segura';

// Configuração do pool do PostgreSQL
const pool = new Pool({
  user: 'neondb_owner',
  host: 'ep-cold-sky-a537fwxd-pooler.us-east-2.aws.neon.tech',
  database: 'neondb',
  password: 'npg_91HbcvdzrFLw',
  port: 5432,
  ssl: { rejectUnauthorized: false } // <-- Adicione esta linha!
});

// Middleware para autenticação JWT
function authMiddleware(req, res, next) {
  const auth = req.headers.authorization;
  if (!auth || !auth.startsWith('Bearer ')) return res.status(401).json({ erro: 'Token não fornecido' });
  const token = auth.split(' ')[1];
  try {
    req.user = jwt.verify(token, SECRET_KEY);
    next();
  } catch {
    res.status(401).json({ erro: 'Token inválido ou expirado' });
  }
}

// LOGIN
app.post('/api/login', async (req, res) => {
  const { usuario, senha } = req.body;
  try {
    const result = await pool.query('SELECT usuario, senha, nome, cargo FROM usuarios WHERE usuario = $1', [usuario]);
    if (result.rows.length === 0) return res.status(401).json({ erro: 'Usuário ou senha inválidos.' });
    const user = result.rows[0];
    const senhaHash = crypto.createHash('sha256').update(senha).digest('hex');
    const senhaOk = senhaHash === user.senha || senha === user.senha || await bcrypt.compare(senha, user.senha);
    if (!senhaOk) return res.status(401).json({ erro: 'Usuário ou senha inválidos.' });
    const token = jwt.sign({ usuario: user.usuario, nome: user.nome, cargo: user.cargo }, SECRET_KEY, { expiresIn: '1h' });
    res.json({ mensagem: 'Login realizado', token, nome: user.nome, cargo: user.cargo });
  } catch (e) {
    res.status(500).json({ erro: 'Erro no login: ' + e.message });
  }
});

// OS TODOS
app.get('/api/os_todos', authMiddleware, async (req, res) => {
  try {
    const result = await pool.query('SELECT * FROM os_cadastros ORDER BY id DESC');
    // Mapeamento dos campos para o formato esperado pelo frontend
    const dados = result.rows.map(row => ({
      "Cliente": row["Cliente"] || row["cliente"],
      "Modelo": row["Modelo"] || row["modelo"],
      "OS": row["OS"] || row["os"],
      "Entrada equip.": row["Entrada equip."] || row["entrada_equip"] || row["Entrada"] || row["entrada"],
      "Valor": row["Valor"] || row["valor"],
      "Saída equip.": row["Saída equip."] || row["saida_equip"] || row["Saída"] || row["saida"],
      "Pagamento": row["Pagamento"] || row["pagamento"],
      "Data pagamento 1": row["Data pagamento 1"] || row["data_pagamento_1"],
      "Data pagamento 2": row["Data pagamento 2"] || row["data_pagamento_2"],
      "Data pagamento 3": row["Data pagamento 3"] || row["data_pagamento_3"],
      "Nº Série": row["Nº Série"] || row["N° Serie"] || row["Série"] || row["serie"],
      "Técnico": row["Técnico"] || row["tecnico"],
      "Vezes": row["Vezes"] || row["vezes"],
      "avaliacao_tecnica": row["avaliacao_tecnica"],
      "causas_provavel": row["causas_provavel"],
      "status": row["status"],
      "id": row["id"]
    }));
    res.json(dados);
  } catch (e) {
    res.status(500).json({ erro: 'Erro ao buscar OS: ' + e.message });
  }
});

// OS DETALHE
app.get('/api/os_detalhe/:id', authMiddleware, async (req, res) => {
  try {
    const result = await pool.query('SELECT * FROM os_cadastros WHERE id = $1', [req.params.id]);
    if (result.rows.length === 0) return res.status(404).json({ erro: 'OS não encontrada' });
    res.json(result.rows[0]);
  } catch (e) {
    res.status(500).json({ erro: 'Erro ao buscar detalhes da OS: ' + e.message });
  }
});

// OS ARQUIVOS
app.get('/api/os_arquivos/:cliente/:os_num', authMiddleware, (req, res) => {
  const baseDir = 'C:/OS';
  const cliente = req.params.cliente;
  const osNum = req.params.os_num;
  const clientePath = path.join(baseDir, cliente);
  const osPath = path.join(clientePath, osNum);
  if (!fs.existsSync(osPath)) return res.json({ arquivos: [] });
  const arquivos = fs.readdirSync(osPath).filter(f => f.endsWith('.pdf') || f.endsWith('.xlsx'));
  res.json({ arquivos });
});

// DOWNLOAD ARQUIVO
app.get('/api/download_arquivo/:cliente/:os_num/:nome_arquivo', authMiddleware, (req, res) => {
  const filePath = path.join('C:/OS', req.params.cliente, req.params.os_num, req.params.nome_arquivo);
  if (!fs.existsSync(filePath)) return res.status(404).json({ erro: 'Arquivo não encontrado' });
  res.download(filePath);
});

// GRÁFICO MENSAL
app.get('/api/grafico_mensal/:ano', authMiddleware, async (req, res) => {
  try {
    const ano = parseInt(req.params.ano);
    const result = await pool.query('SELECT "Saída equip.", "Valor" FROM os_cadastros');
    const meses = Array(12).fill(0);
    result.rows.forEach(row => {
      let dataStr = row['Saída equip.'];
      let valorStr = row['Valor'];
      if (!dataStr || !valorStr) return;
      let data = null;
      // Conversão robusta para dd/mm/yyyy
      if (typeof dataStr === 'string' && dataStr.includes('/')) {
        const [dia, mes, anoStr] = dataStr.split('/');
        if (dia && mes && anoStr) {
          data = new Date(`${anoStr}-${mes}-${dia}`);
        }
      } else {
        data = new Date(dataStr);
      }
      if (!data || isNaN(data.getTime()) || data.getFullYear() !== ano) return;
      // Conversão robusta do valor
      let valor = 0;
      if (typeof valorStr === 'string') {
        valor = parseFloat(valorStr.replace(/[^0-9,.-]+/g, '').replace('.', '').replace(',', '.')) || 0;
      } else if (typeof valorStr === 'number') {
        valor = valorStr;
      }
      const mesIdx = data.getMonth(); // 0 = janeiro
      if (mesIdx >= 0 && mesIdx < 12) {
        meses[mesIdx] += valor;
      }
    });
    res.json({ meses: Array.from({length:12}, (_,i)=>String(i+1).padStart(2,'0')), valores: meses });
  } catch (e) {
    res.status(500).json({ erro: 'Erro ao gerar gráfico: ' + e.message });
  }
});

// GRÁFICO COMPARATIVO
app.get('/api/grafico_comparativo/:ano1/:ano2', authMiddleware, async (req, res) => {
  try {
    const ano1 = parseInt(req.params.ano1);
    const ano2 = parseInt(req.params.ano2);
    const result = await pool.query('SELECT "Saída equip.", "Valor" FROM os_cadastros');
    const meses1 = Array(12).fill(0);
    const meses2 = Array(12).fill(0);
    result.rows.forEach(row => {
      let dataStr = row['Saída equip.'];
      let valorStr = row['Valor'];
      if (!dataStr || !valorStr) return;
      let data = null;
      // Conversão robusta para dd/mm/yyyy
      if (typeof dataStr === 'string' && dataStr.includes('/')) {
        const [dia, mes, anoStr] = dataStr.split('/');
        if (dia && mes && anoStr) {
          data = new Date(`${anoStr}-${mes}-${dia}`);
        }
      } else {
        data = new Date(dataStr);
      }
      if (!data || isNaN(data.getTime())) return;
      // Conversão robusta do valor
      let valor = 0;
      if (typeof valorStr === 'string') {
        valor = parseFloat(valorStr.replace(/[^0-9,.-]+/g, '').replace('.', '').replace(',', '.')) || 0;
      } else if (typeof valorStr === 'number') {
        valor = valorStr;
      }
      const mesIdx = data.getMonth(); // 0 = janeiro
      if (mesIdx >= 0 && mesIdx < 12) {
        if (data.getFullYear() === ano1) meses1[mesIdx] += valor;
        if (data.getFullYear() === ano2) meses2[mesIdx] += valor;
      }
    });
    res.json({
      meses: Array.from({length:12}, (_,i)=>String(i+1).padStart(2,'0')),
      valores1: meses1,
      valores2: meses2
    });
  } catch (e) {
    res.status(500).json({ erro: 'Erro ao gerar gráfico comparativo: ' + e.message });
  }
});

app.listen(5000, () => {
  console.log('Servidor Node rodando na porta 5000');
}); 