-- public.concept definition

-- Drop table

-- DROP TABLE public.concept;

CREATE TABLE public.concept (
	id bigserial NOT NULL,
	"key" text NOT NULL,
	"label" text NULL,
	embedding public.vector NULL,
	created_at timestamptz DEFAULT now() NULL,
	CONSTRAINT concept_key_key UNIQUE (key),
	CONSTRAINT concept_pkey PRIMARY KEY (id)
);


-- public.corpus_jsonl definition

-- Drop table

-- DROP TABLE public.corpus_jsonl;

CREATE TABLE public.corpus_jsonl (
	id bigserial NOT NULL,
	"domain" text NOT NULL,
	doc_key text NOT NULL,
	payload text NOT NULL,
	meta jsonb NULL,
	created_at timestamptz DEFAULT now() NULL,
	CONSTRAINT corpus_jsonl_pkey PRIMARY KEY (id)
);
CREATE INDEX corpus_jsonl_doc_idx ON public.corpus_jsonl USING btree (domain, doc_key);


-- public.corpus_xml definition

-- Drop table

-- DROP TABLE public.corpus_xml;

CREATE TABLE public.corpus_xml (
	id bigserial NOT NULL,
	"domain" text NOT NULL,
	doc_key text NOT NULL,
	xml_payload xml NOT NULL,
	meta jsonb NULL,
	created_at timestamptz DEFAULT now() NULL,
	CONSTRAINT corpus_xml_pkey PRIMARY KEY (id)
);


-- public.curvature_multi definition

-- Drop table

-- DROP TABLE public.curvature_multi;

CREATE TABLE public.curvature_multi (
	session_id text NULL,
	"domain" text NULL,
	ch_a text NULL,
	ch_b text NULL,
	s_sent int4 NULL,
	t_sent int4 NULL,
	da public.vector NULL,
	db public.vector NULL,
	weight float8 NULL,
	frame_a int4 NULL,
	frame_b int4 NULL
);
CREATE INDEX curvature_multi_dom_idx ON public.curvature_multi USING btree (domain);
CREATE INDEX curvature_multi_frame_idx ON public.curvature_multi USING btree (frame_a, frame_b);


-- public.persona definition

-- Drop table

-- DROP TABLE public.persona;

CREATE TABLE public.persona (
	id bigserial NOT NULL,
	"name" text NOT NULL,
	stance jsonb NULL,
	CONSTRAINT persona_name_key UNIQUE (name),
	CONSTRAINT persona_pkey PRIMARY KEY (id)
);


-- public.ring definition

-- Drop table

-- DROP TABLE public.ring;

CREATE TABLE public.ring (
	id smallserial NOT NULL,
	"name" text NOT NULL,
	order_idx int4 NOT NULL,
	"operator" text NULL,
	CONSTRAINT ring_name_key UNIQUE (name),
	CONSTRAINT ring_pkey PRIMARY KEY (id)
);


-- public.root_truth definition

-- Drop table

-- DROP TABLE public.root_truth;

CREATE TABLE public.root_truth (
	id serial4 NOT NULL,
	code text NOT NULL,
	"name" text NOT NULL,
	description text NULL,
	CONSTRAINT root_truth_code_key UNIQUE (code),
	CONSTRAINT root_truth_pkey PRIMARY KEY (id)
);


-- public.truth definition

-- Drop table

-- DROP TABLE public.truth;

CREATE TABLE public.truth (
	id bigserial NOT NULL,
	claim text NOT NULL,
	"method" text NULL,
	evidence jsonb NULL,
	confidence float8 NULL,
	"source" text NULL,
	posit_id int8 NULL,
	created_at timestamptz DEFAULT now() NULL,
	frame_pair text NULL,
	CONSTRAINT truth_pkey PRIMARY KEY (id)
);
CREATE INDEX truth_framepair_idx ON public.truth USING btree (frame_pair);


-- public.doc_unit definition

-- Drop table

-- DROP TABLE public.doc_unit;

CREATE TABLE public.doc_unit (
	id bigserial NOT NULL,
	"domain" text NOT NULL,
	doc_key text NOT NULL,
	kind text NOT NULL,
	"label" text NULL,
	"path" public.ltree NOT NULL,
	ordinal int4 NULL,
	"text" text NULL,
	meta jsonb NULL,
	parent_id int8 NULL,
	CONSTRAINT doc_unit_pkey PRIMARY KEY (id),
	CONSTRAINT doc_unit_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES public.doc_unit(id) ON DELETE CASCADE
);
CREATE INDEX doc_unit_domain_idx ON public.doc_unit USING btree (domain);
CREATE INDEX doc_unit_kind_idx ON public.doc_unit USING btree (kind);
CREATE INDEX doc_unit_meta_idx ON public.doc_unit USING gin (meta jsonb_path_ops);
CREATE INDEX doc_unit_path_gist ON public.doc_unit USING gist (path);
CREATE INDEX doc_unit_path_idx ON public.doc_unit USING gist (path);
CREATE UNIQUE INDEX doc_unit_uq_path ON public.doc_unit USING btree (domain, doc_key, path);


