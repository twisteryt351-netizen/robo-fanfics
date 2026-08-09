import os
import re
import json
import time
import base64
import urllib.parse
import requests
from groq import Groq
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

from motor_fanfic import (
    carregar_estado, salvar_estado, processar_promocoes, processar_encerramentos,
    planejar_slots, registrar_historia_nova, registrar_titulo, avancar_capitulo_serie,
    HISTORIAS_POR_DIA,
)
from prompt_engine_fanfic import (
    montar_prompt_one_shot, montar_prompt_continuacao, montar_prompt_titulo, PALAVRAS_MIN,
)

# ─────────────────────────────────────────────────────────────
#  CONFIGURAÇÕES
# ─────────────────────────────────────────────────────────────
GROQ_API_KEY       = os.environ.get("GROQ_API_KEY")
BLOGGER_ID         = os.environ.get("BLOGGER_ID_FANFIC")
CLIENT_ID          = os.environ.get("BLOGGER_CLIENT_ID")
CLIENT_SECRET      = os.environ.get("BLOGGER_CLIENT_SECRET")
REFRESH_TOKEN      = os.environ.get("BLOGGER_REFRESH_TOKEN")
POLLINATIONS_TOKEN = os.environ.get("POLLINATIONS_TOKEN")
IMGBB_API_KEY      = os.environ.get("IMGBB_API_KEY")

INTERVALO_POLLINATIONS = 6 if POLLINATIONS_TOKEN else 16

for nome, valor in [
    ("GROQ_API_KEY",          GROQ_API_KEY),
    ("BLOGGER_ID_FANFIC",     BLOGGER_ID),
    ("BLOGGER_CLIENT_ID",     CLIENT_ID),
    ("BLOGGER_CLIENT_SECRET", CLIENT_SECRET),
    ("BLOGGER_REFRESH_TOKEN", REFRESH_TOKEN),
]:
    if not valor:
        raise ValueError(f"Faltou configurar a variável/segredo: {nome}")

groq_client = Groq(api_key=GROQ_API_KEY)
MODELO_IA   = "llama-3.3-70b-versatile"

ARQUIVO_HISTORICO_TEXTO = "historico_fanfic.txt"
IMAGEM_PADRAO = "https://upload.wikimedia.org/wikipedia/commons/thumb/9/95/News_icon.svg/640px-News_icon.svg.png"

MOODBOARD_CATEGORIA = {
    "Anime/Mangá": "dynamic anime-style key visual, dramatic action pose, vivid colors, cinematic composition, 8k digital painting",
    "Livros": "epic fantasy book-cover illustration, atmospheric lighting, painterly detail, cinematic wide shot",
    "Filmes": "cinematic blockbuster movie-poster style, dramatic lighting, epic scale, photorealistic 8k",
    "TV": "moody atmospheric TV-drama photography, cinematic color grading, mysterious tone",
    "Games": "video game concept art, dynamic composition, painterly digital art, epic fantasy/sci-fi tone",
    "Cartoons": "vibrant stylized animated-series concept art, bold colors, expressive characters",
    "Quadrinhos": "comic book cover art style, bold inks, dramatic action, vivid colors",
    "Fantasia": "epic fantasy illustration, atmospheric lighting, painterly detail, 8k",
    "Ficção Científica": "sci-fi concept art, futuristic atmosphere, cinematic lighting, 8k",
    "Urban Fantasy": "moody urban fantasy illustration, neon and shadow, cinematic atmosphere",
    "Romance": "warm cinematic romantic illustration, soft lighting, emotional atmosphere",
    "Horror/Sobrevivência": "tense atmospheric survival-horror illustration, dark cinematic tone, no gore, no blood",
    "Aventura Histórica": "historical adventure illustration, cinematic golden-hour lighting, epic scale",
    "Drama/Coming-of-age": "warm cinematic youth-drama photography, soft natural lighting",
    "Mistério": "moody mystery illustration, dramatic shadows, cinematic tension",
    "Fantasia Ecológica": "lush painterly nature-fantasy illustration, magical atmosphere",
    "Drama/Fantasia": "whimsical dramatic fantasy illustration, warm cinematic lighting",
}
MOODBOARD_PADRAO = "cinematic epic illustration, dramatic lighting, 8k digital art"


