import os
import io
import time
import sqlite3
import requests
import threading
from datetime import datetime
import pdfplumber
from bs4 import BeautifulSoup
from flask import Flask

# ============================================================
# 1) MINI SERVIDOR PARA O RENDER NÃO DESLIGAR (HEALTH CHECK)
# ============================================================
app = Flask('MonitorToledo')

@app.route('/')
def home():
    return "Monitores GM e Bombeiros Ativos e Vigiando!"

# ============================================================
# 2) CONFIGURAÇÕES GERAIS E PARAMETROS
# ============================================================
# Credenciais unificadas (conforme seus scripts)
TELEGRAM_BOT_TOKEN = "7627971029:AAHRlLMFyP9f9gxr2dP40AiUfWLip85XDpA"
TELEGRAM_CHAT_ID = "1982853012"

# Caminhos de dados
ARQUIVO_ID_GM = "ultimo_id.txt"
SQLITE_PATH_BM = "/opt/render/project/src/sysbm_toledo.db"

# Endpoints de busca
URL_BASE_GM = "https://gmtoledo.cconet.com.br/impressao/completo?id="
URL_TOLEDO_BM = "https://toledonews.com.br/bombeiros/bombeiros_lista.php"

# Intervalos de varredura (em segundos)
INTERVALO_BM = 45

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

# ============================================================
# 3) FUNÇÕES DE SUPORTE - GUARDA MUNICIPAL (GM)
# ============================================================
def salvar_ultimo_id_gm(id_bo):
    with open(ARQUIVO_ID_GM, "w") as f:
        f.write(str(id_bo))

def ler_ultimo_id_gm():
    if os.path.exists(ARQUIVO_ID_GM):
        with open(ARQUIVO_ID_GM, "r") as f:
            try:
                return int(f.read().strip())
            except:
                return None
    return None

def buscar_valor_pdf(texto, inicio, fins):
    if inicio not in texto: 
        return "Não informado"
    parte = texto.split(inicio)[1]
    for fim in fins:
        if fim in parte:
            parte = parte.split(fim)[0]
    return parte.replace(":", "").strip()

def enviar_telegram_gm(id_bo, conteudo_pdf):
    try:
        with pdfplumber.open(io.BytesIO(conteudo_pdf)) as pdf:
            texto = pdf.pages[0].extract_text()
    except Exception as e:
        log(f"Erro ao extrair PDF do BO {id_bo}: {e}")
        return False

    # Travas de segurança para evitar vazamento de dados pessoais
    travas = ["Solicitante", "Telefone", "Dados", "Apoio", "Próprio", "Bairro", "Endereço", "Cidade"]
    
    data_bruta = buscar_valor_pdf(texto, "Data/Hora Inicial:", ["Data/Hora Final", "Origem"])
    data_hora = data_bruta.replace("\n", " ").strip()
    
    bairro = buscar_valor_pdf(texto, "Bairro:", travas)
    rua = buscar_valor_pdf(texto, "Endereço:", travas + ["Nº"])
    num = buscar_valor_pdf(texto, "Nº:", ["Compl", "Cidade", "Solicitante"])
    cidade = buscar_valor_pdf(texto, "Cidade:", ["Transversal", "Solicitante"])
    descricao = buscar_valor_pdf(texto, "Descrição:", ["Endereço", "Bairro", "Solicitante", "Dados"])

    msg = (
        f"━━━━━━━  <b>OCORRÊNCIA GM</b>  ━━━━━━━\n\n"
        f"📅 <b>DATA/HORA:</b> {data_hora}\n"
        f"🏘️ <b>BAIRRO:</b> {bairro}\n"
        f"🏠 <b>ENDEREÇO:</b> {rua}, {num}\n"
        f"🏙️ <b>CIDADE:</b> {cidade}\n\n"
        f"📝 <b>DESCRIÇÃO:</b>\n<i>{descricao}</i>"
    )
    
    endereco_completo = f"{rua}, {num} - {bairro}, {cidade} - PR"
    maps_url = f"https://www.google.com/maps/search/?api=1&query={endereco_completo.replace(' ', '+')}"
    
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": msg,
        "parse_mode": "HTML",
        "reply_markup": {
            "inline_keyboard": [[
                {"text": "📍 VER NO MAPA", "url": maps_url},
                {"text": "📄 BO COMPLETO", "url": f"{URL_BASE_GM}{id_bo}"}
            ]]
        }
    }
    
    try:
        res = requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", json=payload, timeout=15)
        return res.status_code == 200
    except Exception as e:
        log(f"Erro ao enviar Telegram GM: {e}")
        return False

# ============================================================
# 4) FUNÇÕES DE SUPORTE - BOMBEIROS (BM)
# ============================================================
def enviar_telegram_bm(message, endereco):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        maps_url = f"https://www.google.com/maps/search/?api=1&query={endereco.replace(' ', '+')}+Toledo+PR"
        
        data = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "Markdown",  
            "reply_markup": {
                "inline_keyboard": [[{"text": "📍 VER LOCALIZAÇÃO NO MAPA", "url": maps_url}]]
            }
        }
        requests.post(url, json=data, timeout=15)
    except Exception as e:
        log(f"Erro ao enviar Telegram Bombeiros: {e}")

