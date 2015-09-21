# -*- coding: utf-8 -*-
from __future__ import absolute_import, print_function, unicode_literals, division

import hashlib
import math
from collections import namedtuple

from sc2reader import utils, log_utils
from sc2reader.decoders import ByteDecoder
from sc2reader.constants import *

Location = namedtuple('Location', ['x', 'y'])


class Team(object):
    """
    The team object primarily a container object for organizing :class:`Player`
    objects with some metadata. As such, it implements iterable and can be
    looped over like a list.

    :param interger number: The team number as recorded in the replay
    """

    #: A unique hash identifying the team of players
    hash = str()

    #: The team number as recorded in the replay
    number = int()

    #: A list of the :class:`Player` objects on the team
    players = list()

    #: The result of the game for this team.
    #: One of "Win", "Loss", or "Unknown"
    result = str()

    def __init__(self, number):
        self.number = number
        self.players = list()
        self.result = "Unknown"

    def __iter__(self):
        return self.players.__iter__()

    @property
    def lineup(self):
        """
        A string representation of the team play races like PP or TPZZ. Random
        pick races are not reflected in this string
        """
        return ''.join(sorted(p.play_race[0].upper() for p in self.players))

    @property
    def hash(self):
        raw_hash = ','.join(sorted(p.url for p in self.players))
        return hashlib.sha256(raw_hash).hexdigest()

    def __str__(self):
        return "Team {0}: {1}".format(self.number, ", ".join([str(p) for p in self.players]))

    def __repr__(self):
        return str(self)


@log_utils.loggable
class Attribute(object):

    def __init__(self, header, attr_id, player, value):
        self.header = header
        self.id = attr_id
        self.player = player

        if self.id not in LOBBY_PROPERTIES:
            self.logger.info("Unknown attribute id: {0}".format(self.id))
            self.name = "Unknown"
            self.value = None
        else:
            self.name, lookup = LOBBY_PROPERTIES[self.id]
            self.value = lookup[value.strip("\x00 ")[::-1]]

    def __repr__(self):
        return str(self)

    def __str__(self):
        return "[{0}] {1}: {2}".format(self.player, self.name, self.value)


class Entity(object):
    """
    :param integer sid: The entity's unique slot id.
    :param dict slot_data: The slot data associated with this entity
    """
    def __init__(self, sid, slot_data):
        #: The entity's unique in-game slot id
        self.sid = int(sid)

        #: The entity's replay.initData slot data
        self.slot_data = slot_data

        #: The player's handicap as set prior to game start, ranges from 50-100
        self.handicap = slot_data['handicap']

        #: The entity's team number. None for observers
        self.team_id = slot_data['team_id']+1

        #: A flag indicating if the person is a human or computer
        #: Really just a shortcut for isinstance(entity, User)
        self.is_human = slot_data['control'] == 2

        #: A flag indicating the entity's observer status.
        #: Really just a shortcut for isinstance(entity, Observer).
        self.is_observer = slot_data['observe'] != 0

        #: A flag marking this entity as a referee (can talk to players)
        self.is_referee = slot_data['observe'] == 2

        #:
        self.hero_name = slot_data['hero']

        #:
        self.hero_skin = slot_data['skin']

        #:
        self.hero_mount = slot_data['mount']
        
        #: The unique Battle.net account identifier in the form of
        #: <region_id>-S2-<subregion>-<toon_id>
        self.toon_handle = slot_data['toon_handle']

        toon_handle = self.toon_handle or "0-S2-0-0"
        parts = toon_handle.split("-")

        #: The Battle.net region the entity is registered to
        self.region = GATEWAY_LOOKUP[int(parts[0])]

        #: Deprecated, see Entity.region
        self.gateway = self.region

        #: The Battle.net subregion the entity is registered to
        self.subregion = int(parts[2])

        #: The Battle.net acount identifier. Used to construct the
        #: bnet profile url. This value can be zero for games
        #: played offline when a user was not logged in to battle.net.
        self.toon_id = int(parts[3])

        #: A index to the user that is the leader of the archon team
        self.archon_leader_id = slot_data['tandem_leader_user_id']

        #: A list of :class:`Event` objects representing all the game events
        #: generated by the person over the course of the game
        self.events = list()

        #: A list of :class:`~sc2reader.events.message.ChatEvent` objects representing all of the chat
        #: messages the person sent during the game
        self.messages = list()

    def format(self, format_string):
        return format_string.format(**self.__dict__)


