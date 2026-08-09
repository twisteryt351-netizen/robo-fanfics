# ─────────────────────────────────────────────────────────────
#  MOTOR DE ESTADO — Robô de Fanfics/Histórias Originais
#  Gerencia: séries ativas (com continuidade), histórico de
#  one-shots publicados (candidatos a virar série), e a fila
#  de promoção/encerramento manual controlada por você.
# ─────────────────────────────────────────────────────────────
import json
import os
import random

ARQUIVO_ESTADO = "estado_fanfic.json"
ARQUIVO_PROMOVER = "promover_serie.txt"
ARQUIVO_ENCERRAR = "encerrar_serie.txt"

MAX_SERIES_ATIVAS = 2       # quantas séries podem estar "em andamento" ao mesmo tempo
HISTORIAS_POR_DIA = 4
PROPORCAO_INSPIRADO = 0.70   # 70% inspirado / 30% original nas vagas de one-shot novo

JANELA_ANTIREPETICAO = 20    # quantos universos/templates recentes evitar repetir


def estado_padrao():
    return {
        "proximo_id": 1,
        "series_ativas": {},          # id -> {...} ver criar_entrada_serie()
        "historias_registradas": {},  # id -> {...} ver registrar_historia_nova()
        "historico_universos_inspirados": [],
        "historico_universos_originais": [],
        "historico_titulos": [],
    }


def carregar_estado():
    if not os.path.exists(ARQUIVO_ESTADO):
        estado = estado_padrao()
        salvar_estado(estado)
        return estado
    with open(ARQUIVO_ESTADO, "r", encoding="utf-8") as f:
        return json.load(f)


def salvar_estado(estado):
    with open(ARQUIVO_ESTADO, "w", encoding="utf-8") as f:
        json.dump(estado, f, ensure_ascii=False, indent=2)


def novo_id(estado):
    id_gerado = f"h{estado['proximo_id']:05d}"
    estado["proximo_id"] += 1
    return id_gerado


# ─────────────────────────────────────────────────────────────
#  ARQUIVOS DE CONTROLE MANUAL (você edita, o robô lê e limpa)
# ─────────────────────────────────────────────────────────────
def _ler_lista_arquivo(caminho):
    if not os.path.exists(caminho):
        return []
    with open(caminho, "r", encoding="utf-8") as f:
        return [l.strip() for l in f if l.strip() and not l.strip().startswith("#")]


def _limpar_arquivo(caminho):
    with open(caminho, "w", encoding="utf-8") as f:
        f.write("# Adicione um ID de história por linha (ex: h00012). Linhas com # são ignoradas.\n")


def processar_promocoes(estado):
    """Lê promover_serie.txt — cada ID válido que ainda não é série
    ativa (e se ainda há vaga) vira série a partir de hoje."""
    ids_pedidos = _ler_lista_arquivo(ARQUIVO_PROMOVER)
    if not ids_pedidos:
        return

    promovidos = []
    for id_historia in ids_pedidos:
        if len(estado["series_ativas"]) >= MAX_SERIES_ATIVAS:
            print(f"  ⚠️  Limite de {MAX_SERIES_ATIVAS} séries ativas atingido — "
                  f"'{id_historia}' fica na fila pra um próximo dia.")
            break
        if id_historia in estado["series_ativas"]:
            continue
        registro = estado["historias_registradas"].get(id_historia)
        if not registro:
            print(f"  ⚠️  ID '{id_historia}' não encontrado no histórico — ignorando.")
            continue

        estado["series_ativas"][id_historia] = {
            "titulo_serie": registro["titulo"],
            "tipo": registro["tipo"],
            "categoria": registro["categoria"],
            "universo_id": registro["universo_id"],
            "resumo_acumulado": registro["resumo"],
            "capitulo_atual": 1,
        }
        promovidos.append(id_historia)
        print(f"  🌟 '{registro['titulo']}' ({id_historia}) promovida a série!")

    # remove da fila só quem foi de fato processado (promovido ou não encontrado);
    # quem ficou pra trás por falta de vaga continua na fila pro próximo dia
    ids_restantes = [i for i in ids_pedidos if i not in promovidos
                      and i in estado["historias_registradas"]
                      and len(estado["series_ativas"]) < MAX_SERIES_ATIVAS]
    with open(ARQUIVO_PROMOVER, "w", encoding="utf-8") as f:
        f.write("# Adicione um ID de história por linha (ex: h00012). Linhas com # são ignoradas.\n")
        for i in ids_restantes:
            f.write(i + "\n")