def coletar_ocorrencias_bombeiros():
    lista_final = []
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        resp = requests.get(URL_TOLEDO_BM, headers=headers, timeout=20)
        soup = BeautifulSoup(resp.text, "html.parser")
        tabela = soup.find("table", {"class": "scGridTabela"})
        if not tabela: 
            return lista_final

        linhas = tabela.find_all("tr", class_=["scGridFieldOdd", "scGridFieldEven"])
        for linha in linhas:
            cols = linha.find_all("td")
            if len(cols) >= 7:
                if "TOLEDO" in cols[4].text.strip().upper():
                    lista_final.append({
                        "id": cols[1].text.strip(),
                        "data": cols[3].text.strip().replace('\n', ' '),
                        "natureza": cols[6].text.strip(),
                        "endereco": cols[5].text.strip()
                    })
    except Exception as e:
        log(f"Erro na varredura do site dos Bombeiros: {e}")
    return lista_final

# ============================================================
# 5) THREADS DE MONITORAMENTO EM SEGUNDO PLANO
# ============================================================
def loop_monitoramento_gm():
    proximo_bo = ler_ultimo_id_gm()
    if proximo_bo is None:
        id_env = os.environ.get("START_ID")
        proximo_bo = int(id_env) if id_env else 62586
        salvar_ultimo_id_gm(proximo_bo)

    log(f"🚀 [GM] Monitor iniciado a partir do BO: {proximo_bo}")

    while True:
        try:
            headers = {'User-Agent': 'Mozilla/5.0'}
            res = requests.get(f"{URL_BASE_GM}{proximo_bo}", headers=headers, timeout=20)

            if res.status_code == 200 and res.content.startswith(b"%PDF"):
                log(f"🔔 [GM] Ocorrência {proximo_bo} detectada! Enviando...")
                if enviar_telegram_gm(proximo_bo, res.content):
                    proximo_bo += 1
                    salvar_ultimo_id_gm(proximo_bo)
                    time.sleep(2)
            else:
                # Símbolo de atividade no console do Render para acompanhar o bot ativo
                print(".", end="", flush=True)
                time.sleep(30)

        except Exception as e:
            log(f"❌ [GM] Erro no loop: {e}")
            time.sleep(60)

def loop_monitoramento_bombeiros():
    # Criação do diretório de banco caso não exista (importante para o Render)
    dir_db = os.path.dirname(SQLITE_PATH_BM)
    if dir_db and not os.path.exists(dir_db):
        os.makedirs(dir_db, exist_ok=True)

    conn = sqlite3.connect(SQLITE_PATH_BM)
    cursor = conn.cursor()
    cursor.execute('CREATE TABLE IF NOT EXISTS ocorrencias (id TEXT PRIMARY KEY, datahora TEXT, natureza TEXT, endereco TEXT)')
    conn.commit()

    log("🚀 [BOMBEIROS] Monitor Toledo News iniciado")
    
    cursor.execute('SELECT id FROM ocorrencias')
    ultima_ids = set(row[0] for row in cursor.fetchall())

    while True:
        try:
            dados = coletar_ocorrencias_bombeiros()
            for o in reversed(dados):
                if o['id'] not in ultima_ids:
                    cursor.execute('INSERT OR IGNORE INTO ocorrencias VALUES (?,?,?,?)', (o['id'], o['data'], o['natureza'], o['endereco']))
                    conn.commit()
                    
                    data_bruta = o['data'].strip()
                    if len(data_bruta) >= 14 and data_bruta[10].isdigit():
                        data_formatada = f"{data_bruta[:10]} às {data_bruta[10:]}"
                    else:
                        data_formatada = data_bruta

                    relatorio = (
                        f"*━━━━━━━  OCORRÊNCIA BOMBEIROS  ━━━━━━━*\n\n"
                        f"*📅 DATA/HORA:* {data_formatada}\n"
                        f"*🏠 ENDEREÇO:* {o['endereco'].upper().strip()}\n"
                        f"*🏙️ CIDADE:* TOLEDO\n\n"
                        f"*📝 DESCRIÇÃO:*\n"
                        f"_O Corpo de Bombeiros foi acionado para prestar atendimento a uma situação classificada como: {o['natureza'].upper().strip()}. "
                        f"Equipes de resgate e salvamento operacionais mobilizadas para o endereço informado para controle e suporte da ocorrência._"
                    )
                    
                    enviar_telegram_bm(relatorio, o['endereco'])
                    ultima_ids.add(o['id'])
            
            time.sleep(INTERVALO_BM)
        except Exception as e:
            log(f"❌ [BOMBEIROS] Erro no loop: {e}")
            time.sleep(60)

# ============================================================
# 6) EXECUÇÃO PRINCIPAL
# ============================================================
if __name__ == "__main__":
    # Inicia o monitor da Guarda Municipal em segundo plano
    t_gm = threading.Thread(target=loop_monitoramento_gm)
    t_gm.daemon = True
    t_gm.start()
    
    # Inicia o monitor do Corpo de Bombeiros em segundo plano
    t_bm = threading.Thread(target=loop_monitoramento_bombeiros)
    t_bm.daemon = True
    t_bm.start()
    
    # Executa o servidor Flask do Health Check na porta do Render
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