# ─────────────────────────────────────────────────────────────
#  GROQ (texto)
# ─────────────────────────────────────────────────────────────
def pedir_ia_groq(prompt, temperatura=0.8):
    response = groq_client.chat.completions.create(
        messages=[{"role": "user", "content": prompt}],
        model=MODELO_IA,
        temperature=temperatura,
    )
    return response.choices[0].message.content.strip()


# ─────────────────────────────────────────────────────────────
#  GERAÇÃO DA HISTÓRIA (one-shot ou continuação)
# ─────────────────────────────────────────────────────────────
def extrair_resumo_interno(texto_bruto):
    """Separa o corpo publicável do marcador RESUMO_INTERNO no final."""
    match = re.search(r'RESUMO_INTERNO:\s*(.+)$', texto_bruto, re.IGNORECASE | re.DOTALL)
    if match:
        resumo = match.group(1).strip()
        corpo = texto_bruto[:match.start()].strip()
        return corpo, resumo
    return texto_bruto.strip(), "(sem resumo — continuidade pode ficar limitada)"


def gerar_historia(estado, tarefa):
    if tarefa["modo"] == "continuacao":
        prompt = montar_prompt_continuacao(estado, tarefa["serie_id"], tarefa)
        universo_info = {"categoria": tarefa["categoria"], "id": tarefa["universo_id"]}
    else:
        prompt, universo = montar_prompt_one_shot(estado, tarefa["tipo"])
        universo_info = universo

    raw = pedir_ia_groq(prompt, temperatura=0.82)
    corpo, resumo = extrair_resumo_interno(raw)
    return corpo, resumo, universo_info


def gerar_titulo_historia(tarefa, universo_info, historico_titulos):
    if tarefa["modo"] == "continuacao":
        prompt = montar_prompt_titulo("continuacao", tarefa["titulo_serie"],
                                       capitulo=tarefa["capitulo_atual"] + 1)
    else:
        prompt = montar_prompt_titulo("one_shot", universo_info["premissa"],
                                       titulos_recentes=historico_titulos)
    return pedir_ia_groq(prompt, temperatura=0.85).replace('"', '').strip()


# ─────────────────────────────────────────────────────────────
#  TAGS / MARCADORES (Blogger "labels")
# ─────────────────────────────────────────────────────────────
MAX_TAGS = 8

def gerar_tags(categoria, titulo, tipo_ou_serie):
    prompt = f"""
Gere de 5 a {MAX_TAGS} marcadores/tags (labels) para um post de blog de ficção em
português do Brasil.

Título: "{titulo}"
Categoria/gênero: {categoria}
Contexto: {tipo_ou_serie}

Regras:
- Tags curtas (1 a 3 palavras cada), sem "#", sem numeração.
- Misture tags específicas da história com tags amplas do nicho
  (ex: "ficção", "aventura", "fanfic original", o nome do gênero).
- Não repita o título literalmente como tag.

Retorne APENAS um array JSON válido de strings, nada mais.
Exemplo: ["tag um", "tag dois", "tag tres"]
"""
    raw = pedir_ia_groq(prompt, temperatura=0.5)
    match = re.search(r'\[.*?\]', raw, re.DOTALL)
    if match:
        try:
            tags = json.loads(match.group())
            if isinstance(tags, list):
                tags_limpas = [str(t).strip() for t in tags if str(t).strip()]
                return tags_limpas[:MAX_TAGS]
        except Exception:
            pass
    linhas = [l.strip(" -\"'") for l in raw.split(",") if l.strip()]
    return linhas[:MAX_TAGS] if linhas else [categoria]


