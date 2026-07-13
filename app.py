from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
from functools import wraps
from datetime import datetime
import socket
import urllib.parse

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key')
app.config['DEBUG'] = False
app.config['TEMPLATES_AUTO_RELOAD'] = False
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 31536000

# ========== CONEXÃO COM BANCO (TRANSACTION POOLER) ==========
DATABASE_URL = os.getenv('DATABASE_URL')

def get_db_connection():
    """Retorna uma conexão com o banco de dados usando Transaction Pooler"""
    try:
        if not DATABASE_URL:
            print("❌ DATABASE_URL não configurada!")
            return None
        
        print("🔄 Conectando ao banco via Transaction Pooler...")
        
        conn = psycopg2.connect(
            DATABASE_URL,
            sslmode='require',
            connect_timeout=15,
            keepalives=1,
            keepalives_idle=5,
            keepalives_interval=5,
            keepalives_count=3
        )
        conn.autocommit = False
        print("✅ Conexão com banco estabelecida com sucesso!")
        return conn
    except Exception as e:
        print(f"❌ Erro ao conectar: {e}")
        return None

def query_one(sql, params=None):
    conn = get_db_connection()
    if not conn:
        return None
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(sql, params or ())
        result = cur.fetchone()
        cur.close()
        conn.close()
        return result
    except Exception as e:
        print(f"Erro query_one: {e}")
        conn.close()
        return None

def query_all(sql, params=None):
    conn = get_db_connection()
    if not conn:
        return []
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(sql, params or ())
        result = cur.fetchall()
        cur.close()
        conn.close()
        return result
    except Exception as e:
        print(f"Erro query_all: {e}")
        conn.close()
        return []

def execute_sql(sql, params=None):
    conn = get_db_connection()
    if not conn:
        return False
    try:
        cur = conn.cursor()
        cur.execute(sql, params or ())
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"Erro execute: {e}")
        conn.rollback()
        conn.close()
        return False

# ==========================================
# ROTA DE TESTE
# ==========================================

@app.route('/testdb')
def testdb():
    try:
        conn = get_db_connection()
        if conn:
            cur = conn.cursor()
            cur.execute("SELECT 1")
            cur.close()
            conn.close()
            return "✅ Conexão com banco OK! Query executada com sucesso."
        else:
            return "❌ Falha na conexão com banco!"
    except Exception as e:
        return f"❌ Erro: {str(e)}"

# ==========================================
# ROTA DE DIAGNÓSTICO
# ==========================================

@app.route('/debug')
def debug():
    html = "<h1>🔍 Diagnóstico</h1>"
    
    html += f"<p><strong>DATABASE_URL:</strong> {DATABASE_URL[:60] if DATABASE_URL else 'Não configurada'}...</p>"
    
    try:
        parsed = urllib.parse.urlparse(DATABASE_URL)
        html += f"<p><strong>Host:</strong> {parsed.hostname}</p>"
        html += f"<p><strong>Porta:</strong> {parsed.port}</p>"
        html += f"<p><strong>Database:</strong> {parsed.path[1:]}</p>"
        html += f"<p><strong>User:</strong> {parsed.username}</p>"
    except Exception as e:
        html += f"<p><strong>Erro ao parsear URL:</strong> {e}</p>"
    
    try:
        if parsed:
            ip = socket.gethostbyname(parsed.hostname)
            html += f"<p><strong>IP resolvido:</strong> {ip}</p>"
    except Exception as e:
        html += f"<p><strong>Erro DNS:</strong> {e}</p>"
    
    try:
        conn = get_db_connection()
        if conn:
            html += "<p style='color:green'>✅ Conexão com banco OK!</p>"
            conn.close()
        else:
            html += "<p style='color:red'>❌ Falha na conexão!</p>"
    except Exception as e:
        html += f"<p style='color:red'>❌ Erro: {e}</p>"
    
    return html

# ==========================================
# LOGIN
# ==========================================

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        
        if not username or not password:
            flash('Preencha todos os campos!')
            return render_template('login.html')
        
        try:
            user = query_one(
                "SELECT * FROM usuarios WHERE username = %s AND password = %s",
                (username, password)
            )
            
            if user:
                session['user_id'] = user['id']
                session['user_nome'] = user['nome']
                flash(f'Bem-vindo, {user["nome"]}!')
                return redirect(url_for('index'))
            else:
                flash('Usuário ou senha inválidos!')
        except Exception as e:
            print(f"Erro no login: {e}")
            flash('Erro ao fazer login. Tente novamente.')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Você saiu do sistema')
    return redirect(url_for('login'))

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Faça login para acessar')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# ==========================================
# INDEX
# ==========================================

