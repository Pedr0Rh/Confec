from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
from functools import wraps
from datetime import datetime
import socket
import urllib.parse
import traceback

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key')
app.config['DEBUG'] = False
app.config['TEMPLATES_AUTO_RELOAD'] = False
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 31536000

# ========== CONEXÃO COM BANCO ==========
DATABASE_URL = os.getenv('DATABASE_URL')

print("=" * 60)
print("🚀 INICIANDO APLICAÇÃO")
print(f"📊 DATABASE_URL: {'✅ Configurada' if DATABASE_URL else '❌ NÃO CONFIGURADA'}")
print(f"🔑 SECRET_KEY: {'✅ Configurada' if os.getenv('SECRET_KEY') else '⚠️ Usando chave padrão'}")
print("=" * 60)

def get_db_connection():
    """Retorna uma conexão com o banco de dados"""
    try:
        if not DATABASE_URL:
            print("❌ DATABASE_URL não configurada!")
            return None

        print("🔄 Conectando ao banco...")

        try:
            parsed = urllib.parse.urlparse(DATABASE_URL)
            
            conn_params = {
                'dbname': parsed.path[1:],
                'user': parsed.username,
                'password': parsed.password,
                'host': parsed.hostname,
                'port': parsed.port or 5432,
                'sslmode': 'require',
                'connect_timeout': 10,
                'options': '-c ipv4=1'
            }
            
            conn = psycopg2.connect(**conn_params)
            conn.autocommit = False
            print("✅ Conexão com banco estabelecida com sucesso!")
            return conn
        except Exception as e1:
            print(f"⚠️ Tentativa 1 falhou: {e1}")
            
            try:
                parsed = urllib.parse.urlparse(DATABASE_URL)
                host = parsed.hostname
                ip = socket.gethostbyname(host)
                print(f"🔄 Resolvido para IPv4: {ip}")
                
                conn_params = {
                    'dbname': parsed.path[1:],
                    'user': parsed.username,
                    'password': parsed.password,
                    'hostaddr': ip,
                    'port': parsed.port or 5432,
                    'sslmode': 'require',
                    'connect_timeout': 10
                }
                
                conn = psycopg2.connect(**conn_params)
                conn.autocommit = False
                print("✅ Conexão com banco estabelecida com sucesso (IPv4)!")
                return conn
            except Exception as e2:
                print(f"⚠️ Tentativa 2 falhou: {e2}")
                
                try:
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
                except Exception as e3:
                    print(f"❌ Todas as tentativas falharam: {e3}")
                    return None
    except Exception as e:
        print(f"❌ Erro ao conectar: {e}")
        traceback.print_exc()
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
        traceback.print_exc()
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
        traceback.print_exc()
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
        traceback.print_exc()
        conn.rollback()
        conn.close()
        return False

# ==========================================
# FUNÇÃO PARA GERAR NÚMERO DO PEDIDO (SEM LACUNAS)
# ==========================================

def gerar_numero_pedido():
    """Gera um número de pedido sequencial sem lacunas"""
    ano = datetime.now().year
    
    # Buscar TODOS os números de pedido do ano (de ambas as tabelas)
    pedidos = query_all("""
        SELECT numero_pedido FROM (
            SELECT numero_pedido FROM transacoes_financeiras 
            WHERE numero_pedido LIKE %s AND numero_pedido IS NOT NULL
            UNION ALL
            SELECT numero_pedido FROM producoes 
            WHERE numero_pedido LIKE %s AND numero_pedido IS NOT NULL
        ) AS todos_pedidos
        ORDER BY numero_pedido
    """, (f'PED-{ano}-%', f'PED-{ano}-%'))
    
    # Extrair os números sequenciais
    numeros = []
    for p in pedidos:
        if p and p['numero_pedido']:
            partes = p['numero_pedido'].split('-')
            if len(partes) == 3:
                try:
                    numeros.append(int(partes[2]))
                except:
                    pass
    
    # Se não houver pedidos, começar do 1
    if not numeros:
        return f'PED-{ano}-0001'
    
    # Ordenar e encontrar a primeira lacuna
    numeros.sort()
    proximo = 1
    for num in numeros:
        if num == proximo:
            proximo += 1
        else:
            break
    
    return f'PED-{ano}-{proximo:04d}'

# ==========================================
# FUNÇÃO PARA REORGANIZAR NÚMEROS DE PEDIDO
# ==========================================

