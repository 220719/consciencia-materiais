-- Rede de Materiais v2
-- Não apaga tabelas antigas (professores, materiais, parametros_rede, rota_sintese).
-- Artigo único (DOI normalizado); PDF no Storage; segundo pesquisador pode
-- cadastrar amostras na mesma fonte.

create or replace function public.normalizar_doi(d text)
returns text
language sql
immutable
parallel safe
as $$
  select nullif(
    lower(trim(both from regexp_replace(
      regexp_replace(
        regexp_replace(coalesce(d, ''), '^https?://(dx\.)?doi\.org/', '', 'i'),
        '^doi:\s*', '', 'i'
      ),
      '\s+', '', 'g'
    ))),
    ''
  );
$$;

create or replace function public.nulo_se_zero(n numeric)
returns numeric
language sql
immutable
parallel safe
as $$
  select case when n is null or n = 0 then null else n end;
$$;

create table if not exists public.pesquisadores (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null unique references auth.users (id),
  orcid_id text unique,
  nome text,
  email text,
  afiliacao text,
  aprovado boolean not null default true,
  criado_em timestamptz not null default now()
);

comment on table public.pesquisadores is
  'Quem alimenta a base. Substitui professores no modelo v2.';

create table if not exists public.grupos_espaciais (
  id uuid primary key default gen_random_uuid(),
  numero integer not null check (numero between 1 and 230),
  ext text not null default '',
  hm text not null,
  xhm text,
  hall text,
  sistema_cristalino text not null,
  classe_laue text,
  centrossimetrico boolean,
  restricao_cela jsonb not null default '{}'::jsonb,
  unique (numero, ext)
);

comment on column public.grupos_espaciais.restricao_cela is
  'Ex.: {"b":"a","c":"a","alpha":90,"beta":90,"gamma":90} para cúbico.';

create table if not exists public.fontes (
  id uuid primary key default gen_random_uuid(),
  tipo text not null default 'artigo'
    check (tipo in ('artigo', 'laboratorio', 'legado', 'outro')),
  doi text,
  doi_normalizado text,
  titulo text,
  autores text,
  periodico text,
  ano integer check (ano is null or ano between 1800 and 2100),
  url text,
  arquivo_path text,
  arquivo_nome_original text,
  arquivo_mime text,
  arquivo_bytes integer check (arquivo_bytes is null or arquivo_bytes > 0),
  arquivo_sha256 text,
  inserido_por uuid not null references public.pesquisadores (id),
  criado_em timestamptz not null default now()
);

create unique index if not exists fontes_doi_normalizado_uidx
  on public.fontes (doi_normalizado)
  where doi_normalizado is not null;

create unique index if not exists fontes_sha256_uidx
  on public.fontes (arquivo_sha256)
  where arquivo_sha256 is not null;

create index if not exists fontes_inserido_por_idx on public.fontes (inserido_por);

comment on column public.fontes.doi_normalizado is
  'DOI sem URL, minúsculas. UNIQUE parcial: o artigo entra uma vez. NULL livre (lab/legado).';

create table if not exists public.composicoes (
  id uuid primary key default gen_random_uuid(),
  formula text not null,
  formula_geral text,
  nome_comum text,
  familia_estrutural text,
  aplicacao_alvo text,
  dopante text,
  site_substituicao text check (site_substituicao is null or site_substituicao in ('A', 'B', 'ambos')),
  x_nominal numeric(10, 6) check (x_nominal is null or (x_nominal >= 0 and x_nominal <= 1)),
  percentual_dopagem numeric check (percentual_dopagem is null or (percentual_dopagem >= 0 and percentual_dopagem <= 100)),
  notas text,
  criado_em timestamptz not null default now()
);

create index if not exists composicoes_formula_idx
  on public.composicoes (lower(formula));

create table if not exists public.amostras (
  id uuid primary key default gen_random_uuid(),
  composicao_id uuid not null references public.composicoes (id) on delete restrict,
  fonte_id uuid references public.fontes (id) on delete restrict,
  rotulo text,
  forma text check (forma is null or forma in ('cristal', 'po', 'ceramica', 'filme', 'outro')),
  inserido_por uuid not null references public.pesquisadores (id),
  criado_em timestamptz not null default now()
);

