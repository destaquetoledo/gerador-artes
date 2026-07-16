import streamlit as st
import requests
from bs4 import BeautifulSoup
from PIL import Image
import io
import os
import sqlite3
from datetime import datetime, timedelta
import hashlib
import hmac
import binascii
import re

# ============================================================
# 1) CONFIGURAÇÃO DA PÁGINA
# ============================================================
st.set_page_config(page_title="Painel Destaque Toledo", layout="wide", page_icon="📝")

# ============================================================
# 2) ESTILIZAÇÃO CSS PROFISSIONAL (OTIMIZADA PARA ROLAGEM)
# ============================================================
st.markdown(
    """
    <style>
    /* Forçar rolagem em todos os dispositivos */
    html, body, [data-testid="stAppViewContainer"] {
        overflow-y: auto !important;
    }
    
    /* Tornar a barra de rolagem bem visível */
    ::-webkit-scrollbar {
        width: 14px; /* Barra mais larga para fácil clique */
        height: 14px;
    }
    ::-webkit-scrollbar-track {
        background: #f1f1f1;
        border-radius: 10px;
    }
    ::-webkit-scrollbar-thumb {
        background: #004a99; /* Cor principal do portal */
        border-radius: 10px;
        border: 2px solid #f1f1f1;
    }
    ::-webkit-scrollbar-thumb:hover {
        background: #003366;
    }

    .stApp { background-color: #f8f9fa; }
    .topo-titulo {
        text-align: center; padding: 30px;
        background: linear-gradient(90deg, #004a99 0%, #007bff 100%);
        color: white; border-radius: 15px; margin-bottom: 25px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.1);
    }
    .card-pauta {
        background-color: white; padding: 20px; border-radius: 12px;
        border-left: 6px solid #004a99; margin-bottom: 15px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.05);
    }
    .card-urgente { border-left: 6px solid #dc3545; background-color: #fff5f5; }
    .card-programar { border-left: 6px solid #ffc107; background-color: #fffdf5; }
    .tag-status {
        padding: 4px 12px; border-radius: 20px; font-size: 0.75rem;
        font-weight: bold; text-transform: uppercase;
    }
    .tag-urgente { background-color: #dc3545; color: white; }
    .tag-normal { background-color: #e9ecef; color: #495057; }
    .tag-programar { background-color: #ffc107; color: #000; }
    .obs-box {
        background-color: #e7f1ff; padding: 12px; border-radius: 8px;
        border: 1px dashed #004a99; margin-top: 10px; margin-bottom: 15px; font-style: italic;
    }
    .boas-vindas {
        font-size: 1.5rem; font-weight: bold; color: #004a99; margin-bottom: 10px;
    }
    .descricao-aba {
        color: #666; font-size: 0.95rem; margin-bottom: 20px; line-height: 1.4;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ============================================================
# 3) CONFIG / CONSTANTES
# ============================================================
DB_PATH = os.getenv("DT_DB_PATH", "agenda_destaque.db")
REQUEST_TIMEOUT = int(os.getenv("DT_REQUEST_TIMEOUT", "12"))

# ============================================================
# 4) SEGURANÇA: SENHAS (SEM HARDCODE)
# ============================================================
def verify_password(password: str, stored: str) -> bool:
    try:
        algo, it_str, salt_hex, hash_hex = stored.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        iterations = int(it_str)
        salt = binascii.unhexlify(salt_hex.encode("ascii"))
        expected = binascii.unhexlify(hash_hex.encode("ascii"))
        test = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(test, expected)
    except Exception:
        return False

def load_auth_hashes():
    auth = {}
    try:
        if "AUTH" in st.secrets:
            auth = dict(st.secrets["AUTH"])
    except Exception:
        auth = {}

    juan_hash = auth.get("juan") or os.getenv("DT_AUTH_JUAN", "").strip()
    brayan_hash = auth.get("brayan") or os.getenv("DT_AUTH_BRAYAN", "").strip()

    return {"juan": juan_hash, "brayan": brayan_hash}

AUTH_HASHES = load_auth_hashes()
AUTH_CONFIG_OK = bool(AUTH_HASHES.get("juan")) and bool(AUTH_HASHES.get("brayan"))

# ============================================================
# 5) BANCO DE DADOS (CONFIGURADO PARA PERSISTÊNCIA TOTAL)
# ============================================================
def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=FULL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    return conn

def init_db():
    conn = get_conn()
    try:
        c = conn.cursor()
        # Tabela unificada das pautas de trabalho do Brayan
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS pautas_trabalho (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                titulo TEXT,
                link_ref TEXT,
                status TEXT,
                data_envio TEXT,
                prioridade TEXT,
                observacao TEXT
            )
            """
        )
        conn.commit()
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
    except Exception as e:
        print(f"Erro ao inicializar banco: {e}")
    finally:
        conn.close()

