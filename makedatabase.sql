-- we don't know how to generate root <with-no-name> (class Root) :(
create table auto_punishment
(
    guild               int  not null,
    warn_count          int  not null,
    punishment_type     text not null,
    punishment_duration int,
    warn_timespan       int,
    constraint no_dupes
        unique (guild, warn_count)
);

create table auto_reactions
(
    guild            int not null,
    channel          int not null,
    emoji            int not null,
    react_to_threads bool default false not null
);

create table birthdays
(
    user     int not null
        constraint birthdays_pk
            primary key,
    birthday int not null
);

create table booster_roles
(
    guild int not null,
    user  int not null,
    role  int not null,
    constraint booster_roles_pk
        unique (guild, user)
);

create table experience
(
    user       int not null,
    guild      int not null,
    experience float default 0,
    constraint experience_pk
        primary key (user, guild)
);

create table guild_xp_exclusions
(
    guild         integer not null,
    userorchannel integer not null,
    mod_set       bool default false not null,
    constraint guild_xp_exclusions_pk
        primary key (guild, userorchannel)
);

create table lockedchannelperms
(
    guild   integer not null,
    channel integer not null,
    data    text
);

create table macros
(
    server  int                 not null,
    name    text collate NOCASE not null,
    content text                not null,
    constraint macros_pk
        primary key (server, name),
    constraint contentc
        check (content <> ''),
    constraint namec
        check (name <> '')
);

create table members_to_verify
(
    guild  integer,
    member integer,
    thread integer
);

create table modlog
(
    guild     int not null,
    user      int,
    moderator int,
    text      text,
    datetime  int
);

create table schedule
(
    id        integer  not null
        constraint schedule_pk
            primary key autoincrement,
    eventtype text     not null,
    eventtime DATETIME not null,
    eventdata json     not null
);

create table server_config
(
    guild                int,
    mod_role             int,
    log_channel          int,
    ban_appeal_link      text,
    thin_ice_role        int,
    thin_ice_threshold   int,
    birthday_category    int,
    booster_roles        BOOL,
    booster_role_hoist   int,
    bulk_log_channel     int,
    time_between_xp      float,
    xp_change_per_level  float,
    verification_channel integer,
    verified_role        integer,
    verification_text    text
);

create table thin_ice
(
    user                int not null,
    guild               int not null,
    marked_for_thin_ice bool  default false,
    warns_on_thin_ice   float default 0,
    constraint thin_ice_pk
        primary key (user, guild)
);

create table warnings
(
    server      int      not null,
    user        int      not null,
    issuedby    DATETIME not null,
    issuedat    DATETIME not null,
    reason      TEXT    default 'No reason provided.' not null,
    id          integer
        constraint warnings_pk
            primary key autoincrement,
    deactivated BOOLEAN default 0 not null,
    points      float   default 1 not null
);

