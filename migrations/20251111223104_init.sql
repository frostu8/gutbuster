-- Server list
CREATE TABLE server (
    id INTEGER PRIMARY KEY,
    remote VARCHAR(255) NOT NULL,
    label VARCHAR(255) UNIQUE
);

-- We need to store some basic information about users
-- In Duel Channel, MMR is tied to your player profile, but here it should be
-- tied to your Discord user.
CREATE TABLE user (
    id INTEGER PRIMARY KEY,
    -- The discord ID of the user.
    discord_user_id BIGINT NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL UNIQUE,
    inserted_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);

-- Ratings are typically insert only
-- They may be updated retroactively to refund MMR.
CREATE TABLE rating (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES user(id),
    rating REAL NOT NULL,
    deviation REAL NOT NULL,
    inserted_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);

-- Each Discord channel can be host to a single Mogi room.
CREATE TABLE room (
    id INTEGER PRIMARY KEY,
    -- The discord ID of the channel.
    discord_channel_id BIGINT NOT NULL UNIQUE,
    discord_guild_id BIGINT NOT NULL,
    -- If Mogis can be played in this room.
    -- There isn't any reason for this to be false, but it's useful for
    -- querying
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    -- How many players are required before the mogi can start.
    players_required INTEGER NOT NULL DEFAULT 8,
    -- Whether formats should be selected randomly or voted.
    -- 0 - VOTE
    -- 1 - RANDOM
    format_selection_mode INTEGER NOT NULL DEFAULT 0,
    -- How many votes a format needs to be selected.
    votes_required INTEGER NOT NULL DEFAULT 4,
    inserted_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);

-- Each room can have >0 formats.
CREATE TABLE event_format (
    id INTEGER PRIMARY KEY,
    -- The room this format is a part of
    room_id INTEGER NOT NULL REFERENCES room(id),
    -- The name of the format
    name VARCHAR(255) NOT NULL,
    -- Team balancing mode of the format
    -- 0 - FFA
    -- 1 - Half v Half
    -- 2 - Quarter v Quarter v Quarter v Quarter
    team_mode INTEGER NOT NULL DEFAULT 0,

    UNIQUE (room_id, name)
);

-- Each format wants >0 servers.
CREATE TABLE event_format_server (
    id INTEGER PRIMARY KEY,
    event_format_id INTEGER NOT NULL REFERENCES event_format(id),
    server_id INTEGER NOT NULL REFERENCES server(id),

    UNIQUE (event_format_id, server_id)
);

-- Each room can only have one active mogi and many (>0) inactive mogis.
CREATE TABLE event (
    id INTEGER PRIMARY KEY,
    -- A short ID to be used in contentions.
    short_id CHAR(8) NOT NULL UNIQUE,
    room_id INTEGER NOT NULL REFERENCES room(id),
    -- The status of the mogi
    -- 0 - LFG, the mogi is waiting for enough players.
    -- 1 - STARTED, the mogi is either voting for a format or playing.
    -- 2 - ENDED, the mogi is over and no longer considered active.
    status INTEGER NOT NULL DEFAULT 0,
    -- The format for the mogi.
    -- May be NULL if the mogi's format hasn't been formatted or randomly
    -- selected.
    format_id INTEGER REFERENCES event_format(id),
    inserted_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);

-- A list of participants in a mogi
CREATE TABLE participant (
    id INTEGER PRIMARY KEY,
    -- Foreign keys
    user_id INTEGER NOT NULL REFERENCES user(id),
    event_id INTEGER NOT NULL REFERENCES event(id),
    -- Records the player's current MMR.
    -- This is a little more specific than timestamps.
    rating_id INTEGER REFERENCES rating(id),
    -- How much score the player had at the end of the mogi
    -- If the mogi hasn't finished yet, this can be null.
    -- If the mogi is finished and this is null, this may have been a
    -- substitute player that was unable to play. This shouldn't count against
    -- them and is purely for documentation purposes.
    score INTEGER,
    inserted_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,

    UNIQUE (user_id, event_id)
);

-- Finally, player modifications.
CREATE TABLE player_mod (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES user(id),
    -- The reason the modification was applied
    reason INTEGER NOT NULL,
    -- How many "strikes" this penalty counts as. Set this to 0 for
    -- documentation purposes, or to give MMR bonuses.
    strikes INTEGER NOT NULL DEFAULT 0,
    -- The rating penalty or bonus
    rating INTEGER NOT NULL DEFAULT 0,
    -- A specific human-readable string of why the modification was placed.
    notes VARCHAR(2000) NOT NULL,
    -- When the strikes expire at
    strikes_expire_at TIMESTAMP NOT NULL,
    inserted_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);
