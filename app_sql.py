import streamlit as st
import psycopg2
import pandas as pd
import hashlib
import os
import datetime
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import calendar
from datetime import timedelta
import locale
from urllib.parse import urlparse

# Configuração de locale para formatação de valores em português
try:
    locale.setlocale(locale.LC_ALL, 'pt_BR.UTF-8')
except:
    try:
        locale.setlocale(locale.LC_ALL, 'Portuguese_Brazil.1252')
    except:
        pass

# Configuração da página
st.set_page_config(
    page_title="Sistema de Finanças Pessoal",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Função para conectar ao banco de dados
def get_connection():
    # Usar DATABASE_URL do Streamlit
    DATABASE_URL = os.environ.get('DATABASE_URL')
    
    if not DATABASE_URL:
        st.error("Variável de ambiente DATABASE_URL não configurada!")
        st.stop()
    
    # Parse da URL do banco de dados
    result = urlparse(DATABASE_URL)
    username = result.username
    password = result.password
    database = result.path[1:]
    hostname = result.hostname
    port = result.port
    
    return psycopg2.connect(
        dbname=database,
        user=username,
        password=password,
        host=hostname,
        port=port
    )

# Funções para autenticação e banco de dados
def init_db():
    conn = get_connection()
    cur = conn.cursor()
    
    # Banco de dados principal para autenticação
    cur.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        is_admin INTEGER DEFAULT 0,
        is_active INTEGER DEFAULT 1
    )
    ''')
    
    # Verificar se já existe um usuário admin, se não, criar
    cur.execute("SELECT * FROM users WHERE username = 'admin'")
    if not cur.fetchone():
        # Senha padrão 'admin123' com hash
        hashed_password = hashlib.sha256('admin123'.encode()).hexdigest()
        cur.execute("INSERT INTO users (username, password, is_admin, is_active) VALUES (%s, %s, 1, 1)", 
                 ('admin', hashed_password))
    
    conn.commit()
    conn.close()

def init_user_db(username):
    conn = get_connection()
    cur = conn.cursor()
    
    # Tabela para categorias
    cur.execute(f'''
    CREATE TABLE IF NOT EXISTS categorias_{username} (
        id SERIAL PRIMARY KEY,
        nome TEXT UNIQUE NOT NULL,
        tipo TEXT NOT NULL
    )
    ''')
    
    # Tabela para movimentações
    cur.execute(f'''
    CREATE TABLE IF NOT EXISTS movimentacoes_{username} (
        id SERIAL PRIMARY KEY,
        categoria_id INTEGER NOT NULL,
        valor REAL NOT NULL,
        data DATE NOT NULL,
        tipo TEXT NOT NULL,
        descricao TEXT,
        parcela INTEGER DEFAULT 0,
        total_parcelas INTEGER DEFAULT 0,
        id_grupo_parcela INTEGER,
        FOREIGN KEY (categoria_id) REFERENCES categorias_{username} (id)
    )
    ''')
    
    # Adicionando algumas categorias padrão se não existirem
    categorias_padrao = [
        ('Salário', 'entrada'),
        ('Alimentação', 'saida'),
        ('Transporte', 'saida'),
        ('Lazer', 'saida'),
        ('Saúde', 'saida'),
        ('Educação', 'saida'),
        ('Moradia', 'saida'),
        ('Diversos', 'saida')
    ]
    
    for cat in categorias_padrao:
        try:
            cur.execute(f"INSERT INTO categorias_{username} (nome, tipo) VALUES (%s, %s) ON CONFLICT (nome) DO NOTHING", cat)
        except psycopg2.IntegrityError:
            conn.rollback()  # Categoria já existe
        
    conn.commit()
    conn.close()
    
    return username

def verify_password(username, password):
    conn = get_connection()
    cur = conn.cursor()
    
    hashed_password = hashlib.sha256(password.encode()).hexdigest()
    cur.execute("SELECT is_active, is_admin FROM users WHERE username = %s AND password = %s", 
             (username, hashed_password))
    result = cur.fetchone()
    conn.close()
    
    if result:
        is_active, is_admin = result
        if is_active:
            return True, is_admin
        else:
            return False, False
    return False, False

def register_user(username, password, is_admin=False):
    conn = get_connection()
    cur = conn.cursor()
    
    hashed_password = hashlib.sha256(password.encode()).hexdigest()
    try:
        cur.execute("INSERT INTO users (username, password, is_admin) VALUES (%s, %s, %s)", 
                 (username, hashed_password, is_admin))
        conn.commit()
        # Inicializar o banco de dados do usuário
        init_user_db(username)
        return True
    except psycopg2.IntegrityError:
        return False
    finally:
        conn.close()

def get_all_users():
    conn = get_connection()
    query = "SELECT id, username, is_admin, is_active FROM users"
    users = pd.read_sql_query(query, conn)
    conn.close()
    return users

def toggle_user_status(user_id, status):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE users SET is_active = %s WHERE id = %s", (status, user_id))
    conn.commit()
    conn.close()

def change_password(username, new_password):
    conn = get_connection()
    cur = conn.cursor()
    
    hashed_password = hashlib.sha256(new_password.encode()).hexdigest()
    cur.execute("UPDATE users SET password = %s WHERE username = %s", (hashed_password, username))
    conn.commit()
    conn.close()

# Funções para gerenciar categorias
def get_categorias(username):
    conn = get_connection()
    query = f"SELECT id, nome, tipo FROM categorias_{username} ORDER BY nome"
    categorias = pd.read_sql_query(query, conn)
    conn.close()
    return categorias

def add_categoria(username, nome, tipo):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(f"INSERT INTO categorias_{username} (nome, tipo) VALUES (%s, %s)", (nome, tipo))
        conn.commit()
        success = True
    except psycopg2.IntegrityError:
        conn.rollback()
        success = False
    conn.close()
    return success

def update_categoria(username, id, nome, tipo):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(f"UPDATE categorias_{username} SET nome = %s, tipo = %s WHERE id = %s", (nome, tipo, id))
        conn.commit()
        success = True
    except psycopg2.IntegrityError:
        conn.rollback()
        success = False
    conn.close()
    return success

def delete_categoria(username, id):
    conn = get_connection()
    cur = conn.cursor()
    
    # Verificar se existe movimentação associada
    cur.execute(f"SELECT COUNT(*) FROM movimentacoes_{username} WHERE categoria_id = %s", (id,))
    count = cur.fetchone()[0]
    
    if count > 0:
        success = False
    else:
        cur.execute(f"DELETE FROM categorias_{username} WHERE id = %s", (id,))
        conn.commit()
        success = True
    
    conn.close()
    return success

# Funções para gerenciar movimentações
def add_movimentacao(username, categoria_id, valor, data, tipo, descricao="", parcela=0, total_parcelas=0):
    conn = get_connection()
    cur = conn.cursor()
    
    # Se for uma movimentação parcelada
    if total_parcelas > 1:
        # Gerar um ID único para o grupo de parcelas
        cur.execute(f"SELECT MAX(id_grupo_parcela) FROM movimentacoes_{username}")
        max_id = cur.fetchone()[0]
        id_grupo = 1 if max_id is None else max_id + 1
        
        data_obj = datetime.datetime.strptime(data, "%Y-%m-%d")
        
        # Inserir cada parcela
        for i in range(1, total_parcelas + 1):
            parcela_data = data_obj + datetime.timedelta(days=(i-1)*30)  # Aproximadamente um mês entre parcelas
            parcela_valor = valor / total_parcelas
            cur.execute(f"""
                INSERT INTO movimentacoes_{username} 
                (categoria_id, valor, data, tipo, descricao, parcela, total_parcelas, id_grupo_parcela) 
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (categoria_id, parcela_valor, parcela_data.strftime("%Y-%m-%d"), 
                      tipo, f"{descricao} ({i}/{total_parcelas})", i, total_parcelas, id_grupo))
    else:
        # Movimentação normal (não parcelada)
        cur.execute(f"""
            INSERT INTO movimentacoes_{username}
            (categoria_id, valor, data, tipo, descricao) 
            VALUES (%s, %s, %s, %s, %s)
            """, (categoria_id, valor, data, tipo, descricao))
    
    conn.commit()
    conn.close()
    return True

def get_movimentacoes(username, data_inicio=None, data_fim=None):
    conn = get_connection()
    
    query = f"""
    SELECT m.id, c.nome as categoria, m.valor, m.data, m.tipo, m.descricao, 
           m.parcela, m.total_parcelas, m.id_grupo_parcela
    FROM movimentacoes_{username} m
    JOIN categorias_{username} c ON m.categoria_id = c.id
    """
    
    params = []
    if data_inicio and data_fim:
        query += " WHERE m.data BETWEEN %s AND %s"
        params.extend([data_inicio, data_fim])
    
    query += " ORDER BY m.data DESC"
    
    movimentacoes = pd.read_sql_query(query, conn, params=params)
    movimentacoes['id'] = movimentacoes['id'].astype(int)
    
    conn.close()
    return movimentacoes

def update_movimentacao(username, id, categoria_id, valor, data, tipo, descricao=""):
    conn = get_connection()
    cur = conn.cursor()
    
    # Verificar se é parte de um grupo de parcelas
    cur.execute(f"""
        SELECT id_grupo_parcela, total_parcelas 
        FROM movimentacoes_{username} 
        WHERE id = %s
    """, (id,))
    result = cur.fetchone()
    
    if result and result[0] is not None and result[1] > 1:
        # É uma parcela, perguntar se quer atualizar todas ou apenas esta
        st.warning("Esta é uma movimentação parcelada. As alterações afetarão apenas esta parcela.")
    
    cur.execute(f"""
        UPDATE movimentacoes_{username} 
        SET categoria_id = %s, valor = %s, data = %s, tipo = %s, descricao = %s
        WHERE id = %s
    """, (categoria_id, valor, data, tipo, descricao, id))
    
    conn.commit()
    conn.close()
    return True

def delete_movimentacao(username, id):
    conn = get_connection()
    cur = conn.cursor()
    
    # Verificar se é parte de um grupo de parcelas
    cur.execute(f"""
        SELECT id_grupo_parcela, total_parcelas 
        FROM movimentacoes_{username} 
        WHERE id = %s
    """, (id,))
    result = cur.fetchone()
    
    if result and result[0] is not None and result[1] > 1:
        # É uma parcela, perguntar se quer excluir todas ou apenas esta
        if st.session_state.get('excluir_todas_parcelas', False):
            cur.execute(f"DELETE FROM movimentacoes_{username} WHERE id_grupo_parcela = %s", (result[0],))
        else:
            cur.execute(f"DELETE FROM movimentacoes_{username} WHERE id = %s", (id,))
    else:
        cur.execute(f"DELETE FROM movimentacoes_{username} WHERE id = %s", (id,))
    
    conn.commit()
    conn.close()
    return True

# Funções para análise e dashboard
def get_dados_dashboard(username, data_inicio=None, data_fim=None):
    # Se não especificado, usar mês atual
    if not data_inicio or not data_fim:
        hoje = datetime.date.today()
        primeiro_dia = datetime.date(hoje.year, hoje.month, 1)
        ultimo_dia = datetime.date(hoje.year, hoje.month, calendar.monthrange(hoje.year, hoje.month)[1])
        data_inicio = primeiro_dia.strftime("%Y-%m-%d")
        data_fim = ultimo_dia.strftime("%Y-%m-%d")
    
    conn = get_connection()
    
    # Total de entradas e saídas
    query_totais = f"""
    SELECT tipo, SUM(valor) as total
    FROM movimentacoes_{username}
    WHERE data BETWEEN %s AND %s
    GROUP BY tipo
    """
    totais = pd.read_sql_query(query_totais, conn, params=[data_inicio, data_fim])
    
    # Gastos por categoria
    query_categorias = f"""
    SELECT c.nome, SUM(m.valor) as total
    FROM movimentacoes_{username} m
    JOIN categorias_{username} c ON m.categoria_id = c.id
    WHERE m.tipo = 'saida' AND m.data BETWEEN %s AND %s
    GROUP BY c.nome
    ORDER BY total DESC
    """
    gastos_categoria = pd.read_sql_query(query_categorias, conn, params=[data_inicio, data_fim])
    
    # Evolução diária
    query_diaria = f"""
    SELECT m.data, m.tipo, SUM(m.valor) as total
    FROM movimentacoes_{username} m
    WHERE m.data BETWEEN %s AND %s
    GROUP BY m.data, m.tipo
    ORDER BY m.data
    """
    evolucao_diaria = pd.read_sql_query(query_diaria, conn, params=[data_inicio, data_fim])
    
    # Gastos do dia atual
    hoje = datetime.date.today().strftime("%Y-%m-%d")
    query_hoje = f"""
    SELECT c.nome, SUM(m.valor) as total
    FROM movimentacoes_{username} m
    JOIN categorias_{username} c ON m.categoria_id = c.id
    WHERE m.tipo = 'saida' AND m.data = %s
    GROUP BY c.nome
    ORDER BY total DESC
    """
    gastos_hoje = pd.read_sql_query(query_hoje, conn, params=[hoje])
    
    # Gastos do próximo mês
    hoje = datetime.date.today()
    proximo_mes = hoje.month + 1 if hoje.month < 12 else 1
    proximo_ano = hoje.year if hoje.month < 12 else hoje.year + 1
    primeiro_dia_prox = datetime.date(proximo_ano, proximo_mes, 1)
    ultimo_dia_prox = datetime.date(proximo_ano, proximo_mes, 
                                   calendar.monthrange(proximo_ano, proximo_mes)[1])
    
    query_prox_mes = f"""
    SELECT tipo, SUM(valor) as total
    FROM movimentacoes_{username}
    WHERE data BETWEEN %s AND %s
    GROUP BY tipo
    """
    gastos_prox_mes = pd.read_sql_query(query_prox_mes, conn, 
                                       params=[primeiro_dia_prox.strftime("%Y-%m-%d"), 
                                              ultimo_dia_prox.strftime("%Y-%m-%d")])
    
    conn.close()
    
    return {
        'totais': totais,
        'gastos_categoria': gastos_categoria,
        'evolucao_diaria': evolucao_diaria,
        'gastos_hoje': gastos_hoje,
        'gastos_prox_mes': gastos_prox_mes,
        'periodo': {'inicio': data_inicio, 'fim': data_fim}
    }

def get_dados_mes(username, ano, mes):
    primeiro_dia = datetime.date(ano, mes, 1)
    ultimo_dia = datetime.date(ano, mes, calendar.monthrange(ano, mes)[1])
    
    conn = get_connection()
    
    # Total de entradas e saídas
    query_totais = f"""
    SELECT tipo, SUM(valor) as total
    FROM movimentacoes_{username}
    WHERE data BETWEEN %s AND %s
    GROUP BY tipo
    """
    totais = pd.read_sql_query(query_totais, conn, 
                              params=[primeiro_dia.strftime("%Y-%m-%d"), 
                                     ultimo_dia.strftime("%Y-%m-%d")])
    
    conn.close()
    
    return totais

# Interface do usuário com Streamlit
def main():
    # Inicializar banco de dados
    try:
        init_db()
    except Exception as e:
        st.error(f"Erro ao conectar ao banco de dados: {e}")
        st.write("Verifique se as configurações do PostgreSQL estão corretas.")
        return
    
    # Verificar e inicializar estado da sessão
    if 'logged_in' not in st.session_state:
        st.session_state.logged_in = False
    if 'is_admin' not in st.session_state:
        st.session_state.is_admin = False
    if 'username' not in st.session_state:
        st.session_state.username = ""
    
    # Estilo CSS personalizado
    st.markdown("""
    <style>
    .reportview-container {
        background-color: #f8f9fa;
    }
    .main-header {
        font-size: 2.5rem;
        font-weight: 700;
        color: #1E88E5;
        text-align: center;
        margin-bottom: 2rem;
    }
    .dashboard-card {
        background-color: white;
        border-radius: 10px;
        padding: 20px;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        margin-bottom: 20px;
    }
    .card-title {
        font-size: 1.2rem;
        font-weight: 600;
        margin-bottom: 15px;
        color: #333;
    }
    .value-display {
        font-size: 2rem;
        font-weight: 700;
        margin: 10px 0;
    }
    .positive {
        color: #4CAF50;
    }
    .negative {
        color: #F44336;
    }
    </style>
    """, unsafe_allow_html=True)
    
    # Tela de login
    if not st.session_state.logged_in:
        st.markdown("<h1 class='main-header'>Sistema de Finanças Pessoal</h1>", unsafe_allow_html=True)
        
        col1, col2 = st.columns([1, 1])
        
        with col1:
            st.subheader("Login")
            username = st.text_input("Usuário", key="login_username")
            password = st.text_input("Senha", type="password", key="login_password")
            
            if st.button("Entrar"):
                is_valid, is_admin = verify_password(username, password)
                if is_valid:
                    st.session_state.logged_in = True
                    st.session_state.username = username
                    st.session_state.is_admin = is_admin
                    st.rerun()
                else:
                    st.error("Usuário ou senha inválidos ou conta desativada.")
    
    # Interface principal após login
    else:
        # Sidebar
        with st.sidebar:
            st.title(f"Olá, {st.session_state.username}")
            
            menu = ["Visão Geral", "Cadastro", "Lançar Movimentação", "Auditoria"]
            if st.session_state.is_admin:
                menu.append("Administração")
            
            choice = st.sidebar.selectbox("Menu", menu)
            
            if st.button("Sair"):
                st.session_state.logged_in = False
                st.session_state.username = ""
                st.session_state.is_admin = False
                st.rerun()
        
        # Conteúdo principal
        if choice == "Visão Geral":
            st.markdown("<h1 class='main-header'>Visão Geral</h1>", unsafe_allow_html=True)
            
            # Filtro de período
            col1, col2 = st.columns(2)
            with col1:
                data_inicio = st.date_input("Data Inicial", 
                                          value=datetime.date.today().replace(day=1),
                                          format="DD/MM/YYYY")
            with col2:
                ultimo_dia = calendar.monthrange(datetime.date.today().year, 
                                              datetime.date.today().month)[1]
                data_fim = st.date_input("Data Final", 
                                       value=datetime.date.today().replace(day=ultimo_dia),
                                       format="DD/MM/YYYY")
            
            # Obter dados para o dashboard
            dados = get_dados_dashboard(st.session_state.username, 
                                       data_inicio.strftime("%Y-%m-%d"),
                                       data_fim.strftime("%Y-%m-%d"))
            
            # Cards de resumo
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.markdown("<div class='dashboard-card'>", unsafe_allow_html=True)
                st.markdown("<div class='card-title'>Total de Entradas</div>", unsafe_allow_html=True)
                
                entrada = dados['totais'][dados['totais']['tipo'] == 'entrada']['total'].sum() if not dados['totais'].empty and 'entrada' in dados['totais']['tipo'].values else 0
                st.markdown(f"<div class='value-display positive'>R$ {entrada:,.2f}</div>".replace(',', 'X').replace('.', ',').replace('X', '.'), unsafe_allow_html=True)
                st.markdown("</div>", unsafe_allow_html=True)
            
            with col2:
                st.markdown("<div class='dashboard-card'>", unsafe_allow_html=True)
                st.markdown("<div class='card-title'>Total de Saídas</div>", unsafe_allow_html=True)
                
                saida = dados['totais'][dados['totais']['tipo'] == 'saida']['total'].sum() if not dados['totais'].empty and 'saida' in dados['totais']['tipo'].values else 0
                st.markdown(f"<div class='value-display negative'>R$ {saida:,.2f}</div>".replace(',', 'X').replace('.', ',').replace('X', '.'), unsafe_allow_html=True)
                st.markdown("</div>", unsafe_allow_html=True)
            
            with col3:
                st.markdown("<div class='dashboard-card'>", unsafe_allow_html=True)
                st.markdown("<div class='card-title'>Saldo</div>", unsafe_allow_html=True)
                
                saldo = entrada - saida
                color = "positive" if saldo >= 0 else "negative"
                st.markdown(f"<div class='value-display {color}'>R$ {saldo:,.2f}</div>".replace(',', 'X').replace('.', ',').replace('X', '.'), unsafe_allow_html=True)
                st.markdown("</div>", unsafe_allow_html=True)
            
            # Gráficos
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("<div class='dashboard-card'>", unsafe_allow_html=True)
                st.markdown("<div class='card-title'>Gastos por Categoria</div>", unsafe_allow_html=True)
                
                if not dados['gastos_categoria'].empty:
                    fig = px.pie(dados['gastos_categoria'], values='total', names='nome', 
                               title='', 
                               color_discrete_sequence=px.colors.qualitative.Set3)
                    fig.update_layout(margin=dict(l=20, r=20, t=30, b=0))
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("Sem dados para exibir neste período.")
                
                st.markdown("</div>", unsafe_allow_html=True)
            
            with col2:
                st.markdown("<div class='dashboard-card'>", unsafe_allow_html=True)
                st.markdown("<div class='card-title'>Evolução no Período</div>", unsafe_allow_html=True)
                
                if not dados['evolucao_diaria'].empty:
                    # Preparar dados para o gráfico
                    evolucao_pivot = dados['evolucao_diaria'].pivot_table(
                        index='data', columns='tipo', values='total', aggfunc='sum').reset_index()
                    
                    # Preencher valores ausentes com 0
                    if 'entrada' not in evolucao_pivot.columns:
                        evolucao_pivot['entrada'] = 0
                    if 'saida' not in evolucao_pivot.columns:
                        evolucao_pivot['saida'] = 0
                    
                    # Criar gráfico de linhas
                    fig = go.Figure()
                    
                    fig.add_trace(go.Scatter(
                        x=evolucao_pivot['data'], 
                        y=evolucao_pivot['entrada'],
                        mode='lines+markers',
                        name='Entradas',
                        line=dict(color='#4CAF50', width=2),
                        marker=dict(size=8)
                    ))
                    
                    fig.add_trace(go.Scatter(
                        x=evolucao_pivot['data'], 
                        y=evolucao_pivot['saida'],
                        mode='lines+markers',
                        name='Saídas',
                        line=dict(color='#F44336', width=2),
                        marker=dict(size=8)
                    ))
                    
                    fig.update_layout(
                        xaxis_title="Data",
                        yaxis_title="Valor (R$)",
                        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                        margin=dict(l=20, r=20, t=30, b=0)
                    )
                    
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("Sem dados para exibir neste período.")
                
                st.markdown("</div>", unsafe_allow_html=True)
            
            # Cards informativos adicionais
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("<div class='dashboard-card'>", unsafe_allow_html=True)
                st.markdown("<div class='card-title'>Gastos de Hoje</div>", unsafe_allow_html=True)
                
                if not dados['gastos_hoje'].empty:
                    total_hoje = dados['gastos_hoje']['total'].sum()
                    st.markdown(f"<div class='value-display negative'>R$ {total_hoje:,.2f}</div>".replace(',', 'X').replace('.', ',').replace('X', '.'), unsafe_allow_html=True)
                    
                    # Mostrar detalhes dos gastos
                    st.markdown("### Detalhamento:")
                    for idx, row in dados['gastos_hoje'].iterrows():
                        st.markdown(f"**{row['nome']}**: R$ {row['total']:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.'))
                else:
                    st.info("Sem gastos registrados hoje.")
                
                st.markdown("</div>", unsafe_allow_html=True)
            
            with col2:
                st.markdown("<div class='dashboard-card'>", unsafe_allow_html=True)
                st.markdown("<div class='card-title'>Previsão para o Próximo Mês</div>", unsafe_allow_html=True)
                
                # Seletor de mês
                hoje = datetime.date.today()
                proximo_mes = hoje.month + 1 if hoje.month < 12 else 1
                proximo_ano = hoje.year if hoje.month < 12 else hoje.year + 1
                
                meses = {
                    1: "Janeiro", 2: "Fevereiro", 3: "Março", 4: "Abril",
                    5: "Maio", 6: "Junho", 7: "Julho", 8: "Agosto",
                    9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro"
                }
                
                anos = list(range(hoje.year - 2, hoje.year + 3))
                
                col_mes, col_ano = st.columns(2)
                with col_mes:
                    mes_selecionado = st.selectbox("Mês", 
                                                  options=list(meses.keys()),
                                                  format_func=lambda x: meses[x],
                                                  index=list(meses.keys()).index(proximo_mes))
                
                with col_ano:
                    ano_selecionado = st.selectbox("Ano", 
                                                  options=anos,
                                                  index=anos.index(proximo_ano))
                
                # Obter dados do mês selecionado
                dados_mes = get_dados_mes(st.session_state.username, ano_selecionado, mes_selecionado)
                
                entrada_mes = dados_mes[dados_mes['tipo'] == 'entrada']['total'].sum() if not dados_mes.empty and 'entrada' in dados_mes['tipo'].values else 0
                saida_mes = dados_mes[dados_mes['tipo'] == 'saida']['total'].sum() if not dados_mes.empty and 'saida' in dados_mes['tipo'].values else 0
                saldo_mes = entrada_mes - saida_mes
                
                # Exibir informações
                st.write(f"Previsão para {meses[mes_selecionado]} de {ano_selecionado}:")
                col1, col2 = st.columns(2)
                with col1:
                    st.metric("Entradas", f"R$ {entrada_mes:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.'))
                    st.metric("Saídas", f"R$ {saida_mes:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.'))
                with col2:
                    color = "positive" if saldo_mes >= 0 else "negative"
                    st.markdown(f"<div class='value-display {color}'>Saldo: R$ {saldo_mes:,.2f}</div>".replace(',', 'X').replace('.', ',').replace('X', '.'), unsafe_allow_html=True)
                
                st.markdown("</div>", unsafe_allow_html=True)
            
            # Tabela de movimentações recentes
            st.markdown("<div class='dashboard-card'>", unsafe_allow_html=True)
            st.markdown("<div class='card-title'>Movimentações Recentes</div>", unsafe_allow_html=True)
            
            movimentacoes = get_movimentacoes(st.session_state.username, 
                                            data_inicio.strftime("%Y-%m-%d"),
                                            data_fim.strftime("%Y-%m-%d"))
            
            if not movimentacoes.empty:
                # Formatando valores e datas
                movimentacoes['valor_formatado'] = movimentacoes['valor'].apply(
                    lambda x: f"R$ {x:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.'))
                
                movimentacoes['data_formatada'] = pd.to_datetime(movimentacoes['data']).dt.strftime('%d/%m/%Y')
                
                # Exibir tabela de movimentações
                st.dataframe(
                    movimentacoes[['id', 'data_formatada', 'categoria', 'descricao', 'valor_formatado', 'tipo']].rename(
                        columns={
                            'data_formatada': 'Data',
                            'categoria': 'Categoria',
                            'descricao': 'Descrição',
                            'valor_formatado': 'Valor',
                            'tipo': 'Tipo'
                        }
                    ),
                    hide_index=True,
                    use_container_width=True
                )
            else:
                st.info("Sem movimentações neste período.")
            
            st.markdown("</div>", unsafe_allow_html=True)
        
        elif choice == "Cadastro":
            st.markdown("<h1 class='main-header'>Cadastro de Categorias</h1>", unsafe_allow_html=True)
            
            # Obter todas as categorias
            categorias = get_categorias(st.session_state.username)
            
            # Formulário para adicionar nova categoria
            with st.expander("Adicionar Nova Categoria", expanded=False):
                col1, col2 = st.columns(2)
                with col1:
                    nome_categoria = st.text_input("Nome da Categoria")
                with col2:
                    tipo_categoria = st.selectbox("Tipo", ["entrada", "saida"])
                
                if st.button("Adicionar"):
                    if nome_categoria:
                        if add_categoria(st.session_state.username, nome_categoria, tipo_categoria):
                            st.success(f"Categoria '{nome_categoria}' adicionada com sucesso!")
                            st.rerun()
                        else:
                            st.error(f"Erro ao adicionar categoria. Verifique se já existe uma categoria com esse nome.")
                    else:
                        st.warning("Preencha o nome da categoria.")
            
            # Exibir categorias existentes
            st.subheader("Categorias Existentes")
            
            # Separar categorias por tipo
            if not categorias.empty:
                categorias_entrada = categorias[categorias['tipo'] == 'entrada']
                categorias_saida = categorias[categorias['tipo'] == 'saida']
                
                col1, col2 = st.columns(2)
                
                with col1:
                    st.markdown("### Categorias de Entrada")
                    if not categorias_entrada.empty:
                        for idx, cat in categorias_entrada.iterrows():
                            with st.expander(f"{cat['nome']}"):
                                cat_id = cat['id']
                                cat_nome_edit = st.text_input("Nome", cat['nome'], key=f"entrada_nome_{cat_id}")
                                cat_tipo_edit = st.selectbox("Tipo", ["entrada", "saida"], 
                                                          index=0 if cat['tipo'] == 'entrada' else 1,
                                                          key=f"entrada_tipo_{cat_id}")
                                
                                col1, col2 = st.columns(2)
                                with col1:
                                    if st.button("Atualizar", key=f"entrada_update_{cat_id}"):
                                        if update_categoria(st.session_state.username, cat_id, cat_nome_edit, cat_tipo_edit):
                                            st.success("Categoria atualizada!")
                                            st.rerun()
                                        else:
                                            st.error("Erro ao atualizar categoria.")
                                
                                with col2:
                                    if st.button("Excluir", key=f"entrada_delete_{cat_id}"):
                                        if delete_categoria(st.session_state.username, cat_id):
                                            st.success("Categoria excluída!")
                                            st.rerun()
                                        else:
                                            st.error("Não é possível excluir categorias que possuem movimentações.")
                    else:
                        st.info("Nenhuma categoria de entrada cadastrada.")
                
                with col2:
                    st.markdown("### Categorias de Saída")
                    if not categorias_saida.empty:
                        for idx, cat in categorias_saida.iterrows():
                            with st.expander(f"{cat['nome']}"):
                                cat_id = cat['id']
                                cat_nome_edit = st.text_input("Nome", cat['nome'], key=f"saida_nome_{cat_id}")
                                cat_tipo_edit = st.selectbox("Tipo", ["entrada", "saida"], 
                                                          index=0 if cat['tipo'] == 'entrada' else 1,
                                                          key=f"saida_tipo_{cat_id}")
                                
                                col1, col2 = st.columns(2)
                                with col1:
                                    if st.button("Atualizar", key=f"saida_update_{cat_id}"):
                                        if update_categoria(st.session_state.username, cat_id, cat_nome_edit, cat_tipo_edit):
                                            st.success("Categoria atualizada!")
                                            st.rerun()
                                        else:
                                            st.error("Erro ao atualizar categoria.")
                                
                                with col2:
                                    if st.button("Excluir", key=f"saida_delete_{cat_id}"):
                                        if delete_categoria(st.session_state.username, cat_id):
                                            st.success("Categoria excluída!")
                                            st.rerun()
                                        else:
                                            st.error("Não é possível excluir categorias que possuem movimentações.")
                    else:
                        st.info("Nenhuma categoria de saída cadastrada.")
            else:
                st.info("Nenhuma categoria cadastrada.")
        
        elif choice == "Lançar Movimentação":
            st.markdown("<h1 class='main-header'>Lançar Movimentação</h1>", unsafe_allow_html=True)
            
            # Obter todas as categorias
            categorias = get_categorias(st.session_state.username)
            
            # Formulário para adicionar nova movimentação
            col1, col2 = st.columns(2)
            
            with col1:
                tipo = st.selectbox("Tipo de Movimentação", ["entrada", "saida"])
                
                # Filtrar categorias pelo tipo selecionado
                categorias_filtradas = categorias[categorias['tipo'] == tipo]
                
                if not categorias_filtradas.empty:
                    categoria_id = st.selectbox("Categoria", 
                                             options=categorias_filtradas['id'].tolist(),
                                             format_func=lambda x: categorias_filtradas[categorias_filtradas['id'] == x]['nome'].iloc[0])
                else:
                    st.error(f"Não há categorias do tipo '{tipo}' cadastradas. Crie uma categoria primeiro.")
                    categoria_id = None
                
                valor = st.number_input("Valor", min_value=0.01, step=0.01)
                data = st.date_input("Data", value=datetime.date.today(), format="DD/MM/YYYY")
            
            with col2:
                descricao = st.text_area("Descrição", height=100)
                
                # Opção para parcelar
                is_parcelado = st.checkbox("Movimentação Parcelada?")
                
                if is_parcelado:
                    total_parcelas = st.number_input("Número de Parcelas", min_value=2, max_value=48, step=1)
                else:
                    total_parcelas = 0
            
            if st.button("Lançar Movimentação"):
                if categoria_id is not None and valor > 0:
                    if add_movimentacao(st.session_state.username, categoria_id, valor, data.strftime("%Y-%m-%d"), 
                                       tipo, descricao, 1 if is_parcelado else 0, total_parcelas if is_parcelado else 0):
                        st.success("Movimentação lançada com sucesso!")
                        
                        # Limpar campos
                        st.rerun()
                    else:
                        st.error("Erro ao lançar movimentação.")
                else:
                    st.warning("Preencha todos os campos corretamente.")
            
            # Visualizar movimentações recentes
            st.markdown("### Movimentações Recentes")
            
            # Filtros
            col1, col2 = st.columns(2)
            with col1:
                data_inicio = st.date_input("De", 
                                          value=datetime.date.today() - datetime.timedelta(days=30),
                                          format="DD/MM/YYYY", 
                                          key="mov_data_inicio")
            with col2:
                data_fim = st.date_input("Até", 
                                       value=datetime.date.today(),
                                       format="DD/MM/YYYY",
                                       key="mov_data_fim")
            
            movimentacoes = get_movimentacoes(st.session_state.username, 
                                            data_inicio.strftime("%Y-%m-%d"),
                                            data_fim.strftime("%Y-%m-%d"))
            
            if not movimentacoes.empty:
                # Formatando valores e datas
                movimentacoes['valor_formatado'] = movimentacoes['valor'].apply(
                    lambda x: f"R$ {x:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.'))
                
                movimentacoes['data_formatada'] = pd.to_datetime(movimentacoes['data']).dt.strftime('%d/%m/%Y')
                
                # Adicionar colunas de ação
                movimentacoes_exibir = movimentacoes[['id', 'data_formatada', 'categoria', 'descricao', 'valor_formatado', 'tipo']].copy()
                movimentacoes_exibir.rename(
                    columns={
                        'data_formatada': 'Data',
                        'categoria': 'Categoria',
                        'descricao': 'Descrição',
                        'valor_formatado': 'Valor',
                        'tipo': 'Tipo'
                    }, inplace=True
                )
                
                # Exibir tabela
                st.dataframe(movimentacoes_exibir, hide_index=True, use_container_width=True)
                
                # Ações de edição
                col1, col2 = st.columns(2)
                with col1:
                    mov_id_edit = st.number_input("ID para Editar/Excluir", min_value=1, step=1)
                
                with col2:
                    acao = st.selectbox("Ação", ["Selecione uma ação", "Editar", "Excluir"])
                
                if acao == "Editar" and mov_id_edit > 0:
                    if mov_id_edit in movimentacoes['id'].values:
                        mov = movimentacoes[movimentacoes['id'] == mov_id_edit].iloc[0]
                        
                        st.subheader(f"Editar Movimentação #{mov_id_edit}")
                        
                        col1, col2 = st.columns(2)
                        
                        with col1:
                            tipo_edit = st.selectbox("Tipo de Movimentação", ["entrada", "saida"], 
                                                  index=0 if mov['tipo'] == 'entrada' else 1,
                                                  key=f"edit_tipo_{mov_id_edit}")
                            
                            # Filtrar categorias pelo tipo selecionado
                            categorias_filtradas = categorias[categorias['tipo'] == tipo_edit]
                            
                            if not categorias_filtradas.empty:
                                # Encontrar o ID da categoria atual
                                cat_atual_id = categorias[categorias['nome'] == mov['categoria']]['id'].iloc[0] if mov['categoria'] in categorias['nome'].values else categorias_filtradas['id'].iloc[0]
                                
                                categoria_id_edit = st.selectbox("Categoria", 
                                                            options=categorias_filtradas['id'].tolist(),
                                                            index=list(categorias_filtradas['id']).index(cat_atual_id) if cat_atual_id in categorias_filtradas['id'].values else 0,
                                                            format_func=lambda x: categorias_filtradas[categorias_filtradas['id'] == x]['nome'].iloc[0],
                                                            key=f"edit_cat_{mov_id_edit}")
                            else:
                                st.error(f"Não há categorias do tipo '{tipo_edit}' cadastradas.")
                                categoria_id_edit = None
                            
                            valor_edit = st.number_input("Valor", 
                                                      min_value=0.01, 
                                                      value=float(mov['valor']),
                                                      step=0.01,
                                                      key=f"edit_valor_{mov_id_edit}")
                            
                            data_edit = st.date_input("Data", 
                                                    value=pd.to_datetime(mov['data']).date(),
                                                    format="DD/MM/YYYY",
                                                    key=f"edit_data_{mov_id_edit}")
                        
                        with col2:
                            descricao_edit = st.text_area("Descrição", 
                                                       value=mov['descricao'] if pd.notna(mov['descricao']) else "",
                                                       height=100,
                                                       key=f"edit_desc_{mov_id_edit}")
                            
                            if st.button("Salvar Alterações"):
                                if categoria_id_edit is not None and valor_edit > 0:
                                    if update_movimentacao(st.session_state.username, mov_id_edit, 
                                                         categoria_id_edit, valor_edit, 
                                                         data_edit.strftime("%Y-%m-%d"), 
                                                         tipo_edit, descricao_edit):
                                        st.success("Movimentação atualizada com sucesso!")
                                        st.rerun()
                                    else:
                                        st.error("Erro ao atualizar movimentação.")
                                else:
                                    st.warning("Preencha todos os campos corretamente.")
                    else:
                        st.error("ID de movimentação não encontrado.")
                
                elif acao == "Excluir" and mov_id_edit > 0:
                    if mov_id_edit in movimentacoes['id'].values:
                        mov = movimentacoes[movimentacoes['id'] == mov_id_edit].iloc[0]
                        
                        st.subheader(f"Excluir Movimentação #{mov_id_edit}")
                        st.write(f"**Data:** {mov['data_formatada']}")
                        st.write(f"**Categoria:** {mov['categoria']}")
                        st.write(f"**Valor:** {mov['valor_formatado']}")
                        st.write(f"**Descrição:** {mov['descricao'] if pd.notna(mov['descricao']) else '-'}")
                        
                        # Verificar se é uma parcela
                        if mov['parcela'] > 0 and mov['total_parcelas'] > 0:
                            st.warning(f"Esta é uma movimentação parcelada ({mov['parcela']}/{mov['total_parcelas']}).")
                            st.session_state.excluir_todas_parcelas = st.checkbox("Excluir todas as parcelas?")
                        
                        if st.button("Confirmar Exclusão"):
                            if delete_movimentacao(st.session_state.username, mov_id_edit):
                                st.success("Movimentação excluída com sucesso!")
                                st.rerun()
                            else:
                                st.error("Erro ao excluir movimentação.")
                    else:
                        st.error("ID de movimentação não encontrado.")
            else:
                st.info("Nenhuma movimentação encontrada neste período.")
        
        elif choice == "Auditoria":
            st.markdown("<h1 class='main-header'>Relatórios e Auditoria</h1>", unsafe_allow_html=True)
            
            # Abas para diferentes relatórios
            tab1, tab2, tab3 = st.tabs(["Fluxo Mensal", "Análise de Categorias", "Exportar Dados"])
            
            with tab1:
                st.subheader("Fluxo de Caixa Mensal")
                
                # Seletor de período
                col1, col2 = st.columns(2)
                with col1:
                    ano = st.selectbox("Ano", options=list(range(datetime.date.today().year - 2, datetime.date.today().year + 1)))
                with col2:
                    todos_meses = st.checkbox("Todos os meses", value=True)
                    
                    if not todos_meses:
                        mes = st.selectbox("Mês", options=list(range(1, 13)), 
                                         format_func=lambda x: calendar.month_name[x])
                
                # Obter dados para cada mês
                dados_meses = {}
                meses_para_analisar = list(range(1, 13)) if todos_meses else [mes]
                
                for m in meses_para_analisar:
                    primeiro_dia = datetime.date(ano, m, 1)
                    ultimo_dia = datetime.date(ano, m, calendar.monthrange(ano, m)[1])
                    
                    dados = get_dados_dashboard(st.session_state.username, 
                                              primeiro_dia.strftime("%Y-%m-%d"),
                                              ultimo_dia.strftime("%Y-%m-%d"))
                    
                    entrada = dados['totais'][dados['totais']['tipo'] == 'entrada']['total'].sum() if not dados['totais'].empty and 'entrada' in dados['totais']['tipo'].values else 0
                    saida = dados['totais'][dados['totais']['tipo'] == 'saida']['total'].sum() if not dados['totais'].empty and 'saida' in dados['totais']['tipo'].values else 0
                    saldo = entrada - saida
                    
                    dados_meses[m] = {
                        'nome': calendar.month_name[m],
                        'entrada': entrada,
                        'saida': saida,
                        'saldo': saldo
                    }
                
                # Criar DataFrame para visualização
                df_meses = pd.DataFrame.from_dict(dados_meses, orient='index')
                
                # Criar gráfico de barras
                if not df_meses.empty:
                    # Gráfico de barras empilhadas
                    fig = make_subplots(specs=[[{"secondary_y": True}]])
                    
                    fig.add_trace(
                        go.Bar(
                            x=df_meses['nome'],
                            y=df_meses['entrada'],
                            name='Entradas',
                            marker_color='#4CAF50'
                        ),
                        secondary_y=False
                    )
                    
                    fig.add_trace(
                        go.Bar(
                            x=df_meses['nome'],
                            y=df_meses['saida'],
                            name='Saídas',
                            marker_color='#F44336'
                        ),
                        secondary_y=False
                    )
                    
                    fig.add_trace(
                        go.Scatter(
                            x=df_meses['nome'],
                            y=df_meses['saldo'],
                            name='Saldo',
                            mode='lines+markers',
                            line=dict(color='#2196F3', width=3),
                            marker=dict(size=8)
                        ),
                        secondary_y=True
                    )
                    
                    fig.update_layout(
                        title_text=f"Fluxo de Caixa Mensal - {ano}",
                        barmode='group',
                        xaxis_title="Mês",
                        legend=dict(
                            orientation="h",
                            yanchor="bottom",
                            y=1.02,
                            xanchor="right",
                            x=1
                        ),
                        height=500
                    )
                    
                    fig.update_yaxes(title_text="Valores (R$)", secondary_y=False)
                    fig.update_yaxes(title_text="Saldo (R$)", secondary_y=True)
                    
                    st.plotly_chart(fig, use_container_width=True)
                    
                    # Tabela com os dados mensais
                    st.subheader("Dados Mensais")
                    df_exibir = df_meses.copy()
                    df_exibir['entrada'] = df_exibir['entrada'].apply(lambda x: f"R$ {x:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.'))
                    df_exibir['saida'] = df_exibir['saida'].apply(lambda x: f"R$ {x:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.'))
                    df_exibir['saldo'] = df_exibir['saldo'].apply(lambda x: f"R$ {x:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.'))
                    
                    st.dataframe(df_exibir.reset_index(drop=True).rename(
                        columns={
                            'nome': 'Mês',
                            'entrada': 'Entradas',
                            'saida': 'Saídas',
                            'saldo': 'Saldo'
                        }
                    ), hide_index=True, use_container_width=True)
                else:
                    st.info("Nenhum dado disponível para o período selecionado.")
            
            with tab2:
                st.subheader("Análise de Categorias")
                
                # Seletor de período
                col1, col2 = st.columns(2)
                with col1:
                    data_inicio = st.date_input("Data Inicial", 
                                              value=datetime.date.today().replace(day=1),
                                              format="DD/MM/YYYY",
                                              key="cat_data_inicio")
                with col2:
                    data_fim = st.date_input("Data Final", 
                                           value=datetime.date.today().replace(day=calendar.monthrange(datetime.date.today().year, datetime.date.today().month)[1]),
                                           format="DD/MM/YYYY",
                                           key="cat_data_fim")
                
                # Obter dados para o dashboard
                dados = get_dados_dashboard(st.session_state.username, 
                                           data_inicio.strftime("%Y-%m-%d"),
                                           data_fim.strftime("%Y-%m-%d"))
                
                # Analisar gastos por categoria
                if not dados['gastos_categoria'].empty:
                    # Gráfico de barras para categorias
                    st.subheader("Gastos por Categoria")
                    fig = px.bar(
                        dados['gastos_categoria'].sort_values('total', ascending=False),
                        x='nome',
                        y='total',
                        title='',
                        labels={'nome': 'Categoria', 'total': 'Valor (R$)'},
                        color='total',
                        color_continuous_scale='Reds'
                    )
                    fig.update_layout(height=500)
                    st.plotly_chart(fig, use_container_width=True)
                    
                    # Tabela com os dados
                    df_exibir = dados['gastos_categoria'].copy()
                    df_exibir['total'] = df_exibir['total'].apply(lambda x: f"R$ {x:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.'))
                    df_exibir['percentual'] = dados['gastos_categoria']['total'] / dados['gastos_categoria']['total'].sum() * 100
                    df_exibir['percentual'] = df_exibir['percentual'].apply(lambda x: f"{x:.2f}%".replace('.', ','))
                    
                    st.dataframe(df_exibir.sort_values('total', ascending=False).reset_index(drop=True).rename(
                        columns={
                            'nome': 'Categoria',
                            'total': 'Valor',
                            'percentual': 'Percentual'
                        }
                    ), hide_index=True, use_container_width=True)
                else:
                    st.info("Nenhum gasto registrado no período selecionado.")
            
            with tab3:
                st.subheader("Exportar Dados")
                
                # Seletor de período
                col1, col2 = st.columns(2)
                with col1:
                    data_inicio = st.date_input("Data Inicial", 
                                              value=datetime.date.today().replace(month=1, day=1),
                                              format="DD/MM/YYYY",
                                              key="exp_data_inicio")
                with col2:
                    data_fim = st.date_input("Data Final", 
                                           value=datetime.date.today(),
                                           format="DD/MM/YYYY",
                                           key="exp_data_fim")
                
                # Obter movimentações
                movimentacoes = get_movimentacoes(st.session_state.username, 
                                                data_inicio.strftime("%Y-%m-%d"),
                                                data_fim.strftime("%Y-%m-%d"))
                
                if not movimentacoes.empty:
                    # Converter para CSV
                    csv = movimentacoes.to_csv(index=False).encode('utf-8')
                    
                    st.download_button(
                        label="Download CSV",
                        data=csv,
                        file_name=f"financas_{st.session_state.username}_{data_inicio.strftime('%Y%m%d')}_{data_fim.strftime('%Y%m%d')}.csv",
                        mime="text/csv",
                    )
                    
                    # Exibir visualização
                    st.dataframe(movimentacoes, use_container_width=True)
                else:
                    st.info("Nenhuma movimentação encontrada no período selecionado.")
        
        elif choice == "Administração" and st.session_state.is_admin:
            st.markdown("<h1 class='main-header'>Administração do Sistema</h1>", unsafe_allow_html=True)
            
            # Abas para diferentes funcionalidades de administração
            tab1, tab2 = st.tabs(["Gerenciar Usuários", "Configurações"])
            
            with tab1:
                st.subheader("Gerenciar Usuários")
                
                # Formulário para criar novo usuário
                with st.expander("Adicionar Novo Usuário", expanded=False):
                    col1, col2 = st.columns(2)
                    with col1:
                        novo_username = st.text_input("Nome de Usuário")
                    with col2:
                        nova_senha = st.text_input("Senha", type="password")
                    is_admin = st.checkbox("Usuário é Administrador?")
                    
                    if st.button("Criar Usuário"):
                        if novo_username and nova_senha:
                            if register_user(novo_username, nova_senha, is_admin):
                                st.success(f"Usuário '{novo_username}' criado com sucesso!")
                                st.rerun()
                            else:
                                st.error(f"Erro ao criar usuário. O nome '{novo_username}' já está em uso.")
                        else:
                            st.warning("Preencha todos os campos.")
                
                # Lista de usuários
                st.subheader("Usuários do Sistema")
                users = get_all_users()
                
                if not users.empty:
                    for idx, user in users.iterrows():
                        with st.expander(f"{user['username']} {'(Admin)' if user['is_admin'] else ''}"):
                            user_id = user['id']
                            user_status = "Ativo" if user['is_active'] else "Inativo"
                            st.write(f"**Status:** {user_status}")
                            
                            # Não permitir desativar o próprio usuário
                            if user['username'] != st.session_state.username:
                                if user['is_active']:
                                    if st.button("Desativar Usuário", key=f"deactivate_{user_id}"):
                                        toggle_user_status(user_id, 0)
                                        st.success(f"Usuário '{user['username']}' desativado.")
                                        st.rerun()
                                else:
                                    if st.button("Ativar Usuário", key=f"activate_{user_id}"):
                                        toggle_user_status(user_id, 1)
                                        st.success(f"Usuário '{user['username']}' ativado.")
                                        st.rerun()
                            else:
                                st.info("Você não pode desativar seu próprio usuário.")
                            
                            # Opção para redefinir senha
                            with st.expander("Redefinir Senha"):
                                nova_senha = st.text_input("Nova Senha", type="password", key=f"new_pass_{user_id}")
                                confirmar_senha = st.text_input("Confirmar Senha", type="password", key=f"confirm_pass_{user_id}")
                                
                                if st.button("Alterar Senha", key=f"change_pass_{user_id}"):
                                    if nova_senha and nova_senha == confirmar_senha:
                                        change_password(user['username'], nova_senha)
                                        st.success("Senha alterada com sucesso!")
                                    else:
                                        st.error("As senhas não coincidem ou estão em branco.")
                else:
                    st.info("Nenhum usuário encontrado.")
            
            with tab2:
                st.subheader("Configurações do Sistema")
                
                st.info("Seu banco de dados PostgreSQL está configurado corretamente.")
                
                # Mostrar informações do banco de dados
                conn = get_connection()
                cur = conn.cursor()
                
                try:
                    # Versão do PostgreSQL
                    cur.execute("SELECT version();")
                    version = cur.fetchone()[0]
                    st.write(f"**Versão do PostgreSQL:** {version}")
                    
                    # Tamanho do banco de dados
                    cur.execute("SELECT pg_size_pretty(pg_database_size(current_database()));")
                    db_size = cur.fetchone()[0]
                    st.write(f"**Tamanho do Banco de Dados:** {db_size}")
                    
                    # Estatísticas de usuários
                    cur.execute("SELECT COUNT(*) FROM users;")
                    total_users = cur.fetchone()[0]
                    st.write(f"**Total de Usuários:** {total_users}")
                    
                    # Estatísticas de tabelas
                    cur.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public';")
                    total_tables = cur.fetchone()[0]
                    st.write(f"**Total de Tabelas:** {total_tables}")
                    
                except Exception as e:
                    st.error(f"Erro ao obter informações do banco de dados: {e}")
                
                conn.close()
                
                # Opção para backup
                st.subheader("Backup do Banco de Dados")
                st.warning("O backup deve ser realizado pelo administrador do banco de dados PostgreSQL.")
                st.info("Recomendamos utilizar ferramentas como pg_dump para realizar backups regulares.")

if __name__ == "__main__":
    main()