# ─────────────────────────────────────────────────────────────
#  PROMPTS DE IMAGEM (prompt + legenda juntos)
# ─────────────────────────────────────────────────────────────
def gerar_prompts_imagens(categoria, titulo, num_imagens=3):
    moodboard = MOODBOARD_CATEGORIA.get(categoria, MOODBOARD_PADRAO)
    prompt = f"""
You are an art director for a fiction storytelling blog with an epic, cinematic tone
(no gore, no blood, no explicit content, no real copyrighted characters/logos).

Visual mood: {moodboard}
Story title: "{titulo}"

Create exactly {num_imagens} image concepts:
- Image 1 (COVER): eye-catching but tasteful thumbnail-style image matching the mood above.
- Remaining images: DISTINCT scenes/moments that could plausibly illustrate this story,
  each visually different from the others.

For EACH image, provide:
- "prompt": one vivid descriptive paragraph in ENGLISH for the image generator. No text,
  logos, or copyrighted characters/symbols inside the image.
- "legenda": a short caption in BRAZILIAN PORTUGUESE (under 12 words).

Return ONLY a valid JSON array of {num_imagens} objects, nothing else.
Example: [{{"prompt": "...", "legenda": "..."}}, {{"prompt": "...", "legenda": "..."}}]
"""
    raw = pedir_ia_groq(prompt, temperatura=0.6)
    match = re.search(r'\[.*\]', raw, re.DOTALL)
    if match:
        try:
            itens = json.loads(match.group())
            if isinstance(itens, list) and all(isinstance(i, dict) for i in itens):
                resultado = [
                    {"prompt": str(i.get("prompt", "")).strip(),
                     "legenda": str(i.get("legenda", "")).strip()}
                    for i in itens[:num_imagens]
                ]
                if all(r["prompt"] for r in resultado):
                    return resultado
        except Exception:
            pass
    return [{"prompt": f"{moodboard}, scene {i+1}", "legenda": ""} for i in range(num_imagens)]


# ─────────────────────────────────────────────────────────────
#  GERAÇÃO DE IMAGEM — Pollinations.ai + ImgBB (com verificação) + Openverse
# ─────────────────────────────────────────────────────────────
DIMENSOES_RATIO = {"16:9": (1280, 720), "1:1": (1024, 1024), "9:16": (720, 1280)}


def gerar_imagem_worker_b64(prompt_img, ratio="16:9"):
    largura, altura = DIMENSOES_RATIO.get(ratio, (1280, 720))
    prompt_codificado = urllib.parse.quote(prompt_img)
    url = f"https://image.pollinations.ai/prompt/{prompt_codificado}"
    params = {
        "width": largura, "height": altura, "model": "flux",
        "seed": __import__("random").randint(1, 999999), "nologo": "true",
    }
    headers = {}
    if POLLINATIONS_TOKEN:
        headers["Authorization"] = f"Bearer {POLLINATIONS_TOKEN}"
    resp = requests.get(url, params=params, headers=headers, timeout=120)
    resp.raise_for_status()
    if "image" not in resp.headers.get("Content-Type", ""):
        raise ValueError("Resposta não parece ser uma imagem.")
    b64 = base64.b64encode(resp.content).decode("utf-8")
    if not b64:
        raise ValueError("Pollinations.ai retornou imagem vazia.")
    return b64


def hospedar_imgbb(b64_data, nome="fanfic_img"):
    if not IMGBB_API_KEY:
        raise ValueError("IMGBB_API_KEY não configurada.")
    resp = requests.post(
        "https://api.imgbb.com/1/image",
        data={"key": IMGBB_API_KEY, "image": b64_data, "name": nome[:100]},
        timeout=60,
    )
    resp.raise_for_status()
    resultado = resp.json()
    if not resultado.get("success"):
        raise ValueError(f"ImgBB recusou o upload: {resultado}")
    return resultado["data"]["url"]


def verificar_url_imagem(url, tentativas=5, espera_segundos=2):
    for tentativa in range(1, tentativas + 1):
        try:
            resp = requests.head(url, timeout=10, allow_redirects=True)
            if resp.status_code == 200:
                return True
            if resp.status_code in (403, 405):
                resp = requests.get(url, timeout=10, stream=True)
                if resp.status_code == 200:
                    return True
        except requests.RequestException:
            pass
        if tentativa < tentativas:
            time.sleep(espera_segundos)
    return False


def buscar_imagens_openverse(palavra_chave, quantidade=3):
    try:
        resposta = requests.get(
            "https://api.openverse.org/v1/images/",
            params={"q": palavra_chave, "license_type": "commercial",
                    "page_size": max(quantidade, 5), "mature": "false"},
            headers={"User-Agent": "RoboFanfic/1.0"}, timeout=15,
        )
        resultados = resposta.json().get("results", [])
        urls = [r["url"] for r in resultados[:quantidade]]
        return urls if urls else [IMAGEM_PADRAO]
    except Exception as e:
        print(f"⚠️ Erro Openverse: {e}")
        return [IMAGEM_PADRAO]


