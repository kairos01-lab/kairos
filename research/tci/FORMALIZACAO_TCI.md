# Formalização limpa das previsões da TCI-F

> **Isto é uma formalização, não um resultado.** O V19 foi reprovado; as
> previsões abaixo são o que uma versão futura precisaria testar.

## P1 — Acoplamento Φ

Definição operacional:

```text
Φ_TCI = TE média entre os componentes especificados do sistema.
```

TE (transferência de entropia) mede dependência preditiva direcional. Ela **não
é** Φ_MIP. Se a hipótese for sobre Φ_MIP, é preciso implementar Φ_MIP
(bipartipação + D_KL) ou renomear a hipótese para “TE × Σ”, sem alegar que é TCI.

A previsão: a relação entre Φ e estabilidade/desempenho não é necessariamente
linear; pode haver uma região de transição crítica.

Falsificação: sob ruído e parâmetros controlados, não observar nenhuma relação
pré-especificada entre Φ e estabilidade, dentro do poder estatístico planejado,
enfraquece/refuta esta previsão operacional.

## P2 — Irreversibilidade Σ

Definição operacional:

```text
Σ ≈ D_KL(P_forward || P_reverse)
```

ou uma medida equivalente de produção de entropia/irreversibilidade, declarada
antes dos dados.

A previsão: mantidos constantes armazenamento, ruído, arquitetura e tarefa, a
retenção histórica R aumenta monotonicamente com Σ.

**Não** declarar automaticamente que Σ = 0 implica amnésia. Markovidade não é o
mesmo que ausência de memória: o estado atual pode carregar história. A
implicação “Σ→0 ⇒ amnésia” precisa ser uma hipótese independente e testada.

## P3 — Acoplamento × irreversibilidade

Modelo:

```text
S = β0 + β1·Φ + β2·Σ + β3·(Φ·Σ) + ε
```

Previsão principal: `β3 > 0`.

“β3 é dominante” é uma **segunda** hipótese, mais forte. Pode ocorrer
`β1 > 0`, `β2 > 0`, `β3 > 0` e `β3` pequeno; isso não refuta a interação, apenas
a afirmação de dominância.

Falsificação: um experimento com poder adequado que produza um limite superior
compatível com ausência de interação, ou um efeito claramente abaixo da margem
mínima teoricamente relevante, enfraquece/refuta a previsão. Não basta
`β3 ≤ 0` com IC largo; isso é inconclusivo.

## Variável dependente

Não usar “inteligência emergente” como variável dependente antes de
operacionalizá-la. Prefira medidas observáveis:

- retenção;
- previsão;
- adaptação;
- planejamento;
- desempenho sob perturbação;
- recuperação após mudança de ambiente.

Depois se pergunta se o conjunto produz o fenômeno que o projeto chama de
complexidade/inteligência emergente. Isso evita circularidade.

## Status

Estas previsões não foram testadas de forma válida no V19. O V19 operacionalizou
Φ como TE e teve problemas de independência e de desfecho. Veja
`AUDITORIA_REDTEAM_V19_FASE_A.md`.
