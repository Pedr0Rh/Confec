from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, send_file
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2.pool import SimpleConnectionPool
from dotenv import load_dotenv
from functools import wraps
from datetime import datetime, timedelta
import socket
import urllib.parse
import traceback
import io
from decimal import Decimal
import json
import time

# ==========================================
# CARREGAR VARIÁVEIS DO .env
# ==========================================
load_dotenv()
load_dotenv(override=True)

# ==========================================
# CONFIGURAR FUSO HORÁRIO PARA BRASIL (UTC-3)
# ==========================================
os.environ['TZ'] = 'America/Sao_Paulo'
try:
    import time as t
    t.tzset()
except:
    pass

# ==========================================
# FUNÇÃO PARA OBTER DATA/HORA ATUAL EM BRASÍLIA
# ==========================================

def agora_brasil():
    """Retorna a data/hora atual no fuso horário de Brasília (UTC-3)"""
    return datetime.now()

def ajustar_data_brasil(data_utc):
    """Converte uma data UTC para horário de Brasília (UTC-3)"""
    if not data_utc:
        return data_utc
    
    if isinstance(data_utc, str):
        try:
            data_utc = data_utc.replace('Z', '+00:00')
            data_utc = datetime.fromisoformat(data_utc)
        except:
            return data_utc
    
    return data_utc - timedelta(hours=3)

# ==========================================
# IMPORTAÇÕES PARA PDF
# ==========================================

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.graphics.shapes import Drawing
from reportlab.graphics.charts.barcharts import VerticalBarChart

# ==========================================
# VERIFICAR VARIÁVEIS DE AMBIENTE
# ==========================================
DATABASE_URL = os.getenv('DATABASE_URL')
SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key')
PORT = os.getenv('PORT', 8080)

if not DATABASE_URL:
    print("⚠️ DATABASE_URL não encontrada. Tentando carregar manualmente...")
    try:
        with open('.env', 'r') as f:
            for line in f:
                if line.startswith('DATABASE_URL='):
                    DATABASE_URL = line.strip().split('=', 1)[1].strip()
                    os.environ['DATABASE_URL'] = DATABASE_URL
                    break
    except:
        pass

print("=" * 60)
print("🚀 INICIANDO APLICAÇÃO")
print(f"📊 DATABASE_URL: {'✅ Configurada' if DATABASE_URL else '❌ NÃO CONFIGURADA'}")
print(f"🔑 SECRET_KEY: {'✅ Configurada' if SECRET_KEY != 'dev-secret-key' else '⚠️ Usando chave padrão'}")
print("=" * 60)

app = Flask(__name__)
app.config['SECRET_KEY'] = SECRET_KEY
app.config['DEBUG'] = False
app.config['TEMPLATES_AUTO_RELOAD'] = False
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 31536000

# ==========================================
# POOL DE CONEXÕES (OTIMIZADO)
# ==========================================

db_pool = None

def init_db_pool():
    """Inicializa o pool de conexões"""
    global db_pool
    if not DATABASE_URL:
        return None
    
    try:
        db_pool = SimpleConnectionPool(
            2, 10, DATABASE_URL,
            sslmode='require',
            connect_timeout=5,
            keepalives=1,
            keepalives_idle=5,
            keepalives_interval=2,
            keepalives_count=2,
            application_name='confec_system'
        )
        print("✅ Pool de conexões inicializado!")
        return db_pool
    except Exception as e:
        print(f"❌ Erro ao inicializar pool: {e}")
        return None

def get_conn():
    """Obtém uma conexão do pool"""
    global db_pool
    if db_pool is None:
        init_db_pool()
    try:
        if db_pool:
            return db_pool.getconn()
        return psycopg2.connect(DATABASE_URL, sslmode='require', connect_timeout=5)
    except:
        return psycopg2.connect(DATABASE_URL, sslmode='require', connect_timeout=5)

def put_conn(conn):
    """Libera uma conexão de volta ao pool"""
    global db_pool
    if db_pool and conn:
        try:
            db_pool.putconn(conn)
        except:
            try:
                conn.close()
            except:
                pass

# ==========================================
# QUERY OTIMIZADAS
# ==========================================

def query_one(sql, params=None):
    """Executa uma consulta e retorna um resultado (OTIMIZADO)"""
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(sql, params or ())
        result = cur.fetchone()
        cur.close()
        if result:
            for key in result.keys():
                if 'data' in key.lower() and isinstance(result[key], datetime):
                    result[key] = ajustar_data_brasil(result[key])
        return result
    except Exception as e:
        print(f"❌ Erro query_one: {e}")
        return None
    finally:
        put_conn(conn)

def query_all(sql, params=None):
    """Executa uma consulta e retorna todos os resultados (OTIMIZADO)"""
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(sql, params or ())
        results = cur.fetchall()
        cur.close()
        for result in results:
            for key in result.keys():
                if 'data' in key.lower() and isinstance(result[key], datetime):
                    result[key] = ajustar_data_brasil(result[key])
        return results
    except Exception as e:
        print(f"❌ Erro query_all: {e}")
        return []
    finally:
        put_conn(conn)

def execute_sql(sql, params=None):
    """Executa um comando SQL (OTIMIZADO)"""
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(sql, params or ())
        conn.commit()
        cur.close()
        return True
    except Exception as e:
        print(f"❌ Erro execute: {e}")
        try:
            conn.rollback()
        except:
            pass
        return False
    finally:
        put_conn(conn)

# ==========================================
# FUNÇÕES AUXILIARES
# ==========================================

meses_dict = {
    1: 'Janeiro', 2: 'Fevereiro', 3: 'Março', 4: 'Abril',
    5: 'Maio', 6: 'Junho', 7: 'Julho', 8: 'Agosto',
    9: 'Setembro', 10: 'Outubro', 11: 'Novembro', 12: 'Dezembro'
}

def traduzir_mes(data):
    if not data:
        return ''
    if isinstance(data, str):
        try:
            data = datetime.strptime(data, '%Y-%m-%d').date()
        except:
            try:
                data = datetime.fromisoformat(data.replace('Z', '+00:00')).date()
            except:
                return data
    if hasattr(data, 'month') and hasattr(data, 'year'):
        return f"{meses_dict.get(data.month, '')} {data.year}"
    return str(data)

@app.template_filter('mes_pt')
def mes_pt_filter(data):
    return traduzir_mes(data)

@app.template_filter('mes_ano_pt')
def mes_ano_pt_filter(data):
    if not data:
        return ''
    if isinstance(data, str):
        try:
            data = datetime.strptime(data, '%Y-%m-%d').date()
        except:
            try:
                data = datetime.fromisoformat(data.replace('Z', '+00:00')).date()
            except:
                return data
    if hasattr(data, 'month') and hasattr(data, 'year'):
        return f"{meses_dict.get(data.month, '')[:3]}/{data.year}"
    return str(data)

@app.template_filter('from_json')
def from_json_filter(value):
    if not value:
        return None
    try:
        return json.loads(value)
    except:
        return None

def formatar_data_brasil(data, formato='%d/%m/%Y %H:%M'):
    if not data:
        return '-'
    if isinstance(data, str):
        try:
            data = datetime.fromisoformat(data.replace('Z', '+00:00'))
        except:
            return data
    if isinstance(data, datetime):
        data = ajustar_data_brasil(data)
        return data.strftime(formato)
    return str(data)

def gerar_sku(nome_produto):
    palavras = nome_produto.strip().upper().split()
    if len(palavras) >= 2:
        sku_base = ''.join([p[0] for p in palavras[:4]])
    else:
        sku_base = nome_produto[:4].upper()
    
    ultimo = query_one("SELECT sku FROM produtos WHERE sku LIKE %s ORDER BY sku DESC LIMIT 1", (f'{sku_base}%',))
    if ultimo and ultimo['sku']:
        partes = ultimo['sku'].split('-')
        if len(partes) == 2:
            try:
                num = int(partes[1]) + 1
                return f'{sku_base}-{num:03d}'
            except:
                pass
    return f'{sku_base}-001'

def gerar_numero_pedido():
    agora = agora_brasil()
    prefixo = f'PED-{agora.year}-{agora.month:02d}-{agora.day:02d}'
    ultimo = query_one("SELECT numero_pedido FROM producoes WHERE numero_pedido LIKE %s ORDER BY numero_pedido DESC LIMIT 1", (f'{prefixo}-%',))
    if ultimo and ultimo['numero_pedido']:
        partes = ultimo['numero_pedido'].split('-')
        if len(partes) == 5:
            try:
                return f'{prefixo}-{int(partes[4]) + 1:04d}'
            except:
                pass
    return f'{prefixo}-0001'

def reorganizar_numeros_pedido():
    pedidos = query_all("SELECT id, numero_pedido, data_entrada FROM producoes WHERE numero_pedido IS NOT NULL ORDER BY data_entrada ASC")
    if not pedidos:
        return
    conn = get_conn()
    try:
        cur = conn.cursor()
        pedidos_por_data = {}
        for pedido in pedidos:
            data_str = pedido['data_entrada'].strftime('%Y-%m-%d') if pedido['data_entrada'] else agora_brasil().strftime('%Y-%m-%d')
            if data_str not in pedidos_por_data:
                pedidos_por_data[data_str] = []
            pedidos_por_data[data_str].append(pedido)
        for data_str, lista in pedidos_por_data.items():
            ano, mes, dia = data_str.split('-')
            prefixo = f'PED-{ano}-{mes}-{dia}'
            for i, pedido in enumerate(lista, 1):
                cur.execute("UPDATE producoes SET numero_pedido = %s WHERE id = %s", (f'{prefixo}-{i:04d}', pedido['id']))
        conn.commit()
        cur.close()
    except Exception as e:
        print(f"❌ Erro ao reorganizar: {e}")
    finally:
        put_conn(conn)

# ==========================================
# FUNÇÃO PARA GERAR RELATÓRIO PDF (OTIMIZADA)
# ==========================================