def html_imagem_blogger(src, alt_title, legenda="", height=360, width=640):
    legenda_html = ""
    if legenda:
        legenda_html = (
            f'<div style="font-size:13px;color:#777;font-style:italic;'
            f'text-align:center;margin-top:6px;margin-bottom:20px;">{legenda}</div>'
        )
    return (
        '<table align="center" cellpadding="0" cellspacing="0" '
        'class="tr-caption-container" '
        'style="margin-left:auto;margin-right:auto;margin-bottom:8px;">'
        '<tbody><tr><td style="text-align:center;">'
        f'<img alt="{legenda or alt_title}" border="0" height="{height}" src="{src}" '
        f'title="{legenda or alt_title}" width="{width}" '
        'style="max-width:100%;border-radius:10px;box-shadow:0 2px 8px rgba(0,0,0,0.12);" />'
        '</td></tr></tbody></table>'
        f'{legenda_html}'
    )


def obter_imagens_html(itens_imagem, titulo, palavra_fallback):
    imagens_html = []
    openverse_cache = None
    for i, item in enumerate(itens_imagem):
        prompt_img = item["prompt"]
        legenda = item.get("legenda", "")
        src = None
        try:
            print(f"  🖼️  [{i+1}/{len(itens_imagem)}] Gerando via Pollinations.ai...")
            b64 = gerar_imagem_worker_b64(prompt_img, ratio="16:9")
            try:
                url_imgbb = hospedar_imgbb(b64, nome=f"fanfic_{titulo[:40].replace(' ','_')}_{i+1}")
                if verificar_url_imagem(url_imgbb):
                    src = url_imgbb
                else:
                    raise ValueError("URL do ImgBB não respondeu 200 depois de várias tentativas.")
            except Exception as e_imgbb:
                print(f"  ⚠️  ImgBB falhou/não propagou ({e_imgbb}). Usando data URI...")
                src = f"data:image/png;base64,{b64}"
        except Exception as e_ia:
            print(f"  ⚠️  Pollinations.ai falhou ({e_ia}). Buscando no Openverse...")
            if openverse_cache is None:
                openverse_cache = buscar_imagens_openverse(palavra_fallback, quantidade=len(itens_imagem))
            src = openverse_cache[i % len(openverse_cache)]
        altura = 420 if i == 0 else 300
        imagens_html.append(html_imagem_blogger(src, titulo, legenda=legenda, height=altura))
        if i < len(itens_imagem) - 1:
            time.sleep(INTERVALO_POLLINATIONS)
    return imagens_html


