import streamlit as st
import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont
import textwrap
import io
import os
import sqlite3
from datetime import datetime, timedelta
from urllib.parse import urljoin
import hashlib
import hmac
import binascii
import re

# ============================================================
# 1) CONFIGURAÇÃO DA PÁGINA
# ============================================================
st.set_page_config(page_title="Painel Destaque Toledo", layout="wide", page_icon="🎨")

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
    
    /* Tornar a barra de rolagem bem visível para o Brayan */
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
    /* ... (restante dos seus estilos de card-pauta, tag-status etc permanecem iguais) ... */
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

CAMINHO_FONTE = os.getenv("DT_FONTE_PATH", "Shoika Bold.ttf")
TEMPLATE_FEED = os.getenv("DT_TEMPLATE_FEED", "template_feed.png")
TEMPLATE_STORIE = os.getenv("DT_TEMPLATE_STORIE", "template_storie.png")

HEADERS = {
    "User-Agent": os.getenv(
        "DT_USER_AGENT",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    )
}

REQUEST_TIMEOUT = int(os.getenv("DT_REQUEST_TIMEOUT", "12"))

# ============================================================
# 4) SEGURANÇA: SENHAS (SEM HARDCODE)
# ============================================================

def make_password_hash(password: str, iterations: int = 200_000) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "pbkdf2_sha256$%d$%s$%s" % (
        iterations,
        binascii.hexlify(salt).decode("ascii"),
        binascii.hexlify(dk).decode("ascii"),
    )

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
# 5) BANCO DE DADOS (AJUSTADO PARA PERSISTÊNCIA TOTAL)
# ============================================================
def get_conn():
    # Aumentado o timeout para 10 segundos para evitar travamentos em escritas rápidas
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10)
    
    # Ativa o modo WAL para permitir leitura e escrita simultâneas
    conn.execute("PRAGMA journal_mode=WAL;")
    
    # Mudado de NORMAL para FULL: Garante que o sistema espere o dado gravar no disco físico
    conn.execute("PRAGMA synchronous=FULL;")
    
    conn.execute("PRAGMA busy_timeout=5000;")
    return conn

def init_db():
    conn = get_conn()
    try:
        c = conn.cursor()

        # Tabela antiga (mantida por compatibilidade)
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS agenda (
                dia TEXT PRIMARY KEY,
                pauta TEXT
            )
            """
        )

        # Pautas do Brayan
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

        # Agenda unificada
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS agenda_itens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                data_ref TEXT NOT NULL,
                titulo TEXT NOT NULL,
                descricao TEXT,
                status TEXT NOT NULL DEFAULT 'Pendente',
                criado_por TEXT,
                criado_em TEXT
            )
            """
        )

        conn.commit()
        # COMANDO CRÍTICO: Força o SQLite a transferir tudo do log temporário para o arquivo .db real
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
    except Exception as e:
        print(f"Erro ao inicializar banco: {e}")
    finally:
        conn.close()

# Inicializa o banco garantindo a estrutura
init_db()

# ============================================================
# 6) HTTP HELPERS (COM TIMEOUT + TRATAMENTO)
# ============================================================
@st.cache_resource(show_spinner=False)
def get_requests_session(headers: dict):
    s = requests.Session()
    s.headers.update(headers)
    return s

SESSION = get_requests_session(HEADERS)

def safe_get_text(url: str) -> str:
    try:
        r = SESSION.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        r.raise_for_status()
        if not r.encoding:
            r.encoding = r.apparent_encoding or "utf-8"
        return r.text
    except requests.exceptions.Timeout:
        raise RuntimeError("Tempo limite excedido ao acessar a página.")
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Falha HTTP ao acessar a página: {e}")

def safe_get_bytes(url: str) -> bytes:
    try:
        r = SESSION.get(url, timeout=REQUEST_TIMEOUT, stream=True, allow_redirects=True)
        r.raise_for_status()
        return r.content
    except requests.exceptions.Timeout:
        raise RuntimeError("Tempo limite excedido ao baixar a imagem.")
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Falha HTTP ao baixar a imagem: {e}")

# ============================================================
# 7) SCRAPING + ARTE (ROBUSTO)
# ============================================================
def extrair_titulo(soup: BeautifulSoup) -> str:
    h1 = soup.find("h1")
    if h1:
        t = h1.get_text(" ", strip=True)
        if t:
            return t
    if soup.title and soup.title.get_text(strip=True):
        return soup.title.get_text(strip=True)
    return "Sem título"

def normalizar_url(base: str, candidate: str) -> str:
    if not candidate:
        return ""
    return urljoin(base, candidate)

