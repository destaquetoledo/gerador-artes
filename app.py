import streamlit as st
import requests
import pdfplumber
import io
import pandas as pd
from datetime import datetime
import re

# Configuração da Página
st.set_page_config(page_title="Painel Destaque Toledo", page_icon="🚨", layout="wide")

# === CONFIGURAÇÕES FIXAS ===
TOKEN = "7627971029:AAHRlLMFyP9f9gxr2dP40AiUfWLip85XDpA"
CHAT_ID = "1982853012"
URL_BASE = "https://gmtoledo.cconet.com.br/impressao/completo?id="

# === FUNÇÕES DE APOIO ===
def extrair_campo(texto, rotulo):
    padrao = rf"{rotulo}\s*[:\-]?\s*(.*?)(?=(?:Data/Hora|Bairro|Endereço|Nº|Cidade|Descrição|Equipe|Solicitante)|$)"
    match = re.search(padrao, texto, re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).replace('\n', ' ').strip()
    return "Não informado"

def processar_pdf(conteudo_pdf):
    try:
        with pdfplumber.open(io.BytesIO(conteudo_pdf)) as pdf:
            texto = " ".join(pdf.pages[0].extract_text().split())
            return {
                "data_hora": extrair_campo(texto, "Data/Hora Inicial"),
                "bairro": extrair_campo(texto, "Bairro"),
                "rua": extrair_campo(texto, "Endereço"),
                "num": extrair_campo(texto, "Nº"),
                "cidade": extrair_campo(texto, "Cidade"),
                "descricao": extrair_campo(texto, "Descrição")
            }
    except:
        return None

def enviar_telegram(id_bo, dados):
    msg = (
        f"━━━━━ 🚨 <b>PLANTÃO STREAMLIT</b> ━━━━━\n\n"
        f"📅 <b>DATA/HORA:</b> {dados['data_hora']}\n"
        f"🏘️ <b>BAIRRO:</b> {dados['bairro']}\n"
        f"🏠 <b>ENDEREÇO:</b> {dados['rua']}, {dados['num']}\n"
        f"🏙️ <b>CIDADE:</b> {dados['cidade']}\n\n"
        f"📝 <b>RESUMO:</b>\n<i>{dados['descricao'][:300]}...</i>"
    )
    payload = {"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"}
    requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", json=payload)

# === INTERFACE STREAMLIT ===
st.title("🚨 Sistema de Inteligência - Destaque Toledo")
st.markdown("---")

# Barra Lateral
st.sidebar.header("Configurações de Varredura")
id_partida = st.sidebar.number_input("ID Inicial", value=60289)
quantidade = st.sidebar.slider("Quantidade de BOs para checar", 1, 50, 10)

if st.sidebar.button("🔍 Iniciar Varredura Manual"):
    resultados = []
    progresso = st.progress(0)
    
    for i, id_atual in enumerate(range(id_partida, id_partida + quantidade)):
        status_text = st.empty()
        status_text.text(f"Checando BO: {id_atual}...")
        
        try:
            res = requests.get(f"{URL_BASE}{id_atual}", timeout=10)
            if res.status_code == 200 and res.content.startswith(b"%PDF"):
                dados = processar_pdf(res.content)
                if dados:
                    dados['id'] = id_atual
                    resultados.append(dados)
                    st.success(f"✅ BO {id_atual} encontrado: {dados['bairro']}")
            
        except Exception as e:
            st.error(f"Erro no ID {id_atual}: {e}")
        
        progresso.progress((i + 1) / quantidade)
    
    if resultados:
        st.subheader("📋 Ocorrências Encontradas")
        df = pd.DataFrame(resultados)
        st.dataframe(df[['id', 'data_hora', 'bairro', 'rua', 'descricao']])
        
        if st.button("📤 Enviar tudo para o Telegram"):
            for r in resultados:
                enviar_telegram(r['id'], r)
            st.toast("Enviado com sucesso!")
    else:
        st.warning("Nenhuma ocorrência nova encontrada nesta faixa.")

# Seção de Busca Rápida
st.sidebar.markdown("---")
st.sidebar.header("Busca Rápida por ID")
id_unico = st.sidebar.text_input("Digite o ID do BO")
if st.sidebar.button("Visualizar BO"):
    if id_unico:
        st.info(f"Buscando informações do BO {id_unico}...")
        res = requests.get(f"{URL_BASE}{id_unico}")
        if res.status_code == 200:
            dados = processar_pdf(res.content)
            if dados:
                col1, col2 = st.columns(2)
                with col1:
                    st.metric("Bairro", dados['bairro'])
                    st.write(f"**Rua:** {dados['rua']}, {dados['num']}")
                with col2:
                    st.write(f"**Data:** {dados['data_hora']}")
                    st.write(f"**Cidade:** {dados['cidade']}")
                st.text_area("Descrição Completa", dados['descricao'], height=200)
                st.link_button("📄 Abrir PDF Original", f"{URL_BASE}{id_unico}")
            else:
                st.error("Não foi possível ler o texto deste PDF.")
        else:
            st.error("BO não encontrado.")
