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

-- Ratings are insert-only.
CREATE TABLE rating (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES user(id),
    rating REAL NOT NULL,
    deviation REAL NOT NULL,
    inserted_at TIMESTAMP NOT NULL
);

-- Each Discord channel can be host to a single Mogi room.
CREATE TABLE room (
    id INTEGER PRIMARY KEY,
    -- The discord ID of the channel.
    discord_channel_id BIGINT NOT NULL UNIQUE,
    -- If Mogis can be played in this room.
    -- There isn't any reason for this to be false, but it's useful for
    -- querying
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    inserted_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);

-- Each room can only have one active mogi and many (>0) inactive mogis.
CREATE TABLE event (
    id INTEGER PRIMARY KEY,
    -- A short ID to be used in contentions.
    short_id CHAR(8) NOT NULL UNIQUE,
    room_id INTEGER NOT NULL REFERENCES room(id),
    -- Whether the mogi is active (either waiting for players or queuing)
    active BOOLEAN NOT NULL DEFAULT TRUE,
    inserted_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);

-- A list of participants in a mogi
CREATE TABLE participant (
    id INTEGER PRIMARY KEY,
    -- Foreign keys
    user_id INTEGER NOT NULL REFERENCES user(id),
    event_id INTEGER NOT NULL REFERENCES event(id),
    -- How much score the player had at the end of the mogi
    -- If the mogi hasn't finished yet, this can be null.
    -- If the mogi is finished and this is null, this may have been a
    -- substitute player that was unable to play. This shouldn't count against
    -- them and is purely for documentation purposes.
    score INTEGER,
    inserted_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);

-- Finally, player penalties.
CREATE TABLE penalty (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES user(id),
    -- The reason the penalty was applied
    reason INTEGER NOT NULL,
    -- How many "strikes" this penalty counts as. Set this to 0 for
    -- documentation purposes.
    strikes INTEGER NOT NULL DEFAULT 1,
    -- A specific human-readable string of why the strike was placed.
    notes VARCHAR(2000) NOT NULL,
    -- When the strike expires at
    expires_at TIMESTAMP NOT NULL,
    inserted_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);