def reorganizar_numeros_pedido():
    """Reorganiza os números de pedido para eliminar lacunas"""
    ano = datetime.now().year
    
    # Buscar todos os pedidos do ano em ordem de criação
    pedidos = query_all("""
        SELECT id, numero_pedido, 'transacao' as tipo FROM transacoes_financeiras 
        WHERE numero_pedido LIKE %s AND numero_pedido IS NOT NULL
        UNION ALL
        SELECT id, numero_pedido, 'producao' as tipo FROM producoes 
        WHERE numero_pedido LIKE %s AND numero_pedido IS NOT NULL
        ORDER BY numero_pedido
    """, (f'PED-{ano}-%', f'PED-{ano}-%'))
    
    if not pedidos:
        return
    
    conn = get_db_connection()
    if not conn:
        return
    
    try:
        cur = conn.cursor()
        
        # Reorganizar sequencialmente
        novo_num = 1
        for pedido in pedidos:
            novo_pedido = f'PED-{ano}-{novo_num:04d}'
            novo_num += 1
            
            # Atualizar na tabela correta
            if pedido['tipo'] == 'transacao':
                cur.execute("""
                    UPDATE transacoes_financeiras 
                    SET numero_pedido = %s 
                    WHERE id = %s
                """, (novo_pedido, pedido['id']))
            else:
                cur.execute("""
                    UPDATE producoes 
                    SET numero_pedido = %s 
                    WHERE id = %s
                """, (novo_pedido, pedido['id']))
        
        conn.commit()
        cur.close()
        conn.close()
        print(f"✅ Números de pedido reorganizados! Total: {len(pedidos)}")
        
    except Exception as e:
        conn.rollback()
        conn.close()
        print(f"❌ Erro ao reorganizar números: {e}")

# ==========================================
# ROTA DE HEALTHCHECK
# ==========================================

@app.route('/health')
def health():
    return "OK", 200

@app.route('/')
def home():
    if 'user_id' in session:
        return redirect(url_for('index'))
    return redirect(url_for('login'))

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
            return "✅ Conexão com banco OK!"
        else:
            return "❌ Falha na conexão com banco!", 500
    except Exception as e:
        return f"❌ Erro: {str(e)}", 500

# ==========================================
# GERAR NÚMERO DO PEDIDO VIA AJAX
# ==========================================

@app.route('/gerar_numero_pedido')
@login_required
def gerar_numero_pedido_ajax():
    """Retorna o próximo número de pedido via JSON"""
    numero = gerar_numero_pedido()
    return jsonify({'numero': numero})

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
# INDEX / DASHBOARD
# ==========================================

@app.route('/dashboard')
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

    # TOP CLIENTES
    top_clientes = query_all("""
        SELECT 
            c.nome,
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

    # VENDAS ÚLTIMOS 7 DIAS
    vendas_por_dia = query_all("""
        SELECT 
            TO_CHAR(DATE(data), 'DD/MM') AS dia,
            COUNT(*) AS quantidade,
            COALESCE(SUM(valor), 0) AS total
        FROM transacoes_financeiras
        WHERE tipo = 'entrada'
          AND data >= (CURRENT_DATE - INTERVAL '6 days')
        GROUP BY DATE(data)
        ORDER BY DATE(data) ASC
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
        # Gerar número do pedido automaticamente
        numero_pedido = gerar_numero_pedido()
        
        sql = """
            INSERT INTO producoes (pedido, numero_pedido, etapa_id, quantidade_pecas, colaborador_id, produto_id) 
            VALUES (%s, %s, %s, %s, %s, %s)
        """
        if execute_sql(sql, (
            request.form['pedido'] or numero_pedido,
            numero_pedido,
            request.form['etapa_id'],
            int(request.form['quantidade']),
            request.form.get('colaborador_id') or None,
            request.form.get('produto_id') or None
        )):
            flash(f'✅ Produção adicionada com sucesso! Pedido: {numero_pedido}')
        else:
            flash('❌ Erro ao adicionar produção')
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
        flash('✅ Produção atualizada com sucesso!')
    else:
        flash('❌ Erro ao atualizar produção')
    return redirect(url_for('producao'))

@app.route('/producao/delete/<string:id>', methods=['POST'])
@login_required
def producao_delete(id):
    # Buscar a produção antes de excluir
    producao = query_one("SELECT * FROM producoes WHERE id = %s", (id,))
    if not producao:
        flash('Produção não encontrada')
        return redirect(url_for('producao'))
    
    # Se já estiver finalizada, não pode excluir
    if producao['finalizado']:
        flash('⚠️ Não é possível excluir uma produção já finalizada!')
        return redirect(url_for('producao'))
    
    # Excluir
    if execute_sql("DELETE FROM producoes WHERE id = %s", (id,)):
        # Reorganizar os números de pedido após a exclusão
        reorganizar_numeros_pedido()
        flash('✅ Produção excluída com sucesso! Números de pedido reorganizados.')
    else:
        flash('❌ Erro ao excluir produção')
    
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
                    f'Produção finalizada - Pedido {producao["numero_pedido"] or producao["pedido"]}',
                    id
                ))
            flash('✅ Produção finalizada e estoque atualizado!')
        else:
            flash('✅ Produção finalizada!')
    else:
        flash('❌ Erro ao finalizar produção')
    return redirect(url_for('producao'))