class Player(object):
    """
    :param integer pid: The player's unique player id.
    :param dict detail_data: The detail data associated with this player
    :param dict attribute_data: The attribute data associated with this player
    """
    def __init__(self, pid, detail_data, attribute_data):
        #: The player's unique in-game player id
        self.pid = int(pid)

        #: The replay.details data on this player
        self.detail_data = detail_data

        #: The replay.attributes.events data on this player
        self.attribute_data = attribute_data

        #: The player result, one of "Win", "Loss", or None
        self.result = None
        if detail_data['result'] == 1:
            self.result = "Win"
        elif detail_data['result'] == 2:
            self.result = "Loss"

        #: A reference to the player's :class:`Team` object
        self.team = None

        #: The race the player picked prior to the game starting.
        #: One of Protoss, Terran, Zerg, Random
        self.pick_race = attribute_data.get('Race', 'Unknown')

        #: The difficulty setting for the player. Always Medium for human players.
        #: Very Easy, Easy, Medium, Hard, Harder, Very hard, Elite, Insane,
        #: Cheater 2 (Resources), Cheater 1 (Vision)
        self.difficulty = attribute_data.get('Difficulty', 'Unknown')

        #: The race the player played the game with.
        #: One of Protoss, Terran, Zerg
        self.play_race = LOCALIZED_RACES.get(detail_data['race'], detail_data['race'])

        #: A reference to a :class:`~sc2reader.utils.Color` object representing the player's color
        self.color = utils.Color(**detail_data['color'])

        #: A list of references to the :class:`~sc2reader.data.Unit` objects the player had this game
        self.units = list()

        #: A list of references to the :class:`~sc2reader.data.Unit` objects that the player killed this game
        self.killed_units = list()

        #: The Battle.net region the entity is registered to
        self.region = GATEWAY_LOOKUP[detail_data['bnet']['region']]

        #: Deprecated, see `Player.region`
        self.gateway = self.region

        #: The Battle.net subregion the entity is registered to
        self.subregion = detail_data['bnet']['subregion']

        #: The Battle.net acount identifier. Used to construct the
        #: bnet profile url. This value can be zero for games
        #: played offline when a user was not logged in to battle.net.
        self.toon_id = detail_data['bnet']['uid']


class User(object):
    """
    :param integer uid: The user's unique user id
    :param dict init_data: The init data associated with this user
    """
    #: The Battle.net profile url template
    URL_TEMPLATE = "http://{region}.battle.net/sc2/en/profile/{toon_id}/{subregion}/{name}/"

    def __init__(self, uid, init_data):
        #: The user's unique in-game user id
        self.uid = int(uid)

        #: The replay.initData data on this user
        self.init_data = init_data

        #: The user's Battle.net clan tag at the time of the game
        self.clan_tag = init_data['clan_tag']

        #: The user's Battle.net name at the time of the game
        self.name = init_data['name']

        #: The user's combined Battle.net race levels
        self.combined_race_levels = init_data['combined_race_levels']

        #: The highest 1v1 league achieved by the user in the current season with 1 as Bronze and
        #: 7 as Grandmaster. 8 seems to indicate that there is no current season 1v1 ranking.
        self.highest_league = init_data['highest_league']

        #: A flag indicating if this person was the one who recorded the game.
        #: This is deprecated because it doesn't actually work.
        self.recorder = None

    @property
    def url(self):
        """The player's formatted Battle.net profile url"""
        return self.URL_TEMPLATE.format(**self.__dict__)  # region=self.region, toon_id=self.toon_id, subregion=self.subregion, name=self.name.('utf8'))


class Observer(Entity, User):
    """ Extends :class:`Entity` and :class:`User`.

    :param integer sid: The entity's unique slot id.
    :param dict slot_data: The slot data associated with this entity
    :param integer uid: The user's unique user id
    :param dict init_data: The init data associated with this user
    :param integer pid: The player's unique player id.
    """
    def __init__(self, sid, slot_data, uid, init_data, pid):
        Entity.__init__(self, sid, slot_data)
        User.__init__(self, uid, init_data)

        #: The player id of the observer. Only meaningful in pre 2.0.4 replays
        self.pid = pid

    def __str__(self):
        return "Observer {0} - {1}".format(self.uid, self.name)

    def __repr__(self):
        return str(self)