-- public.frame definition

-- Drop table

-- DROP TABLE public.frame;

CREATE TABLE public.frame (
	id serial4 NOT NULL,
	root_id int4 NULL,
	code text NOT NULL,
	"name" text NOT NULL,
	dimension text NULL,
	"language" text NULL,
	moral_axis jsonb DEFAULT '{}'::jsonb NULL,
	notes text NULL,
	CONSTRAINT frame_code_key UNIQUE (code),
	CONSTRAINT frame_pkey PRIMARY KEY (id),
	CONSTRAINT frame_root_id_fkey FOREIGN KEY (root_id) REFERENCES public.root_truth(id) ON DELETE CASCADE
);


-- public."move" definition

-- Drop table

-- DROP TABLE public."move";

CREATE TABLE public."move" (
	id bigserial NOT NULL,
	session_id text NULL,
	"domain" text NULL,
	channel text NULL,
	span jsonb NULL,
	features public.vector NULL,
	created_at timestamptz DEFAULT now() NULL,
	frame_id int4 NULL,
	CONSTRAINT move_pkey PRIMARY KEY (id),
	CONSTRAINT move_frame_id_fkey FOREIGN KEY (frame_id) REFERENCES public.frame(id)
);
CREATE INDEX move_domain_channel_idx ON public.move USING btree (domain, channel);
CREATE INDEX move_frame_idx ON public.move USING btree (frame_id);
CREATE INDEX move_session_id_idx ON public.move USING btree (session_id);


-- public.move_edge definition

-- Drop table

-- DROP TABLE public.move_edge;

CREATE TABLE public.move_edge (
	id bigserial NOT NULL,
	source_move int8 NULL,
	target_move int8 NULL,
	channel text NULL,
	delta public.vector NULL,
	weight float8 DEFAULT 0.0 NULL,
	freq int4 DEFAULT 0 NULL,
	last_seen timestamptz DEFAULT now() NULL,
	context jsonb NULL,
	frame_id int4 NULL,
	CONSTRAINT move_edge_pkey PRIMARY KEY (id),
	CONSTRAINT move_edge_frame_id_fkey FOREIGN KEY (frame_id) REFERENCES public.frame(id),
	CONSTRAINT move_edge_source_move_fkey FOREIGN KEY (source_move) REFERENCES public."move"(id) ON DELETE CASCADE,
	CONSTRAINT move_edge_target_move_fkey FOREIGN KEY (target_move) REFERENCES public."move"(id) ON DELETE CASCADE
);
CREATE INDEX move_edge_ch_idx ON public.move_edge USING btree (channel);
CREATE UNIQUE INDEX move_edge_uniq ON public.move_edge USING btree (source_move, target_move, channel);
CREATE INDEX moveedge_frame_idx ON public.move_edge USING btree (frame_id);


-- public.observation definition

-- Drop table

-- DROP TABLE public.observation;

CREATE TABLE public.observation (
	id bigserial NOT NULL,
	session_id text NULL,
	seq int4 NULL,
	concept_id int8 NULL,
	outcome text NULL,
	"at" timestamptz DEFAULT now() NULL,
	CONSTRAINT observation_pkey PRIMARY KEY (id),
	CONSTRAINT observation_concept_id_fkey FOREIGN KEY (concept_id) REFERENCES public.concept(id)
);
CREATE INDEX obs_session_seq_idx ON public.observation USING btree (session_id, seq);


-- public.posit definition

-- Drop table

-- DROP TABLE public.posit;

CREATE TABLE public.posit (
	id bigserial NOT NULL,
	author_id int8 NULL,
	"statement" text NOT NULL,
	"domain" text NULL,
	kind text NULL,
	status text DEFAULT 'pinned'::text NULL,
	method_pref jsonb NULL,
	created_at timestamptz DEFAULT now() NULL,
	frame_id int4 NULL,
	CONSTRAINT posit_pkey PRIMARY KEY (id),
	CONSTRAINT posit_author_id_fkey FOREIGN KEY (author_id) REFERENCES public.persona(id),
	CONSTRAINT posit_frame_id_fkey FOREIGN KEY (frame_id) REFERENCES public.frame(id)
);
CREATE INDEX posit_author_idx ON public.posit USING btree (author_id);