create unique index if not exists amostras_fonte_composicao_pesquisador_uidx
  on public.amostras (fonte_id, composicao_id, inserido_por)
  where fonte_id is not null;

create index if not exists amostras_fonte_idx on public.amostras (fonte_id);
create index if not exists amostras_composicao_idx on public.amostras (composicao_id);
create index if not exists amostras_inserido_por_idx on public.amostras (inserido_por);

comment on index public.amostras_fonte_composicao_pesquisador_uidx is
  'O mesmo pesquisador não grava a mesma composição duas vezes no mesmo artigo. Outro pesquisador pode.';

create table if not exists public.rotas_sintese (
  id uuid primary key default gen_random_uuid(),
  amostra_id uuid not null unique references public.amostras (id) on delete cascade,
  metodo text,
  precursores text,
  temp_calcinacao numeric,
  tempo_calcinacao numeric,
  temp_sinterizacao numeric,
  tempo_sinterizacao numeric,
  taxa_aquecimento numeric,
  taxa_resfriamento numeric,
  atmosfera text check (atmosfera is null or atmosfera in ('Ar', 'O2', 'N2', 'Vacuo', 'Vácuo', 'Ar/O2')),
  observacao text,
  criado_em timestamptz not null default now()
);

create table if not exists public.medidas_estruturais (
  id uuid primary key default gen_random_uuid(),
  amostra_id uuid not null references public.amostras (id) on delete cascade,
  fonte_id uuid references public.fontes (id) on delete restrict,
  condicao text,
  temperatura_k numeric check (temperatura_k is null or (temperatura_k >= 0 and temperatura_k <= 4000)),
  pressao_gpa numeric check (pressao_gpa is null or pressao_gpa >= 0),
  grupo_espacial_id uuid references public.grupos_espaciais (id),
  grupo_espacial_hm text,
  setting text check (setting is null or setting in ('hexagonal', 'romboedrico')),
  sistema_cristalino text check (
    sistema_cristalino is null or sistema_cristalino in (
      'Cúbico', 'Tetragonal', 'Ortorrômbico', 'Romboédrico',
      'Hexagonal', 'Monoclínico', 'Triclínico'
    )
  ),
  a numeric(14, 7),
  a_esd numeric(14, 7),
  b numeric(14, 7),
  b_esd numeric(14, 7),
  c numeric(14, 7),
  c_esd numeric(14, 7),
  alpha numeric(10, 5),
  alpha_esd numeric(10, 5),
  beta numeric(10, 5),
  beta_esd numeric(10, 5),
  gamma numeric(10, 5),
  gamma_esd numeric(10, 5),
  volume numeric(16, 6),
  volume_esd numeric(16, 6),
  z integer check (z is null or z > 0),
  fracao_fase numeric check (fracao_fase is null or (fracao_fase >= 0 and fracao_fase <= 1)),
  tecnica_medicao text check (
    tecnica_medicao is null or tecnica_medicao in (
      'DRX laboratório (Cu Kα)', 'Síncrotron', 'Nêutrons', 'Monocristal', 'Outra'
    )
  ),
  radiacao text,
  comprimento_onda_a numeric(10, 6),
  instrumento text,
  ccdc_ou_cod text,
  status text not null default 'extraido'
    check (status in ('extraido', 'revisado', 'medido')),
  inserido_por uuid not null references public.pesquisadores (id),
  revisado_por uuid references public.pesquisadores (id),
  revisado_em timestamptz,
  criado_em timestamptz not null default now(),
  check (a is null or a > 0),
  check (b is null or b > 0),
  check (c is null or c > 0)
);

create index if not exists medidas_amostra_idx on public.medidas_estruturais (amostra_id);
create index if not exists medidas_fonte_idx on public.medidas_estruturais (fonte_id);
create index if not exists medidas_temperatura_idx on public.medidas_estruturais (temperatura_k);

create unique index if not exists medidas_amostra_condicao_uidx
  on public.medidas_estruturais (
    amostra_id,
    coalesce(temperatura_k, -1),
    coalesce(grupo_espacial_hm, ''),
    coalesce(condicao, '')
  );

-- ---------- triggers ----------

create or replace function public.fontes_antes_gravar()
returns trigger
language plpgsql
as $$
begin
  new.doi_normalizado := public.normalizar_doi(new.doi);
  if new.arquivo_sha256 is not null then
    new.arquivo_sha256 := lower(new.arquivo_sha256);
  end if;
  return new;
