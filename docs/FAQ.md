# Perguntas frequentes

## O Kairós é consciente?

Não. Ele é uma arquitetura simulada de controle afetivo. “Emoção” aqui é um
estado de três eixos (valência, energia, previsibilidade) mais estresse e
política. Não há alegação de subjetividade ou consciência.

## É AGI?

Não. É um loop de controle com memória, política e LLM opcional.

## Ele controla meu computador?

Não no demo. O demo usa Guarda-Costas falso e não encerra processos. O
Guarda-Costas real em Rust é opcional e precisa ser compilado e revisado antes
de qualquer uso com processos reais.

## Precisa de GPU?

O demo não. O córtex real (LLM) é opcional e pode rodar via API ou llama-server
local. O piloto SV-01 com Qwen3-8B exige um ambiente maior, mas não está
autorizado.

## Ele executa os 64 runs?

Não. O piloto está bloqueado. O repositório traz o protocolo e a instrumentação,
não resultados experimentais.

## O que é “Maktub” nos arquivos?

É o codinome histórico da pesquisa. O framework público chama-se Kairós; os
artefatos congelados preservam o nome antigo para não alterar o experimento.

## Por que AGPLv3?

Porque o projeto quer que melhorias no software permaneçam abertas, inclusive
quando ele é oferecido como serviço de rede. Para uso comercial em produto
fechado, é possível negociar uma licença separada com o autor.

## Posso usar comercialmente?

Sob AGPL-3.0, sim, desde que cumpra a licença (incluindo disponibilizar o
código-fonte correspondente a usuários do serviço de rede). Para uso fechado,
fale com o mantenedor sobre licença comercial.

## O tokenizer/modelo Qwen está incluído?

Não. O tokenizer e os pesos não estão no repositório. Veja
`docs/RESEARCH_SV01.md` para a revisão e o procedimento de paridade.

## Como contribuir?

Leia `CONTRIBUTING.md`. Comece por uma issue pequena e bem descrita.