@app.route('/producao/reativar/<string:id>', methods=['POST'])
@login_required
def producao_reativar(id):
    if execute_sql("UPDATE producoes SET finalizado = false, status = 'Em andamento' WHERE id = %s", (id,)):
        flash('✅ Produção reativada com sucesso!')
    else:
        flash('❌ Erro ao reativar produção')
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
            flash('✅ Colaborador cadastrado com sucesso!')
        else:
            flash('❌ Erro ao cadastrar colaborador')
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
        flash('✅ Colaborador atualizado com sucesso!')
    else:
        flash('❌ Erro ao atualizar colaborador')
    return redirect(url_for('colaboradores'))

@app.route('/colaboradores/delete/<string:id>', methods=['POST'])
@login_required
def colaborador_delete(id):
    em_uso = query_one("SELECT COUNT(*) as total FROM producoes WHERE colaborador_id = %s", (id,))
    if em_uso and em_uso['total'] > 0:
        flash('⚠️ Não é possível excluir. Colaborador está vinculado a produções!')
        return redirect(url_for('colaboradores'))

    if execute_sql("DELETE FROM colaboradores WHERE id = %s", (id,)):
        flash('✅ Colaborador excluído com sucesso!')
    else:
        flash('❌ Erro ao excluir colaborador')
    return redirect(url_for('colaboradores'))

# ==========================================
# FINANCEIRO (COM BAIXA NO ESTOQUE E NÚMERO DO PEDIDO)
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
        
        # Gerar número do pedido automaticamente apenas para vendas
        numero_pedido = gerar_numero_pedido() if tipo == 'entrada' else None

        # VALIDAÇÃO: Verificar estoque antes de registrar
        if tipo == 'entrada' and produto_id and quantidade > 0:
            produto_check = query_one("SELECT * FROM produtos WHERE id = %s", (produto_id,))
            if not produto_check:
                flash('❌ Produto não encontrado!')
                return redirect(url_for('financeiro'))
            
            if produto_check['estoque_atual'] < quantidade:
                flash(f'❌ Estoque insuficiente! Disponível: {produto_check["estoque_atual"]}, Solicitado: {quantidade}')
                return redirect(url_for('financeiro'))

        conn = get_db_connection()
        if not conn:
            flash('❌ Erro de conexão com banco de dados')
            return redirect(url_for('financeiro'))

        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # 1. Inserir a transação financeira com número do pedido
            sql_transacao = """
                INSERT INTO transacoes_financeiras 
                (tipo, categoria, descricao, valor, produto_id, quantidade, cliente_id, numero_pedido) 
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """
            cur.execute(sql_transacao, (tipo, categoria, request.form['descricao'], valor, produto_id, quantidade, cliente_id, numero_pedido))
            transacao_id = cur.fetchone()['id']

            # 2. Se for uma VENDA (entrada) e tiver produto e quantidade
            if tipo == 'entrada' and produto_id and quantidade > 0:
                cur.execute("SELECT * FROM produtos WHERE id = %s FOR UPDATE", (produto_id,))
                produto = cur.fetchone()

                if produto:
                    estoque_atual = produto['estoque_atual']
                    novo_estoque = estoque_atual - quantidade

                    if novo_estoque < 0:
                        novo_estoque = 0
                        flash('⚠️ Aviso: Estoque ficaria negativo. Ajustado para 0.', 'warning')

                    cur.execute("""
                        UPDATE produtos 
                        SET estoque_atual = %s, updated_at = NOW() 
                        WHERE id = %s
                    """, (novo_estoque, produto_id))

                    cur.execute("""
                        INSERT INTO movimentacoes_estoque 
                        (produto_id, tipo, origem, quantidade, descricao, referencia_id) 
                        VALUES (%s, 'saida', 'venda', %s, %s, %s)
                    """, (produto_id, quantidade, f'Venda - {request.form["descricao"]} - Pedido: {numero_pedido}', transacao_id))

                    flash(f'✅ Venda registrada! Pedido: {numero_pedido} | Estoque: {estoque_atual} → {novo_estoque} {produto["unidade"] or "UN"}', 'success')

            conn.commit()
            cur.close()
            conn.close()

            if tipo != 'entrada' or not produto_id or quantidade == 0:
                flash(f'✅ Transação registrada com sucesso!{" Pedido: " + numero_pedido if numero_pedido else ""}')

        except Exception as e:
            conn.rollback()
            conn.close()
            print(f"❌ Erro ao registrar transação: {e}")
            traceback.print_exc()
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
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # 1. Reverter alterações da transação original no estoque (se houver)
        if transacao_original['tipo'] == 'entrada' and transacao_original['produto_id'] and transacao_original['quantidade'] > 0:
            cur.execute("SELECT * FROM produtos WHERE id = %s FOR UPDATE", (transacao_original['produto_id'],))
            produto_original = cur.fetchone()
            if produto_original:
                estoque_atual = produto_original['estoque_atual']
                novo_estoque = estoque_atual + transacao_original['quantidade']
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
                estoque_atual = produto_novo['estoque_atual']
                novo_estoque = estoque_atual - nova_quantidade
                if novo_estoque < 0:
                    novo_estoque = 0
                    flash('⚠️ Aviso: Estoque ficaria negativo. Ajustado para 0.', 'warning')

                cur.execute("""
                    UPDATE produtos SET estoque_atual = %s, updated_at = NOW() 
                    WHERE id = %s
                """, (novo_estoque, novo_produto_id))

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
        print(f"❌ Erro ao atualizar transação: {e}")
        traceback.print_exc()
        flash(f'❌ Erro ao atualizar transação: {str(e)}')

    return redirect(url_for('financeiro'))