end;
$$;

drop trigger if exists fontes_antes_gravar on public.fontes;
create trigger fontes_antes_gravar
  before insert or update of doi, arquivo_sha256 on public.fontes
  for each row execute function public.fontes_antes_gravar();

create or replace function public.composicoes_preencher_x()
returns trigger
language plpgsql
as $$
begin
  new.formula := nullif(trim(new.formula), '');
  if new.formula is null then
    raise exception 'formula é obrigatória';
  end if;
  if new.x_nominal is null and new.percentual_dopagem is not null then
    new.x_nominal := new.percentual_dopagem / 100.0;
  elsif new.percentual_dopagem is null and new.x_nominal is not null then
    new.percentual_dopagem := new.x_nominal * 100.0;
  end if;
  return new;
end;
$$;

drop trigger if exists composicoes_preencher_x on public.composicoes;
create trigger composicoes_preencher_x
  before insert or update on public.composicoes
  for each row execute function public.composicoes_preencher_x();

create or replace function public.aplicar_restricao_cela()
returns trigger
language plpgsql
as $$
declare
  r jsonb := '{}'::jsonb;
  sistema text;
begin
  new.a := public.nulo_se_zero(new.a);
  new.b := public.nulo_se_zero(new.b);
  new.c := public.nulo_se_zero(new.c);

  if new.grupo_espacial_id is not null then
    select restricao_cela, sistema_cristalino
      into r, sistema
      from public.grupos_espaciais
     where id = new.grupo_espacial_id;
    if sistema is not null and new.sistema_cristalino is null then
      new.sistema_cristalino := sistema;
    end if;
  end if;

  sistema := coalesce(new.sistema_cristalino, sistema);

  if r = '{}'::jsonb or r is null then
    if sistema = 'Cúbico' then
      r := '{"b":"a","c":"a","alpha":90,"beta":90,"gamma":90}'::jsonb;
    elsif sistema = 'Tetragonal' then
      r := '{"b":"a","alpha":90,"beta":90,"gamma":90}'::jsonb;
    elsif sistema = 'Hexagonal' then
      r := '{"b":"a","alpha":90,"beta":90,"gamma":120}'::jsonb;
    elsif sistema = 'Romboédrico' then
      r := '{"b":"a","c":"a","beta":"alpha","gamma":"alpha"}'::jsonb;
    elsif sistema = 'Ortorrômbico' then
      r := '{"alpha":90,"beta":90,"gamma":90}'::jsonb;
    end if;
  end if;

  if r->>'b' = 'a' and new.a is not null then
    new.b := new.a;
    new.b_esd := coalesce(new.b_esd, new.a_esd);
  end if;
  if r->>'c' = 'a' and new.a is not null then
    new.c := new.a;
    new.c_esd := coalesce(new.c_esd, new.a_esd);
  end if;
  if jsonb_typeof(r->'alpha') = 'number' then
    new.alpha := (r->>'alpha')::numeric;
  end if;
  if r->>'beta' = 'alpha' then
    new.beta := new.alpha;
  elsif jsonb_typeof(r->'beta') = 'number' then
    new.beta := (r->>'beta')::numeric;
  end if;
  if r->>'gamma' = 'alpha' then
    new.gamma := new.alpha;
  elsif jsonb_typeof(r->'gamma') = 'number' then
    new.gamma := (r->>'gamma')::numeric;
  end if;

  if new.fonte_id is null then
    select fonte_id into new.fonte_id from public.amostras where id = new.amostra_id;
  end if;
  return new;
end;
$$;

drop trigger if exists medidas_aplicar_restricao on public.medidas_estruturais;
create trigger medidas_aplicar_restricao
  before insert or update on public.medidas_estruturais
  for each row execute function public.aplicar_restricao_cela();

create or replace function public.pesquisador_esta_aprovado()
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1 from public.pesquisadores
    where user_id = auth.uid() and aprovado is true
  );
$$;

create or replace function public.pesquisador_id_atual()
returns uuid
language sql
stable
security definer
set search_path = public
as $$
  select id from public.pesquisadores where user_id = auth.uid() limit 1;
$$;

-- ---------- RLS ----------

