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
MODELO_IA   = "openai/gpt-oss-120b"

# Diagnóstico: mostra no log se os tokens OPCIONAIS realmente chegaram ao
# processo (sem expor o valor). Se aparecer "NÃO configurado" aqui mesmo
# tendo cadastrado o secret no GitHub, o problema é que o workflow .yml
# não está passando ele como variável de ambiente pro step que roda o script.
def _mascarar(valor):
    if not valor:
        return "❌ NÃO configurado"
    return f"✅ configurado ({len(valor)} caracteres, começa com '{valor[:4]}...')"

print(f"🔑 POLLINATIONS_TOKEN: {_mascarar(POLLINATIONS_TOKEN)}")
print(f"🔑 IMGBB_API_KEY:      {_mascarar(IMGBB_API_KEY)}")

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
def pedir_ia_groq(prompt, temperatura=0.8, max_tokens=8000):
    response = groq_client.chat.completions.create(
        messages=[{"role": "user", "content": prompt}],
        model=MODELO_IA,
        temperature=temperatura,
        max_tokens=max_tokens,
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


TAGS_BLOCO_PRONTAS = ("<h2", "<h3", "<blockquote", "<div", "<p", "<table", "<ul", "<ol")


def normalizar_para_html(texto):
    """Rede de segurança contra a IA usar Markdown (## título, **negrito**,
    > citação) em vez de HTML puro, e contra parágrafos separados só por
    linha em branco — que o navegador/Blogger colapsa em espaço único,
    virando uma parede de texto só com '##' aparecendo literalmente.

    Divide o texto em blocos por linha em branco (a estrutura que a IA de
    fato produziu) e converte cada bloco pro HTML equivalente."""
    texto = texto.strip().replace("\r\n", "\n").replace("\r", "\n")
    blocos = re.split(r'\n\s*\n', texto)

    html_blocos = []
    for bloco in blocos:
        bloco = bloco.strip()
        if not bloco:
            continue

        # já é HTML de verdade (ex: a <div class="nota-autor">) -> mantém
        if bloco.lower().startswith(TAGS_BLOCO_PRONTAS):
            html_blocos.append(bloco)
            continue

        # heading estilo Markdown: "## Texto" ou "### Texto"
        m = re.match(r'^#{1,3}\s*(.+)$', bloco, flags=re.DOTALL)
        if m:
            resto = m.group(1).strip()
            # protege contra a IA grudar o parágrafo seguinte na mesma linha
            # do título (sem quebra) — corta no fim da 1ª frase ou em ~12 palavras
            corte = re.search(r'[.!?]\s+[A-ZÀ-Ú]', resto)
            if corte and corte.start() < 100:
                titulo_bloco = resto[:corte.start() + 1].strip()
                resto_paragrafo = resto[corte.start() + 1:].strip()
            elif len(resto) > 90:
                palavras = resto.split()
                titulo_bloco = " ".join(palavras[:12])
                resto_paragrafo = " ".join(palavras[12:])
            else:
                titulo_bloco, resto_paragrafo = resto, ""
            html_blocos.append(f"<h2>{titulo_bloco}</h2>")
            if resto_paragrafo:
                resto_paragrafo = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', resto_paragrafo)
                html_blocos.append(f"<p>{resto_paragrafo}</p>")
            continue

        # blockquote estilo Markdown: "> Texto"
        if bloco.startswith(">"):
            citado = re.sub(r'^>\s?', '', bloco, flags=re.MULTILINE).strip().replace("\n", "<br>")
            html_blocos.append(f"<blockquote>{citado}</blockquote>")
            continue

        # parágrafo comum
        paragrafo = bloco.replace("\n", "<br>")
        paragrafo = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', paragrafo)
        paragrafo = re.sub(r'(?<!\*)\*([^*\n]+?)\*(?!\*)', r'<em>\1</em>', paragrafo)
        html_blocos.append(f"<p>{paragrafo}</p>")

    return "\n".join(html_blocos)


def contar_palavras_html(texto_html):
    texto_puro = re.sub(r'<[^>]+>', ' ', texto_html)
    return len(re.findall(r"[A-Za-zÀ-ÿ]+(?:['’-][A-Za-zÀ-ÿ]+)*", texto_puro))


def gerar_historia(estado, tarefa):
    if tarefa["modo"] == "continuacao":
        prompt = montar_prompt_continuacao(estado, tarefa["serie_id"], tarefa)
        universo_info = {"categoria": tarefa["categoria"], "id": tarefa["universo_id"]}
    else:
        prompt, universo = montar_prompt_one_shot(estado, tarefa["tipo"])
        universo_info = universo

    raw = pedir_ia_groq(prompt, temperatura=0.82, max_tokens=8000)
    corpo, resumo = extrair_resumo_interno(raw)
    corpo = normalizar_para_html(corpo)

    # Se saiu curta (a Groq às vezes encerra antes do pedido), pede
    # continuação real da história em vez de publicar algo raso/incompleto.
    tentativas = 0
    while contar_palavras_html(corpo) < int(PALAVRAS_MIN * 0.8) and tentativas < 2:
        tentativas += 1
        palavras_atuais = contar_palavras_html(corpo)
        print(f"  ✏️  História curta ({palavras_atuais} palavras, meta {PALAVRAS_MIN}) "
              f"— pedindo continuação (tentativa {tentativas})...")
        prompt_continuar = f"""
A história abaixo terminou curta demais (menos de {PALAVRAS_MIN} palavras).
Continue-a EXATAMENTE de onde parou, mesmo tom, personagens e formato HTML
(pode abrir novos <h2> se fizer sentido pra próxima cena). NÃO repita nada
do que já foi escrito — só continue e desenvolva mais até fechar a história
com um final satisfatório.

HISTÓRIA ATÉ AGORA:
{corpo}
"""
        continuacao = pedir_ia_groq(prompt_continuar, temperatura=0.82, max_tokens=8000)
        continuacao = normalizar_para_html(continuacao)
        corpo = corpo + "\n" + continuacao

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


def gerar_imagem_worker_b64(prompt_img, ratio="16:9", tentativas=3):
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

    ultimo_erro = None
    for tentativa in range(1, tentativas + 1):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=120)
            if resp.status_code != 200:
                trecho = resp.text[:200].replace("\n", " ")
                raise ValueError(f"HTTP {resp.status_code} — resposta: {trecho!r}")
            if "image" not in resp.headers.get("Content-Type", ""):
                trecho = resp.text[:200].replace("\n", " ")
                raise ValueError(f"Resposta não é imagem (Content-Type: {resp.headers.get('Content-Type')}) — corpo: {trecho!r}")
            b64 = base64.b64encode(resp.content).decode("utf-8")
            if not b64:
                raise ValueError("Pollinations.ai retornou imagem vazia.")
            return b64
        except Exception as e:
            ultimo_erro = e
            if tentativa < tentativas:
                espera = 5 * tentativa
                print(f"  ⚠️  Pollinations.ai falhou (tentativa {tentativa}/{tentativas}): {e}. "
                      f"Tentando de novo em {espera}s...")
                time.sleep(espera)
                # muda o seed pra evitar bater exatamente no mesmo erro/cache
                params["seed"] = __import__("random").randint(1, 999999)
    raise ultimo_erro