@app.route('/financeiro/delete/<string:id>', methods=['POST'])
@login_required
def financeiro_delete(id):
    transacao = query_one("SELECT * FROM transacoes_financeiras WHERE id = %s", (id,))
    if not transacao:
        flash('Transação não encontrada')
        return redirect(url_for('financeiro'))

    conn = get_db_connection()
    if not conn:
        flash('Erro de conexão com banco de dados')
        return redirect(url_for('financeiro'))

    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)

        if transacao['tipo'] == 'entrada' and transacao['produto_id'] and transacao['quantidade'] > 0:
            cur.execute("SELECT * FROM produtos WHERE id = %s FOR UPDATE", (transacao['produto_id'],))
            produto = cur.fetchone()
            if produto:
                estoque_atual = produto['estoque_atual']
                novo_estoque = estoque_atual + transacao['quantidade']
                cur.execute("""
                    UPDATE produtos SET estoque_atual = %s, updated_at = NOW() 
                    WHERE id = %s
                """, (novo_estoque, transacao['produto_id']))

                cur.execute("""
                    INSERT INTO movimentacoes_estoque 
                    (produto_id, tipo, origem, quantidade, descricao, referencia_id) 
                    VALUES (%s, 'entrada', 'cancelamento', %s, %s, %s)
                """, (transacao['produto_id'], transacao['quantidade'], f'Cancelamento de venda - {transacao["descricao"]}', id))

        cur.execute("DELETE FROM transacoes_financeiras WHERE id = %s", (id,))
        
        conn.commit()
        cur.close()
        conn.close()
        
        # Reorganizar os números de pedido após a exclusão
        reorganizar_numeros_pedido()
        
        flash('✅ Transação excluída com sucesso! Estoque revertido e números reorganizados.')

    except Exception as e:
        conn.rollback()
        conn.close()
        print(f"❌ Erro ao excluir transação: {e}")
        traceback.print_exc()
        flash(f'❌ Erro ao excluir transação: {str(e)}')

    return redirect(url_for('financeiro'))

# ==========================================
# RELATÓRIO
# ==========================================