@app.route('/')
@login_required
def index():
    stats = query_one("""
        SELECT 
            (SELECT COUNT(*) FROM colaboradores) as total_colaboradores,
            (SELECT COUNT(*) FROM producoes WHERE finalizado = false) as total_producoes,
            (SELECT COUNT(*) FROM clientes) as total_clientes,
            (SELECT COUNT(*) FROM produtos WHERE status = 'ativo') as total_produtos,
            (SELECT COALESCE(SUM(estoque_atual), 0) FROM produtos) as total_estoque,
            (SELECT COALESCE(SUM(CASE WHEN tipo = 'entrada' THEN valor ELSE 0 END), 0) FROM transacoes_financeiras) as entradas,
            (SELECT COALESCE(SUM(CASE WHEN tipo = 'saida' THEN valor ELSE 0 END), 0) FROM transacoes_financeiras) as saidas
    """)
    
    entradas = stats['entradas'] if stats else 0
    saidas = stats['saidas'] if stats else 0
    
    etapas = query_all("SELECT * FROM etapas_producao ORDER BY ordem")
    producao_por_etapa = []
    for etapa in etapas:
        total = query_one("SELECT COUNT(*) as total FROM producoes WHERE etapa_id = %s AND finalizado = false", (etapa['id'],))
        producao_por_etapa.append({
            'etapa': etapa['nome'],
            'total': total['total'] if total else 0
        })

    # Top Clientes (por vendas registradas em transacoes_financeiras)
    top_clientes = query_all("""
        SELECT c.nome,
               COUNT(t.id) AS total_vendas,
               COALESCE(SUM(t.valor), 0) AS total_gasto,
               COALESCE(SUM(t.quantidade), 0) AS total_produtos
        FROM clientes c
        JOIN transacoes_financeiras t ON t.cliente_id = c.id
        WHERE t.tipo = 'entrada'
        GROUP BY c.id, c.nome
        ORDER BY total_gasto DESC
        LIMIT 5
    """) or []

    # Vendas dos últimos 7 dias
    vendas_por_dia = query_all("""
        SELECT DATE(data) AS dia,
               COUNT(*) AS quantidade,
               COALESCE(SUM(valor), 0) AS total
        FROM transacoes_financeiras
        WHERE tipo = 'entrada'
          AND data >= (CURRENT_DATE - INTERVAL '6 days')
        GROUP BY DATE(data)
        ORDER BY dia DESC
    """) or []

    return render_template('index.html',
                         total_colaboradores=stats['total_colaboradores'] if stats else 0,
                         total_producoes=stats['total_producoes'] if stats else 0,
                         total_clientes=stats['total_clientes'] if stats else 0,
                         total_produtos=stats['total_produtos'] if stats else 0,
                         total_estoque=stats['total_estoque'] if stats else 0,
                         entradas=entradas,
                         saidas=saidas,
                         saldo=entradas - saidas,
                         producao_por_etapa=producao_por_etapa,
                         top_clientes=top_clientes,
                         vendas_por_dia=vendas_por_dia)


# ==========================================
# ESTOQUE
# ==========================================

@app.route('/estoque')
@login_required
def estoque():
    produtos = query_all("SELECT * FROM produtos WHERE status = 'ativo' ORDER BY nome")
    
    resumo = query_one("""
        SELECT 
            COUNT(*) as total_produtos,
            COALESCE(SUM(estoque_atual), 0) as total_itens,
            COALESCE(SUM(estoque_atual * preco_custo), 0) as valor_total_estoque,
            COUNT(CASE WHEN estoque_atual <= estoque_minimo THEN 1 END) as produtos_abaixo_minimo
        FROM produtos
        WHERE status = 'ativo'
    """)
    
    return render_template('estoque.html', produtos=produtos, resumo=resumo)