-- public.posit_query definition

-- Drop table

-- DROP TABLE public.posit_query;

CREATE TABLE public.posit_query (
	id bigserial NOT NULL,
	posit_id int8 NULL,
	prompt text NOT NULL,
	kind text NULL,
	state text DEFAULT 'open'::text NULL,
	created_at timestamptz DEFAULT now() NULL,
	CONSTRAINT posit_query_pkey PRIMARY KEY (id),
	CONSTRAINT posit_query_posit_id_fkey FOREIGN KEY (posit_id) REFERENCES public.posit(id) ON DELETE CASCADE
);


-- public.trajectory definition

-- Drop table

-- DROP TABLE public.trajectory;

CREATE TABLE public.trajectory (
	id bigserial NOT NULL,
	source_id int8 NOT NULL,
	target_id int8 NOT NULL,
	delta public.vector NULL,
	weight float8 DEFAULT 0.0 NULL,
	freq int4 DEFAULT 0 NULL,
	last_seen timestamptz DEFAULT now() NULL,
	context jsonb NULL,
	CONSTRAINT trajectory_pkey PRIMARY KEY (id),
	CONSTRAINT trajectory_source_id_fkey FOREIGN KEY (source_id) REFERENCES public.concept(id) ON DELETE CASCADE,
	CONSTRAINT trajectory_target_id_fkey FOREIGN KEY (target_id) REFERENCES public.concept(id) ON DELETE CASCADE
);
CREATE INDEX traj_delta_ivf ON public.trajectory USING ivfflat (delta) WITH (lists='100');
CREATE INDEX traj_source_idx ON public.trajectory USING btree (source_id);
CREATE INDEX traj_target_idx ON public.trajectory USING btree (target_id);


-- public.truth_lineage definition

-- Drop table

-- DROP TABLE public.truth_lineage;

CREATE TABLE public.truth_lineage (
	id bigserial NOT NULL,
	child_truth int8 NULL,
	parent_truth int8 NULL,
	relation text NULL,
	CONSTRAINT truth_lineage_pkey PRIMARY KEY (id),
	CONSTRAINT truth_lineage_child_truth_fkey FOREIGN KEY (child_truth) REFERENCES public.truth(id) ON DELETE CASCADE,
	CONSTRAINT truth_lineage_parent_truth_fkey FOREIGN KEY (parent_truth) REFERENCES public.truth(id) ON DELETE CASCADE
);


-- public.challenge definition

-- Drop table

-- DROP TABLE public.challenge;

CREATE TABLE public.challenge (
	id bigserial NOT NULL,
	posit_id int8 NULL,
	challenger text NULL,
	claim text NULL,
	severity int4 DEFAULT 1 NULL,
	state text DEFAULT 'open'::text NULL,
	CONSTRAINT challenge_pkey PRIMARY KEY (id),
	CONSTRAINT challenge_posit_id_fkey FOREIGN KEY (posit_id) REFERENCES public.posit(id) ON DELETE CASCADE
);


-- public.evaluation definition

-- Drop table

-- DROP TABLE public.evaluation;

CREATE TABLE public.evaluation (
	id bigserial NOT NULL,
	posit_id int8 NULL,
	coherence numeric NULL,
	correspondence numeric NULL,
	consensus numeric NULL,
	method_fit numeric NULL,
	confidence numeric NULL,
	verdict text NULL,
	notes text NULL,
	created_at timestamptz DEFAULT now() NULL,
	CONSTRAINT evaluation_pkey PRIMARY KEY (id),
	CONSTRAINT evaluation_posit_id_fkey FOREIGN KEY (posit_id) REFERENCES public.posit(id) ON DELETE CASCADE
);
CREATE INDEX eval_posit_idx ON public.evaluation USING btree (posit_id);


-- public.evidence definition

-- Drop table

-- DROP TABLE public.evidence;

CREATE TABLE public.evidence (
	id bigserial NOT NULL,
	posit_id int8 NULL,
	"source" text NULL,
	excerpt text NULL,
	"method" text NULL,
	weight float8 NULL,
	created_at timestamptz DEFAULT now() NULL,
	CONSTRAINT evidence_pkey PRIMARY KEY (id),
	CONSTRAINT evidence_posit_id_fkey FOREIGN KEY (posit_id) REFERENCES public.posit(id) ON DELETE CASCADE
);