class Computer(Entity, Player):
    """ Extends :class:`Entity` and :class:`Player`

    :param integer sid: The entity's unique slot id.
    :param dict slot_data: The slot data associated with this entity
    :param integer pid: The player's unique player id.
    :param dict detail_data: The detail data associated with this player
    :param dict attribute_data: The attribute data associated with this player
    """
    def __init__(self, sid, slot_data, pid, detail_data, attribute_data):
        Entity.__init__(self, sid, slot_data)
        Player.__init__(self, pid, detail_data, attribute_data)

        #: The auto-generated in-game name for this computer player
        self.name = detail_data['name']

    def __str__(self):
        return "Player {0} - {1} ({2})".format(self.pid, self.name, self.play_race)

    def __repr__(self):
        return str(self)


class Participant(Entity, User, Player):
    """ Extends :class:`Entity`, :class:`User`, and :class:`Player`

    :param integer sid: The entity's unique slot id.
    :param dict slot_data: The slot data associated with this entity
    :param integer uid: The user's unique user id
    :param dict init_data: The init data associated with this user
    :param integer pid: The player's unique player id.
    :param dict detail_data: The detail data associated with this player
    :param dict attribute_data: The attribute data associated with this player
    """
    def __init__(self, sid, slot_data, uid, init_data, pid, detail_data, attribute_data):
        Entity.__init__(self, sid, slot_data)
        User.__init__(self, uid, init_data)
        Player.__init__(self, pid, detail_data, attribute_data)

    def __str__(self):
        return "Player {0} - {1} ({2})".format(self.pid, self.name, self.play_race)

    def __repr__(self):
        return str(self)


class PlayerSummary():
    """
    Resents a player as loaded from a :class:`~sc2reader.resources.GameSummary`
    file.
    """

    #: The index of the player in the game
    pid = int()

    #: The index of the players team in the game
    teamid = int()

    #: The race the player played in the game.
    play_race = str()

    #: The race the player picked in the lobby.
    pick_race = str()

    #: If the player is a computer
    is_ai = False

    #: If the player won the game
    is_winner = False

    #: Battle.Net id of the player
    bnetid = int()

    #: Subregion id of player
    subregion = int()

    #: The player's gateway, such as us, eu
    gateway = str()

    #: The player's region, such as na, la, eu or ru.  This is
    # provided for convenience, but as of 20121018 is strictly a
    # function of gateway and subregion.
    region = str()

    #: unknown1
    unknown1 = int()

    #: unknown2
    unknown2 = dict()

    #: :class:`Graph` of player army values over time (seconds)
    army_graph = None

    #: :class:`Graph` of player income over time (seconds)
    income_graph = None

    #: Stats from the game in a dictionary
    stats = dict()

    def __init__(self, pid):
        self.unknown2 = dict()
        self.pid = pid

    def __str__(self):
        if not self.is_ai:
            return 'User {0}-S2-{1}-{2}'.format(self.region.upper(), self.subregion, self.bnetid)
        else:
            return 'AI ({0})'.format(self.play_race)

    def __repr__(self):
        return str(self)

    def get_stats(self):
        s = ''
        for k in self.stats:
            s += '{0}: {1}\n'.format(self.stats_pretty_names[k], self.stats[k])
        return s.strip()


BuildEntry = namedtuple('BuildEntry', ['supply', 'total_supply', 'time', 'order', 'build_index'])


# TODO: Are there libraries with classes like this in them
class Graph():
    """
    A class to represent a graph on the score screen. Derived from data in the
    :class:`~sc2reader.resources.GameSummary` file.
    """

    #: Times in seconds on the x-axis of the graph
    times = list()

    #: Values on the y-axis of the graph
    values = list()

    def __init__(self, x, y, xy_list=None):
        self.times = list()
        self.values = list()

        if xy_list:
            for x, y in xy_list:
                self.times.append(x)
                self.values.append(y)
        else:
            self.times = x
            self.values = y

    def as_points(self):
        """ Get the graph as a list of (x, y) tuples """
        return list(zip(self.times, self.values))

    def __str__(self):
        return "Graph with {0} values".format(len(self.times))


