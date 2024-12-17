import os
import textwrap
import google.generativeai as genai
import streamlit as st
import PyPDF2
import requests
from bs4 import BeautifulSoup
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound
import re

# Configuração da chave da API
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')

if not GOOGLE_API_KEY:
    st.error("Erro: A variável de ambiente GOOGLE_API_KEY não está definida.")
    st.stop()

genai.configure(api_key=GOOGLE_API_KEY)

# Configuração do modelo
try:
    model = genai.GenerativeModel('gemini-1.5-pro')
except Exception as e:
    st.error(f"Erro ao configurar o modelo: {e}")
    st.stop()

# Inicialização da sessão
if "messages" not in st.session_state:
    st.session_state.messages = []
if "knowledge_base" not in st.session_state:
    st.session_state.knowledge_base = ""

# Funções para processar diferentes tipos de conteúdo
def process_pdf(pdf_file):
    pdf_reader = PyPDF2.PdfReader(pdf_file)
    text = ""
    for page in pdf_reader.pages:
        text += page.extract_text() + "\n"
    return text

def process_text(text_file):
    return text_file.getvalue().decode("utf-8")

def process_website(url):
    response = requests.get(url)
    soup = BeautifulSoup(response.content, 'html.parser')
    return soup.get_text()

def process_youtube(url, auth_cookie=None):
    try:
        video_id_match = re.search(r'(?:v=|\/)([0-9A-Za-z_-]{11}).*', url)
        if not video_id_match:
            return "Erro: URL do YouTube inválida."
        video_id = video_id_match.group(1)
        
        options = {}
        if auth_cookie:
            options['cookies'] = {'VISITOR_INFO1_LIVE': auth_cookie}

        try:
            transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=['pt'], **options)
        except NoTranscriptFound:
            transcript = YouTubeTranscriptApi.list_transcripts(video_id, **options).find_transcript(['pt-BR', 'pt'])
        
        processed_text = ""
        chunk_size = 1000
        for i in range(0, len(transcript), chunk_size):
            chunk = transcript[i:i+chunk_size]
            processed_text += " ".join([entry['text'] for entry in chunk]) + " "
        
        return processed_text.strip()
    except TranscriptsDisabled:
        return "As transcrições estão desativadas para este vídeo."
    except Exception as e:
        return f"Erro ao processar o vídeo do YouTube: {str(e)}"

def summarize_content(content, max_tokens=1000):
    try:
        summary = model.generate_content(
            f"Resuma o seguinte texto em no máximo {max_tokens} tokens, mantendo as informações mais importantes:\n\n{content}",
            generation_config={
                "temperature": 0.5,
                "top_p": 0.95,
                "top_k": 40,
                "max_output_tokens": max_tokens,
            }
        )
        return summary.text
    except Exception as e:
        return f"Erro ao resumir o conteúdo: {str(e)}"

def limit_knowledge_base(knowledge_base, max_tokens=100000):
    tokens = knowledge_base.split()
    if len(tokens) > max_tokens:
        return " ".join(tokens[-max_tokens:])
    return knowledge_base

# Interface do usuário
st.title("Chat com Gemini AI em Português (com Treinamento)")

# Área de upload e processamento de conteúdo
st.sidebar.header("Adicionar Conhecimento")

uploaded_file = st.sidebar.file_uploader("Carregar documento", type=["pdf", "txt"])
if uploaded_file:
    if uploaded_file.type == "application/pdf":
        new_content = process_pdf(uploaded_file)
    else:
        new_content = process_text(uploaded_file)
    st.session_state.knowledge_base += new_content
    st.session_state.knowledge_base = limit_knowledge_base(st.session_state.knowledge_base)
    st.sidebar.success("Documento processado com sucesso!")

website_url = st.sidebar.text_input("URL do site")
if website_url:
    try:
        new_content = process_website(website_url)
        st.session_state.knowledge_base += new_content
        st.session_state.knowledge_base = limit_knowledge_base(st.session_state.knowledge_base)
        st.sidebar.success("Conteúdo do site processado com sucesso!")
    except Exception as e:
        st.sidebar.error(f"Erro ao processar o site: {e}")

youtube_url = st.sidebar.text_input("URL do vídeo do YouTube")
youtube_auth_cookie = st.sidebar.text_input("Cookie de autenticação do YouTube (opcional)", type="password")
summarize_video = st.sidebar.checkbox("Resumir conteúdo do vídeo")

if youtube_url:
    auth_cookie = youtube_auth_cookie if youtube_auth_cookie else None
    new_content = process_youtube(youtube_url, auth_cookie)
    if not new_content.startswith("Erro") and not new_content.startswith("As transcrições estão desativadas"):
        if summarize_video:
            new_content = summarize_content(new_content)
        st.session_state.knowledge_base += new_content
        st.session_state.knowledge_base = limit_knowledge_base(st.session_state.knowledge_base)
        st.sidebar.success("Transcrição do vídeo processada com sucesso!")
        if summarize_video:
            st.sidebar.info("O conteúdo do vídeo foi resumido para economizar espaço.")
    else:
        st.sidebar.error(new_content)

# Exibição das mensagens anteriores
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# Entrada do usuário
if prompt := st.chat_input("Digite sua mensagem"):
    # Adiciona a mensagem do usuário ao histórico
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Preparação do contexto da conversa
    conversation_history = "\n".join([f"{m['role']}: {m['content']}" for m in st.session_state.messages])
    
    # Instrução para responder em português do Brasil
    system_prompt = "Você é um assistente AI amigável. Responda sempre em português do Brasil. Mantenha um tom cordial e informal. Use o conhecimento adicional fornecido para enriquecer suas respostas quando relevante."
    
    # Geração da resposta da IA
    try:
        response = model.generate_content(
            f"{system_prompt}\n\nConhecimento Adicional:\n{st.session_state.knowledge_base}\n\nHistórico da conversa:\n{conversation_history}\n\nUsuário: {prompt}\nAssistente:",
            generation_config={
                "temperature": 0.8,
                "top_p": 0.95,
                "top_k": 40,
                "max_output_tokens": 8192,
            }
        )
        
        # Verifica se a resposta tem conteúdo
        if response.parts:
            # Extrai o texto da resposta
            response_text = response.text
            
            # Formata a resposta em Markdown
            markdown_response = textwrap.indent(response_text.replace('•', '*'), '> ', predicate=lambda _: True)

            # Adiciona a resposta da IA ao histórico
            st.session_state.messages.append({"role": "assistant", "content": markdown_response})
            with st.chat_message("assistant"):
                st.markdown(markdown_response)
        else:
            st.error("A resposta do modelo está vazia. Por favor, tente novamente.")

    except Exception as e:
        st.error(f"Erro ao gerar resposta: {e}")

# Botão para limpar o histórico
if st.sidebar.button("Limpar Conversa e Conhecimento"):
    st.session_state.messages = []
    st.session_state.knowledge_base = ""
    st.rerun()