init_db()

# ============================================================
# 9) LOGIN (VERSÃO OTIMIZADA)
# ============================================================
if "autenticado" not in st.session_state:
    st.session_state.autenticado = False

if not st.session_state.autenticado:
    st.markdown(
        """
        <div style="text-align: center; padding: 20px;">
            <h1 style="color: #004a99; margin-bottom: 0; font-family: sans-serif;">DESTAQUE TOLEDO</h1>
            <p style="color: #666; font-size: 1.1rem;">Painel de Controle Administrativo</p>
        </div>
        """, 
        unsafe_allow_html=True
    )

    _, col2, _ = st.columns([1, 1.2, 1])
    
    with col2:
        with st.form("painel_login"):
            st.markdown("<h3 style='text-align: center; margin-top: 0;'>Acesso Restrito</h3>", unsafe_allow_html=True)
            
            if not AUTH_CONFIG_OK:
                st.error(
                    "⚠️ **Configuração Faltando**\n\n"
                    "As chaves de autenticação não foram detectadas.\n"
                    "Certifique-se de configurar os secrets no Streamlit Cloud."
                )
                st.stop()

            u = st.text_input("👤 Usuário", placeholder="Digite seu usuário").lower().strip()
            s = st.text_input("🔑 Senha", type="password", placeholder="Digite sua senha")
            
            manter_conectado = st.checkbox("Manter-se conectado", value=True)
            st.write("") 
            
            entrar = st.form_submit_button("ENTRAR NO SISTEMA", use_container_width=True, type="primary")
            
            if entrar:
                if u in ("juan", "brayan") and verify_password(s, AUTH_HASHES.get(u, "")):
                    st.session_state.autenticado = True
                    st.session_state.perfil = u
                    st.session_state["login_em"] = datetime.utcnow().timestamp()
                    st.toast(f"Bem-vindo, {u.capitalize()}!", icon="✅")
                    st.rerun()
                else:
                    st.error("❌ Usuário ou senha incorretos.")

        st.markdown(
            """
            <div style="text-align: center; margin-top: 20px;">
                <a href="https://www.destaquetoledo.com.br" target="_blank" style="text-decoration: none; color: #007bff; font-size: 0.85rem;">🌐 Acessar Site Público</a>
                <br><br>
                <small style="color: #999;">Suporte técnico: <a href="mailto:admin@destaquetoledo.com.br" style="color: #999;">Contato</a></small>
            </div>
            """, 
            unsafe_allow_html=True
        )