# ─────────────────────────────────────────────────────────────
#  MONTAGEM DO HTML FINAL — imagens distribuídas antes de cada <h2>
# ─────────────────────────────────────────────────────────────
def montar_html(corpo_artigo, imagens_html, rodape_info):
    capa = imagens_html[0]
    extras = imagens_html[1:]

    if not extras:
        corpo_final = corpo_artigo
    else:
        posicoes_h2 = [m.start() for m in re.finditer(r'<h2\b', corpo_artigo, flags=re.IGNORECASE)]
        if not posicoes_h2:
            corpo_final = corpo_artigo + "".join(extras)
        else:
            alvos = posicoes_h2[1:] if len(posicoes_h2) > 1 else posicoes_h2
            passo = max(1, len(alvos) // len(extras))
            posicoes_escolhidas = [alvos[min(i * passo, len(alvos) - 1)] for i in range(len(extras))]
            corpo_final = corpo_artigo
            for pos, img in sorted(zip(posicoes_escolhidas, extras), key=lambda par: -par[0]):
                corpo_final = corpo_final[:pos] + img + corpo_final[pos:]

    rodape = (
        '<p style="font-size:12px;color:#999;font-style:italic;margin-top:24px;">'
        f'📚 {rodape_info} — Obra de ficção original. Qualquer semelhança com '
        'outras obras é estilística/de gênero, não reprodução.</p>'
    )
    return f"{capa}{corpo_final}{rodape}"


# ─────────────────────────────────────────────────────────────
#  BLOGGER
# ─────────────────────────────────────────────────────────────
def obter_credenciais():
    creds = Credentials(
        token=None, refresh_token=REFRESH_TOKEN, client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET, token_uri="https://oauth2.googleapis.com/token",
    )
    creds.refresh(Request())
    return creds


def publicar_no_blogger(titulo, conteudo, tags=None):
    creds = obter_credenciais()
    blogger = build("blogger", "v3", credentials=creds)
    corpo = {"kind": "blogger#post", "title": titulo, "content": conteudo}
    if tags:
        corpo["labels"] = tags
    res = blogger.posts().insert(blogId=BLOGGER_ID, body=corpo).execute()
    print(f"📖 Postado: '{titulo}' -> {res.get('url')}")


def registrar_historico_texto(id_historia, titulo, modo, categoria):
    with open(ARQUIVO_HISTORICO_TEXTO, "a", encoding="utf-8") as f:
        f.write(f"[{id_historia} | {modo} | {categoria}] {titulo}\n")


# ─────────────────────────────────────────────────────────────
#  PROCESSA UMA TAREFA (one-shot ou continuação) DE PONTA A PONTA
# ─────────────────────────────────────────────────────────────
def processar_tarefa(estado, tarefa, indice, total):
    print(f"\n{'='*60}\n📝 História {indice}/{total} — modo: {tarefa['modo']}\n{'='*60}")

    corpo, resumo, universo_info = gerar_historia(estado, tarefa)
    titulo = gerar_titulo_historia(tarefa, universo_info if tarefa["modo"] == "one_shot" else tarefa,
                                    estado["historico_titulos"])
    print(f"✏️  Título: {titulo}")

    categoria = universo_info.get("categoria") if tarefa["modo"] == "one_shot" else tarefa["categoria"]
    contexto_tags = (f"one-shot {tarefa['tipo']}" if tarefa["modo"] == "one_shot"
                      else f"série: {tarefa['titulo_serie']}")
    tags = gerar_tags(categoria, titulo, contexto_tags)

    itens_imagem = gerar_prompts_imagens(categoria, titulo, num_imagens=3)
    imagens_html = obter_imagens_html(itens_imagem, titulo, categoria)

    if tarefa["modo"] == "continuacao":
        rodape_info = f"{tarefa['titulo_serie']} — Capítulo {tarefa['capitulo_atual'] + 1}"
    else:
        rodape_info = f"História original — {categoria}"

    html_final = montar_html(corpo, imagens_html, rodape_info)
    publicar_no_blogger(titulo, html_final, tags=tags)

    registrar_titulo(estado, titulo)

    if tarefa["modo"] == "continuacao":
        avancar_capitulo_serie(estado, tarefa["serie_id"], resumo, titulo)
        registrar_historico_texto(tarefa["serie_id"], titulo, "continuação", categoria)
    else:
        id_historia = registrar_historia_nova(
            estado, titulo, tarefa["tipo"], universo_info["id"], categoria, resumo
        )
        registrar_historico_texto(id_historia, titulo, f"one-shot ({tarefa['tipo']})", categoria)

    salvar_estado(estado)  # salva a cada história — se uma falhar, as anteriores não se perdem


# ─────────────────────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("📚 Gerando as histórias de hoje...")

    estado = carregar_estado()
    processar_promocoes(estado)
    processar_encerramentos(estado)
    salvar_estado(estado)

    tarefas = planejar_slots(estado, quantidade=HISTORIAS_POR_DIA)
    print(f"📋 Plano do dia: {len(tarefas)} história(s) — "
          f"{sum(1 for t in tarefas if t['modo']=='continuacao')} continuação(ões), "
          f"{sum(1 for t in tarefas if t['modo']=='one_shot')} one-shot(s) novo(s)")

    for i, tarefa in enumerate(tarefas, start=1):
        try:
            processar_tarefa(estado, tarefa, i, len(tarefas))
        except Exception as e:
            print(f"❌ Falha na história {i}/{len(tarefas)}: {e}")
            # continua tentando as próximas em vez de abortar o dia inteiro
            continue

    print("\n✅ Execução do dia concluída.")