@app.route('/estoque/produto/novo', methods=['POST'])
@login_required
def produto_novo():
    try:
        nome = request.form.get('nome', '').strip()
        if not nome:
            flash('O campo Nome é obrigatório!')
            return redirect(url_for('estoque'))
        
        preco_custo = float(request.form.get('preco_custo', '0').replace(',', '.') or 0)
        preco_venda = float(request.form.get('preco_venda', '0').replace(',', '.') or 0)
        estoque_minimo = int(request.form.get('estoque_minimo', 0) or 0)
        estoque_atual = int(request.form.get('estoque_atual', 0) or 0)
        
        sql = """
            INSERT INTO produtos (nome, descricao, sku, categoria, preco_custo, preco_venda, unidade, estoque_minimo, estoque_atual) 
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        
        if execute_sql(sql, (
            nome,
            request.form.get('descricao', ''),
            request.form.get('sku', ''),
            request.form.get('categoria', ''),
            preco_custo,
            preco_venda,
            request.form.get('unidade', 'UN'),
            estoque_minimo,
            estoque_atual
        )):
            flash('Produto cadastrado com sucesso!')
        else:
            flash('Erro ao cadastrar produto')
    except Exception as e:
        print(f"Erro: {e}")
        flash('Erro ao cadastrar produto')
    return redirect(url_for('estoque'))

@app.route('/estoque/produto/editar/<string:id>', methods=['POST'])
@login_required
def produto_editar(id):
    try:
        nome = request.form.get('nome', '').strip()
        if not nome:
            flash('O campo Nome é obrigatório!')
            return redirect(url_for('estoque'))
        
        preco_custo = float(request.form.get('preco_custo', '0').replace(',', '.') or 0)
        preco_venda = float(request.form.get('preco_venda', '0').replace(',', '.') or 0)
        estoque_minimo = int(request.form.get('estoque_minimo', 0) or 0)
        
        sql = """
            UPDATE produtos SET 
                nome = %s, descricao = %s, sku = %s, categoria = %s,
                preco_custo = %s, preco_venda = %s, unidade = %s,
                estoque_minimo = %s, status = %s, updated_at = NOW()
            WHERE id = %s
        """
        
        if execute_sql(sql, (
            nome,
            request.form.get('descricao', ''),
            request.form.get('sku', ''),
            request.form.get('categoria', ''),
            preco_custo,
            preco_venda,
            request.form.get('unidade', 'UN'),
            estoque_minimo,
            request.form.get('status', 'ativo'),
            id
        )):
            flash('Produto atualizado com sucesso!')
        else:
            flash('Erro ao atualizar produto')
    except Exception as e:
        print(f"Erro: {e}")
        flash('Erro ao atualizar produto')
    return redirect(url_for('estoque'))

@app.route('/estoque/produto/delete/<string:id>', methods=['POST'])
@login_required
def produto_delete(id):
    if execute_sql("UPDATE produtos SET status = 'inativo' WHERE id = %s", (id,)):
        flash('Produto desativado com sucesso!')
    else:
        flash('Erro ao desativar produto')
    return redirect(url_for('estoque'))

@app.route('/estoque/movimentacoes/<string:produto_id>')
@login_required
def movimentacoes_produto(produto_id):
    movimentacoes = query_all("""
        SELECT * FROM movimentacoes_estoque 
        WHERE produto_id = %s 
        ORDER BY data_movimentacao DESC
        LIMIT 100
    """, (produto_id,))
    
    produto = query_one("SELECT * FROM produtos WHERE id = %s", (produto_id,))
    
    if not produto:
        flash('Produto não encontrado')
        return redirect(url_for('estoque'))
    
    return render_template('movimentacoes.html', movimentacoes=movimentacoes, produto=produto)

@app.route('/estoque/ajustar/<string:produto_id>', methods=['POST'])
@login_required
def estoque_ajustar(produto_id):
    tipo = request.form['tipo']
    quantidade = int(request.form['quantidade'])
    descricao = request.form['descricao']
    
    produto = query_one("SELECT * FROM produtos WHERE id = %s", (produto_id,))
    if not produto:
        flash('Produto não encontrado')
        return redirect(url_for('estoque'))
    
    if tipo == 'entrada':
        novo_estoque = produto['estoque_atual'] + quantidade
    else:
        novo_estoque = produto['estoque_atual'] - quantidade
    
    if novo_estoque < 0:
        novo_estoque = 0
    
    sql = """
        UPDATE produtos SET estoque_atual = %s, updated_at = NOW() 
        WHERE id = %s
    """
    if execute_sql(sql, (novo_estoque, produto_id)):
        sql_mov = """
            INSERT INTO movimentacoes_estoque (produto_id, tipo, origem, quantidade, descricao) 
            VALUES (%s, %s, %s, %s, %s)
        """
        execute_sql(sql_mov, (produto_id, tipo, 'ajuste', quantidade, descricao))
        flash('Estoque ajustado com sucesso!')
    else:
        flash('Erro ao ajustar estoque')
    
    return redirect(url_for('estoque'))

# ==========================================
# PRODUÇÃO
# ==========================================

@app.route('/producao', methods=['GET', 'POST'])
@login_required
def producao():
    if request.method == 'POST':
        sql = """
            INSERT INTO producoes (pedido, etapa_id, quantidade_pecas, colaborador_id, produto_id) 
            VALUES (%s, %s, %s, %s, %s)
        """
        if execute_sql(sql, (
            request.form['pedido'],
            request.form['etapa_id'],
            int(request.form['quantidade']),
            request.form.get('colaborador_id') or None,
            request.form.get('produto_id') or None
        )):
            flash('Produção adicionada com sucesso!')
        else:
            flash('Erro ao adicionar produção')
        return redirect(url_for('producao'))
    
    etapas = query_all("SELECT * FROM etapas_producao ORDER BY ordem")
    colaboradores = query_all("SELECT * FROM colaboradores ORDER BY nome")
    produtos = query_all("SELECT * FROM produtos WHERE status = 'ativo' ORDER BY nome")
    producoes = query_all("""
        SELECT p.*, e.nome as etapa_nome, c.nome as colaborador_nome, pr.nome as produto_nome
        FROM producoes p 
        LEFT JOIN etapas_producao e ON p.etapa_id = e.id 
        LEFT JOIN colaboradores c ON p.colaborador_id = c.id
        LEFT JOIN produtos pr ON p.produto_id = pr.id
        ORDER BY p.data_entrada DESC
    """)
    
    return render_template('producao.html', etapas=etapas, producoes=producoes, colaboradores=colaboradores, produtos=produtos)

@app.route('/producao/editar/<string:id>', methods=['POST'])
@login_required
def producao_editar(id):
    sql = """
        UPDATE producoes SET 
            pedido = %s, etapa_id = %s, quantidade_pecas = %s,
            colaborador_id = %s, produto_id = %s
        WHERE id = %s
    """
    if execute_sql(sql, (
        request.form['pedido'],
        request.form['etapa_id'],
        int(request.form['quantidade']),
        request.form.get('colaborador_id') or None,
        request.form.get('produto_id') or None,
        id
    )):
        flash('Produção atualizada com sucesso!')
    else:
        flash('Erro ao atualizar produção')
    return redirect(url_for('producao'))

@app.route('/producao/delete/<string:id>', methods=['POST'])
@login_required
def producao_delete(id):
    if execute_sql("DELETE FROM producoes WHERE id = %s", (id,)):
        flash('Produção excluída com sucesso!')
    else:
        flash('Erro ao excluir produção')
    return redirect(url_for('producao'))

@app.route('/producao/finalizar/<string:id>', methods=['POST'])
@login_required
def producao_finalizar(id):
    producao = query_one("SELECT * FROM producoes WHERE id = %s", (id,))
    if not producao:
        flash('Produção não encontrada')
        return redirect(url_for('producao'))
    
    if execute_sql("UPDATE producoes SET finalizado = true, status = 'Finalizado' WHERE id = %s", (id,)):
        if producao.get('produto_id'):
            produto = query_one("SELECT * FROM produtos WHERE id = %s", (producao['produto_id'],))
            if produto:
                novo_estoque = produto['estoque_atual'] + producao['quantidade_pecas']
                execute_sql("UPDATE produtos SET estoque_atual = %s WHERE id = %s", (novo_estoque, producao['produto_id']))
                
                sql_mov = """
                    INSERT INTO movimentacoes_estoque (produto_id, tipo, origem, quantidade, descricao, referencia_id) 
                    VALUES (%s, 'entrada', 'producao', %s, %s, %s)
                """
                execute_sql(sql_mov, (
                    producao['produto_id'],
                    producao['quantidade_pecas'],
                    f'Produção finalizada - Pedido {producao["pedido"]}',
                    id
                ))
            flash('Produção finalizada e estoque atualizado!')
        else:
            flash('Produção finalizada!')
    else:
        flash('Erro ao finalizar produção')
    return redirect(url_for('producao'))

@app.route('/producao/reativar/<string:id>', methods=['POST'])
@login_required
def producao_reativar(id):
    if execute_sql("UPDATE producoes SET finalizado = false, status = 'Em andamento' WHERE id = %s", (id,)):
        flash('Produção reativada com sucesso!')
    else:
        flash('Erro ao reativar produção')
    return redirect(url_for('producao'))

# ==========================================
# COLABORADORES
# ==========================================

@app.route('/colaboradores', methods=['GET', 'POST'])
@login_required
def colaboradores():
    if request.method == 'POST':
        sql = "INSERT INTO colaboradores (nome, funcao, telefone, observacao) VALUES (%s, %s, %s, %s)"
        if execute_sql(sql, (request.form['nome'], request.form['funcao'], request.form['telefone'], request.form['observacao'])):
            flash('Colaborador cadastrado com sucesso!')
        else:
            flash('Erro ao cadastrar colaborador')
        return redirect(url_for('colaboradores'))
    
    colaboradores = query_all("SELECT * FROM colaboradores ORDER BY nome")
    funcoes = ['Costura', 'Elástico', 'Corte', 'Aprontamento', 'Fornecedor', 'Recepção', 'Expedição', 'Outro']
    return render_template('colaboradores.html', colaboradores=colaboradores, funcoes=funcoes)

@app.route('/colaboradores/editar/<string:id>', methods=['POST'])
@login_required
def colaborador_editar(id):
    sql = """
        UPDATE colaboradores SET nome = %s, funcao = %s, telefone = %s, observacao = %s
        WHERE id = %s
    """
    if execute_sql(sql, (request.form['nome'], request.form['funcao'], request.form['telefone'], request.form['observacao'], id)):
        flash('Colaborador atualizado com sucesso!')
    else:
        flash('Erro ao atualizar colaborador')
    return redirect(url_for('colaboradores'))

@app.route('/colaboradores/delete/<string:id>', methods=['POST'])
@login_required
def colaborador_delete(id):
    em_uso = query_one("SELECT COUNT(*) as total FROM producoes WHERE colaborador_id = %s", (id,))
    if em_uso and em_uso['total'] > 0:
        flash('Não é possível excluir. Colaborador está vinculado a produções!')
        return redirect(url_for('colaboradores'))
    
    if execute_sql("DELETE FROM colaboradores WHERE id = %s", (id,)):
        flash('Colaborador excluído com sucesso!')
    else:
        flash('Erro ao excluir colaborador')
    return redirect(url_for('colaboradores'))

# ==========================================
# FINANCEIRO (ATUALIZADO COM BAIXA NO ESTOQUE)
# ==========================================

@app.route('/financeiro', methods=['GET', 'POST'])
@login_required
def financeiro():
    if request.method == 'POST':
        categoria = request.form.get('categoria_personalizada')
        if not categoria:
            categoria = request.form.get('categoria_selecionada', 'Geral')
        
        produto_id = request.form.get('produto_id') or None
        cliente_id = request.form.get('cliente_id') or None
        quantidade = int(request.form.get('quantidade', 0) or 0)
        valor = float(request.form['valor'])
        tipo = request.form['tipo']
        
        # Inicia transação manual para garantir consistência
        conn = get_db_connection()
        if not conn:
            flash('Erro de conexão com banco de dados')
            return redirect(url_for('financeiro'))
        
        try:
            cur = conn.cursor()
            
            # 1. Inserir a transação financeira
            sql_transacao = """
                INSERT INTO transacoes_financeiras 
                (tipo, categoria, descricao, valor, produto_id, quantidade, cliente_id) 
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """
            cur.execute(sql_transacao, (tipo, categoria, request.form['descricao'], valor, produto_id, quantidade, cliente_id))
            transacao_id = cur.fetchone()[0]
            
            # 2. Se for uma VENDA (entrada) e tiver produto e quantidade
            if tipo == 'entrada' and produto_id and quantidade > 0:
                # Buscar produto atual
                cur.execute("SELECT * FROM produtos WHERE id = %s FOR UPDATE", (produto_id,))
                produto = cur.fetchone()
                
                if produto:
                    # Calcular novo estoque
                    novo_estoque = produto[8] - quantidade
                    if novo_estoque < 0:
                        novo_estoque = 0
                        flash(f'Aviso: Estoque ficaria negativo. Ajustado para 0.', 'warning')
                    
                    # Atualizar estoque do produto
                    cur.execute("""
                        UPDATE produtos 
                        SET estoque_atual = %s, updated_at = NOW() 
                        WHERE id = %s
                    """, (novo_estoque, produto_id))
                    
                    # Registrar movimentação de estoque (saída)
                    cur.execute("""
                        INSERT INTO movimentacoes_estoque 
                        (produto_id, tipo, origem, quantidade, descricao, referencia_id) 
                        VALUES (%s, 'saida', 'venda', %s, %s, %s)
                    """, (produto_id, quantidade, f'Venda - {request.form["descricao"]}', transacao_id))
                    
                    flash(f'✅ Venda registrada! Estoque atualizado: {produto[8]} → {novo_estoque} {produto[7] or "UN"}', 'success')
            
            conn.commit()
            cur.close()
            conn.close()
            flash('Transação registrada com sucesso!')
            
        except Exception as e:
            conn.rollback()
            conn.close()
            print(f"Erro ao registrar transação: {e}")
            flash(f'❌ Erro ao registrar transação: {str(e)}')
        
        return redirect(url_for('financeiro'))
    
    # GET - mostrar página
    transacoes = query_all("""
        SELECT t.*, p.nome as produto_nome, c.nome as cliente_nome
        FROM transacoes_financeiras t
        LEFT JOIN produtos p ON t.produto_id = p.id
        LEFT JOIN clientes c ON t.cliente_id = c.id
        ORDER BY t.data DESC
    """)
    
    produtos = query_all("SELECT * FROM produtos WHERE status = 'ativo' ORDER BY nome")
    clientes = query_all("SELECT * FROM clientes ORDER BY nome")
    
    resumo = query_one("""
        SELECT 
            COALESCE(SUM(CASE WHEN tipo = 'entrada' THEN valor ELSE 0 END), 0) as entradas,
            COALESCE(SUM(CASE WHEN tipo = 'saida' THEN valor ELSE 0 END), 0) as saidas
        FROM transacoes_financeiras
    """)
    
    categorias = query_all("SELECT DISTINCT categoria FROM transacoes_financeiras WHERE categoria IS NOT NULL ORDER BY categoria")
    lista_categorias = [c['categoria'] for c in categorias] if categorias else []
    categorias_padrao = ['Fixa', 'Variável', 'Dívida', 'Imposto', 'Folha', 'Marketing', 'Manutenção', 'Geral']
    
    entradas = resumo['entradas'] if resumo else 0
    saidas = resumo['saidas'] if resumo else 0
    
    return render_template('financeiro.html',
                         transacoes=transacoes,
                         entradas=entradas,
                         saidas=saidas,
                         saldo=entradas - saidas,
                         categorias_padrao=categorias_padrao,
                         categorias_existentes=lista_categorias,
                         produtos=produtos,
                         clientes=clientes)

@app.route('/financeiro/editar/<string:id>', methods=['POST'])
@login_required
def financeiro_editar(id):
    # Buscar transação original
    transacao_original = query_one("SELECT * FROM transacoes_financeiras WHERE id = %s", (id,))
    if not transacao_original:
        flash('Transação não encontrada')
        return redirect(url_for('financeiro'))
    
    categoria = request.form.get('categoria_personalizada')
    if not categoria:
        categoria = request.form.get('categoria_selecionada', 'Geral')
    
    novo_tipo = request.form['tipo']
    novo_produto_id = request.form.get('produto_id') or None
    nova_quantidade = int(request.form.get('quantidade', 0) or 0)
    novo_valor = float(request.form['valor'])
    
    conn = get_db_connection()
    if not conn:
        flash('Erro de conexão com banco de dados')
        return redirect(url_for('financeiro'))
    
    try:
        cur = conn.cursor()
        
        # 1. Reverter alterações da transação original no estoque (se houver)
        if transacao_original['tipo'] == 'entrada' and transacao_original['produto_id'] and transacao_original['quantidade'] > 0:
            # Devolver ao estoque (entrada)
            cur.execute("SELECT * FROM produtos WHERE id = %s FOR UPDATE", (transacao_original['produto_id'],))
            produto_original = cur.fetchone()
            if produto_original:
                # Adicionar de volta ao estoque
                novo_estoque = produto_original[8] + transacao_original['quantidade']
                cur.execute("""
                    UPDATE produtos SET estoque_atual = %s, updated_at = NOW() 
                    WHERE id = %s
                """, (novo_estoque, transacao_original['produto_id']))
        
        # 2. Atualizar a transação
        sql_update = """
            UPDATE transacoes_financeiras SET 
                tipo = %s, categoria = %s, descricao = %s, 
                valor = %s, produto_id = %s, quantidade = %s, cliente_id = %s
            WHERE id = %s
        """
        cur.execute(sql_update, (
            novo_tipo,
            categoria,
            request.form['descricao'],
            novo_valor,
            novo_produto_id,
            nova_quantidade,
            request.form.get('cliente_id') or None,
            id
        ))
        
        # 3. Aplicar nova alteração no estoque (se for venda)
        if novo_tipo == 'entrada' and novo_produto_id and nova_quantidade > 0:
            cur.execute("SELECT * FROM produtos WHERE id = %s FOR UPDATE", (novo_produto_id,))
            produto_novo = cur.fetchone()
            if produto_novo:
                novo_estoque = produto_novo[8] - nova_quantidade
                if novo_estoque < 0:
                    novo_estoque = 0
                    flash('Aviso: Estoque ficaria negativo. Ajustado para 0.', 'warning')
                
                cur.execute("""
                    UPDATE produtos SET estoque_atual = %s, updated_at = NOW() 
                    WHERE id = %s
                """, (novo_estoque, novo_produto_id))
                
                # Registrar movimentação
                cur.execute("""
                    INSERT INTO movimentacoes_estoque 
                    (produto_id, tipo, origem, quantidade, descricao, referencia_id) 
                    VALUES (%s, 'saida', 'venda', %s, %s, %s)
                """, (novo_produto_id, nova_quantidade, f'Venda editada - {request.form["descricao"]}', id))
        
        conn.commit()
        cur.close()
        conn.close()
        flash('✅ Transação atualizada com sucesso!')
        
    except Exception as e:
        conn.rollback()
        conn.close()
        print(f"Erro ao atualizar transação: {e}")
        flash(f'❌ Erro ao atualizar transação: {str(e)}')
    
    return redirect(url_for('financeiro'))

@app.route('/financeiro/delete/<string:id>', methods=['POST'])
@login_required
def financeiro_delete(id):
    # Buscar a transação antes de excluir
    transacao = query_one("SELECT * FROM transacoes_financeiras WHERE id = %s", (id,))
    if not transacao:
        flash('Transação não encontrada')
        return redirect(url_for('financeiro'))
    
    conn = get_db_connection()
    if not conn:
        flash('Erro de conexão com banco de dados')
        return redirect(url_for('financeiro'))
    
    try:
        cur = conn.cursor()
        
        # Se for uma venda (entrada), devolver ao estoque
        if transacao['tipo'] == 'entrada' and transacao['produto_id'] and transacao['quantidade'] > 0:
            cur.execute("SELECT * FROM produtos WHERE id = %s FOR UPDATE", (transacao['produto_id'],))
            produto = cur.fetchone()
            if produto:
                novo_estoque = produto[8] + transacao['quantidade']
                cur.execute("""
                    UPDATE produtos SET estoque_atual = %s, updated_at = NOW() 
                    WHERE id = %s
                """, (novo_estoque, transacao['produto_id']))
                
                # Registrar movimentação de reversão
                cur.execute("""
                    INSERT INTO movimentacoes_estoque 
                    (produto_id, tipo, origem, quantidade, descricao, referencia_id) 
                    VALUES (%s, 'entrada', 'cancelamento', %s, %s, %s)
                """, (transacao['produto_id'], transacao['quantidade'], f'Cancelamento de venda - {transacao["descricao"]}', id))
        
        # Excluir a transação
        cur.execute("DELETE FROM transacoes_financeiras WHERE id = %s", (id,))
        
        conn.commit()
        cur.close()
        conn.close()
        flash('✅ Transação excluída com sucesso! Estoque revertido.')
        
    except Exception as e:
        conn.rollback()
        conn.close()
        print(f"Erro ao excluir transação: {e}")
        flash(f'❌ Erro ao excluir transação: {str(e)}')
    
    return redirect(url_for('financeiro'))

# ==========================================
# CRM
# ==========================================

@app.route('/crm')
@login_required
def crm():
    clientes = query_all("""
        SELECT c.*, COUNT(i.id) as total_interacoes
        FROM clientes c
        LEFT JOIN interacoes_clientes i ON c.id = i.cliente_id
        GROUP BY c.id
        ORDER BY 
            CASE c.status WHEN 'ativo' THEN 1 WHEN 'potencial' THEN 2 WHEN 'inativo' THEN 3 END,
            c.nome
    """)
    
    interacoes_recentes = query_all("""
        SELECT i.*, c.nome as cliente_nome 
        FROM interacoes_clientes i
        JOIN clientes c ON i.cliente_id = c.id
        ORDER BY i.data_interacao DESC LIMIT 10
    """)
    
    stats = query_one("""
        SELECT 
            COUNT(*) as total_clientes,
            COUNT(CASE WHEN status = 'ativo' THEN 1 END) as ativos,
            COUNT(CASE WHEN status = 'potencial' THEN 1 END) as potenciais,
            COUNT(CASE WHEN status = 'inativo' THEN 1 END) as inativos,
            COUNT(i.id) as total_interacoes
        FROM clientes c
        LEFT JOIN interacoes_clientes i ON c.id = i.cliente_id
    """)
    
    return render_template('crm.html', clientes=clientes, interacoes_recentes=interacoes_recentes, stats=stats)

@app.route('/crm/cliente/<string:id>')
@login_required
def cliente_detalhe(id):
    cliente = query_one("""
        SELECT c.*, COUNT(i.id) as total_interacoes
        FROM clientes c
        LEFT JOIN interacoes_clientes i ON c.id = i.cliente_id
        WHERE c.id = %s GROUP BY c.id
    """, (id,))
    
    if not cliente:
        flash('Cliente não encontrado')
        return redirect(url_for('crm'))
    
    interacoes = query_all("SELECT * FROM interacoes_clientes WHERE cliente_id = %s ORDER BY data_interacao DESC", (id,))
    return render_template('cliente_detalhe.html', cliente=cliente, interacoes=interacoes)

@app.route('/crm/novo', methods=['POST'])
@login_required
def cliente_novo():
    sql = """
        INSERT INTO clientes (nome, telefone, email, cnpj_cpf, endereco, cidade, estado, status, tipo, observacao, proximo_contato) 
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    proximo_contato = request.form.get('proximo_contato')
    if proximo_contato:
        proximo_contato = datetime.strptime(proximo_contato, '%Y-%m-%d').date()
    
    if execute_sql(sql, (request.form['nome'], request.form['telefone'], request.form['email'], request.form.get('cnpj_cpf'), request.form.get('endereco'), request.form.get('cidade'), request.form.get('estado'), request.form.get('status', 'potencial'), request.form.get('tipo', 'pessoa_fisica'), request.form.get('observacao'), proximo_contato)):
        flash('Cliente cadastrado com sucesso!')
    else:
        flash('Erro ao cadastrar cliente')
    return redirect(url_for('crm'))