alter table public.pesquisadores enable row level security;
alter table public.grupos_espaciais enable row level security;
alter table public.fontes enable row level security;
alter table public.composicoes enable row level security;
alter table public.amostras enable row level security;
alter table public.rotas_sintese enable row level security;
alter table public.medidas_estruturais enable row level security;

drop policy if exists select_pesquisadores on public.pesquisadores;
create policy select_pesquisadores on public.pesquisadores
  for select to authenticated using (true);
drop policy if exists insert_own_pesquisador on public.pesquisadores;
create policy insert_own_pesquisador on public.pesquisadores
  for insert to authenticated with check (auth.uid() = user_id);
drop policy if exists update_own_pesquisador on public.pesquisadores;
create policy update_own_pesquisador on public.pesquisadores
  for update to authenticated
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

drop policy if exists select_grupos_espaciais on public.grupos_espaciais;
create policy select_grupos_espaciais on public.grupos_espaciais
  for select to authenticated using (true);

drop policy if exists select_fontes on public.fontes;
create policy select_fontes on public.fontes
  for select to authenticated using (public.pesquisador_esta_aprovado());
drop policy if exists insert_fontes on public.fontes;
create policy insert_fontes on public.fontes
  for insert to authenticated
  with check (
    public.pesquisador_esta_aprovado()
    and inserido_por = public.pesquisador_id_atual()
  );
drop policy if exists update_own_fontes on public.fontes;
create policy update_own_fontes on public.fontes
  for update to authenticated
  using (inserido_por = public.pesquisador_id_atual())
  with check (inserido_por = public.pesquisador_id_atual());

drop policy if exists select_composicoes on public.composicoes;
create policy select_composicoes on public.composicoes
  for select to authenticated using (public.pesquisador_esta_aprovado());
drop policy if exists insert_composicoes on public.composicoes;
create policy insert_composicoes on public.composicoes
  for insert to authenticated with check (public.pesquisador_esta_aprovado());
drop policy if exists update_composicoes on public.composicoes;
create policy update_composicoes on public.composicoes
  for update to authenticated
  using (public.pesquisador_esta_aprovado())
  with check (public.pesquisador_esta_aprovado());

drop policy if exists select_amostras on public.amostras;
create policy select_amostras on public.amostras
  for select to authenticated using (public.pesquisador_esta_aprovado());
drop policy if exists insert_amostras on public.amostras;
create policy insert_amostras on public.amostras
  for insert to authenticated
  with check (
    public.pesquisador_esta_aprovado()
    and inserido_por = public.pesquisador_id_atual()
  );
drop policy if exists update_own_amostras on public.amostras;
create policy update_own_amostras on public.amostras
  for update to authenticated
  using (inserido_por = public.pesquisador_id_atual())
  with check (inserido_por = public.pesquisador_id_atual());

drop policy if exists select_rotas_sintese on public.rotas_sintese;
create policy select_rotas_sintese on public.rotas_sintese
  for select to authenticated using (public.pesquisador_esta_aprovado());
drop policy if exists insert_rotas_sintese on public.rotas_sintese;
create policy insert_rotas_sintese on public.rotas_sintese
  for insert to authenticated
  with check (
    public.pesquisador_esta_aprovado()
    and amostra_id in (select id from public.amostras where inserido_por = public.pesquisador_id_atual())
  );
drop policy if exists update_own_rotas_sintese on public.rotas_sintese;
create policy update_own_rotas_sintese on public.rotas_sintese
  for update to authenticated
  using (amostra_id in (select id from public.amostras where inserido_por = public.pesquisador_id_atual()))
  with check (amostra_id in (select id from public.amostras where inserido_por = public.pesquisador_id_atual()));

drop policy if exists select_medidas on public.medidas_estruturais;
create policy select_medidas on public.medidas_estruturais
  for select to authenticated using (public.pesquisador_esta_aprovado());
drop policy if exists insert_medidas on public.medidas_estruturais;
create policy insert_medidas on public.medidas_estruturais
  for insert to authenticated
  with check (
    public.pesquisador_esta_aprovado()
    and inserido_por = public.pesquisador_id_atual()
    and amostra_id in (select id from public.amostras where inserido_por = public.pesquisador_id_atual())
  );
drop policy if exists update_own_medidas on public.medidas_estruturais;
create policy update_own_medidas on public.medidas_estruturais
  for update to authenticated
  using (inserido_por = public.pesquisador_id_atual())
  with check (inserido_por = public.pesquisador_id_atual());