@app.route('/relatorio')
@login_required
def relatorio():
    vendas_por_dia = query_all("""
        SELECT 
            TO_CHAR(DATE(data), 'DD/MM') AS dia,
            COUNT(*) AS quantidade,
            COALESCE(SUM(valor), 0) AS total
        FROM transacoes_financeiras
        WHERE tipo = 'entrada'
          AND data >= (CURRENT_DATE - INTERVAL '6 days')
        GROUP BY DATE(data)
        ORDER BY DATE(data) ASC
    """) or []

    top_clientes = query_all("""
        SELECT 
            c.nome,
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

    produtos_mais_vendidos = query_all("""
        SELECT 
            p.nome,
            COALESCE(SUM(t.quantidade), 0) AS total_vendido,
            COALESCE(SUM(t.valor), 0) AS total_faturamento
        FROM produtos p
        JOIN transacoes_financeiras t ON t.produto_id = p.id
        WHERE t.tipo = 'entrada'
        GROUP BY p.id, p.nome
        ORDER BY total_vendido DESC
        LIMIT 5
    """) or []

    produtos_estoque = query_all("""
        SELECT nome, estoque_atual 
        FROM produtos 
        WHERE status = 'ativo' 
        ORDER BY estoque_atual DESC 
        LIMIT 5
    """) or []

    ultimas_vendas = query_all("""
        SELECT 
            t.*,
            p.nome as produto_nome,
            c.nome as cliente_nome
        FROM transacoes_financeiras t
        LEFT JOIN produtos p ON t.produto_id = p.id
        LEFT JOIN clientes c ON t.cliente_id = c.id
        WHERE t.tipo = 'entrada'
        ORDER BY t.data DESC
        LIMIT 20
    """) or []

    ultimas_movimentacoes = query_all("""
        SELECT 
            m.*,
            p.nome as produto_nome
        FROM movimentacoes_estoque m
        LEFT JOIN produtos p ON m.produto_id = p.id
        ORDER BY m.data_movimentacao DESC
        LIMIT 20
    """) or []

    total_vendas = query_one("SELECT COUNT(*) as total FROM transacoes_financeiras WHERE tipo = 'entrada'")
    total_faturamento = query_one("SELECT COALESCE(SUM(valor), 0) as total FROM transacoes_financeiras WHERE tipo = 'entrada'")
    total_clientes = query_one("SELECT COUNT(*) as total FROM clientes")
    total_produtos = query_one("SELECT COUNT(*) as total FROM produtos WHERE status = 'ativo'")

    return render_template('relatorio.html',
                         vendas_por_dia=vendas_por_dia,
                         top_clientes=top_clientes,
                         produtos_mais_vendidos=produtos_mais_vendidos,
                         produtos_estoque=produtos_estoque,
                         ultimas_vendas=ultimas_vendas,
                         ultimas_movimentacoes=ultimas_movimentacoes,
                         total_vendas=total_vendas['total'] if total_vendas else 0,
                         total_faturamento=total_faturamento['total'] if total_faturamento else 0,
                         total_clientes=total_clientes['total'] if total_clientes else 0,
                         total_produtos=total_produtos['total'] if total_produtos else 0)

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
# ROTA PARA REORGANIZAR MANUALMENTE
# ==========================================

@app.route('/reorganizar_pedidos')
@login_required
def reorganizar_pedidos():
    """Rota para reorganizar números de pedido manualmente"""
    try:
        reorganizar_numeros_pedido()
        flash('✅ Números de pedido reorganizados com sucesso!')
    except Exception as e:
        flash(f'❌ Erro ao reorganizar: {str(e)}')
    return redirect(url_for('index'))

# ==========================================
# ROTA DE TESTE DE ESTOQUE
# ==========================================

@app.route('/teste/estoque/<string:produto_id>')
@login_required
def teste_estoque(produto_id):
    produto = query_one("SELECT * FROM produtos WHERE id = %s", (produto_id,))
    if not produto:
        return f"❌ Produto {produto_id} não encontrado!"
    
    movimentacoes = query_all("""
        SELECT * FROM movimentacoes_estoque 
        WHERE produto_id = %s 
        ORDER BY data_movimentacao DESC 
        LIMIT 20
    """, (produto_id,))
    
    html = f"""
    <h1>📦 Teste de Estoque - {produto['nome']}</h1>
    <p><strong>ID:</strong> {produto['id']}</p>
    <p><strong>Estoque Atual:</strong> {produto['estoque_atual']} {produto['unidade'] or 'UN'}</p>
    <p><strong>Estoque Mínimo:</strong> {produto['estoque_minimo']}</p>
    
    <h2>📊 Últimas Movimentações:</h2>
    <table border="1" cellpadding="5">
        <tr>
            <th>Data</th>
            <th>Tipo</th>
            <th>Origem</th>
            <th>Quantidade</th>
            <th>Descrição</th>
        </tr>
    """
    
    for m in movimentacoes:
        html += f"""
        <tr>
            <td>{m['data_movimentacao']}</td>
            <td>{m['tipo']}</td>
            <td>{m['origem']}</td>
            <td>{m['quantidade']}</td>
            <td>{m['descricao']}</td>
        </tr>
        """
    
    html += "</table>"
    return html

# ==========================================
# RODAR APP
# ==========================================

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    print(f"\n🚀 Iniciando aplicação na porta {port}")
    print(f"🔗 Acesse: http://localhost:{port}")
    print(f"🔗 Healthcheck: http://localhost:{port}/health")
    print("=" * 60)
    app.run(debug=False, host='0.0.0.0', port=port)