@app.route('/crm/editar/<string:id>', methods=['POST'])
@login_required
def cliente_editar(id):
    sql = """
        UPDATE clientes SET nome = %s, telefone = %s, email = %s, cnpj_cpf = %s,
            endereco = %s, cidade = %s, estado = %s, status = %s,
            tipo = %s, observacao = %s, proximo_contato = %s
        WHERE id = %s
    """
    proximo_contato = request.form.get('proximo_contato')
    if proximo_contato:
        proximo_contato = datetime.strptime(proximo_contato, '%Y-%m-%d').date()
    
    if execute_sql(sql, (request.form['nome'], request.form['telefone'], request.form['email'], request.form.get('cnpj_cpf'), request.form.get('endereco'), request.form.get('cidade'), request.form.get('estado'), request.form.get('status'), request.form.get('tipo'), request.form.get('observacao'), proximo_contato, id)):
        flash('Cliente atualizado com sucesso!')
    else:
        flash('Erro ao atualizar cliente')
    return redirect(url_for('cliente_detalhe', id=id))

@app.route('/crm/interacao/<string:cliente_id>', methods=['POST'])
@login_required
def cliente_interacao(cliente_id):
    if execute_sql("INSERT INTO interacoes_clientes (cliente_id, tipo, descricao) VALUES (%s, %s, %s)", (cliente_id, request.form['tipo'], request.form['descricao'])):
        execute_sql("UPDATE clientes SET ultimo_contato = NOW()::date WHERE id = %s", (cliente_id,))
        flash('Interação registrada com sucesso!')
    else:
        flash('Erro ao registrar interação')
    return redirect(url_for('cliente_detalhe', id=cliente_id))

@app.route('/crm/buscar', methods=['GET'])
@login_required
def cliente_buscar():
    termo = request.args.get('q', '').strip()
    if not termo:
        return redirect(url_for('crm'))
    
    clientes = query_all("""
        SELECT c.*, COUNT(i.id) as total_interacoes
        FROM clientes c
        LEFT JOIN interacoes_clientes i ON c.id = i.cliente_id
        WHERE c.nome ILIKE %s OR c.telefone ILIKE %s OR c.email ILIKE %s
        GROUP BY c.id ORDER BY c.nome
    """, (f'%{termo}%', f'%{termo}%', f'%{termo}%'))
    
    return render_template('crm_busca.html', clientes=clientes, termo=termo)

@app.route('/crm/delete/<string:id>', methods=['POST'])
@login_required
def cliente_delete(id):
    if execute_sql("DELETE FROM clientes WHERE id = %s", (id,)):
        flash('Cliente excluído com sucesso!')
    else:
        flash('Erro ao excluir cliente')
    return redirect(url_for('crm'))

# ==========================================
# RODAR APP
# ==========================================

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(debug=False, host='0.0.0.0', port=port)