grant execute on function public.normalizar_doi(text) to anon, authenticated;
grant execute on function public.pesquisador_esta_aprovado() to anon, authenticated;
grant execute on function public.pesquisador_id_atual() to anon, authenticated;

grant select, insert, update, delete on table
  public.pesquisadores,
  public.grupos_espaciais,
  public.fontes,
  public.composicoes,
  public.amostras,
  public.rotas_sintese,
  public.medidas_estruturais
to anon, authenticated, service_role;

-- Storage: bucket privado de PDFs
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('artigos', 'artigos', false, 26214400, array['application/pdf'])
on conflict (id) do update set
  public = excluded.public,
  file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;

drop policy if exists artigos_select on storage.objects;
create policy artigos_select on storage.objects
  for select to authenticated
  using (bucket_id = 'artigos' and public.pesquisador_esta_aprovado());

drop policy if exists artigos_insert on storage.objects;
create policy artigos_insert on storage.objects
  for insert to authenticated
  with check (bucket_id = 'artigos' and public.pesquisador_esta_aprovado());

drop policy if exists artigos_update on storage.objects;
create policy artigos_update on storage.objects
  for update to authenticated
  using (bucket_id = 'artigos' and public.pesquisador_esta_aprovado())
  with check (bucket_id = 'artigos' and public.pesquisador_esta_aprovado());

-- Seed mínimo de grupos (perovskitas / artigos-exemplo)
insert into public.grupos_espaciais
  (numero, ext, hm, xhm, sistema_cristalino, classe_laue, centrossimetrico, restricao_cela)
values
  (1,  '', 'P1',     'P 1',     'Triclínico',   '-1',  false, '{}'::jsonb),
  (2,  '', 'P-1',    'P -1',    'Triclínico',   '-1',  true,  '{}'::jsonb),
  (14, '', 'P21/c',  'P 1 21/c 1', 'Monoclínico', '2/m', true, '{"alpha":90,"gamma":90}'::jsonb),
  (55, '', 'Pbam',   'P b a m', 'Ortorrômbico', 'mmm', true,  '{"alpha":90,"beta":90,"gamma":90}'::jsonb),
  (62, '', 'Pnma',   'P n m a', 'Ortorrômbico', 'mmm', true,  '{"alpha":90,"beta":90,"gamma":90}'::jsonb),
  (99, '', 'P4mm',   'P 4 m m', 'Tetragonal',   '4mm', false, '{"b":"a","alpha":90,"beta":90,"gamma":90}'::jsonb),
  (123,'', 'P4/mmm', 'P 4/m m m','Tetragonal',  '4/mmm', true, '{"b":"a","alpha":90,"beta":90,"gamma":90}'::jsonb),
  (160,'', 'R3m',    'R 3 m',   'Romboédrico',  '3m',  false, '{"b":"a","alpha":90,"beta":90,"gamma":120}'::jsonb),
  (161,'', 'R3c',    'R 3 c',   'Romboédrico',  '3m',  false, '{"b":"a","alpha":90,"beta":90,"gamma":120}'::jsonb),
  (166,'', 'R-3m',   'R -3 m',  'Romboédrico',  '-3m', true,  '{"b":"a","alpha":90,"beta":90,"gamma":120}'::jsonb),
  (167,'', 'R-3c',   'R -3 c',  'Romboédrico',  '-3m', true,  '{"b":"a","alpha":90,"beta":90,"gamma":120}'::jsonb),
  (194,'', 'P63/mmc','P 63/m m c','Hexagonal',  '6/mmm', true, '{"b":"a","alpha":90,"beta":90,"gamma":120}'::jsonb),
  (221,'', 'Pm-3m',  'P m -3 m','Cúbico',       'm-3m', true,  '{"b":"a","c":"a","alpha":90,"beta":90,"gamma":90}'::jsonb),
  (225,'', 'Fm-3m',  'F m -3 m','Cúbico',       'm-3m', true,  '{"b":"a","c":"a","alpha":90,"beta":90,"gamma":90}'::jsonb),
  (227,'', 'Fd-3m',  'F d -3 m','Cúbico',       'm-3m', true,  '{"b":"a","c":"a","alpha":90,"beta":90,"gamma":90}'::jsonb)
on conflict (numero, ext) do nothing;