else:
    # ============================================================
    # 10) INTERFACE INTERNA - DASHBOARD DIRETA (SEM ABAS)
    # ============================================================
    try:
        from streamlit_autorefresh import st_autorefresh
        st_autorefresh(interval=30000, key="refresh_dashboard")
    except:
        pass

    st.markdown('<div class="topo-titulo"><h1>DESTAQUE TOLEDO</h1></div>', unsafe_allow_html=True)

    # Identificação do usuário logado
    st.markdown(f'<div class="boas-vindas">Bem-vindo, {st.session_state.perfil.capitalize()}!</div>', unsafe_allow_html=True)
    st.markdown('<p class="descricao-aba">Envie, monitore e gerencie as matérias e publicações enviadas na Fila de Trabalho em tempo real.</p>', unsafe_allow_html=True)

    # Divisão em duas colunas: Esquerda para envio, Direita para o monitoramento
    col_envio, col_monitor = st.columns([1.1, 1.2])

    with col_envio:
        st.subheader("🚀 Enviar Nova Pauta")
        with st.form("form_envio_pauta", clear_on_submit=True):
            col_f1, col_f2 = st.columns([3, 1])
            with col_f1:
                f_titulo = st.text_input("📌 Título da Matéria")
            with col_f2:
                f_urgencia = st.selectbox("Prioridade", ["Normal", "Programar", "URGENTE"])
            
            f_link = st.text_input("🔗 Link da Matéria (se houver)")
            f_obs = st.text_area("📄 Texto da Matéria / Release", height=230, placeholder="Cole aqui o conteúdo da notícia ou release...")

            if st.form_submit_button("🚀 ENVIAR PARA A FILA", use_container_width=True, type="primary"):
                if f_titulo:
                    hora_br = (datetime.utcnow() - timedelta(hours=3)).strftime("%H:%M")
                    conn = get_conn()
                    c = conn.cursor()
                    c.execute(
                        """
                        INSERT INTO pautas_trabalho
                        (titulo, link_ref, status, data_envio, prioridade, observacao)
                        VALUES (?,?,'Pendente',?,?,?)
                        """,
                        (f_titulo, f_link if f_link else "Sem link", hora_br, f_urgencia, f_obs),
                    )
                    conn.commit()
                    conn.close()
                    st.success("✅ Matéria adicionada à fila com sucesso!")
                    st.rerun()
                else:
                    st.warning("Por favor, informe ao menos o título da pauta.")

    with col_monitor:
        col_m_tit, col_m_ref = st.columns([2, 1])
        with col_m_tit:
            st.subheader("👀 Fila de Trabalho")
        with col_m_ref:
            if st.button("🔄 Atualizar Fila", key="up_fila_direta", use_container_width=True):
                st.rerun()

        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT id, titulo, prioridade, data_envio, status, link_ref, observacao FROM pautas_trabalho WHERE status != 'Concluído' ORDER BY id DESC LIMIT 10")
        monitor = c.fetchall()
        conn.close()

        if not monitor:
            st.info("✨ Tudo em dia! Nenhuma postagem pendente no momento.")
        else:
            for p in monitor:
                p_id, p_titulo, p_prioridade, p_data, p_status, p_link, p_obs = p
                
                # Cores de prioridade da borda lateral do card
                classe_card = "card-pauta"
                if p_prioridade == "URGENTE":
                    classe_card = "card-pauta card-urgente"
                elif p_prioridade == "Programar":
                    classe_card = "card-pauta card-programar"

                # Define cores do status
                if p_status == "Postando":
                    status_cor = "#fd7e14" # Laranja
                    status_txt = "⚡ POSTANDO AGORA"
                else:
                    status_cor = "#004a99" # Azul
                    status_txt = "⏳ NA FILA"

                with st.container():
                    st.markdown(
                        f"""
                        <div class="{classe_card}">
                            <div style="display:flex; justify-content:space-between; align-items:center;">
                                <span style="font-size:0.8rem; color:#666; font-weight:bold;">🕒 {p_data}</span>
                                <span style="color:{status_cor}; font-weight:bold; font-size:0.85rem;">{status_txt}</span>
                            </div>
                            <h4 style="margin: 8px 0; color:#111;">{p_titulo}</h4>
                            <p style="margin: 4px 0; font-size:0.85rem;"><b>Prioridade:</b> {p_prioridade} | <b>Link:</b> <a href="{p_link}" target="_blank">{p_link}</a></p>
                            {f'<div class="obs-box"><b>Texto/Obs:</b> {p_obs}</div>' if p_obs else ''}
                        </div>
                        """,
                        unsafe_allow_html=True
                    )
                    
                    # Botões de Ação rápidos do Card
                    b_col1, b_col2, b_col3 = st.columns([1, 1, 1])
                    with b_col1:
                        if p_status == "Pendente":
                            if st.button("⚡ Iniciar", key=f"init_{p_id}", use_container_width=True):
                                conn = get_conn()
                                c = conn.cursor()
                                c.execute("UPDATE pautas_trabalho SET status='Postando' WHERE id=?", (p_id,))
                                conn.commit()
                                conn.close()
                                st.rerun()
                        else:
                            if st.button("⏳ Pausar", key=f"pause_{p_id}", use_container_width=True):
                                conn = get_conn()
                                c = conn.cursor()
                                c.execute("UPDATE pautas_trabalho SET status='Pendente' WHERE id=?", (p_id,))
                                conn.commit()
                                conn.close()
                                st.rerun()
                    
                    with b_col2:
                        if st.button("✅ Concluir", key=f"done_{p_id}", use_container_width=True, type="primary"):
                            conn = get_conn()
                            c = conn.cursor()
                            c.execute("UPDATE pautas_trabalho SET status='Concluído' WHERE id=?", (p_id,))
                            conn.commit()
                            conn.close()
                            st.toast("Pauta concluída!", icon="✅")
                            st.rerun()
                    
                    with b_col3:
                        if st.button("❌ Excluir", key=f"del_{p_id}", use_container_width=True):
                            conn = get_conn()
                            c = conn.cursor()
                            c.execute("DELETE FROM pautas_trabalho WHERE id=?", (p_id,))
                            conn.commit()
                            conn.close()
                            st.rerun()
                    
                    st.markdown("<div style='margin-bottom:20px;'></div>", unsafe_allow_html=True)