def encontrar_primeira_imagem_util(base_url: str, soup: BeautifulSoup) -> str:
    candidatos = []
    corpo = soup.find(class_="post-body") or soup.find("article") or soup

    for img in corpo.find_all("img"):
        src = (img.get("src") or "").strip()
        data_src = (img.get("data-src") or "").strip()
        data_lazy = (img.get("data-lazy-src") or "").strip()
        pick = src or data_src or data_lazy
        if not pick:
            continue

        full = normalizar_url(base_url, pick)
        low = full.lower()

        if "logo" in low or "icon" in low or "sprite" in low:
            continue

        if not re.search(r"\.(jpg|jpeg|png|webp)(\?|$)", low):
            candidatos.append(full)
            continue

        return full

    return candidatos[0] if candidatos else ""

def garantir_fonte():
    if not os.path.exists(CAMINHO_FONTE):
        raise FileNotFoundError(
            f"Fonte não encontrada: {CAMINHO_FONTE}. "
            f"Ajuste DT_FONTE_PATH ou coloque o arquivo no mesmo diretório."
        )

def aplicar_template_se_existir(base_img: Image.Image, template_path: str, size: tuple):
    if os.path.exists(template_path):
        tmp = Image.open(template_path).convert("RGBA").resize(size)
        base_img.alpha_composite(tmp)