def processar_encerramentos(estado):
    """Lê encerrar_serie.txt — cada ID listado sai de séries ativas."""
    ids_pedidos = _ler_lista_arquivo(ARQUIVO_ENCERRAR)
    if not ids_pedidos:
        return
    for id_historia in ids_pedidos:
        if id_historia in estado["series_ativas"]:
            titulo = estado["series_ativas"][id_historia]["titulo_serie"]
            del estado["series_ativas"][id_historia]
            print(f"  🏁 Série '{titulo}' ({id_historia}) encerrada.")
    _limpar_arquivo(ARQUIVO_ENCERRAR)


# ─────────────────────────────────────────────────────────────
#  PLANEJAMENTO DAS VAGAS DO DIA
# ─────────────────────────────────────────────────────────────
def planejar_slots(estado, quantidade=HISTORIAS_POR_DIA):
    """Retorna uma lista de 'tarefas' pro dia: continuações de séries
    ativas primeiro (1 vaga garantida por série), o resto preenchido
    com one-shots novos na proporção 70/30 inspirado/original."""
    tarefas = []

    for id_serie, dados in estado["series_ativas"].items():
        tarefas.append({"modo": "continuacao", "serie_id": id_serie, **dados})

    vagas_restantes = max(0, quantidade - len(tarefas))
    for _ in range(vagas_restantes):
        tipo = "inspirado" if random.random() < PROPORCAO_INSPIRADO else "original"
        tarefas.append({"modo": "one_shot", "tipo": tipo})

    return tarefas


# ─────────────────────────────────────────────────────────────
#  REGISTRO DE HISTÓRIAS / CONTINUAÇÃO DE SÉRIE
# ─────────────────────────────────────────────────────────────
def registrar_historia_nova(estado, titulo, tipo, universo_id, categoria, resumo):
    id_historia = novo_id(estado)
    estado["historias_registradas"][id_historia] = {
        "titulo": titulo, "tipo": tipo, "universo_id": universo_id,
        "categoria": categoria, "resumo": resumo,
    }
    if tipo == "inspirado":
        estado["historico_universos_inspirados"].append(universo_id)
        estado["historico_universos_inspirados"] = estado["historico_universos_inspirados"][-JANELA_ANTIREPETICAO:]
    else:
        estado["historico_universos_originais"].append(universo_id)
        estado["historico_universos_originais"] = estado["historico_universos_originais"][-JANELA_ANTIREPETICAO:]
    return id_historia


def registrar_titulo(estado, titulo):
    estado["historico_titulos"].append(titulo)
    estado["historico_titulos"] = estado["historico_titulos"][-40:]


def avancar_capitulo_serie(estado, serie_id, resumo_do_capitulo, novo_titulo_capitulo):
    serie = estado["series_ativas"][serie_id]
    serie["capitulo_atual"] += 1
    serie["resumo_acumulado"] += f" [Cap. {serie['capitulo_atual']}: {resumo_do_capitulo}]"
    # também atualiza o registro mestre da história (usado se um dia for
    # necessário consultar título/resumo mais recente fora do dict de série)
    if serie_id in estado["historias_registradas"]:
        estado["historias_registradas"][serie_id]["resumo"] = serie["resumo_acumulado"]
