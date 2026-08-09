# Robô de Fanfics e Histórias Originais

Gera 4 histórias por dia (2600+ palavras cada), publicadas no Blogger:
70% inspiradas em gêneros populares (sem usar nenhum nome/personagem real),
30% totalmente originais. Nenhuma franquia real é nomeada em nenhum momento —
só o clima/tropos do gênero são usados como inspiração.

## Arquivos

- `motor_fanfic.py` — estado, séries ativas, fila de promoção/encerramento
- `conteudo_fanfic.py` — pools de universos inspirados e originais
- `prompt_engine_fanfic.py` — monta os prompts (one-shot e continuação)
- `fanfic_diario.py` — orquestra tudo: geração, imagens, publicação no Blogger
- `postar_fanfic.yml` — workflow do GitHub Actions (copiar pra `.github/workflows/`)

## Como transformar uma história em série

1. Veja o `historico_fanfic.txt` (ou `estado_fanfic.json`) e ache o ID da
   história que você quer continuar (formato `h00012`).
2. Abra `promover_serie.txt` e adicione o ID numa linha nova.
3. No próximo dia, o robô lê esse arquivo, promove a história a série ativa,
   e garante 1 vaga certa entre as 4 diárias pra continuar o próximo capítulo,
   mantendo os mesmos personagens e a continuidade da trama.
4. Limite de 2 séries ativas ao mesmo tempo (dá pra mudar `MAX_SERIES_ATIVAS`
   em `motor_fanfic.py`). Se você promover mais do que cabe, o excedente
   fica na fila esperando uma vaga abrir.

## Como encerrar uma série

Adicione o ID da série (mesmo ID usado na promoção) numa linha em
`encerrar_serie.txt`. No próximo dia ela sai da lista de séries ativas.

## Variáveis de ambiente / secrets necessários

Mesmos dos outros robôs (`GROQ_API_KEY`, `BLOGGER_CLIENT_ID`,
`BLOGGER_CLIENT_SECRET`, `BLOGGER_REFRESH_TOKEN`, `POLLINATIONS_TOKEN`
opcional, `IMGBB_API_KEY`), mais um `BLOGGER_ID_FANFIC` apontando pro blog
dedicado a esse conteúdo (recomendado ser um blog separado dos outros).