class MapInfoPlayer(object):
    """
    Describes the player data as found in the MapInfo document of SC2Map archives.
    """
    def __init__(self, pid, control, color, race, unknown, start_point, ai, decal):
        #: The pid of the player
        self.pid = pid

        #: The controller of the player, one of:
        #:
        #: * 0 = Default?
        #: * 1 = User
        #: * 2 = Computer
        #: * 3 = Neutral
        #: * 4 = Hostile
        #: * More?
        #:
        self.control = control

        #: The color of the player, one of:
        #:
        #: * 0xffffffff = (Any)
        #: * 0 = White
        #: * 1 = Red
        #: * 2 = Blue
        #: * 3 = Teal
        #: * 4 = Purple
        #: * 5 = Yellow
        #: * 6 = Orange
        #: * 7 = Green
        #: * 8 = Pink
        #: * 9 = Violet
        #: * 10 = Light Grey
        #: * 11 = Dark Green
        #: * 12 = Brown
        #: * 13 = Light Green
        #: * 14 = Dark Grey
        #: * 15 = Lavender
        #:
        self.color = color

        #: The player race, "" for unset
        self.race = race

        #: Unknown player setting
        self.unknown = unknown

        #: The point index of the player start location; 0 = random
        self.start_point = start_point

        #: The AI to use
        self.ai = ai

        #: The player decal
        self.decal = decal