def processar_artes_integrado(url: str, tipo_solicitado: str, titulo_personalizado: str = None) -> Image.Image:
    garantir_fonte()

    html = safe_get_text(url)
    soup = BeautifulSoup(html, "html.parser")

    # --- AJUSTE AQUI: Lógica de escolha do título ---
    titulo_site = extrair_titulo(soup)
    # Se você digitou algo na caixa, usamos o seu. Se estiver vazio, usa o do site.
    titulo = titulo_personalizado if titulo_personalizado and titulo_personalizado.strip() != "" else titulo_site
    
    img_url = encontrar_primeira_imagem_util(url, soup)

    if not img_url:
        raise ValueError("Não foi encontrada uma imagem válida na matéria.")

    img_original = Image.open(io.BytesIO(safe_get_bytes(img_url))).convert("RGBA")
    larg_o, alt_o = img_original.size
    prop_o = larg_o / alt_o

    if tipo_solicitado == "FEED":
        TAMANHO_FEED = 1000
        if prop_o > 1.0:
            n_alt = TAMANHO_FEED
            n_larg = int(n_alt * prop_o)
            img_redim = img_original.resize((n_larg, n_alt), Image.LANCZOS)
            margem = (n_larg - TAMANHO_FEED) // 2
            fundo = img_redim.crop((margem, 0, margem + TAMANHO_FEED, TAMANHO_FEED))
        else:
            n_larg = TAMANHO_FEED
            n_alt = int(n_larg / prop_o)
            img_redim = img_original.resize((n_larg, n_alt), Image.LANCZOS)
            margem = (n_alt - TAMANHO_FEED) // 2
            fundo = img_redim.crop((0, margem, TAMANHO_FEED, margem + TAMANHO_FEED))

        fundo = fundo.convert("RGBA")
        aplicar_template_se_existir(fundo, TEMPLATE_FEED, (TAMANHO_FEED, TAMANHO_FEED))
        draw = ImageDraw.Draw(fundo)

        tam = 85
        while tam > 20:
            fonte = ImageFont.truetype(CAMINHO_FONTE, tam)
            try: limite = int(662 / (fonte.getlength("W") * 0.55))
            except: limite = 26
            
            # O textwrap agora usa o 'titulo' que pode ser o seu editado
            linhas = textwrap.wrap(titulo, width=max(10, limite))
            alt_bloco = (len(linhas) * tam) + ((len(linhas) - 1) * 4)
            if alt_bloco <= 165 and len(linhas) <= 3:
                break
            tam -= 1

        y = 811 - (alt_bloco // 2)
        for lin in linhas:
            bbox = draw.textbbox((0, 0), lin, font=fonte)
            larg_l = bbox[2] - bbox[0]
            draw.text((488 - (larg_l // 2), y), lin, fill="black", font=fonte)
            y += tam + 4
        return fundo.convert("RGB")

    # STORY
    LARG_STORY, ALT_STORY = 940, 541
    ratio_a = LARG_STORY / ALT_STORY
    if prop_o > ratio_a:
        ns_alt = ALT_STORY
        ns_larg = int(ns_alt * prop_o)
    else:
        ns_larg = LARG_STORY
        ns_alt = int(ns_larg / prop_o)

    img_redim = img_original.resize((ns_larg, ns_alt), Image.LANCZOS)
    l_cut = (ns_larg - LARG_STORY) / 2
    t_cut = (ns_alt - ALT_STORY) / 2
    img_final = img_redim.crop((l_cut, t_cut, l_cut + LARG_STORY, t_cut + ALT_STORY))
    
    storie_canvas = Image.new("RGBA", (1080, 1920), (0, 0, 0, 255))
    storie_canvas.paste(img_final, (69, 504))
    aplicar_template_se_existir(storie_canvas, TEMPLATE_STORIE, (1080, 1920))

    draw_s = ImageDraw.Draw(storie_canvas)
    tam_s = 60
    while tam_s > 20:
        fonte_s = ImageFont.truetype(CAMINHO_FONTE, tam_s)
        try: limite_s = int(912 / (fonte_s.getlength("W") * 0.55))
        except: limite_s = 34
        
        # O textwrap do story também usa o seu 'titulo' editado
        linhas_s = textwrap.wrap(titulo, width=max(10, limite_s))
        alt_bloco_s = (len(linhas_s) * tam_s) + (len(linhas_s) * 10)
        if alt_bloco_s <= 300 and len(linhas_s) <= 4:
            break
        tam_s -= 2

    y_s = 1079
    for lin in linhas_s:
        draw_s.text((69, y_s), lin, fill="white", font=fonte_s)
        y_s += tam_s + 12

    return storie_canvas.convert("RGB")

# ============================================================
# 8) BUSCAR ÚLTIMAS (COM CACHE + URL ABSOLUTA)
# ============================================================
@st.cache_data(ttl=120)
def buscar_ultimas():
    try:
        base = "https://www.destaquetoledo.com.br/"
        html = safe_get_text(base)
        soup = BeautifulSoup(html, "html.parser")

        news = []
        for a in soup.find_all("a", href=True):
            href = (a.get("href") or "").strip()
            if ".html" in href and "/20" in href:
                t = a.get_text(strip=True)
                if t and len(t) > 25:
                    news.append({"t": t, "u": urljoin(base, href)})

        seen = set()
        out = []
        for item in news:
            if item["u"] in seen:
                continue
            seen.add(item["u"])
            out.append(item)

        return out[:12]
    except Exception:
        return []

# ============================================================
# 9) LOGIN (VERSÃO OTIMIZADA E MODERNA)
# ============================================================
if "autenticado" not in st.session_state:
    st.session_state.autenticado = False

if not st.session_state.autenticado:
    # Centralização da logo e título com estilo aprimorado
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
        # Trocamos o container por form para habilitar o login com a tecla ENTER
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
            
            # Recurso visual de "Mantenha-me conectado"
            manter_conectado = st.checkbox("Manter-se conectado", value=True)
            
            st.write("") # Espaçador
            
            # Botão de submissão do formulário (detecta o Enter automaticamente)
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

        # Links auxiliares abaixo do card
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
    # 10) INTERFACE INTERNA
    # ============================================================
    # Sistema automático (30 segundos) - Não mexe no layout
    try:
        from streamlit_autorefresh import st_autorefresh
        st_autorefresh(interval=30000, key="refresh_juan")
    except:
        pass

    # Função auxiliar interna para garantir que o título seja carregado para edição
    def obter_titulo_limpo(url):
        try:
            r = requests.get(url, timeout=5)
            s = BeautifulSoup(r.text, 'html.parser')
            t = s.find('title').text
            return t.replace(' - Destaque Toledo', '').strip()
        except:
            return ""

    st.markdown('<div class="topo-titulo"><h1>DESTAQUE TOLEDO</h1></div>', unsafe_allow_html=True)

    if st.session_state.perfil == "juan":
        st.markdown('<div class="boas-vindas">Bem-vindo, Juan!</div>', unsafe_allow_html=True)
        tab1, tab2, tab3 = st.tabs(["🎨 GERADOR DE ARTES", "📝 FILA DO BRAYAN", "📅 AGENDA"])

        with tab1:
            st.markdown(
                '<p class="descricao-aba">Aqui você gera automaticamente os posts para Instagram.</p>',
                unsafe_allow_html=True,
            )
            c1, col_preview = st.columns([1, 2])

            with c1:
                # Cabeçalho com botão de atualizar matérias
                col_t1, col_t2 = st.columns([2, 1])
                with col_t1:
                    st.subheader("📰 Notícias Recentes")
                with col_t2:
                    if st.button("🔄 Atualizar", key="up_artes"):
                        st.cache_data.clear()
                        st.rerun()

                ultimas = buscar_ultimas()
                if not ultimas:
                    st.info("Não foi possível carregar as notícias agora.")
                for i, item in enumerate(ultimas):
                    if st.button(item["t"], key=f"btn_{i}", use_container_width=True):
                        st.session_state.url_atual = item["u"]

            with col_preview:
                url_f = st.text_input("Link da Matéria:", value=st.session_state.get("url_atual", ""))

                # --- PARTE NOVA: CAMPO PARA VOCÊ EDITAR O TÍTULO ---
                if url_f:
                    # Puxa o título automático do site para a caixa de edição
                    titulo_sugerido = obter_titulo_limpo(url_f)
                    
                    # Caixa para editar o texto (mudar frase, dar espaço, etc)
                    titulo_editado = st.text_area("📝 Ajuste o título da arte se desejar:", value=titulo_sugerido, height=100)

                    ca, cb = st.columns(2)

                    if ca.button("🖼️ GERAR FEED", use_container_width=True, type="primary"):
                        try:
                            # Passa o seu texto editado para a arte
                            img = processar_artes_integrado(url_f, "FEED", titulo_personalizado=titulo_editado)
                            st.image(img)

                            buf = io.BytesIO()
                            img.save(buf, "JPEG", quality=95, optimize=True)
                            st.download_button(
                                "📥 BAIXAR FEED",
                                buf.getvalue(),
                                "feed.jpg",
                                use_container_width=True,
                            )
                        except Exception as e:
                            st.error(f"Falha ao gerar FEED: {e}")

                    if cb.button("📱 GERAR STORY", use_container_width=True):
                        try:
                            # Passa o seu texto editado para a arte
                            img = processar_artes_integrado(url_f, "STORY", titulo_personalizado=titulo_editado)
                            st.image(img, width=280)

                            buf = io.BytesIO()
                            img.save(buf, "JPEG", quality=95, optimize=True)
                            st.download_button(
                                "📥 BAIXAR STORY",
                                buf.getvalue(),
                                "story.jpg",
                                use_container_width=True,
                            )
                        except Exception as e:
                            st.error(f"Falha ao gerar STORY: {e}")

        with tab2:
            st.markdown(
                '<p class="descricao-aba">Envie matérias, links ou releases para o Brayan postar.</p>',
                unsafe_allow_html=True,
            )
            with st.form("form_envio_colorido", clear_on_submit=True):
                col_f1, col_f2 = st.columns([3, 1])
                with col_f1:
                    f_titulo = st.text_input("📌 Título da Matéria")
                with col_f2:
                    f_urgencia = st.selectbox("Prioridade", ["Normal", "Programar", "URGENTE"])
                
                f_link = st.text_input("🔗 Link da Matéria (se houver)")
                f_obs = st.text_area("📄 Texto da Matéria / Release", height=200, placeholder="Cole aqui o conteúdo da notícia ou release...")

                if st.form_submit_button("🚀 ENVIAR PARA O BRAYAN", use_container_width=True):
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
                        st.success(f"✅ Matéria enviada para o Brayan!")
                        st.rerun()
                    else:
                        st.warning("Informe ao menos o título.")

            st.markdown("---")
            
            # Cabeçalho com botão de atualizar fila
            col_m_tit, col_m_ref = st.columns([3, 1])
            with col_m_tit:
                st.subheader("👀 Monitor de Status (Tempo Real)")
            with col_m_ref:
                if st.button("🔄 Atualizar Fila", key="up_fila"):
                    st.rerun()
            
            conn = get_conn()
            c = conn.cursor()
            c.execute("SELECT id, titulo, prioridade, data_envio, status FROM pautas_trabalho WHERE status != 'Concluído' ORDER BY id DESC LIMIT 10")
            monitor = c.fetchall()
            conn.close()

            if not monitor:
                st.info("Tudo em dia! Nenhuma postagem pendente.")
            else:
                for p in monitor:
                    if p[4] == "Postando":
                        status_cor = "#fd7e14" # Laranja
                        status_txt = "⚡ POSTANDO AGORA"
                    else:
                        status_cor = "#004a99" # Azul
                        status_txt = "⏳ NA FILA"
                    
                    col_m1, col_m2, col_m3 = st.columns([3, 1, 1])
                    with col_m1:
                        st.markdown(f"**{p[3]}** - {p[1]} <br><small>Prioridade: {p[2]}</small>", unsafe_allow_html=True)
                    with col_m2:
                        st.markdown(f"<p style='color:{status_cor}; font-weight:bold; margin-top:10px;'>{status_txt}</p>", unsafe_allow_html=True)
                    with col_m3:
                        if st.button("Remover", key=f"ex_{p[0]}", use_container_width=True):
                            conn = get_conn()
                            c = conn.cursor()
                            c.execute("DELETE FROM pautas_trabalho WHERE id=?", (p[0],))
                            conn.commit()
                            conn.close()
                            st.rerun()

        # ============================================================
        # 📅 ABA AGENDA - PADRÃO BRASILEIRO EM TUDO
        # ============================================================
        with tab3:
            conn = get_conn()
            c = conn.cursor()
            hoje_dt = (datetime.utcnow() - timedelta(hours=3)).date()
            hoje_str = hoje_dt.strftime("%Y-%m-%d")

            # 1) LIMPEZA AUTOMÁTICA
            c.execute("DELETE FROM agenda_itens WHERE status = 'Concluído' AND data_ref < ?", (hoje_str,))
            conn.commit()

            # 2) CABEÇALHO COMPACTO
            col_tit, col_btn = st.columns([3, 1])
            with col_tit:
                st.markdown("### 📋 Cronograma")
            with col_btn:
                with st.popover("➕ AGENDAR", use_container_width=True):
                    with st.form("form_novo_v2", clear_on_submit=True):
                        st.markdown("##### Novo Compromisso")
                        ntit = st.text_input("O que fazer?")
                        ndes = st.text_area("Observações")
                        # PADRÃO BR AQUI
                        ndat = st.date_input("Data", value=hoje_dt, format="DD/MM/YYYY")
                        if st.form_submit_button("🚀 SALVAR", use_container_width=True):
                            if ntit:
                                agora = (datetime.utcnow() - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M")
                                c.execute("INSERT INTO agenda_itens (data_ref, titulo, descricao, status, criado_por, criado_em) VALUES (?, ?, ?, ?, ?, ?)",
                                    (ndat.strftime("%Y-%m-%d"), ntit, ndes, "Pendente", st.session_state.perfil, agora))
                                conn.commit(); st.rerun()

            # 3) FILTRO
            opcao_filtro = st.selectbox("Período:", ["Próximos 7 dias", "Próximos 15 dias", "Próximos 30 dias", "Tudo"], label_visibility="collapsed")
            dias_map = {"7": 7, "15": 15, "30": 30, "Tudo": 365}
            dias_limite = dias_map.get(opcao_filtro.split()[1] if " " in opcao_filtro else "Tudo", 7)
            data_limite_filtro = (hoje_dt + timedelta(days=dias_limite)).strftime("%Y-%m-%d")

            # 4) BUSCA
            c.execute("""SELECT id, data_ref, titulo, descricao, status, criado_por FROM agenda_itens 
                         WHERE (data_ref BETWEEN ? AND ?) OR (status = 'Pendente' AND data_ref < ?)
                         ORDER BY status DESC, data_ref ASC""", (hoje_str, data_limite_filtro, hoje_str))
            itens = c.fetchall()

            if not itens:
                st.info("✨ Nada agendado.")
            else:
                dias_semana = ["Segunda-feira", "Terça-feira", "Quarta-feira", "Quinta-feira", "Sexta-feira", "Sábado", "Domingo"]
                cols = st.columns(3)
                
                for idx, (tid, data_ref, titulo, descricao, status, criado_por) in enumerate(itens):
                    dt_obj = datetime.strptime(data_ref, "%Y-%m-%d").date()
                    dia_nome = dias_semana[dt_obj.weekday()]
                    
                    if status == "Concluído": cor, fundo = "#198754", "#f1fff6"
                    elif dt_obj < hoje_dt: cor, fundo = "#dc3545", "#fff5f5"
                    elif dt_obj == hoje_dt: cor, fundo = "#ffc107", "#fffdf5"
                    else: cor, fundo = "#0d6efd", "#f3f7ff"

                    with cols[idx % 3]:
                        html_desc = f'<div style="font-size:0.75rem; color:#555; margin-top:4px; font-style: italic;">{(descricao[:40] + "...") if len(descricao) > 40 else descricao}</div>' if descricao else ""
                        
                        st.markdown(f"""
                            <div style="background:{fundo}; padding:10px 12px; border-radius:10px; border-top:4px solid {cor}; box-shadow:0 2px 5px rgba(0,0,0,0.05); margin-bottom:8px;">
                                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:2px;">
                                    <b style="color:{cor}; font-size:0.7rem;">{dt_obj.strftime('%d/%m/%Y')}</b>
                                    <span style="font-size:0.55rem; color:#888; font-weight:bold;">{dia_nome.upper()}</span>
                                </div>
                                <div style="font-weight:800; font-size:0.85rem; color:#111; text-transform: uppercase; line-height:1.1;">{titulo.upper()}</div>
                                {html_desc}
                            </div>
                        """, unsafe_allow_html=True)
                        
                        b1, b2, b3 = st.columns([1, 1, 0.7])
                        with b1:
                            if st.button("✅" if status == "Pendente" else "↩️", key=f"ok_{tid}", use_container_width=True):
                                c.execute("UPDATE agenda_itens SET status=? WHERE id=?", ("Concluído" if status == "Pendente" else "Pendente", tid))
                                conn.commit(); st.rerun()
                        with b2:
                            with st.popover("📝", use_container_width=True):
                                with st.form(f"ed_{tid}"):
                                    nt = st.text_input("Título", value=titulo.upper())
                                    # CORREÇÃO DO PADRÃO DE DATA NO EDITAR AQUI
                                    nd = st.date_input("Data", value=dt_obj, format="DD/MM/YYYY")
                                    ns = st.text_area("Obs", value=descricao if descricao else "")
                                    if st.form_submit_button("Salvar"):
                                        c.execute("UPDATE agenda_itens SET titulo=?, data_ref=?, descricao=? WHERE id=?", (nt, nd.strftime("%Y-%m-%d"), ns, tid))
                                        conn.commit(); st.rerun()
                                    if st.form_submit_button("🗑️ Excluir"):
                                        c.execute("DELETE FROM agenda_itens WHERE id=?", (tid,))
                                        conn.commit(); st.rerun()
                        with b3:
                            if descricao:
                                with st.popover("ℹ️", use_container_width=True):
                                    st.write(descricao)
                            else:
                                st.button("ℹ️", key=f"no_d_{tid}", disabled=True, use_container_width=True)
            conn.close()

    else:
        # ============================================================
        # BRAYAN OS - DASHBOARD PREMIUM (TECH STYLE)
        # ============================================================
        
        conn = get_conn()
        c = conn.cursor()
        hoje_dt = (datetime.utcnow() - timedelta(hours=3)).date()
        hoje_str = hoje_dt.strftime("%Y-%m-%d")
        dias_semana = ["Segunda-feira", "Terça-feira", "Quarta-feira", "Quinta-feira", "Sexta-feira", "Sábado", "Domingo"]

        # CSS Original Preservado
        st.markdown("""
            <style>
                .stApp { background-color: #f4f7fb; }
                .kpi-card {
                    background: white; padding: 25px; border-radius: 24px;
                    box-shadow: 0 10px 30px rgba(0, 74, 153, 0.05);
                    text-align: center; border: 1px solid #ffffff;
                }
                .kpi-num { font-size: 2.2rem; font-weight: 800; color: #004a99; margin-bottom: 5px; }
                .kpi-lab { font-size: 0.85rem; color: #8898aa; font-weight: 600; text-transform: uppercase; letter-spacing: 1px; }
                .glass-card {
                    background: white; border-radius: 20px; padding: 20px;
                    border: 1px solid #e9ecef; box-shadow: 0 4px 12px rgba(0,0,0,0.03);
                    margin-bottom: 15px;
                }
                .prio-tag {
                    padding: 5px 14px; border-radius: 10px; font-size: 0.7rem;
                    font-weight: 800; text-transform: uppercase;
                }
            </style>
        """, unsafe_allow_html=True)

        # HEADER
        col_h1, col_h2 = st.columns([2, 1])
        with col_h1:
            st.markdown(f"<h1 style='margin-bottom:0;'>Controle de Operações</h1>", unsafe_allow_html=True)
            st.markdown(f"<p style='color:#666; font-size:1.1rem;'>Bem-vindo, <b>Brayan</b>. Status do sistema: <span style='color:green;'>● Online</span></p>", unsafe_allow_html=True)
        
        # KPIs
        c.execute("SELECT COUNT(*) FROM pautas_trabalho WHERE status != 'Concluído'")
        pautas_ativas = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM agenda_itens WHERE status = 'Pendente' AND criado_por = 'brayan'")
        agenda_trabalho = c.fetchone()[0]

        k1, k2 = st.columns(2)
        with k1:
            st.markdown(f'<div class="kpi-card"><div class="kpi-num">{pautas_ativas}</div><div class="kpi-lab">Fila de Postagem</div></div>', unsafe_allow_html=True)
        with k2:
            st.markdown(f'<div class="kpi-card"><div class="kpi-num">{agenda_trabalho}</div><div class="kpi-lab">Tarefas Agenda</div></div>', unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)
        t_work, t_agenda, t_pessoal, t_add = st.tabs(["🚀 FLUXO OPERACIONAL", "📅 CRONOGRAMA", "🏠 VIDA PESSOAL", "➕ NOVO"])

        # --- ABA 1: TRABALHO (CORREÇÃO DE CLIQUE ÚNICO) ---
        with t_work:
            c.execute("""
                SELECT id, titulo, link_ref, prioridade, data_envio, observacao, status 
                FROM pautas_trabalho WHERE status != 'Concluído' 
                ORDER BY CASE WHEN prioridade = 'URGENTE' THEN 1 WHEN prioridade = 'Normal' THEN 2 ELSE 3 END ASC, id DESC
            """)
            items = c.fetchall()
            if not items:
                st.info("✨ Sistema limpo. Sem pautas pendentes.")
            for id_p, tit, link, prio, hora, obs, stat in items:
                cor_p = "#ff4b4b" if prio == "URGENTE" else ("#ffa500" if prio == "Programar" else "#007bff")
                bg_p = "rgba(255, 75, 75, 0.1)" if prio == "URGENTE" else "rgba(0, 123, 255, 0.1)"
                st.markdown(f"""
                    <div class="glass-card">
                        <div style="display: flex; justify-content: space-between; align-items: center;">
                            <span class="prio-tag" style="background:{bg_p}; color:{cor_p};">{prio}</span>
                            <span style="font-size:0.8rem; color:#999; font-weight:600;">📦 ID: {id_p} | 🕒 {hora}</span>
                        </div>
                        <h4 style="margin: 15px 0 10px 0; color:#111; font-size:1.25rem;">{tit}</h4>
                    </div>
                """, unsafe_allow_html=True)
                
                c1, c2, c3 = st.columns([1, 1, 2])
                with c1:
                    # Usamos uma chave única e removemos o excesso de lógica que trava o clique
                    if st.button("🚀 INICIAR", key=f"btn_go_{id_p}", use_container_width=True, type="primary"):
                        if link and "http" in link:
                            # O segredo: Abrir o link e DEPOIS atualizar o banco
                            st.components.v1.html(f"""
                                <script>
                                    window.open('{link}', '_blank');
                                </script>
                            """, height=0)
                            
                            # Atualiza status silenciosamente
                            c.execute("UPDATE pautas_trabalho SET status='Postando' WHERE id=?", (id_p,))
                            conn.commit()
                            # Aguarda um milissegundo antes do rerun para o JS processar a janela
                            st.rerun()
                        else:
                            st.error("Link inválido")
                        
                with c2:
                    if st.button("✅ FEITO", key=f"ok_{id_p}", use_container_width=True):
                        c.execute("UPDATE pautas_trabalho SET status='Concluído' WHERE id=?", (id_p,))
                        conn.commit(); st.rerun()
                with c3:
                    if obs:
                        with st.expander("📄 Ver Conteúdo"): st.write(obs)

        # --- ABA 2: CRONOGRAMA TRABALHO (CORRIGIDO PARA PUXAR TUDO) ---
        with t_agenda:
            col_tit, col_fil = st.columns([2, 1])
            with col_tit: st.markdown("### 📅 Cronograma de Trabalho")
            with col_fil: 
                f_w = st.selectbox("Período:", ["7 dias", "15 dias", "30 dias", "Tudo"], key="f_work", label_visibility="collapsed")
            
            # Define o limite de dias conforme o filtro
            d_lim = {"7 dias": 7, "15 dias": 15, "30 dias": 30, "Tudo": 9999}.get(f_w, 7)
            dt_lim_str = (hoje_dt + timedelta(days=d_lim)).strftime("%Y-%m-%d")

            # SQL CORRIGIDO: Puxa tudo que está atrasado (independente do filtro) OU dentro do limite de dias
            c.execute("""SELECT id, data_ref, titulo, descricao FROM agenda_itens 
                         WHERE status = 'Pendente' AND criado_por = 'brayan' 
                         AND (data_ref < ? OR data_ref <= ?) 
                         ORDER BY data_ref ASC""", (hoje_str, dt_lim_str))
            
            itens_work = c.fetchall()
            if not itens_work:
                st.write("✨ Nenhuma atividade de trabalho pendente.")
            else:
                cols = st.columns(3)
                for idx, (tid, data, t, d) in enumerate(itens_work):
                    dt = datetime.strptime(data, "%Y-%m-%d").date()
                    dia_n = dias_semana[dt.weekday()]
                    
                    if dt < hoje_dt: cor, fundo = "#dc3545", "#fff5f5"      # Atrasado
                    elif dt == hoje_dt: cor, fundo = "#ffc107", "#fffdf5"   # Hoje
                    else: cor, fundo = "#004a99", "white"                   # Futuro

                    with cols[idx % 3]:
                        html_d = f'<div style="font-size:0.75rem; color:#555; margin-top:4px; font-style: italic;">{(d[:40] + "...") if len(d) > 40 else d}</div>' if d else ""
                        st.markdown(f"""
                            <div style="background:{fundo}; padding:10px 12px; border-radius:12px; border-top:5px solid {cor}; box-shadow:0 2px 8px rgba(0,0,0,0.05); margin-bottom:8px;">
                                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:2px;">
                                    <b style="color:{cor}; font-size:0.7rem;">{dt.strftime('%d/%m/%Y')}</b>
                                    <span style="font-size:0.55rem; color:#888; font-weight:bold;">{dia_n.upper()}</span>
                                </div>
                                <div style="font-weight:800; font-size:0.85rem; color:#111; text-transform: uppercase; line-height:1.1;">{t.upper()}</div>
                                {html_d}
                            </div>
                        """, unsafe_allow_html=True)
                        
                        btn_c1, btn_c2, btn_c3 = st.columns([1, 1, 0.7])
                        with btn_c1:
                            if st.button("✅", key=f"at_{tid}", use_container_width=True):
                                c.execute("UPDATE agenda_itens SET status='Concluído' WHERE id=?", (tid,))
                                conn.commit(); st.rerun()
                        with btn_c2:
                            with st.popover("📝", use_container_width=True):
                                with st.form(f"f_ed_w_{tid}"):
                                    nt = st.text_input("Título", value=t.upper())
                                    nd = st.date_input("Data", value=dt, format="DD/MM/YYYY")
                                    ns = st.text_area("Obs", value=d if d else "")
                                    if st.form_submit_button("Salvar"):
                                        c.execute("UPDATE agenda_itens SET titulo=?, data_ref=?, descricao=? WHERE id=?", (nt, nd.strftime("%Y-%m-%d"), ns, tid))
                                        conn.commit(); st.rerun()
                        with btn_c3:
                            if d:
                                with st.popover("ℹ️", use_container_width=True): st.write(d)
                            else:
                                st.button("ℹ️", key=f"no_dw_{tid}", disabled=True, use_container_width=True)

        # --- ABA 3: VIDA PESSOAL (CORRIGIDO PARA PUXAR TUDO) ---
        with t_pessoal:
            col_titp, col_filp = st.columns([2, 1])
            with col_titp: st.markdown("### 🏠 Agenda Pessoal")
            with col_filp: 
                f_p = st.selectbox("Período:", ["7 dias", "15 dias", "30 dias", "Tudo"], key="f_pess", label_visibility="collapsed")
            
            d_limp = {"7 dias": 7, "15 dias": 15, "30 dias": 30, "Tudo": 9999}.get(f_p, 7)
            dt_limp_str = (hoje_dt + timedelta(days=d_limp)).strftime("%Y-%m-%d")

            # SQL CORRIGIDO: Puxa tudo que está atrasado OU dentro do limite de dias
            c.execute("""SELECT id, data_ref, titulo, descricao FROM agenda_itens 
                         WHERE status = 'Pendente' AND criado_por = 'brayan_pessoal' 
                         AND (data_ref < ? OR data_ref <= ?) 
                         ORDER BY data_ref ASC""", (hoje_str, dt_limp_str))
            
            itens_pess = c.fetchall()
            if not itens_pess:
                st.info("✨ Vida pessoal organizada no período.")
            else:
                cols_p = st.columns(3)
                for idx, (tid, data, t, d) in enumerate(itens_pess):
                    dt_p = datetime.strptime(data, "%Y-%m-%d").date()
                    dia_p = dias_semana[dt_p.weekday()]

                    if dt_p < hoje_dt: cor_p, fundo_p = "#dc3545", "#fff5f5"
                    elif dt_p == hoje_dt: cor_p, fundo_p = "#ffc107", "#fffdf5"
                    else: cor_p, fundo_p = "#6f42c1", "#f9f5ff"

                    with cols_p[idx % 3]:
                        html_dp = f'<div style="font-size:0.75rem; color:#555; margin-top:4px; font-style: italic;">{(d[:40] + "...") if len(d) > 40 else d}</div>' if d else ""
                        st.markdown(f"""
                            <div style="background:{fundo_p}; padding: 10px 12px; border-radius: 12px; border-top: 5px solid {cor_p}; box-shadow:0 2px 8px rgba(0,0,0,0.05); margin-bottom: 8px;">
                                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:2px;">
                                    <b style="color:{cor_p}; font-size:0.7rem;">{dt_p.strftime('%d/%m/%Y')}</b>
                                    <span style="font-size:0.55rem; color:#888; font-weight:bold;">{dia_p.upper()}</span>
                                </div>
                                <div style="font-weight:800; font-size:0.85rem; color:#333; text-transform: uppercase; line-height:1.1;">{t.upper()}</div>
                                {html_dp}
                            </div>
                        """, unsafe_allow_html=True)
                        
                        btn_p1, btn_p2, btn_p3 = st.columns([1, 1, 0.7])
                        with btn_p1:
                            if st.button("✅", key=f"ps_ok_{tid}", use_container_width=True):
                                c.execute("UPDATE agenda_itens SET status='Concluído' WHERE id=?", (tid,))
                                conn.commit(); st.rerun()
                        with btn_p2:
                            with st.popover("📝", use_container_width=True):
                                with st.form(f"f_ed_p_{tid}"):
                                    nt = st.text_input("Título", value=t.upper())
                                    nd = st.date_input("Data", value=dt_p, format="DD/MM/YYYY")
                                    ns = st.text_area("Obs", value=d if d else "")
                                    if st.form_submit_button("Salvar"):
                                        c.execute("UPDATE agenda_itens SET titulo=?, data_ref=?, descricao=? WHERE id=?", (nt, nd.strftime("%Y-%m-%d"), ns, tid))
                                        conn.commit(); st.rerun()
                        with btn_p3:
                            if d:
                                with st.popover("ℹ️", use_container_width=True): st.write(d)
                            else:
                                st.button("ℹ️", key=f"no_dp_{tid}", disabled=True, use_container_width=True)

        # --- ABA 4: NOVO (PRESERVADA) ---
        with t_add:
            st.markdown("### ➕ Nova Entrada")
            tipo = st.segmented_control("Onde cadastrar?", ["Trabalho", "Vida Pessoal"], default="Trabalho")
            with st.form("form_novo_dash", clear_on_submit=True):
                v_tit = st.text_input("Título / O que fazer?")
                v_des = st.text_area("Notas extras (opcional)")
                v_dat = st.date_input("Data", value=hoje_dt, format="DD/MM/YYYY")
                if st.form_submit_button("🚀 SALVAR NO SISTEMA", use_container_width=True):
                    if v_tit:
                        autor = "brayan" if tipo == "Trabalho" else "brayan_pessoal"
                        agora = (datetime.utcnow() - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M")
                        c.execute("INSERT INTO agenda_itens (data_ref, titulo, descricao, status, criado_por, criado_em) VALUES (?, ?, ?, ?, ?, ?)",
                                 (v_dat.strftime("%Y-%m-%d"), v_tit, v_des, "Pendente", autor, agora))
                        conn.commit(); st.success("Registrado!"); st.rerun()

        conn.close()

    # ============================================================
    # SIDEBAR
    # ============================================================
    with st.sidebar:
        st.write(f"Logado como: **{st.session_state.perfil.upper()}**")
        if st.button("🚪 Sair do Sistema", use_container_width=True):
            st.session_state.autenticado = False
            st.rerun()





















































