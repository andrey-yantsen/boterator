--
-- PostgreSQL database dump
--

-- Dumped from database version 9.5.3
-- Dumped by pg_dump version 9.5.3

SET statement_timeout = 0;
SET lock_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SET check_function_bodies = false;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: plpgsql; Type: EXTENSION; Schema: -; Owner: 
--

CREATE EXTENSION IF NOT EXISTS plpgsql WITH SCHEMA pg_catalog;


--
-- Name: EXTENSION plpgsql; Type: COMMENT; Schema: -; Owner: 
--

COMMENT ON EXTENSION plpgsql IS 'PL/pgSQL procedural language';


SET search_path = public, pg_catalog;

SET default_tablespace = '';

SET default_with_oids = false;

--
-- Name: incoming_messages; Type: TABLE; Schema: public; Owner: virus
--

CREATE TABLE incoming_messages (
    id integer NOT NULL,
    original_chat_id integer NOT NULL,
    owner_id integer NOT NULL,
    bot_id integer NOT NULL,
    created_at timestamp without time zone NOT NULL,
    is_voting_fail boolean DEFAULT false NOT NULL,
    is_published boolean DEFAULT false NOT NULL,
    is_voting_success boolean DEFAULT false NOT NULL,
    message jsonb,
    moderation_message_id integer
);


ALTER TABLE incoming_messages OWNER TO virus;

--
-- Name: registered_bots; Type: TABLE; Schema: public; Owner: virus
--

CREATE TABLE registered_bots (
    id integer NOT NULL,
    token character varying NOT NULL,
    owner_id integer NOT NULL,
    moderator_chat_id integer NOT NULL,
    target_channel character varying NOT NULL,
    active boolean NOT NULL,
    last_moderation_message_at timestamp without time zone,
    last_channel_message_at timestamp without time zone,
    settings jsonb DEFAULT '{}'::jsonb NOT NULL
);


ALTER TABLE registered_bots OWNER TO virus;

--
-- Name: stages; Type: TABLE; Schema: public; Owner: virus
--

CREATE TABLE stages (
    bot_id integer NOT NULL,
    key character varying NOT NULL,
    stage character varying NOT NULL,
    data jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp without time zone NOT NULL
);


ALTER TABLE stages OWNER TO virus;

--
-- Name: users; Type: TABLE; Schema: public; Owner: virus
--

CREATE TABLE users (
    bot_id integer NOT NULL,
    user_id integer NOT NULL,
    first_name character varying NOT NULL,
    last_name character varying,
    username character varying,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    banned_at timestamp without time zone,
    ban_reason character varying,
    settings jsonb DEFAULT '{}'::jsonb NOT NULL
);


ALTER TABLE users OWNER TO virus;

--
-- Name: votes_history; Type: TABLE; Schema: public; Owner: virus
--

CREATE TABLE votes_history (
    id integer NOT NULL,
    user_id integer NOT NULL,
    message_id integer NOT NULL,
    original_chat_id integer NOT NULL,
    created_at timestamp without time zone NOT NULL,
    vote_yes boolean NOT NULL
);


ALTER TABLE votes_history OWNER TO virus;

--
-- Name: votes_history_id_seq; Type: SEQUENCE; Schema: public; Owner: virus
--

CREATE SEQUENCE votes_history_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE votes_history_id_seq OWNER TO virus;

--
-- Name: votes_history_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: virus
--

ALTER SEQUENCE votes_history_id_seq OWNED BY votes_history.id;


--
-- Name: id; Type: DEFAULT; Schema: public; Owner: virus
--

ALTER TABLE ONLY votes_history ALTER COLUMN id SET DEFAULT nextval('votes_history_id_seq'::regclass);


--
-- Name: incoming_messages_pkey; Type: CONSTRAINT; Schema: public; Owner: virus
--

ALTER TABLE ONLY incoming_messages
    ADD CONSTRAINT incoming_messages_pkey PRIMARY KEY (id, original_chat_id);


--
-- Name: registered_bots_pkey; Type: CONSTRAINT; Schema: public; Owner: virus
--

ALTER TABLE ONLY registered_bots
    ADD CONSTRAINT registered_bots_pkey PRIMARY KEY (id);


--
-- Name: stages_pkey; Type: CONSTRAINT; Schema: public; Owner: virus
--

ALTER TABLE ONLY stages
    ADD CONSTRAINT stages_pkey PRIMARY KEY (bot_id, key);


--
-- Name: users_pkey; Type: CONSTRAINT; Schema: public; Owner: virus
--

ALTER TABLE ONLY users
    ADD CONSTRAINT users_pkey PRIMARY KEY (bot_id, user_id);


--
-- Name: votes_history_pkey; Type: CONSTRAINT; Schema: public; Owner: virus
--

ALTER TABLE ONLY votes_history
    ADD CONSTRAINT votes_history_pkey PRIMARY KEY (id);


--
-- Name: im_pending_die_idx; Type: INDEX; Schema: public; Owner: virus
--

CREATE INDEX im_pending_die_idx ON incoming_messages USING btree (bot_id, is_voting_success, is_voting_fail, created_at DESC);


--
-- Name: im_pending_idx; Type: INDEX; Schema: public; Owner: virus
--

CREATE INDEX im_pending_idx ON incoming_messages USING btree (bot_id, is_voting_success, is_published, created_at);


--
-- Name: rb_active_idx; Type: INDEX; Schema: public; Owner: virus
--

CREATE INDEX rb_active_idx ON registered_bots USING btree (active);


--
-- Name: rb_moderator_chat_idx; Type: INDEX; Schema: public; Owner: virus
--

CREATE INDEX rb_moderator_chat_idx ON registered_bots USING btree (moderator_chat_id);


--
-- Name: users_banned_idx; Type: INDEX; Schema: public; Owner: virus
--

CREATE INDEX users_banned_idx ON users USING btree (bot_id, banned_at);


--
-- Name: votes_history_mo_idx; Type: INDEX; Schema: public; Owner: virus
--

CREATE INDEX votes_history_mo_idx ON votes_history USING btree (message_id, original_chat_id);


--
-- Name: votes_history_umo_idx; Type: INDEX; Schema: public; Owner: virus
--

CREATE INDEX votes_history_umo_idx ON votes_history USING btree (user_id, message_id, original_chat_id);


--
-- Name: public; Type: ACL; Schema: -; Owner: virus
--

REVOKE ALL ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON SCHEMA public FROM virus;
GRANT ALL ON SCHEMA public TO virus;
GRANT ALL ON SCHEMA public TO PUBLIC;


--
-- PostgreSQL database dump complete
--

