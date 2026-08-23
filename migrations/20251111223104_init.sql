-- Database for storing persistent server boards.
CREATE TABLE persistent_boards (
    id INTEGER PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    discord_channel_id BIGINT NOT NULL UNIQUE,
    discord_message_id BIGINT,
    inserted_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);
