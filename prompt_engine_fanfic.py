# ─────────────────────────────────────────────────────────────
#  MOTOR DE PROMPTS — monta o prompt pra cada história do dia,
#  seja one-shot novo (inspirado ou original) ou continuação
#  de uma série já ativa.
# ─────────────────────────────────────────────────────────────
import random
from conteudo_fanfic import (
    UNIVERSOS_INSPIRADOS, UNIVERSOS_ORIGINAIS,
    NOMES_PROTAGONISTAS, TITULOS_SERIE_HONORIFICOS,
)

PALAVRAS_MIN = 2600


def escolher_universo(tipo, estado):
    pool = UNIVERSOS_INSPIRADOS if tipo == "inspirado" else UNIVERSOS_ORIGINAIS
    historico = (estado["historico_universos_inspirados"] if tipo == "inspirado"
                 else estado["historico_universos_originais"])
    disponiveis = [u for u in pool if u["id"] not in historico]
    if not disponiveis:
        disponiveis = pool
    return random.choice(disponiveis)


def cabecalho_regras(categoria=None):
    linha_categoria = f"\nCategoria/estilo: {categoria}" if categoria else ""
    return f"""
Você é um escritor profissional de ficção, publicando num blog de histórias
originais com forte apelo de leitura (o público gosta do MESMO clima de fanfics
populares, mas toda a obra aqui é 100% autoral — nomes, mundos, personagens e
tramas próprios, sem usar nada de nenhuma franquia real).{linha_categoria}

REGRAS INEGOCIÁVEIS DE PROPRIEDADE INTELECTUAL:
- PROIBIDO usar nomes de personagens, lugares, técnicas, organizações ou títulos
  de qualquer obra real (anime, livro, filme, série, jogo, HQ). Tudo deve ser
  inventado, mesmo que o CLIMA lembre um gênero popular.
- PROIBIDO copiar diálogos, falas de efeito ou frases icônicas de qualquer obra real.
- A trama deve ser sua, com reviravoltas próprias — não recontar o enredo de
  nenhuma obra existente, só usar o mesmo tipo de ambientação/gênero.

REGRAS DE CONTEÚDO:
- Sem conteúdo sexual explícito, sem violência gráfica gratuita, sem discurso de ódio.
- Tom: envolvente, cinematográfico, com ganchos que prendem o leitor até o fim.

REGRAS DE FORMATO (HTML puro, sem Markdown):
- Mínimo de {PALAVRAS_MIN} palavras.
- Abertura forte, já dentro de uma cena, sem introdução genérica.
- Pelo menos 2 subtítulos <h2> ESPECÍFICOS da cena que introduzem (nunca rótulos
  genéricos tipo "Capítulo 1" sozinho — combine com algo que aconteceu nessa parte,
  ex: "O Portão que Não Deveria Abrir").
- 1 a 2 <blockquote> com uma fala ou pensamento marcante de um personagem.
- Final com gancho: uma pergunta em aberto, uma reviravolta, ou tensão que
  deixa o leitor querendo mais (mesmo em um one-shot).
"""


def montar_prompt_one_shot(estado, tipo):
    universo = escolher_universo(tipo, estado)
    protagonista = random.choice(NOMES_PROTAGONISTAS)

    prompt = cabecalho_regras(universo["categoria"]) + f"""
PREMISSA BASE (desenvolva com originalidade, não fique preso a ela literalmente):
{universo['premissa']}

Protagonista sugerido (pode ajustar): {protagonista}.

Escreva uma história COMPLETA (one-shot) de aventura/drama envolvendo essa premissa,
com começo, meio e fim satisfatórios dentro deste único capítulo.

No FINAL do texto, depois da história, adicione uma linha separada exatamente assim
(sem nada antes ou depois na mesma linha):
RESUMO_INTERNO: [um resumo de 1-2 frases da história pra referência editorial, não
é pra aparecer publicado, é só controle interno]
"""
    return prompt, universo


def montar_prompt_continuacao(estado, serie_id, dados_serie):
    prompt = cabecalho_regras(dados_serie["categoria"]) + f"""
Isto é uma CONTINUAÇÃO de uma série já em andamento.

Título da série: "{dados_serie['titulo_serie']}"
Capítulo atual: {dados_serie['capitulo_atual'] + 1}
Resumo do que já aconteceu até aqui: {dados_serie['resumo_acumulado']}

Escreva o PRÓXIMO capítulo, avançando a trama de forma natural a partir de onde
parou. Não repita eventos já narrados — avance a história. Mantenha os mesmos
personagens e o mesmo tom estabelecido antes. Pode introduzir um elemento novo
(personagem, reviravolta, ameaça) desde que se conecte ao que já existe.

No FINAL do texto, depois da história, adicione uma linha separada exatamente assim:
RESUMO_INTERNO: [um resumo de 1-2 frases do que aconteceu NESTE capítulo especificamente]
"""
    return prompt


def montar_prompt_titulo(tipo_modo, universo_ou_serie, capitulo=None, titulos_recentes=None):
    titulos_recentes = titulos_recentes or []
    if tipo_modo == "continuacao":
        return f"""
Crie um título de capítulo em português do Brasil pra série "{universo_ou_serie}",
capítulo {capitulo}. Formato sugerido: "{universo_ou_serie} — Capítulo {capitulo}: [algo específico do capítulo]".
Responda apenas o título, texto puro, sem aspas.
"""
    return f"""
Crie um título de história em português do Brasil, envolvente, otimizado para SEO,
sem aspas, para uma história de ficção original sobre: {universo_ou_serie}.
NÃO pode ser parecido com nenhum destes já usados recentemente:
{chr(10).join(titulos_recentes[-15:]) if titulos_recentes else '(nenhum ainda)'}
Responda apenas o título, texto puro.
"""


def montar_prompt_serie_honorifico(premissa):
    """Gera um nome de série mais 'de capa de livro' quando um one-shot é promovido."""
    prefixo = random.choice(TITULOS_SERIE_HONORIFICOS)
    return prefixo  # usado como sugestão de estilo pro prompt de título, se quiser
