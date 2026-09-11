-- Rede de Materiais — permite várias medidas por material.
-- Um artigo pode relatar o mesmo composto em várias temperaturas ou fases:
-- cada conjunto de parâmetros de rede vira uma linha em parametros_rede.
-- Rode no SQL Editor do Supabase. É aditivo e não apaga dado existente.

alter table public.parametros_rede
    add column if not exists condicao text,
    add column if not exists temperatura_k numeric;

comment on column public.parametros_rede.condicao is
    'Como o artigo identifica a medida. Ex: "298 K", "fase cúbica", "após sinterização".';
comment on column public.parametros_rede.temperatura_k is
    'Temperatura da medida, em kelvin.';

create index if not exists parametros_rede_material_idx
    on public.parametros_rede (material_id);