def gerar_relatorio_pdf():
    dados = {
        'resumo': query_one("""
            SELECT 
                (SELECT COUNT(*) FROM produtos WHERE status = 'ativo') as total_produtos,
                (SELECT COALESCE(SUM(estoque_atual), 0) FROM produtos) as total_estoque,
                (SELECT COALESCE(SUM(estoque_atual * preco_custo), 0) FROM produtos) as valor_estoque,
                (SELECT COUNT(*) FROM clientes) as total_clientes,
                (SELECT COUNT(*) FROM colaboradores) as total_colaboradores,
                (SELECT COUNT(*) FROM producoes WHERE finalizado = false) as producoes_andamento,
                (SELECT COUNT(*) FROM producoes WHERE finalizado = true) as producoes_finalizadas
        """),
        'vendas_por_dia': query_all("""
            SELECT TO_CHAR(DATE(data), 'DD/MM') AS dia, COUNT(*) AS quantidade, COALESCE(SUM(valor), 0) AS total
            FROM transacoes_financeiras WHERE tipo = 'entrada' AND data >= (CURRENT_DATE - INTERVAL '29 days')
            GROUP BY DATE(data) ORDER BY DATE(data) ASC
        """) or [],
        'top_clientes': query_all("""
            SELECT c.nome, COUNT(t.id) AS total_vendas, COALESCE(SUM(t.valor), 0) AS total_gasto
            FROM clientes c JOIN transacoes_financeiras t ON t.cliente_id = c.id
            WHERE t.tipo = 'entrada' GROUP BY c.id, c.nome ORDER BY total_gasto DESC LIMIT 10
        """) or [],
        'produtos_mais_vendidos': query_all("""
            SELECT p.nome, p.sku, COALESCE(SUM(t.quantidade), 0) AS total_vendido, COALESCE(SUM(t.valor), 0) AS total_faturamento
            FROM produtos p JOIN transacoes_financeiras t ON t.produto_id = p.id
            WHERE t.tipo = 'entrada' GROUP BY p.id, p.nome, p.sku ORDER BY total_vendido DESC LIMIT 10
        """) or [],
        'produtos_estoque_baixo': query_all("""
            SELECT nome, sku, estoque_atual, estoque_minimo
            FROM produtos WHERE status = 'ativo' AND estoque_atual <= estoque_minimo ORDER BY estoque_atual ASC
        """) or []
    }
    
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=15*mm, leftMargin=15*mm, topMargin=20*mm, bottomMargin=15*mm)
    styles = getSampleStyleSheet()
    story = []
    
    # Título
    title_style = ParagraphStyle('TitleStyle', parent=styles['Title'], fontSize=18, textColor=colors.HexColor('#1a1a2e'), alignment=TA_CENTER, spaceAfter=6)
    story.append(Paragraph("📊 RELATÓRIO COMPLETO", title_style))
    story.append(Paragraph(f"Gerado em: {agora_brasil().strftime('%d/%m/%Y %H:%M')}", styles['Normal']))
    story.append(Spacer(1, 6*mm))
    
    # Resumo
    story.append(Paragraph("1. RESUMO GERAL", styles['Heading2']))
    story.append(Spacer(1, 3*mm))
    
    resumo = dados['resumo']
    resumo_data = [
        ['Métrica', 'Valor'],
        ['Total de Produtos', str(resumo['total_produtos'] or 0)],
        ['Itens em Estoque', str(resumo['total_estoque'] or 0)],
        ['Valor do Estoque', f'R$ {resumo["valor_estoque"] or 0:.2f}'],
        ['Total de Clientes', str(resumo['total_clientes'] or 0)],
        ['Total de Colaboradores', str(resumo['total_colaboradores'] or 0)],
        ['Produções em Andamento', str(resumo['producoes_andamento'] or 0)],
        ['Produções Finalizadas', str(resumo['producoes_finalizadas'] or 0)],
    ]
    
    resumo_table = Table(resumo_data, colWidths=[80*mm, 70*mm])
    resumo_table.setStyle(TableStyle([
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1a1a2e')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#e5e7eb')),
        ('PADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(resumo_table)
    story.append(Spacer(1, 6*mm))
    
    # Vendas por dia (gráfico)
    story.append(Paragraph("2. VENDAS POR DIA", styles['Heading2']))
    vendas_data = dados['vendas_por_dia']
    if vendas_data:
        try:
            drawing = Drawing(400, 150)
            bc = VerticalBarChart()
            bc.x, bc.y = 50, 30
            bc.width, bc.height = 300, 100
            bc.data = [[float(v['total']) for v in vendas_data]]
            bc.categoryAxis.categoryNames = [v['dia'] for v in vendas_data]
            bc.categoryAxis.labels.fontSize = 6
            bc.categoryAxis.labels.angle = 45
            bc.valueAxis.valueMin = 0
            max_val = max([float(v['total']) for v in vendas_data]) * 1.2
            bc.valueAxis.valueMax = max_val if max_val > 0 else 100
            bc.valueAxis.labelTextFormat = 'R$ %s'
            bc.valueAxis.labels.fontSize = 7
            bc.bars[0].fillColor = colors.HexColor('#3498db')
            drawing.add(bc)
            story.append(drawing)
        except:
            pass
        story.append(Spacer(1, 6*mm))
    
    # Top clientes
    story.append(Paragraph("3. TOP CLIENTES", styles['Heading2']))
    top_clientes = dados['top_clientes']
    if top_clientes:
        clientes_data = [['Cliente', 'Vendas', 'Total Gasto']]
        for c in top_clientes:
            clientes_data.append([c['nome'][:25], str(c['total_vendas']), f'R$ {c["total_gasto"]:.2f}'])
        clientes_table = Table(clientes_data, colWidths=[80*mm, 40*mm, 50*mm])
        clientes_table.setStyle(TableStyle([
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1a1a2e')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#e5e7eb')),
            ('PADDING', (0,0), (-1,-1), 5),
        ]))
        story.append(clientes_table)
    story.append(Spacer(1, 6*mm))
    
    doc.build(story)
    pdf_data = buffer.getvalue()
    buffer.close()
    return pdf_data

# ==========================================
# ROTAS
# ==========================================

@app.route('/health')
def health():
    return "OK", 200