def hospedar_imgbb(b64_data, nome="fanfic_img"):
    if not IMGBB_API_KEY:
        raise ValueError("IMGBB_API_KEY não configurada.")
    resp = requests.post(
        "https://api.imgbb.com/1/upload",
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

    def _openverse_fallback(i):
        nonlocal openverse_cache
        if openverse_cache is None:
            openverse_cache = buscar_imagens_openverse(palavra_fallback, quantidade=len(itens_imagem))
        return openverse_cache[i % len(openverse_cache)]

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
                # NUNCA usa data URI aqui: o Blogger não gera miniatura nem
                # sempre renderiza base64 embutido de primeira, o que causava
                # o "só aparece depois de abrir e atualizar". Sempre cai pra
                # uma URL externa real (Openverse) em vez disso.
                print(f"  ⚠️  ImgBB falhou/não propagou ({e_imgbb}). Buscando no Openverse...")
                src = _openverse_fallback(i)
        except Exception as e_ia:
            print(f"  ⚠️  Pollinations.ai falhou ({e_ia}). Buscando no Openverse...")
            src = _openverse_fallback(i)
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
        alvos = posicoes_h2[1:] if len(posicoes_h2) > 1 else posicoes_h2

        if not alvos:
            # nenhum <h2> pra ancorar — vai tudo pro fim, mas nunca sobreposto
            corpo_final = corpo_artigo + "".join(extras)
        elif len(alvos) >= len(extras):
            # âncoras suficientes: espalha as imagens do INÍCIO ao FIM da lista
            # de âncoras (usa a primeira e a última quando possível), em vez de
            # amontoar tudo nas primeiras posições
            if len(extras) == 1:
                indices = [len(alvos) // 2]
            else:
                indices = [round(i * (len(alvos) - 1) / (len(extras) - 1)) for i in range(len(extras))]
            posicoes_escolhidas = sorted({alvos[i] for i in indices})
            # se a deduplicação por arredondamento colidiu, completa com âncoras livres
            livres = [a for a in alvos if a not in posicoes_escolhidas]
            while len(posicoes_escolhidas) < len(extras) and livres:
                posicoes_escolhidas.append(livres.pop(0))
            posicoes_escolhidas = sorted(posicoes_escolhidas)[:len(extras)]

            corpo_final = corpo_artigo
            for pos, img in sorted(zip(posicoes_escolhidas, extras), key=lambda par: -par[0]):
                corpo_final = corpo_final[:pos] + img + corpo_final[pos:]
        else:
            # menos âncoras do que imagens extras: usa TODAS as âncoras
            # disponíveis (uma imagem cada, nunca duas na mesma) e o que
            # sobrar vai pro fim — melhor do que empilhar imagem sobre imagem
            corpo_final = corpo_artigo
            for pos, img in sorted(zip(alvos, extras), key=lambda par: -par[0]):
                corpo_final = corpo_final[:pos] + img + corpo_final[pos:]
            excedentes = extras[len(alvos):]
            corpo_final += "".join(excedentes)

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
    post_id = res.get("id")
    print(f"📖 Postado: '{titulo}' -> {res.get('url')}")

    # Automatiza o "abrir e atualizar" manual: o Blogger às vezes só
    # (re)processa miniaturas/imagens externas quando o post é resalvo.
    # Um update logo em seguida reproduz esse mesmo efeito via API.
    if post_id:
        try:
            time.sleep(5)  # dá um tempinho pro Blogger terminar de indexar o insert
            blogger.posts().update(blogId=BLOGGER_ID, postId=post_id, body=corpo).execute()
            print("  🔄 Re-save automático aplicado (equivalente a abrir e atualizar).")
        except Exception as e_update:
            print(f"  ⚠️  Re-save automático falhou (post já está publicado normalmente): {e_update}")


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