@log_utils.loggable
class MapInfo(object):
    """
    Represents the data encoded into the MapInfo file inside every SC2Map archive
    """
    def __init__(self, contents):
        # According to http://www.galaxywiki.net/MapInfo_(File_Format)
        # With a couple small changes for version 0x20+
        data = ByteDecoder(contents, endian='LITTLE')
        magic = data.read_string(4)
        if magic != 'MapI':
            self.logger.warn("Invalid MapInfo file: {0}".format(magic))
            return

        #: The map info file format version
        self.version = data.read_uint32()
        if self.version >= 0x18:
            self.unknown1 = data.read_uint32()
            self.unknown2 = data.read_uint32()

        #: The full map width
        self.width = data.read_uint32()

        #: The full map height
        self.height = data.read_uint32()

        #: Small map preview type: 0 = None, 1 = Minimap, 2 = Custom
        self.small_preview_type = data.read_uint32()

        #: (Optional) Small map preview path; relative to root of map archive
        self.small_preview_path = str()
        if self.small_preview_type == 2:
            self.small_preview_path = data.read_cstring()

        #: Large map preview type: 0 = None, 1 = Minimap, 2 = Custom
        self.large_preview_type = data.read_uint32()

        #: (Optional) Large map preview path; relative to root of map archive
        self.large_preview_path = str()
        if self.large_preview_type == 2:
            self.large_preview_path = data.read_cstring()

        if self.version >= 0x1f:
            self.unknown3 = data.read_cstring()
            self.unknown4 = data.read_uint32()

        self.unknown5 = data.read_uint32()

        #: The type of fog of war used on the map
        self.fog_type = data.read_cstring()

        #: The tile set used on the map
        self.tile_set = data.read_cstring()

        #: The left bounds for the camera. This value is 7 less than the value shown in the editor.
        self.camera_left = data.read_uint32()

        #: The bottom bounds for the camera. This value is 4 less than the value shown in the editor.
        self.camera_bottom = data.read_uint32()

        #: The right bounds for the camera. This value is 7 more than the value shown in the editor.
        self.camera_right = data.read_uint32()

        #: The top bounds for the camera. This value is 4 more than the value shown in the editor.
        self.camera_top = data.read_uint32()

        #: The map base height (what is that?). This value is 4096*Base Height in the editor (giving a decimal value).
        self.base_height = data.read_uint32()/4096

        #: Load screen type: 0 = default, 1 = custom
        self.load_screen_type = data.read_uint32()

        #: (Optional) Load screen image path; relative to root of map archive
        self.load_screen_path = data.read_cstring()

        #: Unknown string, usually empty
        self.unknown6 = data.read_bytes(data.read_uint16()).decode('utf8')

        #: Load screen image scaling strategy: 0 = normal, 1 = aspect scaling, 2 = stretch the image.
        self.load_screen_scaling = data.read_uint32()

        #: The text position on the loading screen. One of:
        #:
        #: * 0xffffffff = (Default)
        #: * 0 = Top Left
        #: * 1 = Top
        #: * 2 = Top Right
        #: * 3 = Left
        #: * 4 = Center
        #: * 5 = Right
        #: * 6 = Bottom Left
        #: * 7 = Bottom
        #: * 8 = Bottom Right
        #:
        self.text_position = data.read_uint32()

        #: Loading screen text position offset x
        self.text_position_offset_x = data.read_uint32()

        #: Loading screen text position offset y
        self.text_position_offset_y = data.read_uint32()

        #: Loading screen text size x
        self.text_position_size_x = data.read_uint32()

        #: Loading screen text size y
        self.text_position_size_y = data.read_uint32()

        #: A bit array of flags with the following options (possibly incomplete)
        #:
        #: * 0x00000001 = Disable Replay Recording
        #: * 0x00000002 = Wait for Key (Loading Screen)
        #: * 0x00000004 = Disable Trigger Preloading
        #: * 0x00000008 = Enable Story Mode Preloading
        #: * 0x00000010 = Use Horizontal Field of View
        #:
        self.data_flags = data.read_uint32()

        self.unknown7 = data.read_uint32()

        if self.version >= 0x19:
            self.unknown8 = data.read_bytes(8)

        if self.version >= 0x1f:
            self.unknown9 = data.read_bytes(9)

        if self.version >= 0x20:
            self.unknown10 = data.read_bytes(4)

        #: The number of players enabled via the data editor
        self.player_count = data.read_uint32()

        # Leave early so we dont barf. Turns out ggtracker doesnt need
        # any of the map data thats loaded below.
        return
        
        #: A list of references to :class:`MapInfoPlayer` objects
        self.players = list()
        for i in range(self.player_count):
            self.players.append(MapInfoPlayer(
                pid=data.read_uint8(),
                control=data.read_uint32(),
                color=data.read_uint32(),
                race=data.read_cstring(),
                unknown=data.read_uint32(),
                start_point=data.read_uint32(),
                ai=data.read_uint32(),
                decal=data.read_cstring(),
            ))

        #: A list of the start location point indexes used in Basic Team Settings.
        #: The editor limits these to only Start Locations and not regular points.
        self.start_locations = list()
        for i in range(data.read_uint32()):
            self.start_locations.append(data.read_uint32())

        #: The number of start locations used
        self.start_location_used = data.read_uint32()

        #: The number of alliance flags encoded in :attr:`alliance_flags`.
        self.alliance_flags_length = data.read_uint32()
        # A set bit (1) indicates that the pair of Start Locations are to be allied.
        # bit = 1; // Set up a bitmask
        # // i will be the first Start Location in the Point Indexes array
        # // j will the the Start Location after i
        # for(i=0;i< Start Location Count;i++){
        #    for(j=i+1;j < Start Location Count;j++){ // set j, and then iterate through the rest
        #       bit <<= 1; // Shift left to move the mask to the next bit.
        #       if((Team Enemy Flags & bit) != 0) { // These start locations are allies
        #          // Add more to compensate for byte boundaries. This array can get big.
        #       }
        #    }
        # }
        #: A bit array of flags mapping out the player alliances
        self.alliance_flags = data.read_uint(int(math.ceil(self.alliance_flags_length/8.0)))

        #: A list of the advanced start location point indexes used in Advanced Team Settings.
        #: The editor limits these to only Start Locations and not regular points.
        self.advanced_start_locations = list()
        for i in range(data.read_uint32()):
            # point index for each start location used
            self.advanced_start_locations.append(data.read_uint32())

        #: A list of bit arrays marking which start locations below to which team.
        self.advanced_teams_flags = list()
        for i in range(data.read_uint32()):
            # TODO:
            # One set for each team. Each bit corresponds with the Point Indexes
            # array index (i.e., bit 0 is PointIndexes[0], bit1 is PointIndex[1],
            # etc.). If the bit is set, that start location is a part of that team.
            self.advanced_teams_flags.append(data.read_uint32())

        #: Possibly "number of teams used"? Similar to "start locations used"
        self.advanced_teams_count2 = data.read_uint32()

        #: The number of enemy flags encoded in :attr:`enemy_flags`.
        self.enemy_flags_length = data.read_uint32()
        # A set bit (1) indicates that the pair of teams are to be enemies.
        # bit = 1; // Set up a bitmask
        # // i will be the first Team in the Team Members array.
        # // j will be the Team that comes after i
        # for(i=0;i< Team Count;i++){
        #    for(j=i+1;j < Team Count;j++){ // set j, and then iterate through the rest
        #       bit <<= 1; // Shift left to move the mask to the next bit.
        #       if((Team Enemy Flags & bit) != 0) { // These teams are enemies
        #          // Add more code to compensate for byte boundaries.
        #       }
        #    }
        # }
        #: A bit array of flags mapping out the player enemies.
        self.enemy_flags = data.read_uint(int(math.ceil(self.enemy_flags_length/8.0)))

        if data.length != data.tell():
            self.logger.warn("Not all of the MapInfo file was read!")

    def __str__(self):
        return self.map_name