@app.route('/')
def home():
    if 'user_id' in session:
        return redirect(url_for('index'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        if not username or not password:
            flash('Preencha todos os campos!')
            return render_template('login.html')
        user = query_one("SELECT * FROM usuarios WHERE username = %s AND password = %s", (username, password))
        if user:
            session['user_id'] = user['id']
            session['user_nome'] = user['nome']
            flash(f'Bem-vindo, {user["nome"]}!')
            return redirect(url_for('index'))
        flash('Usuário ou senha inválidos!')
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

@app.route('/gerar_numero_pedido')
@login_required
def gerar_numero_pedido_ajax():
    return jsonify({'numero': gerar_numero_pedido()})

# ==========================================
# DASHBOARD (OTIMIZADO)
# ==========================================

@app.route('/dashboard')
@login_required
def index():
    mes_selecionado_str = request.args.get('mes', '')
    if mes_selecionado_str:
        try:
            ano, mes = mes_selecionado_str.split('-')
            mes_selecionado = datetime(int(ano), int(mes), 1).date()
        except:
            mes_selecionado = datetime.now().replace(day=1).date()
    else:
        mes_selecionado = datetime.now().replace(day=1).date()
    
    # Buscar tudo em uma única conexão
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Dados gerais
        cur.execute("""
            SELECT 
                (SELECT COUNT(*) FROM colaboradores) as total_colaboradores,
                (SELECT COUNT(*) FROM producoes WHERE finalizado = false) as total_producoes,
                (SELECT COUNT(*) FROM clientes) as total_clientes,
                (SELECT COUNT(*) FROM produtos WHERE status = 'ativo') as total_produtos,
                (SELECT COALESCE(SUM(estoque_atual), 0) FROM produtos) as total_estoque
        """)
        stats = cur.fetchone()
        
        # Financeiro do mês
        cur.execute("""
            SELECT 
                COALESCE(SUM(CASE WHEN tipo = 'entrada' THEN valor ELSE 0 END), 0) as entradas,
                COALESCE(SUM(CASE WHEN tipo = 'saida' THEN valor ELSE 0 END), 0) as saidas
            FROM transacoes_financeiras WHERE mes_referencia = %s
        """, (mes_selecionado,))
        fin = cur.fetchone()
        
        entradas = fin['entradas'] if fin else 0
        saidas = fin['saidas'] if fin else 0
        
        # Produção por etapa
        cur.execute("SELECT * FROM etapas_producao ORDER BY ordem")
        etapas = cur.fetchall()
        producao_por_etapa = []
        for etapa in etapas:
            cur.execute("SELECT COUNT(*) as total FROM producoes WHERE etapa_id = %s AND finalizado = false", (etapa['id'],))
            total = cur.fetchone()
            producao_por_etapa.append({'etapa': etapa['nome'], 'total': total['total'] if total else 0})
        
        # Top clientes do mês
        cur.execute("""
            SELECT c.nome, COUNT(t.id) AS total_vendas, COALESCE(SUM(t.valor), 0) AS total_gasto, COALESCE(SUM(t.quantidade), 0) AS total_produtos
            FROM clientes c JOIN transacoes_financeiras t ON t.cliente_id = c.id
            WHERE t.tipo = 'entrada' AND t.mes_referencia = %s
            GROUP BY c.id, c.nome ORDER BY total_gasto DESC LIMIT 5
        """, (mes_selecionado,))
        top_clientes = cur.fetchall() or []
        
        # Vendas por dia do mês
        cur.execute("""
            SELECT TO_CHAR(DATE(data), 'DD/MM') AS dia, COUNT(*) AS quantidade, COALESCE(SUM(valor), 0) AS total
            FROM transacoes_financeiras WHERE tipo = 'entrada' AND mes_referencia = %s
            GROUP BY DATE(data) ORDER BY DATE(data) ASC
        """, (mes_selecionado,))
        vendas_por_dia = cur.fetchall() or []
        
        # Meses disponíveis
        cur.execute("SELECT DISTINCT mes_referencia FROM transacoes_financeiras WHERE mes_referencia IS NOT NULL ORDER BY mes_referencia DESC")
        meses_disponiveis = cur.fetchall()
        
        cur.close()
    finally:
        put_conn(conn)
    
    # Verificar se o mês está fechado
    fechamento = query_one("SELECT * FROM fechamentos_caixa WHERE mes_referencia = %s AND status = 'fechado'", (mes_selecionado,))
    mes_fechado = fechamento is not None
    
    return render_template('index.html',
        total_colaboradores=stats['total_colaboradores'] if stats else 0,
        total_producoes=stats['total_producoes'] if stats else 0,
        total_clientes=stats['total_clientes'] if stats else 0,
        total_produtos=stats['total_produtos'] if stats else 0,
        total_estoque=stats['total_estoque'] if stats else 0,
        entradas=entradas, saidas=saidas, saldo=entradas - saidas,
        producao_por_etapa=producao_por_etapa,
        top_clientes=top_clientes, vendas_por_dia=vendas_por_dia,
        mes_selecionado=mes_selecionado, mes_label=traduzir_mes(mes_selecionado),
        meses_disponiveis=meses_disponiveis, mes_fechado=mes_fechado)

# ==========================================
# ESTOQUE
# ==========================================

@app.route('/estoque')
@login_required
def estoque():
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT p.*,
                COALESCE((SELECT SUM(valor * quantidade) FROM custos_produtos WHERE produto_id = p.id), 0) as custo_total,
                (p.preco_venda - COALESCE((SELECT SUM(valor * quantidade) FROM custos_produtos WHERE produto_id = p.id), 0)) as margem_reais,
                CASE WHEN p.preco_venda > 0 AND COALESCE((SELECT SUM(valor * quantidade) FROM custos_produtos WHERE produto_id = p.id), 0) > 0 
                    THEN ROUND(((p.preco_venda - COALESCE((SELECT SUM(valor * quantidade) FROM custos_produtos WHERE produto_id = p.id), 0)) / p.preco_venda) * 100, 2)
                    ELSE 0 END as margem_percentual
            FROM produtos p WHERE p.status = 'ativo' ORDER BY p.nome
        """)
        produtos = cur.fetchall()
        
        cur.execute("""
            SELECT COUNT(*) as total_produtos, COALESCE(SUM(estoque_atual), 0) as total_itens,
                COALESCE(SUM(estoque_atual * preco_custo), 0) as valor_total_estoque,
                COUNT(CASE WHEN estoque_atual <= estoque_minimo THEN 1 END) as produtos_abaixo_minimo
            FROM produtos WHERE status = 'ativo'
        """)
        resumo = cur.fetchone()
        cur.close()
    finally:
        put_conn(conn)
    
    return render_template('estoque.html', produtos=produtos, resumo=resumo)

# ==========================================
# PRODUÇÃO, FINANCEIRO, CRM, RELATÓRIO, FECHAMENTO
# ==========================================

# ==========================================
# PRODUÇÃO
# ==========================================

@app.route('/producao', methods=['GET', 'POST'])
@login_required
def producao():
    if request.method == 'POST':
        numero_pedido = gerar_numero_pedido()
        sql = """
            INSERT INTO producoes (pedido, numero_pedido, etapa_id, quantidade_pecas, colaborador_id, produto_id) 
            VALUES (%s, %s, %s, %s, %s, %s)
        """
        if execute_sql(sql, (
            request.form['pedido'] or numero_pedido, numero_pedido,
            request.form['etapa_id'], int(request.form['quantidade']),
            request.form.get('colaborador_id') or None,
            request.form.get('produto_id') or None
        )):
            flash(f'✅ Produção adicionada! Pedido: {numero_pedido}')
        else:
            flash('❌ Erro ao adicionar produção')
        return redirect(url_for('producao'))
    
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM etapas_producao ORDER BY ordem")
        etapas = cur.fetchall()
        cur.execute("SELECT * FROM colaboradores ORDER BY nome")
        colaboradores = cur.fetchall()
        cur.execute("SELECT * FROM produtos WHERE status = 'ativo' ORDER BY nome")
        produtos = cur.fetchall()
        cur.execute("""
            SELECT p.*, e.nome as etapa_nome, c.nome as colaborador_nome, pr.nome as produto_nome
            FROM producoes p LEFT JOIN etapas_producao e ON p.etapa_id = e.id 
            LEFT JOIN colaboradores c ON p.colaborador_id = c.id
            LEFT JOIN produtos pr ON p.produto_id = pr.id
            ORDER BY p.data_entrada DESC
        """)
        producoes = cur.fetchall()
        cur.close()
    finally:
        put_conn(conn)
    
    return render_template('producao.html', etapas=etapas, producoes=producoes, colaboradores=colaboradores, produtos=produtos)

@app.route('/producao/editar/<string:id>', methods=['POST'])
@login_required
def producao_editar(id):
    sql = """
        UPDATE producoes SET pedido = %s, etapa_id = %s, quantidade_pecas = %s,
        colaborador_id = %s, produto_id = %s WHERE id = %s
    """
    if execute_sql(sql, (
        request.form['pedido'], request.form['etapa_id'],
        int(request.form['quantidade']), request.form.get('colaborador_id') or None,
        request.form.get('produto_id') or None, id
    )):
        flash('✅ Produção atualizada!')
    else:
        flash('❌ Erro ao atualizar')
    return redirect(url_for('producao'))

@app.route('/producao/delete/<string:id>', methods=['POST'])
@login_required
def producao_delete(id):
    producao = query_one("SELECT * FROM producoes WHERE id = %s", (id,))
    if not producao:
        flash('Produção não encontrada')
        return redirect(url_for('producao'))
    if producao['finalizado']:
        flash('⚠️ Não é possível excluir uma produção finalizada!')
        return redirect(url_for('producao'))
    if execute_sql("DELETE FROM producoes WHERE id = %s", (id,)):
        reorganizar_numeros_pedido()
        flash('✅ Produção excluída! Números reorganizados.')
    else:
        flash('❌ Erro ao excluir')
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
                execute_sql("""
                    INSERT INTO movimentacoes_estoque (produto_id, tipo, origem, quantidade, descricao, referencia_id) 
                    VALUES (%s, 'entrada', 'producao', %s, %s, %s)
                """, (producao['produto_id'], producao['quantidade_pecas'], 
                      f'Produção finalizada - Pedido {producao["numero_pedido"] or producao["pedido"]}', id))
            flash('✅ Produção finalizada e estoque atualizado!')
        else:
            flash('✅ Produção finalizada!')
    else:
        flash('❌ Erro ao finalizar')
    return redirect(url_for('producao'))

@app.route('/producao/reativar/<string:id>', methods=['POST'])
@login_required
def producao_reativar(id):
    if execute_sql("UPDATE producoes SET finalizado = false, status = 'Em andamento' WHERE id = %s", (id,)):
        flash('✅ Produção reativada!')
    else:
        flash('❌ Erro ao reativar')
    return redirect(url_for('producao'))

# ==========================================
# COLABORADORES
# ==========================================

@app.route('/colaboradores', methods=['GET', 'POST'])
@login_required
def colaboradores():
    if request.method == 'POST':
        if execute_sql("INSERT INTO colaboradores (nome, funcao, telefone, observacao) VALUES (%s, %s, %s, %s)",
            (request.form['nome'], request.form['funcao'], request.form['telefone'], request.form['observacao'])):
            flash('✅ Colaborador cadastrado!')
        else:
            flash('❌ Erro ao cadastrar')
        return redirect(url_for('colaboradores'))
    
    colaboradores = query_all("SELECT * FROM colaboradores ORDER BY nome")
    funcoes = ['Costura', 'Elástico', 'Corte', 'Aprontamento', 'Fornecedor', 'Recepção', 'Expedição', 'Outro']
    return render_template('colaboradores.html', colaboradores=colaboradores, funcoes=funcoes)

@app.route('/colaboradores/editar/<string:id>', methods=['POST'])
@login_required
def colaborador_editar(id):
    sql = "UPDATE colaboradores SET nome=%s, funcao=%s, telefone=%s, observacao=%s WHERE id=%s"
    if execute_sql(sql, (request.form['nome'], request.form['funcao'], request.form['telefone'], request.form['observacao'], id)):
        flash('✅ Colaborador atualizado!')
    else:
        flash('❌ Erro ao atualizar')
    return redirect(url_for('colaboradores'))

@app.route('/colaboradores/delete/<string:id>', methods=['POST'])
@login_required
def colaborador_delete(id):
    em_uso = query_one("SELECT COUNT(*) as total FROM producoes WHERE colaborador_id = %s", (id,))
    if em_uso and em_uso['total'] > 0:
        flash('⚠️ Colaborador vinculado a produções!')
        return redirect(url_for('colaboradores'))
    if execute_sql("DELETE FROM colaboradores WHERE id = %s", (id,)):
        flash('✅ Colaborador excluído!')
    else:
        flash('❌ Erro ao excluir')
    return redirect(url_for('colaboradores'))

# ==========================================
# FINANCEIRO (OTIMIZADO)
# ==========================================

@app.route('/financeiro', methods=['GET', 'POST'])
@login_required
def financeiro():
    mes_selecionado_str = request.args.get('mes', '')
    if mes_selecionado_str:
        try:
            ano, mes = mes_selecionado_str.split('-')
            mes_selecionado = datetime(int(ano), int(mes), 1).date()
        except:
            mes_selecionado = datetime.now().replace(day=1).date()
    else:
        mes_selecionado = datetime.now().replace(day=1).date()
    
    fechamento = query_one("SELECT * FROM fechamentos_caixa WHERE mes_referencia = %s AND status = 'fechado'", (mes_selecionado,))
    mes_fechado = fechamento is not None
    
    if request.method == 'POST':
        if mes_fechado:
            flash('❌ Este mês está fechado! Estorne para adicionar.', 'danger')
            return redirect(url_for('financeiro', mes=mes_selecionado.strftime('%Y-%m')))
        
        categoria = request.form.get('categoria_personalizada') or request.form.get('categoria_selecionada', 'Geral')
        produto_id = request.form.get('produto_id') or None
        cliente_id = request.form.get('cliente_id') or None
        quantidade = int(request.form.get('quantidade', 0) or 0)
        valor = float(request.form['valor'])
        tipo = request.form['tipo']
        
        if tipo == 'entrada' and produto_id and quantidade > 0:
            produto_check = query_one("SELECT * FROM produtos WHERE id = %s", (produto_id,))
            if not produto_check:
                flash('❌ Produto não encontrado!')
                return redirect(url_for('financeiro', mes=mes_selecionado.strftime('%Y-%m')))
            if produto_check['estoque_atual'] < quantidade:
                flash(f'❌ Estoque insuficiente! Disponível: {produto_check["estoque_atual"]}')
                return redirect(url_for('financeiro', mes=mes_selecionado.strftime('%Y-%m')))
        
        conn = get_conn()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("""
                INSERT INTO transacoes_financeiras (tipo, categoria, descricao, valor, produto_id, quantidade, cliente_id, mes_referencia, fechado) 
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, false) RETURNING id
            """, (tipo, categoria, request.form['descricao'], valor, produto_id, quantidade, cliente_id, mes_selecionado))
            transacao_id = cur.fetchone()['id']
            
            if tipo == 'entrada' and produto_id and quantidade > 0:
                cur.execute("SELECT * FROM produtos WHERE id = %s FOR UPDATE", (produto_id,))
                produto = cur.fetchone()
                if produto:
                    novo_estoque = max(0, produto['estoque_atual'] - quantidade)
                    cur.execute("UPDATE produtos SET estoque_atual = %s, updated_at = NOW() WHERE id = %s", (novo_estoque, produto_id))
                    cur.execute("""
                        INSERT INTO movimentacoes_estoque (produto_id, tipo, origem, quantidade, descricao, referencia_id) 
                        VALUES (%s, 'saida', 'venda', %s, %s, %s)
                    """, (produto_id, quantidade, f'Venda - {request.form["descricao"]}', transacao_id))
                    flash(f'✅ Venda registrada! Estoque: {produto["estoque_atual"]} → {novo_estoque}')
            
            conn.commit()
            cur.close()
            flash('✅ Transação registrada!')
        except Exception as e:
            try:
                conn.rollback()
            except:
                pass
            print(f"❌ Erro: {e}")
            flash(f'❌ Erro ao registrar: {str(e)}')
        finally:
            put_conn(conn)
        return redirect(url_for('financeiro', mes=mes_selecionado.strftime('%Y-%m')))
    
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        cur.execute("""
            SELECT t.*, p.nome as produto_nome, c.nome as cliente_nome
            FROM transacoes_financeiras t
            LEFT JOIN produtos p ON t.produto_id = p.id
            LEFT JOIN clientes c ON t.cliente_id = c.id
            WHERE t.mes_referencia = %s ORDER BY t.data DESC
        """, (mes_selecionado,))
        transacoes = cur.fetchall()
        
        cur.execute("SELECT * FROM produtos WHERE status = 'ativo' ORDER BY nome")
        produtos = cur.fetchall()
        
        cur.execute("SELECT * FROM clientes ORDER BY nome")
        clientes = cur.fetchall()
        
        cur.execute("""
            SELECT COALESCE(SUM(CASE WHEN tipo = 'entrada' THEN valor ELSE 0 END), 0) as entradas,
                   COALESCE(SUM(CASE WHEN tipo = 'saida' THEN valor ELSE 0 END), 0) as saidas
            FROM transacoes_financeiras WHERE mes_referencia = %s
        """, (mes_selecionado,))
        resumo = cur.fetchone()
        
        cur.execute("""
            SELECT DISTINCT mes_referencia, 
                   EXISTS(SELECT 1 FROM fechamentos_caixa WHERE mes_referencia = t.mes_referencia AND status = 'fechado') as fechado
            FROM transacoes_financeiras t WHERE mes_referencia IS NOT NULL ORDER BY mes_referencia DESC
        """)
        meses_disponiveis = cur.fetchall()
        if not meses_disponiveis:
            meses_disponiveis = [{'mes_referencia': mes_selecionado, 'fechado': mes_fechado}]
        
        cur.execute("SELECT DISTINCT categoria FROM transacoes_financeiras WHERE categoria IS NOT NULL ORDER BY categoria")
        categorias = cur.fetchall()
        cur.close()
    finally:
        put_conn(conn)
    
    lista_categorias = [c['categoria'] for c in categorias] if categorias else []
    categorias_padrao = ['Fixa', 'Variável', 'Dívida', 'Imposto', 'Folha', 'Marketing', 'Manutenção', 'Geral', 'Venda']
    entradas = resumo['entradas'] if resumo else 0
    saidas = resumo['saidas'] if resumo else 0
    
    return render_template('financeiro.html',
        transacoes=transacoes, entradas=entradas, saidas=saidas, saldo=entradas - saidas,
        categorias_padrao=categorias_padrao, categorias_existentes=lista_categorias,
        produtos=produtos, clientes=clientes,
        mes_selecionado=mes_selecionado, mes_label=traduzir_mes(mes_selecionado),
        meses_disponiveis=meses_disponiveis, mes_fechado=mes_fechado)

@app.route('/financeiro/editar/<string:id>', methods=['POST'])
@login_required
def financeiro_editar(id):
    transacao_original = query_one("SELECT * FROM transacoes_financeiras WHERE id = %s", (id,))
    if not transacao_original:
        flash('Transação não encontrada')
        return redirect(url_for('financeiro'))
    
    fechamento = query_one("SELECT * FROM fechamentos_caixa WHERE mes_referencia = %s AND status = 'fechado'", (transacao_original['mes_referencia'],))
    if fechamento:
        flash('❌ Mês fechado! Estorne para editar.', 'danger')
        return redirect(url_for('financeiro', mes=transacao_original['mes_referencia'].strftime('%Y-%m')))
    
    categoria = request.form.get('categoria_personalizada') or request.form.get('categoria_selecionada', 'Geral')
    novo_tipo = request.form['tipo']
    novo_produto_id = request.form.get('produto_id') or None
    nova_quantidade = int(request.form.get('quantidade', 0) or 0)
    novo_valor = float(request.form['valor'])
    
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        if transacao_original['tipo'] == 'entrada' and transacao_original['produto_id'] and transacao_original['quantidade'] > 0:
            cur.execute("SELECT * FROM produtos WHERE id = %s FOR UPDATE", (transacao_original['produto_id'],))
            produto = cur.fetchone()
            if produto:
                cur.execute("UPDATE produtos SET estoque_atual = %s, updated_at = NOW() WHERE id = %s", 
                    (produto['estoque_atual'] + transacao_original['quantidade'], transacao_original['produto_id']))
        
        cur.execute("""
            UPDATE transacoes_financeiras SET tipo=%s, categoria=%s, descricao=%s, valor=%s, produto_id=%s, quantidade=%s, cliente_id=%s
            WHERE id = %s
        """, (novo_tipo, categoria, request.form['descricao'], novo_valor, novo_produto_id, nova_quantidade, 
              request.form.get('cliente_id') or None, id))
        
        if novo_tipo == 'entrada' and novo_produto_id and nova_quantidade > 0:
            cur.execute("SELECT * FROM produtos WHERE id = %s FOR UPDATE", (novo_produto_id,))
            produto = cur.fetchone()
            if produto:
                novo_estoque = max(0, produto['estoque_atual'] - nova_quantidade)
                cur.execute("UPDATE produtos SET estoque_atual = %s, updated_at = NOW() WHERE id = %s", (novo_estoque, novo_produto_id))
                cur.execute("""
                    INSERT INTO movimentacoes_estoque (produto_id, tipo, origem, quantidade, descricao, referencia_id) 
                    VALUES (%s, 'saida', 'venda', %s, %s, %s)
                """, (novo_produto_id, nova_quantidade, f'Venda editada - {request.form["descricao"]}', id))
        
        conn.commit()
        cur.close()
        flash('✅ Transação atualizada!')
    except Exception as e:
        try:
            conn.rollback()
        except:
            pass
        print(f"❌ Erro: {e}")
        flash(f'❌ Erro ao atualizar: {str(e)}')
    finally:
        put_conn(conn)
    
    return redirect(url_for('financeiro', mes=transacao_original['mes_referencia'].strftime('%Y-%m')))

@app.route('/financeiro/delete/<string:id>', methods=['POST'])
@login_required
def financeiro_delete(id):
    transacao = query_one("SELECT * FROM transacoes_financeiras WHERE id = %s", (id,))
    if not transacao:
        flash('Transação não encontrada')
        return redirect(url_for('financeiro'))
    
    fechamento = query_one("SELECT * FROM fechamentos_caixa WHERE mes_referencia = %s AND status = 'fechado'", (transacao['mes_referencia'],))
    if fechamento:
        flash('❌ Mês fechado! Estorne para excluir.', 'danger')
        return redirect(url_for('financeiro', mes=transacao['mes_referencia'].strftime('%Y-%m')))
    
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        if transacao['tipo'] == 'entrada' and transacao['produto_id'] and transacao['quantidade'] > 0:
            cur.execute("SELECT * FROM produtos WHERE id = %s FOR UPDATE", (transacao['produto_id'],))
            produto = cur.fetchone()
            if produto:
                cur.execute("UPDATE produtos SET estoque_atual = %s, updated_at = NOW() WHERE id = %s", 
                    (produto['estoque_atual'] + transacao['quantidade'], transacao['produto_id']))
                cur.execute("""
                    INSERT INTO movimentacoes_estoque (produto_id, tipo, origem, quantidade, descricao, referencia_id) 
                    VALUES (%s, 'entrada', 'cancelamento', %s, %s, %s)
                """, (transacao['produto_id'], transacao['quantidade'], f'Cancelamento - {transacao["descricao"]}', id))
        
        cur.execute("DELETE FROM transacoes_financeiras WHERE id = %s", (id,))
        conn.commit()
        cur.close()
        flash('✅ Transação excluída! Estoque revertido.')
    except Exception as e:
        try:
            conn.rollback()
        except:
            pass
        print(f"❌ Erro: {e}")
        flash(f'❌ Erro ao excluir: {str(e)}')
    finally:
        put_conn(conn)
    
    return redirect(url_for('financeiro', mes=transacao['mes_referencia'].strftime('%Y-%m')))

# ==========================================
# CRM
# ==========================================

@app.route('/crm')
@login_required
def crm():
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT c.*, COUNT(i.id) as total_interacoes
            FROM clientes c LEFT JOIN interacoes_clientes i ON c.id = i.cliente_id
            GROUP BY c.id ORDER BY CASE c.status WHEN 'ativo' THEN 1 WHEN 'potencial' THEN 2 WHEN 'inativo' THEN 3 END, c.nome
        """)
        clientes = cur.fetchall()
        
        cur.execute("""
            SELECT i.*, c.nome as cliente_nome FROM interacoes_clientes i
            JOIN clientes c ON i.cliente_id = c.id ORDER BY i.data_interacao DESC LIMIT 10
        """)
        interacoes_recentes = cur.fetchall()
        
        cur.execute("""
            SELECT COUNT(*) as total_clientes, COUNT(CASE WHEN status = 'ativo' THEN 1 END) as ativos,
                COUNT(CASE WHEN status = 'potencial' THEN 1 END) as potenciais,
                COUNT(CASE WHEN status = 'inativo' THEN 1 END) as inativos,
                COUNT(i.id) as total_interacoes
            FROM clientes c LEFT JOIN interacoes_clientes i ON c.id = i.cliente_id
        """)
        stats = cur.fetchone()
        cur.close()
    finally:
        put_conn(conn)
    
    return render_template('crm.html', clientes=clientes, interacoes_recentes=interacoes_recentes, stats=stats)

