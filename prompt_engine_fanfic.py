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

PALAVRAS_MIN = 3400


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

PROFUNDIDADE E RITMO (isso é pra quem gosta de ler de verdade, não um resumo):
- Mínimo de {PALAVRAS_MIN} palavras — e use esse espaço pra desenvolver de verdade,
  não pra encher linguiça. Construa pelo menos 3 a 4 CENAS distintas (não uma
  cena só corrida do início ao fim).
- Escreva DIÁLOGO REAL entre os personagens — falas completas, com personalidade
  própria de cada um, não resumos tipo "eles conversaram sobre o plano".
  Diálogo é uma das partes que mais prende o leitor, não economize nele.
- Aprofunde a motivação interna do protagonista: o que ele sente, teme, deseja,
  não só o que ele faz.

REGRAS DE FORMATO (HTML puro, sem Markdown):
- PROIBIDO usar sintaxe de Markdown em QUALQUER lugar do texto: nada de "##"
  para subtítulo, nada de "**negrito**", nada de "*itálico*", nada de "> "
  pra citação. Use SOMENTE as tags HTML reais indicadas abaixo. Se você
  escrever "##" em algum ponto, está ERRADO — o subtítulo tem que ser uma
  tag <h2>...</h2> de verdade.
- TODO parágrafo normal de texto corrido deve vir envolvido em <p> e </p>,
  um parágrafo por bloco. Nunca deixe frases soltas sem tag ao redor.
- HOOK NO PRIMEIRO PARÁGRAFO: comece IN MEDIAS RES — uma linha de diálogo de
  impacto, uma pergunta intrigante, uma imagem sensorial forte, ou o personagem
  já no meio de uma decisão/ação. NUNCA comece com contexto/explicação genérica
  ("Há muito tempo, num reino distante..." está PROIBIDO). O leitor precisa
  querer continuar já na primeira frase.
- Pelo menos 4 subtítulos <h2>...</h2> ESPECÍFICOS da cena que introduzem (nunca
  rótulos genéricos tipo "Capítulo 1" sozinho — combine com algo que aconteceu
  nessa parte, ex: <h2>O Portão que Não Deveria Abrir</h2>). Cada <h2> marca
  uma cena/momento novo, sozinho em sua própria linha, sem texto colado nele.
- 1 a 2 <blockquote>...</blockquote> com uma fala ou pensamento marcante de
  um personagem.
- EXATAMENTE 3 "Notas do Autor" — comentários curtos, simpáticos e bem-humorados,
  em primeira pessoa, como se você (o autor do blog) estivesse comentando a
  própria história com o leitor nos bastidores (uma reação a uma cena, uma
  confissão de bastidor, uma brincadeira leve). É o que cria comunidade com
  quem acompanha o blog todo dia — tom sempre agradável e condizente com o
  momento da história, nunca fora de contexto. Formate CADA UMA exatamente
  assim (HTML literal, sem markdown):
  <div class="nota-autor" style="background:#fff8e1;border-left:4px solid #ffb300;
  padding:12px 16px;margin:20px 0;border-radius:6px;font-style:italic;">
  <strong>💬 Nota do Autor:</strong> [comentário aqui]</div>
  Posicione: a 1ª logo depois do hook de abertura, a 2ª no ponto de maior tensão
  da história, a 3ª perto do final, antes do gancho de encerramento.
- FINAL: feche o arco central desta história de forma satisfatória (o leitor
  não deve sentir que ficou pela metade) — e ENTÃO adicione um parágrafo curto
  final (2 a 4 linhas) como GANCHO para uma possível próxima aventura: uma
  pergunta em aberto, uma ameaça que ainda espreita, uma decisão que vai ecoar.
  É esse gancho que faz o leitor voltar amanhã.
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