@app.route('/crm/cliente/<string:id>')
@login_required
def cliente_detalhe(id):
    cliente = query_one("""
        SELECT c.*, COUNT(i.id) as total_interacoes
        FROM clientes c LEFT JOIN interacoes_clientes i ON c.id = i.cliente_id
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
    proximo_contato = request.form.get('proximo_contato')
    if proximo_contato:
        proximo_contato = datetime.strptime(proximo_contato, '%Y-%m-%d').date()
    sql = """
        INSERT INTO clientes (nome, telefone, email, cnpj_cpf, endereco, cidade, estado, status, tipo, observacao, proximo_contato) 
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    if execute_sql(sql, (request.form['nome'], request.form['telefone'], request.form['email'], request.form.get('cnpj_cpf'),
        request.form.get('endereco'), request.form.get('cidade'), request.form.get('estado'),
        request.form.get('status', 'potencial'), request.form.get('tipo', 'pessoa_fisica'),
        request.form.get('observacao'), proximo_contato)):
        flash('✅ Cliente cadastrado!')
    else:
        flash('❌ Erro ao cadastrar')
    return redirect(url_for('crm'))

@app.route('/crm/editar/<string:id>', methods=['POST'])
@login_required
def cliente_editar(id):
    proximo_contato = request.form.get('proximo_contato')
    if proximo_contato:
        proximo_contato = datetime.strptime(proximo_contato, '%Y-%m-%d').date()
    sql = """
        UPDATE clientes SET nome=%s, telefone=%s, email=%s, cnpj_cpf=%s, endereco=%s, cidade=%s, estado=%s,
        status=%s, tipo=%s, observacao=%s, proximo_contato=%s WHERE id=%s
    """
    if execute_sql(sql, (request.form['nome'], request.form['telefone'], request.form['email'], request.form.get('cnpj_cpf'),
        request.form.get('endereco'), request.form.get('cidade'), request.form.get('estado'),
        request.form.get('status'), request.form.get('tipo'), request.form.get('observacao'),
        proximo_contato, id)):
        flash('✅ Cliente atualizado!')
    else:
        flash('❌ Erro ao atualizar')
    return redirect(url_for('cliente_detalhe', id=id))

@app.route('/crm/interacao/<string:cliente_id>', methods=['POST'])
@login_required
def cliente_interacao(cliente_id):
    if execute_sql("INSERT INTO interacoes_clientes (cliente_id, tipo, descricao) VALUES (%s, %s, %s)",
        (cliente_id, request.form['tipo'], request.form['descricao'])):
        execute_sql("UPDATE clientes SET ultimo_contato = NOW()::date WHERE id = %s", (cliente_id,))
        flash('✅ Interação registrada!')
    else:
        flash('❌ Erro ao registrar')
    return redirect(url_for('cliente_detalhe', id=cliente_id))

@app.route('/crm/buscar', methods=['GET'])
@login_required
def cliente_buscar():
    termo = request.args.get('q', '').strip()
    if not termo:
        return redirect(url_for('crm'))
    clientes = query_all("""
        SELECT c.*, COUNT(i.id) as total_interacoes
        FROM clientes c LEFT JOIN interacoes_clientes i ON c.id = i.cliente_id
        WHERE c.nome ILIKE %s OR c.telefone ILIKE %s OR c.email ILIKE %s
        GROUP BY c.id ORDER BY c.nome
    """, (f'%{termo}%', f'%{termo}%', f'%{termo}%'))
    return render_template('crm_busca.html', clientes=clientes, termo=termo)

@app.route('/crm/delete/<string:id>', methods=['POST'])
@login_required
def cliente_delete(id):
    if execute_sql("DELETE FROM clientes WHERE id = %s", (id,)):
        flash('✅ Cliente excluído!')
    else:
        flash('❌ Erro ao excluir')
    return redirect(url_for('crm'))

# ==========================================
# RELATÓRIO (OTIMIZADO)
# ==========================================

@app.route('/relatorio')
@login_required
def relatorio():
    """Relatório completo com análises, gráficos e filtros por período"""
    
    # ===== PEGAR FILTROS DA URL =====
    periodo = request.args.get('periodo', '30d')
    data_inicio_str = request.args.get('data_inicio', '')
    data_fim_str = request.args.get('data_fim', '')
    
    # ===== DEFINIR DATAS =====
    hoje = datetime.now().date()
    
    if data_inicio_str and data_fim_str:
        try:
            data_inicio = datetime.strptime(data_inicio_str, '%Y-%m-%d').date()
            data_fim = datetime.strptime(data_fim_str, '%Y-%m-%d').date()
            periodo_label = f"{data_inicio.strftime('%d/%m/%Y')} a {data_fim.strftime('%d/%m/%Y')}"
        except:
            data_inicio = hoje - timedelta(days=30)
            data_fim = hoje
            periodo_label = "Últimos 30 dias"
    else:
        if periodo == '7d':
            data_inicio = hoje - timedelta(days=7)
            data_fim = hoje
            periodo_label = "Últimos 7 dias"
        elif periodo == '15d':
            data_inicio = hoje - timedelta(days=15)
            data_fim = hoje
            periodo_label = "Últimos 15 dias"
        elif periodo == '30d':
            data_inicio = hoje - timedelta(days=30)
            data_fim = hoje
            periodo_label = "Últimos 30 dias"
        elif periodo == '60d':
            data_inicio = hoje - timedelta(days=60)
            data_fim = hoje
            periodo_label = "Últimos 60 dias"
        elif periodo == '90d':
            data_inicio = hoje - timedelta(days=90)
            data_fim = hoje
            periodo_label = "Últimos 90 dias"
        elif periodo == 'mes_atual':
            data_inicio = hoje.replace(day=1)
            data_fim = hoje
            periodo_label = f"Mês atual - {hoje.strftime('%B/%Y')}"
        elif periodo == 'ano':
            data_inicio = hoje.replace(month=1, day=1)
            data_fim = hoje
            periodo_label = f"Ano {hoje.year}"
        else:
            data_inicio = hoje - timedelta(days=30)
            data_fim = hoje
            periodo_label = "Últimos 30 dias"
    
    # ===== USAR UMA ÚNICA CONEXÃO =====
    conn = get_conn()
    
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # 1. RESUMO GERAL (sempre igual)
        cur.execute("""
            SELECT 
                (SELECT COUNT(*) FROM produtos WHERE status = 'ativo') as total_produtos,
                (SELECT COALESCE(SUM(estoque_atual), 0) FROM produtos) as total_estoque,
                (SELECT COALESCE(SUM(estoque_atual * preco_custo), 0) FROM produtos) as valor_estoque,
                (SELECT COUNT(*) FROM clientes) as total_clientes,
                (SELECT COUNT(*) FROM colaboradores) as total_colaboradores,
                (SELECT COUNT(*) FROM producoes WHERE finalizado = false) as producoes_andamento,
                (SELECT COUNT(*) FROM producoes WHERE finalizado = true) as producoes_finalizadas
        """)
        resumo_geral = cur.fetchone()
        
        # 2. ANÁLISE FINANCEIRA (usando mes_referencia)
        cur.execute("""
            SELECT 
                COALESCE(SUM(CASE WHEN tipo = 'entrada' THEN valor ELSE 0 END), 0) as entradas,
                COALESCE(SUM(CASE WHEN tipo = 'saida' THEN valor ELSE 0 END), 0) as saidas,
                COUNT(CASE WHEN tipo = 'entrada' THEN 1 END) as qtd_vendas,
                COUNT(CASE WHEN tipo = 'saida' THEN 1 END) as qtd_despesas,
                COALESCE(AVG(CASE WHEN tipo = 'entrada' THEN valor ELSE NULL END), 0) as ticket_medio,
                COALESCE(MAX(CASE WHEN tipo = 'entrada' THEN valor ELSE 0 END), 0) as maior_venda,
                COALESCE(MIN(CASE WHEN tipo = 'entrada' THEN valor ELSE 0 END), 0) as menor_venda
            FROM transacoes_financeiras
            WHERE mes_referencia >= %s AND mes_referencia <= %s
        """, (data_inicio, data_fim))
        analise_financeira = cur.fetchone()
        
        # 3. VENDAS POR DIA (usando data)
        cur.execute("""
            SELECT 
                TO_CHAR(data::date, 'DD/MM') as dia,
                data::date as data_completa,
                COUNT(*) AS quantidade,
                COALESCE(SUM(valor), 0) AS total,
                COALESCE(AVG(valor), 0) AS ticket_medio
            FROM transacoes_financeiras
            WHERE tipo = 'entrada' AND mes_referencia >= %s AND mes_referencia <= %s
            GROUP BY data::date
            ORDER BY data::date ASC
        """, (data_inicio, data_fim))
        vendas_por_dia = cur.fetchall() or []
        
        # 4. VENDAS MENSAIS
        cur.execute("""
            SELECT 
                TO_CHAR(DATE_TRUNC('month', mes_referencia), 'MM/YYYY') AS mes,
                DATE_TRUNC('month', mes_referencia) as data_mes,
                COUNT(*) AS quantidade,
                COALESCE(SUM(valor), 0) AS total,
                COALESCE(AVG(valor), 0) AS ticket_medio
            FROM transacoes_financeiras
            WHERE tipo = 'entrada'
              AND mes_referencia >= (CURRENT_DATE - INTERVAL '11 months')
            GROUP BY DATE_TRUNC('month', mes_referencia)
            ORDER BY DATE_TRUNC('month', mes_referencia) ASC
        """)
        vendas_mensais = cur.fetchall() or []
        
        # 5. TOP CLIENTES (usando mes_referencia)
        cur.execute("""
            SELECT 
                c.nome,
                c.telefone,
                COUNT(t.id) AS total_vendas,
                COALESCE(SUM(t.valor), 0) AS total_gasto,
                COALESCE(AVG(t.valor), 0) AS ticket_medio,
                COALESCE(SUM(t.quantidade), 0) AS total_produtos
            FROM clientes c
            JOIN transacoes_financeiras t ON t.cliente_id = c.id
            WHERE t.tipo = 'entrada' AND t.mes_referencia >= %s AND t.mes_referencia <= %s
            GROUP BY c.id, c.nome, c.telefone
            ORDER BY total_gasto DESC
            LIMIT 10
        """, (data_inicio, data_fim))
        top_clientes = cur.fetchall() or []
        
        # 6. PRODUTOS MAIS VENDIDOS (usando mes_referencia)
        cur.execute("""
            SELECT 
                p.nome,
                p.sku,
                COALESCE(SUM(t.quantidade), 0) AS total_vendido,
                COALESCE(SUM(t.valor), 0) AS total_faturamento,
                p.estoque_atual
            FROM produtos p
            JOIN transacoes_financeiras t ON t.produto_id = p.id
            WHERE t.tipo = 'entrada' AND t.mes_referencia >= %s AND t.mes_referencia <= %s
            GROUP BY p.id, p.nome, p.sku, p.estoque_atual
            ORDER BY total_vendido DESC
            LIMIT 10
        """, (data_inicio, data_fim))
        produtos_mais_vendidos = cur.fetchall() or []
        
        # 7. PRODUTOS COM ESTOQUE BAIXO
        cur.execute("""
            SELECT 
                nome,
                sku,
                estoque_atual,
                estoque_minimo,
                (estoque_minimo - estoque_atual) as deficit
            FROM produtos 
            WHERE status = 'ativo' AND estoque_atual <= estoque_minimo
            ORDER BY deficit DESC
        """)
        produtos_estoque_baixo = cur.fetchall() or []
        
        # 8. PRODUÇÃO POR ETAPA
        cur.execute("""
            SELECT 
                e.nome as etapa,
                COUNT(p.id) as qtd_producoes,
                COALESCE(SUM(p.quantidade_pecas), 0) as total_pecas,
                COALESCE(AVG(p.quantidade_pecas), 0) as media_pecas,
                COUNT(CASE WHEN p.finalizado = true THEN 1 END) as finalizadas,
                COUNT(CASE WHEN p.finalizado = false THEN 1 END) as em_andamento
            FROM producoes p
            JOIN etapas_producao e ON p.etapa_id = e.id
            WHERE p.data_entrada::date >= %s AND p.data_entrada::date <= %s
            GROUP BY e.id, e.nome
            ORDER BY e.ordem
        """, (data_inicio, data_fim))
        producao_etapas = cur.fetchall() or []
        
        # 9. ANÁLISE DE PRODUÇÃO
        cur.execute("""
            SELECT 
                COUNT(*) as total_producoes,
                COALESCE(SUM(quantidade_pecas), 0) as total_pecas,
                COALESCE(AVG(quantidade_pecas), 0) as media_pecas_por_producao,
                COUNT(CASE WHEN finalizado = true THEN 1 END) as finalizadas,
                COUNT(CASE WHEN finalizado = false THEN 1 END) as em_andamento
            FROM producoes
            WHERE data_entrada::date >= %s AND data_entrada::date <= %s
        """, (data_inicio, data_fim))
        analise_producao = cur.fetchone()
        
        # 10. ÚLTIMAS VENDAS (usando mes_referencia)
        cur.execute("""
            SELECT 
                t.data,
                t.valor,
                t.quantidade,
                t.descricao,
                p.nome as produto_nome,
                c.nome as cliente_nome
            FROM transacoes_financeiras t
            LEFT JOIN produtos p ON t.produto_id = p.id
            LEFT JOIN clientes c ON t.cliente_id = c.id
            WHERE t.tipo = 'entrada' AND t.mes_referencia >= %s AND t.mes_referencia <= %s
            ORDER BY t.data DESC
            LIMIT 20
        """, (data_inicio, data_fim))
        ultimas_vendas = cur.fetchall() or []
        
        # 11. ÚLTIMAS DESPESAS (usando mes_referencia)
        cur.execute("""
            SELECT 
                t.data,
                t.valor,
                t.descricao,
                t.categoria
            FROM transacoes_financeiras t
            WHERE t.tipo = 'saida' AND t.mes_referencia >= %s AND t.mes_referencia <= %s
            ORDER BY t.data DESC
            LIMIT 20
        """, (data_inicio, data_fim))
        ultimas_despesas = cur.fetchall() or []
        
        # 12. CATEGORIAS MAIS VENDIDAS (usando mes_referencia)
        cur.execute("""
            SELECT 
                COALESCE(p.categoria, 'Sem categoria') as categoria,
                COUNT(t.id) as qtd_vendas,
                COALESCE(SUM(t.quantidade), 0) as total_itens,
                COALESCE(SUM(t.valor), 0) as total_faturamento
            FROM transacoes_financeiras t
            LEFT JOIN produtos p ON t.produto_id = p.id
            WHERE t.tipo = 'entrada' AND t.mes_referencia >= %s AND t.mes_referencia <= %s
            GROUP BY p.categoria
            ORDER BY total_faturamento DESC
        """, (data_inicio, data_fim))
        categorias_mais_vendidas = cur.fetchall() or []
        
        # 13. VENDAS POR DIA DA SEMANA (usando mes_referencia)
        cur.execute("""
            SELECT 
                CASE EXTRACT(DOW FROM data)
                    WHEN 0 THEN 'Domingo'
                    WHEN 1 THEN 'Segunda-feira'
                    WHEN 2 THEN 'Terça-feira'
                    WHEN 3 THEN 'Quarta-feira'
                    WHEN 4 THEN 'Quinta-feira'
                    WHEN 5 THEN 'Sexta-feira'
                    WHEN 6 THEN 'Sábado'
                END as dia_semana,
                COUNT(*) as qtd_vendas,
                COALESCE(SUM(valor), 0) as total_vendas,
                COALESCE(AVG(valor), 0) as ticket_medio
            FROM transacoes_financeiras
            WHERE tipo = 'entrada' AND mes_referencia >= %s AND mes_referencia <= %s
            GROUP BY EXTRACT(DOW FROM data)
            ORDER BY EXTRACT(DOW FROM data) ASC
        """, (data_inicio, data_fim))
        vendas_por_dia_semana = cur.fetchall() or []
        
        # 14. MOVIMENTAÇÕES DE ESTOQUE
        cur.execute("""
            SELECT 
                m.data_movimentacao,
                m.tipo,
                m.origem,
                m.quantidade,
                m.descricao,
                p.nome as produto_nome
            FROM movimentacoes_estoque m
            LEFT JOIN produtos p ON m.produto_id = p.id
            WHERE m.data_movimentacao::date >= %s AND m.data_movimentacao::date <= %s
            ORDER BY m.data_movimentacao DESC
            LIMIT 30
        """, (data_inicio, data_fim))
        movimentacoes_estoque = cur.fetchall() or []
        
        # 15. RESUMO POR CATEGORIA (usando mes_referencia)
        cur.execute("""
            SELECT 
                categoria,
                COUNT(*) as total,
                COALESCE(SUM(CASE WHEN tipo = 'entrada' THEN valor ELSE 0 END), 0) as entradas,
                COALESCE(SUM(CASE WHEN tipo = 'saida' THEN valor ELSE 0 END), 0) as saidas,
                COALESCE(SUM(CASE WHEN tipo = 'entrada' THEN valor ELSE -valor END), 0) as saldo
            FROM transacoes_financeiras
            WHERE mes_referencia >= %s AND mes_referencia <= %s
            GROUP BY categoria
            ORDER BY saldo DESC
        """, (data_inicio, data_fim))
        resumo_por_categoria = cur.fetchall() or []
        
        # 16. MESES DISPONÍVEIS
        cur.execute("""
            SELECT DISTINCT 
                TO_CHAR(DATE_TRUNC('month', mes_referencia), 'YYYY-MM') as mes,
                DATE_TRUNC('month', mes_referencia) as data_mes
            FROM transacoes_financeiras
            WHERE mes_referencia IS NOT NULL
            ORDER BY data_mes DESC
        """)
        meses_disponiveis = cur.fetchall() or []
        
        cur.close()
        
    finally:
        put_conn(conn)
    
    return render_template('relatorio_completo.html',
        resumo_geral=resumo_geral,
        vendas_por_dia=vendas_por_dia,
        vendas_mensais=vendas_mensais,
        top_clientes=top_clientes,
        produtos_mais_vendidos=produtos_mais_vendidos,
        produtos_estoque_baixo=produtos_estoque_baixo,
        analise_financeira=analise_financeira,
        analise_producao=analise_producao,
        producao_etapas=producao_etapas,
        ultimas_vendas=ultimas_vendas,
        ultimas_despesas=ultimas_despesas,
        categorias_mais_vendidas=categorias_mais_vendidas,
        vendas_por_dia_semana=vendas_por_dia_semana,
        movimentacoes_estoque=movimentacoes_estoque,
        resumo_por_categoria=resumo_por_categoria,
        periodo=periodo,
        periodo_label=periodo_label,
        data_inicio=data_inicio.strftime('%Y-%m-%d'),
        data_fim=data_fim.strftime('%Y-%m-%d'),
        meses_disponiveis=meses_disponiveis)

@app.route('/relatorio/pdf')
@login_required
def relatorio_pdf():
    try:
        pdf_data = gerar_relatorio_pdf()
        return send_file(io.BytesIO(pdf_data), as_attachment=True,
            download_name=f'relatorio_{agora_brasil().strftime("%Y%m%d_%H%M")}.pdf',
            mimetype='application/pdf')
    except Exception as e:
        flash(f'❌ Erro ao gerar PDF: {str(e)}')
        return redirect(url_for('relatorio'))

# ==========================================
# FECHAMENTO DE FLUXO DE CAIXA MENSAL
# ==========================================

@app.route('/fechamento_caixa')
@login_required
def fechamento_caixa():
    """Tela principal de fechamento de caixa"""
    fechamentos = query_all("""
        SELECT fc.*, u.nome as fechado_por_nome, 
               u2.nome as estornado_por_nome
        FROM fechamentos_caixa fc
        LEFT JOIN usuarios u ON fc.fechado_por = u.id
        LEFT JOIN usuarios u2 ON fc.estornado_por = u2.id
        ORDER BY fc.mes_referencia DESC
    """)
    
    # Buscar APENAS meses com transações NÃO FECHADAS
    meses_com_transacoes = query_all("""
        SELECT DISTINCT mes_referencia
        FROM transacoes_financeiras
        WHERE mes_referencia IS NOT NULL AND fechado = false
        ORDER BY mes_referencia DESC
    """)
    
    meses_disponiveis = []
    for item in meses_com_transacoes:
        mes_ref = item['mes_referencia']
        existe = query_one("""
            SELECT id FROM fechamentos_caixa 
            WHERE mes_referencia = %s AND status = 'fechado'
        """, (mes_ref,))
        
        # Verificar se há transações NÃO FECHADAS no mês
        tem_transacoes_abertas = query_one("""
            SELECT COUNT(*) as total
            FROM transacoes_financeiras
            WHERE mes_referencia = %s AND fechado = false
        """, (mes_ref,))
        
        meses_disponiveis.append({
            'mes': mes_ref,
            'label': traduzir_mes(mes_ref),
            'fechado': existe is not None,
            'fechamento_id': existe['id'] if existe else None,
            'tem_transacoes_abertas': tem_transacoes_abertas['total'] > 0 if tem_transacoes_abertas else False
        })
    
    return render_template('fechamento_caixa.html', 
                         fechamentos=fechamentos,
                         meses_disponiveis=meses_disponiveis)

@app.route('/fechamento_caixa/preview/<int:ano>/<int:mes>')
@login_required
def fechamento_caixa_preview(ano, mes):
    """Preview do fechamento antes de confirmar"""
    data_inicio = datetime(ano, mes, 1).date()
    
    # Verificar se o mês tem movimentos
    tem_movimentos = query_one("""
        SELECT COUNT(*) as total
        FROM transacoes_financeiras
        WHERE mes_referencia = %s AND fechado = false
    """, (data_inicio,))
    
    if not tem_movimentos or tem_movimentos['total'] == 0:
        flash('⚠️ Este mês não tem movimentações para fechar!', 'warning')
        return redirect(url_for('fechamento_caixa'))
    
    # Verificar se já existe fechamento
    fechamento_existente = query_one("""
        SELECT * FROM fechamentos_caixa 
        WHERE mes_referencia = %s AND status = 'fechado'
    """, (data_inicio,))
    
    if fechamento_existente:
        flash('Este mês já foi fechado!', 'warning')
        return redirect(url_for('fechamento_caixa'))
    
    # Buscar APENAS transações do mês selecionado (NÃO fechadas)
    dados = query_one("""
        SELECT 
            COALESCE(SUM(CASE WHEN tipo = 'entrada' THEN valor ELSE 0 END), 0) as entradas,
            COALESCE(SUM(CASE WHEN tipo = 'saida' THEN valor ELSE 0 END), 0) as saidas,
            COUNT(CASE WHEN tipo = 'entrada' THEN 1 END) as total_vendas,
            COUNT(CASE WHEN tipo = 'saida' THEN 1 END) as total_despesas,
            COALESCE(AVG(CASE WHEN tipo = 'entrada' THEN valor ELSE NULL END), 0) as ticket_medio
        FROM transacoes_financeiras
        WHERE mes_referencia = %s AND fechado = false
    """, (data_inicio,))
    
    # Buscar fechamento do mês anterior para pegar o saldo final
    if mes == 1:
        mes_anterior = datetime(ano - 1, 12, 1).date()
    else:
        mes_anterior = datetime(ano, mes - 1, 1).date()
    
    fechamento_anterior = query_one("""
        SELECT saldo_final 
        FROM fechamentos_caixa 
        WHERE mes_referencia = %s AND status = 'fechado'
    """, (mes_anterior,))
    
    # Saldo inicial = saldo final do mês anterior (se existir) ou 0
    saldo_inicial = fechamento_anterior['saldo_final'] if fechamento_anterior else 0
    
    entradas = dados['entradas'] if dados else 0
    saidas = dados['saidas'] if dados else 0
    saldo_final = saldo_inicial + entradas - saidas
    
    # Buscar últimas transações do mês
    ultimas_transacoes = query_all("""
        SELECT t.*, p.nome as produto_nome, c.nome as cliente_nome
        FROM transacoes_financeiras t
        LEFT JOIN produtos p ON t.produto_id = p.id
        LEFT JOIN clientes c ON t.cliente_id = c.id
        WHERE t.mes_referencia = %s AND t.fechado = false
        ORDER BY t.data DESC
        LIMIT 20
    """, (data_inicio,))
    
    # Buscar fechamentos anteriores para referência
    fechamentos_anteriores = query_all("""
        SELECT mes_referencia, saldo_final, status
        FROM fechamentos_caixa
        WHERE mes_referencia < %s AND status = 'fechado'
        ORDER BY mes_referencia DESC
        LIMIT 6
    """, (data_inicio,))
    
    return render_template('fechamento_caixa_preview.html',
                         ano=ano,
                         mes=mes,
                         mes_label=traduzir_mes(data_inicio),
                         data_inicio=data_inicio,
                         saldo_inicial=saldo_inicial,
                         entradas=entradas,
                         saidas=saidas,
                         saldo_final=saldo_final,
                         total_vendas=dados['total_vendas'] if dados else 0,
                         total_despesas=dados['total_despesas'] if dados else 0,
                         ticket_medio=dados['ticket_medio'] if dados else 0,
                         ultimas_transacoes=ultimas_transacoes,
                         fechamentos_anteriores=fechamentos_anteriores)

@app.route('/fechamento_caixa/confirmar', methods=['POST'])
@login_required
def fechamento_caixa_confirmar():
    """Confirmar e salvar o fechamento do caixa"""
    ano = int(request.form['ano'])
    mes = int(request.form['mes'])
    data_inicio = datetime(ano, mes, 1).date()
    observacao = request.form.get('observacao', '').strip()
    user_id = session.get('user_id')
    
    usuario = query_one("SELECT id FROM usuarios WHERE id = %s::uuid", (user_id,))
    if not usuario:
        admin = query_one("SELECT id FROM usuarios WHERE username = 'admin'")
        user_id = admin['id'] if admin else None
        if not user_id:
            flash('Nenhum usuário encontrado!', 'danger')
            return redirect(url_for('fechamento_caixa'))
    
    existe = query_one("SELECT id FROM fechamentos_caixa WHERE mes_referencia = %s AND status = 'fechado'", (data_inicio,))
    if existe:
        flash('Este mês já foi fechado!', 'danger')
        return redirect(url_for('fechamento_caixa'))
    
    dados = query_one("""
        SELECT COALESCE(SUM(CASE WHEN tipo = 'entrada' THEN valor ELSE 0 END), 0) as entradas,
            COALESCE(SUM(CASE WHEN tipo = 'saida' THEN valor ELSE 0 END), 0) as saidas,
            COUNT(CASE WHEN tipo = 'entrada' THEN 1 END) as total_vendas,
            COUNT(CASE WHEN tipo = 'saida' THEN 1 END) as total_despesas
        FROM transacoes_financeiras WHERE mes_referencia = %s AND fechado = false
    """, (data_inicio,))
    
    if mes == 1:
        mes_anterior = datetime(ano - 1, 12, 1).date()
    else:
        mes_anterior = datetime(ano, mes - 1, 1).date()
    
    fechamento_anterior = query_one("SELECT saldo_final FROM fechamentos_caixa WHERE mes_referencia = %s AND status = 'fechado'", (mes_anterior,))
    saldo_inicial = fechamento_anterior['saldo_final'] if fechamento_anterior else 0
    entradas = dados['entradas'] if dados else 0
    saidas = dados['saidas'] if dados else 0
    saldo_final = saldo_inicial + entradas - saidas
    
    # Buscar transações para snapshot
    transacoes = query_all("""
        SELECT t.id, t.tipo, t.categoria, t.descricao, t.valor, t.quantidade, t.data,
            p.nome as produto_nome, c.nome as cliente_nome
        FROM transacoes_financeiras t
        LEFT JOIN produtos p ON t.produto_id = p.id
        LEFT JOIN clientes c ON t.cliente_id = c.id
        WHERE t.mes_referencia = %s AND t.fechado = false
        ORDER BY t.data DESC
    """, (data_inicio,))
    
    def formatar_valor(obj):
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        return obj
    
    # Converter transações para lista de dicionários
    transacoes_lista = []
    for t in transacoes:
        t_dict = {}
        for key, value in t.items():
            if isinstance(value, datetime):
                t_dict[key] = value.isoformat()
            elif isinstance(value, Decimal):
                t_dict[key] = float(value)
            else:
                t_dict[key] = value
        transacoes_lista.append(t_dict)
    
    # Converter para JSON
    import json
    transacoes_json = json.dumps(transacoes_lista, default=formatar_valor)
    resumo_json = json.dumps({
        'saldo_inicial': float(saldo_inicial),
        'total_entradas': float(entradas),
        'total_saidas': float(saidas),
        'saldo_final': float(saldo_final),
        'total_vendas': dados['total_vendas'] if dados else 0,
        'total_despesas': dados['total_despesas'] if dados else 0,
        'quantidade_transacoes': len(transacoes)
    }, default=formatar_valor)
    
    # Salvar usando jsonb
    sql = """
        INSERT INTO fechamentos_caixa (mes_referencia, saldo_inicial, total_entradas, total_saidas, 
            saldo_final, total_vendas, total_despesas, observacao, fechado_por, 
            transacoes_snapshot, resumo_detalhado) 
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
    """
    
    if execute_sql(sql, (data_inicio, saldo_inicial, entradas, saidas, saldo_final,
        dados['total_vendas'] if dados else 0, dados['total_despesas'] if dados else 0,
        observacao, user_id, transacoes_json, resumo_json)):
        execute_sql("UPDATE transacoes_financeiras SET fechado = true WHERE mes_referencia = %s AND fechado = false", (data_inicio,))
        flash(f'✅ Caixa do mês {traduzir_mes(data_inicio)} fechado! {len(transacoes)} transações salvas.', 'success')
    else:
        flash('❌ Erro ao fechar caixa!', 'danger')
    
    return redirect(url_for('fechamento_caixa'))

@app.route('/fechamento_caixa/estornar/<fechamento_id>', methods=['POST'])
@login_required
def fechamento_caixa_estornar(fechamento_id):
    """Estornar um fechamento de caixa - REABRE O MÊS"""
    try:
        fechamento = query_one("SELECT * FROM fechamentos_caixa WHERE id = %s::uuid", (fechamento_id,))
        if not fechamento:
            flash('Fechamento não encontrado!', 'danger')
            return redirect(url_for('fechamento_caixa'))
        if fechamento['status'] == 'estornado':
            flash('Este fechamento já foi estornado!', 'warning')
            return redirect(url_for('fechamento_caixa'))
        
        user_id = session.get('user_id')
        usuario = query_one("SELECT id FROM usuarios WHERE id = %s::uuid", (user_id,))
        if not usuario:
            admin = query_one("SELECT id FROM usuarios WHERE username = 'admin'")
            user_id = admin['id'] if admin else None
            if not user_id:
                flash('Nenhum usuário encontrado!', 'danger')
                return redirect(url_for('fechamento_caixa'))
        
        # Atualizar status para estornado
        sql = """
            UPDATE fechamentos_caixa 
            SET status = 'estornado', 
                estornado_em = NOW(), 
                estornado_por = %s::uuid,
                updated_at = NOW()
            WHERE id = %s::uuid
        """
        
        if execute_sql(sql, (user_id, fechamento_id)):
            # Reabrir as transações
            execute_sql("UPDATE transacoes_financeiras SET fechado = false WHERE mes_referencia = %s", (fechamento['mes_referencia'],))
            flash(f'✅ Mês {traduzir_mes(fechamento["mes_referencia"])} estornado! Snapshot mantido.', 'success')
        else:
            flash('❌ Erro ao estornar!', 'danger')
    except Exception as e:
        print(f"❌ Erro: {e}")
        flash('Erro ao estornar!', 'danger')
    
    return redirect(url_for('fechamento_caixa'))

@app.route('/fechamento_caixa/detalhe/<fechamento_id>')
@login_required
def fechamento_caixa_detalhe(fechamento_id):
    """Visualizar detalhes de um fechamento específico"""
    try:
        print(f"🔍 Buscando fechamento ID: {fechamento_id}")
        
        fechamento = query_one("""
            SELECT fc.*, u.nome as fechado_por_nome, 
                   u2.nome as estornado_por_nome
            FROM fechamentos_caixa fc
            LEFT JOIN usuarios u ON fc.fechado_por = u.id
            LEFT JOIN usuarios u2 ON fc.estornado_por = u2.id
            WHERE fc.id = %s::uuid
        """, (fechamento_id,))
        
        if not fechamento:
            print(f"❌ Fechamento não encontrado: {fechamento_id}")
            flash('Fechamento não encontrado!', 'danger')
            return redirect(url_for('fechamento_caixa'))
        
        print(f"✅ Fechamento encontrado: {fechamento['mes_referencia']}")
        
        # ===== CARREGAR SNAPSHOT =====
        transacoes = []
        import json
        
        # Tenta carregar o snapshot
        if fechamento.get('transacoes_snapshot'):
            try:
                snapshot_data = fechamento['transacoes_snapshot']
                
                # Se for string JSON, fazer parse
                if isinstance(snapshot_data, str):
                    transacoes = json.loads(snapshot_data)
                    print(f"✅ Snapshot JSON carregado: {len(transacoes)} transações")
                # Se for lista, usar diretamente
                elif isinstance(snapshot_data, list):
                    transacoes = snapshot_data
                    print(f"✅ Snapshot lista carregado: {len(transacoes)} transações")
                else:
                    print(f"⚠️ Tipo de snapshot não reconhecido: {type(snapshot_data)}")
            except Exception as e:
                print(f"❌ Erro ao carregar snapshot: {e}")
                transacoes = []
        
        # Se não tiver snapshot, buscar do banco (fallback)
        if not transacoes:
            print("⚠️ Nenhum snapshot encontrado, buscando do banco...")
            transacoes = query_all("""
                SELECT 
                    t.id,
                    t.tipo,
                    t.categoria,
                    t.descricao,
                    t.valor,
                    t.quantidade,
                    t.data,
                    p.nome as produto_nome,
                    c.nome as cliente_nome
                FROM transacoes_financeiras t
                LEFT JOIN produtos p ON t.produto_id = p.id
                LEFT JOIN clientes c ON t.cliente_id = c.id
                WHERE t.mes_referencia = %s
                ORDER BY t.data DESC
            """, (fechamento['mes_referencia'],))
            print(f"📊 Buscados {len(transacoes)} transações do banco")
        
        return render_template('fechamento_caixa_detalhe.html',
                             fechamento=fechamento,
                             transacoes=transacoes,
                             data_inicio=fechamento['mes_referencia'])
    except Exception as e:
        print(f"❌ Erro ao buscar detalhes: {e}")
        traceback.print_exc()
        flash('Erro ao carregar detalhes do fechamento!', 'danger')
        return redirect(url_for('fechamento_caixa'))
# ==========================================
# ROTAS ADICIONAIS
# ==========================================

@app.route('/reorganizar_pedidos')
@login_required
def reorganizar_pedidos():
    try:
        reorganizar_numeros_pedido()
        flash('✅ Números reorganizados!')
    except Exception as e:
        flash(f'❌ Erro: {str(e)}')
    return redirect(url_for('index'))

@app.route('/manifest.json')
def manifest():
    return send_file('static/manifest.json', mimetype='application/json')

@app.route('/estoque/produto/novo', methods=['POST'])
@login_required
def produto_novo():
    try:
        nome = request.form.get('nome', '').strip()
        if not nome:
            flash('Nome é obrigatório!')
            return redirect(url_for('estoque'))
        
        sku = gerar_sku(nome)
        sql = """
            INSERT INTO produtos (nome, descricao, sku, categoria, preco_custo, preco_venda, unidade, estoque_minimo, estoque_atual) 
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        if execute_sql(sql, (nome, request.form.get('descricao', ''), sku, request.form.get('categoria', ''),
            float(request.form.get('preco_custo', '0').replace(',', '.') or 0),
            float(request.form.get('preco_venda', '0').replace(',', '.') or 0),
            request.form.get('unidade', 'UN'),
            int(request.form.get('estoque_minimo', 0) or 0),
            int(request.form.get('estoque_atual', 0) or 0))):
            flash(f'✅ Produto cadastrado! SKU: {sku}')
        else:
            flash('❌ Erro ao cadastrar')
    except Exception as e:
        print(f"❌ Erro: {e}")
        flash('❌ Erro ao cadastrar')
    return redirect(url_for('estoque'))

@app.route('/estoque/produto/editar/<string:id>', methods=['POST'])
@login_required
def produto_editar(id):
    try:
        nome = request.form.get('nome', '').strip()
        if not nome:
            flash('Nome é obrigatório!')
            return redirect(url_for('estoque'))
        
        sql = """
            UPDATE produtos SET nome=%s, descricao=%s, categoria=%s, preco_custo=%s, preco_venda=%s,
            unidade=%s, estoque_minimo=%s, status=%s, updated_at=NOW() WHERE id=%s
        """
        if execute_sql(sql, (nome, request.form.get('descricao', ''), request.form.get('categoria', ''),
            float(request.form.get('preco_custo', '0').replace(',', '.') or 0),
            float(request.form.get('preco_venda', '0').replace(',', '.') or 0),
            request.form.get('unidade', 'UN'),
            int(request.form.get('estoque_minimo', 0) or 0),
            request.form.get('status', 'ativo'), id)):
            flash('✅ Produto atualizado!')
        else:
            flash('❌ Erro ao atualizar')
    except Exception as e:
        print(f"❌ Erro: {e}")
        flash('❌ Erro ao atualizar')
    return redirect(url_for('estoque'))

@app.route('/estoque/produto/delete/<string:id>', methods=['POST'])
@login_required
def produto_delete(id):
    if execute_sql("UPDATE produtos SET status = 'inativo' WHERE id = %s", (id,)):
        flash('✅ Produto desativado!')
    else:
        flash('❌ Erro ao desativar')
    return redirect(url_for('estoque'))

@app.route('/estoque/movimentacoes/<string:produto_id>')
@login_required
def movimentacoes_produto(produto_id):
    movimentacoes = query_all("SELECT * FROM movimentacoes_estoque WHERE produto_id = %s ORDER BY data_movimentacao DESC LIMIT 100", (produto_id,))
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
    
    novo_estoque = max(0, produto['estoque_atual'] + quantidade if tipo == 'entrada' else produto['estoque_atual'] - quantidade)
    if execute_sql("UPDATE produtos SET estoque_atual = %s, updated_at = NOW() WHERE id = %s", (novo_estoque, produto_id)):
        execute_sql("INSERT INTO movimentacoes_estoque (produto_id, tipo, origem, quantidade, descricao) VALUES (%s, %s, %s, %s, %s)",
            (produto_id, tipo, 'ajuste', quantidade, descricao))
        flash('✅ Estoque ajustado!')
    else:
        flash('❌ Erro ao ajustar')
    return redirect(url_for('estoque'))

# ==========================================
# CUSTOS DOS PRODUTOS
# ==========================================

@app.route('/estoque/produto/custos/<string:produto_id>')
@login_required
def produto_custos(produto_id):
    produto = query_one("SELECT * FROM produtos WHERE id = %s", (produto_id,))
    if not produto:
        flash('Produto não encontrado')
        return redirect(url_for('estoque'))
    custos = query_all("SELECT * FROM custos_produtos WHERE produto_id = %s ORDER BY tipo_custo, created_at", (produto_id,))
    total_custos = query_one("SELECT COALESCE(SUM(valor * quantidade), 0) as total FROM custos_produtos WHERE produto_id = %s", (produto_id,))
    return render_template('produto_custos.html', produto=produto, custos=custos,
        total_custos=total_custos['total'] if total_custos else 0)

@app.route('/estoque/produto/custos/novo/<string:produto_id>', methods=['POST'])
@login_required
def produto_custo_novo(produto_id):
    sql = "INSERT INTO custos_produtos (produto_id, tipo_custo, descricao, valor, quantidade, unidade) VALUES (%s, %s, %s, %s, %s, %s)"
    if execute_sql(sql, (produto_id, request.form['tipo_custo'], request.form['descricao'],
        float(request.form['valor']), float(request.form['quantidade'] or 1), request.form['unidade'])):
        flash('✅ Custo adicionado!')
    else:
        flash('❌ Erro ao adicionar')
    return redirect(url_for('produto_custos', produto_id=produto_id))

@app.route('/estoque/produto/custos/editar/<string:custo_id>', methods=['POST'])
@login_required
def produto_custo_editar(custo_id):
    custo = query_one("SELECT * FROM custos_produtos WHERE id = %s", (custo_id,))
    if not custo:
        flash('Custo não encontrado')
        return redirect(url_for('estoque'))
    sql = "UPDATE custos_produtos SET tipo_custo=%s, descricao=%s, valor=%s, quantidade=%s, unidade=%s, updated_at=NOW() WHERE id=%s"
    if execute_sql(sql, (request.form['tipo_custo'], request.form['descricao'], float(request.form['valor']),
        float(request.form['quantidade'] or 1), request.form['unidade'], custo_id)):
        flash('✅ Custo atualizado!')
    else:
        flash('❌ Erro ao atualizar')
    return redirect(url_for('produto_custos', produto_id=custo['produto_id']))

@app.route('/estoque/produto/custos/delete/<string:custo_id>', methods=['POST'])
@login_required
def produto_custo_delete(custo_id):
    custo = query_one("SELECT * FROM custos_produtos WHERE id = %s", (custo_id,))
    if not custo:
        flash('Custo não encontrado')
        return redirect(url_for('estoque'))
    if execute_sql("DELETE FROM custos_produtos WHERE id = %s", (custo_id,)):
        flash('✅ Custo excluído!')
    else:
        flash('❌ Erro ao excluir')
    return redirect(url_for('produto_custos', produto_id=custo['produto_id']))

# ==========================================
# INICIALIZAÇÃO E EXECUÇÃO
# ==========================================

# Inicializar pool de conexões
init_db_pool()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    print(f"\n🚀 Iniciando aplicação na porta {port}")
    print(f"🔗 Acesse: http://localhost:{port}")
    print("=" * 60)
    app.run(debug=False, host='0.0.0.0', port=port)