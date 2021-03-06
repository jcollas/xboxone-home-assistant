"""
Support for functionality to interact with the Xbox One gaming console via SmartGlass protocol.

For more details about this platform, please refer to the documentation at
https://home-assistant.io/components/media_player.xboxone/

CREDITS:
- This module is based on media_player.firetv component, initially created by @happyleavesaoc
- Original code: https://github.com/home-assistant/home-assistant/blob/dev/homeassistant/components/media_player/firetv.py
"""
import functools
import logging
from urllib.parse import urljoin
from functools import partial


import homeassistant.helpers.config_validation as cv
import homeassistant.util.dt as dt_util
import requests
import voluptuous as vol
from homeassistant.components.media_player import PLATFORM_SCHEMA, MediaPlayerEntity
from homeassistant.components.media_player.const import (
    MEDIA_TYPE_CHANNEL,
    MEDIA_TYPE_MUSIC,
    MEDIA_TYPE_TVSHOW,
    MEDIA_TYPE_VIDEO,
    SUPPORT_NEXT_TRACK,
    SUPPORT_PAUSE,
    SUPPORT_PLAY,
    SUPPORT_PREVIOUS_TRACK,
    SUPPORT_SELECT_SOURCE,
    SUPPORT_TURN_OFF,
    SUPPORT_TURN_ON,
    SUPPORT_VOLUME_MUTE,
    SUPPORT_VOLUME_STEP,
)
from homeassistant.const import (
    CONF_AUTHENTICATION,
    CONF_DEVICE,
    CONF_HOST,
    CONF_IP_ADDRESS,
    CONF_NAME,
    CONF_PORT,
    CONF_SSL,
    STATE_IDLE,
    STATE_OFF,
    STATE_ON,
    STATE_PAUSED,
    STATE_PLAYING,
    STATE_UNKNOWN,
)
from packaging import version

_LOGGER = logging.getLogger(__name__)

SUPPORT_XBOXONE = (
    SUPPORT_PAUSE
    | SUPPORT_TURN_ON
    | SUPPORT_TURN_OFF
    | SUPPORT_PREVIOUS_TRACK
    | SUPPORT_NEXT_TRACK
    | SUPPORT_SELECT_SOURCE
    | SUPPORT_PLAY
    | SUPPORT_VOLUME_STEP
    | SUPPORT_VOLUME_MUTE
)

MIN_REQUIRED_SERVER_VERSION = "1.1.2"

DEFAULT_SSL = False
DEFAULT_HOST = "localhost"
DEFAULT_NAME = "Xbox One SmartGlass"
DEFAULT_PORT = 5557
DEFAULT_AUTHENTICATION = True

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_DEVICE): cv.string,
        vol.Optional(CONF_IP_ADDRESS, default=""): cv.string,
        vol.Optional(CONF_HOST, default=DEFAULT_HOST): cv.string,
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): cv.port,
        vol.Optional(CONF_SSL, default=DEFAULT_SSL): cv.boolean,
        vol.Optional(CONF_AUTHENTICATION, default=DEFAULT_AUTHENTICATION): cv.boolean,
    }
)


def setup_platform(hass, config, add_devices, discovery_info=None):
    """Set up the Xbox One platform."""
    name = config.get(CONF_NAME)
    ssl = config.get(CONF_SSL)
    host = config.get(CONF_HOST)
    port = config.get(CONF_PORT)
    liveid = config.get(CONF_DEVICE)
    ip = config.get(CONF_IP_ADDRESS)
    auth = config.get(CONF_AUTHENTICATION)

    proto = "https" if ssl else "http"
    base_url = f"{proto}://{host}:{port}"

    add_devices([XboxOneDevice(hass, base_url, liveid, ip, name, auth)])


class XboxOne:
    def __init__(self, hass, base_url, liveid, ip, auth):
        self.is_server_up = False
        self.is_server_correct_version = True

        self.base_url = base_url
        self._hass = hass
        self.liveid = liveid
        self._ip = ip
        self._auth = auth
        self._available = False
        self._connected = False
        self._media_status = None
        self._console_status = None
        self._volume_controls = None
        self._pins = None
        self._apps = {}

    async def get(self, endpoint, **kwargs):
        endpoint = endpoint.replace("<liveid>", self.liveid)
        full_url = urljoin(self.base_url, endpoint)

        try:
            partial_req = partial(requests.get, full_url, **kwargs)
            response = await self._hass.loop.run_in_executor(None, partial_req)

            if response.status_code != 200:
                _LOGGER.warning(
                    "Invalid status_code %s from url %s", response.status_code, full_url
                )
                _LOGGER.warning(response.text)
                return {}

            json_response = response.json()

        except requests.exceptions.RequestException:
            _LOGGER.warning("Request failed for url %s", full_url)
            return {}
        except ValueError:
            _LOGGER.warning("Unable to parse JSON from response")
            return {}

        return json_response

    @property
    def available(self):
        return self._available

    @property
    def connected(self):
        return self._connected

    @property
    def console_status(self):
        return self._console_status

    @property
    def media_status(self):
        return self._media_status

    @property
    def volume_controls(self):
        volume_controls = self._volume_controls
        if not volume_controls:
            return None

        controls = volume_controls.get("avr") or volume_controls.get("tv")
        if not controls:
            return None

        return {
            "mute": controls["buttons"]["btn.vol_mute"]["url"],
            "up": controls["buttons"]["btn.vol_up"]["url"],
            "down": controls["buttons"]["btn.vol_down"]["url"],
        }

    @property
    def media_playback_state(self):
        if self.media_status:
            return self.media_status.get("playback_status")

    @property
    def media_type(self):
        if self.media_status:
            return self.media_status.get("media_type")

    @property
    def media_position(self):
        if self.media_status:
            position = self.media_status.get("position")
            # Convert from nanoseconds
            if isinstance(position, int) and position >= 10000000:
                return position / 10000000

    @property
    def media_duration(self):
        if self.media_status:
            media_end = self.media_status.get("media_end")
            # Convert from nanoseconds
            if isinstance(media_end, int) and media_end >= 10000000:
                return media_end / 10000000

    @property
    def media_title(self):
        if self.media_status:
            return self.media_status.get("metadata", {}).get("title")

    @property
    def active_app(self):
        if self.console_status:
            active_titles = self.console_status.get("active_titles")
            app = [a.get("name") for a in active_titles if a.get("has_focus")]
            if len(app):
                return app[0]

    @property
    def active_app_image(self):
        if self.console_status:
            active_titles = self.console_status.get("active_titles")
            app = [a.get("image") for a in active_titles if a.get("has_focus")]
            if len(app):
                return app[0] or None

    @property
    def active_app_type(self):
        if self.console_status:
            active_titles = self.console_status.get("active_titles")
            app = [a.get("type") for a in active_titles if a.get("has_focus")]
            if len(app):
                return app[0]

    @property
    def all_apps(self):
        return self._apps

    async def _refresh_all_apps(self):
        apps = {"Home": "ms-xbox-dashboard://home?view=home", "TV": "ms-xbox-livetv://"}

        if not self._pins and await self._check_authentication():
            self._pins = await self.get("/web/pins")

        if self._pins:
            try:
                for item in self._pins["ListItems"]:
                    if (
                        item["Item"]["ContentType"] == "DApp"
                        and item["Item"]["Title"] not in apps.keys()
                    ):
                        apps[item["Item"]["Title"]] = "appx:{0}!App".format(
                            item["Item"]["ItemId"]
                        )
            except:
                pass

        if self.console_status:
            active_titles = self.console_status.get("active_titles")
            for app in active_titles:
                if app.get("has_focus") and app.get("name") not in apps.keys():
                    apps[app.get("name")] = app.get("aum")

        self._apps = apps

        return apps

    async def _check_authentication(self):

        response = await self.get("/auth")
        if response.get("authenticated"):
            return True

        response = await self.get("/auth/refresh")
        if response.get("success"):
            return True

        _LOGGER.error("Refreshing authentication tokens failed!")
        return False

    async def _refresh_devicelist(self):
        params = None
        if self._ip:
            params = {"addr": self._ip}
        await self.get("/device", params=params)

    async def _connect(self):
        if self._auth and not await self._check_authentication():
            return False

        url = "/device/<liveid>/connect"
        params = {}
        if not self._auth:
            params["anonymous"] = True
        response = await self.get(url, params=params)
        if not response.get("success"):
            _LOGGER.error(
                "Failed to connect to console {0}: {1}".format(
                    self.liveid, str(response)
                )
            )
            return False

        return True

    async def _get_device_info(self):

        response = await self.get("/device/<liveid>")
        # _LOGGER.warn(response)
        if not response.get("success"):
            _LOGGER.debug(f"Console {self.liveid} not available")
            return None

        return response["device"]

    async def _update_console_status(self):

        response = await self.get("/device/<liveid>/console_status")
        if not response.get("success"):
            _LOGGER.error(f"Console {self.liveid} not available")
            return None

        self._console_status = response["console_status"]

    async def _update_media_status(self):

        response = await self.get("/device/<liveid>/media_status")
        if not response.get("success"):
            _LOGGER.error(f"Console {self.liveid} not available")
            return None

        self._media_status = response["media_status"]

    async def _update_volume_controls(self):
        if self._volume_controls:
            return

        response = await self.get("/device/<liveid>/ir")
        if not response.get("success"):
            _LOGGER.error(f"Console {self.liveid} not available")
            return None

        self._volume_controls = response

    async def poweron(self):

        url = "/device/<liveid>/poweron"
        params = None
        if self._ip:
            params = {"addr": self._ip}
        response = await self.get(url, params=params)
        if not response.get("success"):
            _LOGGER.error(f"Failed to poweron {self.liveid}")
            return None

        return response

    async def poweroff(self):

        response = await self.get("/device/<liveid>/poweroff")
        if not response.get("success"):
            _LOGGER.error(f"Failed to poweroff {self.liveid}")

        return response

    async def ir_command(self, device, command):

        response = await self.get("/device/<liveid>/ir")
        if not response.get("success"):
            return None

        enabled_commands = response.get(device).get("buttons")
        if command not in enabled_commands:
            _LOGGER.error(
                f"Provided command {command} not enabled for current ir device"
            )
            return None
        else:
            button_url = enabled_commands.get(command).get("url")

        response = await self.get("{0}".format(button_url))
        if not response.get("success"):
            return None

        return response

    async def media_command(self, command):

        response = await self.get("/device/<liveid>/media")
        if not response.get("success"):
            return None

        enabled_commands = response.get("commands")
        if command not in enabled_commands:
            _LOGGER.error(f"Provided command {command} not enabled for current media")
            return None

        response = await self.get(f"/device/<liveid>/media/{command}")
        if not response.get("success"):
            return None

        return response

    async def volume_command(self, command):
        if not self._volume_controls:
            return None

        url = self._volume_controls.get(command)

        if not url:
            return None

        response = await self.get(url)
        if not response.get("success"):
            return None

        return response

    async def launch_title(self, launch_uri):

        apps = self.all_apps
        if launch_uri in apps.keys():
            launch_uri = apps[launch_uri]
        response = await self.get(f"/device/<liveid>/launch/{launch_uri}")
        if not response.get("success"):
            return None

        return response

    async def _check_server(self):
        if not self.is_server_correct_version:
            return False

        response = await self.get("/versions")
        if not response:
            self.is_server_up = False
            return False

        lib_version = response["versions"]["xbox-smartglass-core"]
        if version.parse(lib_version) < version.parse(MIN_REQUIRED_SERVER_VERSION):
            self.is_server_correct_version = False
            _LOGGER.error(
                "Invalid xbox-smartglass-core version: %s. Min Required: %s",
                lib_version,
                MIN_REQUIRED_SERVER_VERSION,
            )

        self.is_server_up = True
        return True

    async def refresh(self):
        """
        Enumerate devices and refresh status info
        """

        if not await self._check_server():
            return

        await self._check_authentication()
        await self._refresh_devicelist()
        await self._refresh_all_apps()

        device_info = await self._get_device_info()
        if not device_info or device_info.get("device_status") == "Unavailable":
            self._available = False
            self._connected = False
            self._console_status = None
            self._media_status = None
            self._volume_controls = None
        else:
            self._available = True

            connection_state = device_info.get("connection_state")
            if connection_state == "Connected":
                self._connected = True
            else:
                success = await self._connect()
                if not success:
                    _LOGGER.error(f"Failed to connect to {self.liveid}")
                    self._connected = False
                else:
                    self._connected = True

        if self.available and self.connected:
            await self._update_console_status()
            await self._update_media_status()
            await self._update_volume_controls()


class XboxOneDevice(MediaPlayerEntity):
    """Representation of an Xbox One device on the network."""

    def __init__(self, hass, base_url, liveid, ip, name, auth):
        """Initialize the Xbox One device."""
        self._xboxone = XboxOne(hass, base_url, liveid, ip, auth)
        self._name = name
        self._liveid = liveid
        self._state = STATE_UNKNOWN
        self._running_apps = None
        self._current_app = None

    @property
    def name(self):
        """Return the device name."""
        return self._name

    @property
    def unique_id(self):
        """Console Live ID"""
        return self._liveid

    @property
    def should_poll(self):
        """Device should be polled."""
        return True

    @property
    def supported_features(self):
        """Flag media player features that are supported."""
        active_support = SUPPORT_XBOXONE
        if self.state not in [STATE_PLAYING, STATE_PAUSED] and (
            self._xboxone.active_app_type not in ["Application", "App"]
            or self._xboxone.active_app == "Home"
        ):
            active_support &= ~SUPPORT_NEXT_TRACK & ~SUPPORT_PREVIOUS_TRACK
        if not self._xboxone.volume_controls:
            active_support &= ~SUPPORT_VOLUME_MUTE & ~SUPPORT_VOLUME_STEP
        return active_support

    @property
    def state(self):
        """Return the state of the player."""
        playback_state = {
            "Closed": STATE_IDLE,
            "Changing": STATE_IDLE,
            "Stopped": STATE_IDLE,
            "Playing": STATE_PLAYING,
            "Paused": STATE_PAUSED,
        }.get(self._xboxone.media_playback_state)

        if playback_state:
            state = playback_state
        elif self._xboxone.connected or self._xboxone.available:
            if (
                self._xboxone.active_app_type in ["Application", "App", "Game"]
                or self._xboxone.active_app == "Home"
            ):
                state = STATE_ON
            else:
                state = STATE_UNKNOWN
        else:
            state = STATE_OFF

        return state

    @property
    def media_content_type(self):
        """Media content type"""
        if self.state in [STATE_PLAYING, STATE_PAUSED]:
            return {"Music": MEDIA_TYPE_MUSIC, "Video": MEDIA_TYPE_VIDEO}.get(
                self._xboxone.media_type
            )

    @property
    def media_duration(self):
        """Duration in seconds"""
        if self.state in [STATE_PLAYING, STATE_PAUSED]:
            return self._xboxone.media_duration

    @property
    def media_position(self):
        """Position in seconds"""
        if self.state in [STATE_PLAYING, STATE_PAUSED]:
            return self._xboxone.media_position

    @property
    def media_position_updated_at(self):
        """Last valid time of media position"""
        if self.state in [STATE_PLAYING, STATE_PAUSED]:
            return dt_util.utcnow()

    @property
    def media_image_url(self):
        """Image url of current playing media."""
        return self._xboxone.active_app_image

    @property
    def media_title(self):
        """When media is playing, print title (if any) - otherwise, print app name"""
        if self.state in [STATE_PLAYING, STATE_PAUSED]:
            return self._xboxone.media_title
        return self._xboxone.active_app

    @property
    def source(self):
        """Return the current app."""
        return self._xboxone.active_app

    @property
    def source_list(self):
        """Return a list of running apps."""
        return list(self._xboxone.all_apps.keys())

    async def async_update(self):
        """Get the latest date and update device state."""
        await self._xboxone.refresh()

    async def async_turn_on(self):
        """Turn on the device."""
        await self._xboxone.poweron()

    async def turn_off(self):
        """Turn off the device."""
        await self._xboxone.poweroff()

    async def async_mute_volume(self, mute):
        """Mute the volume."""
        await self._xboxone.volume_command("mute")

    async def async_volume_up(self):
        """Turn volume up for media player."""
        await self._xboxone.volume_command("up")

    async def async_volume_down(self):
        """Turn volume down for media player."""
        await self._xboxone.volume_command("down")

    async def async_media_play(self):
        """Send play command."""
        await self._xboxone.media_command("play")

    async def async_media_pause(self):
        """Send pause command."""
        await self._xboxone.media_command("pause")

    async def async_media_stop(self):
        await self._xboxone.media_command("stop")

    async def async_media_play_pause(self):
        """Send play/pause command."""
        await self._xboxone.media_command("play_pause")

    async def async_media_previous_track(self):
        """Send previous track command."""
        if self._xboxone.active_app == "TV":
            await self._xboxone.ir_command("stb", "btn.ch_down")
        else:
            await self._xboxone.media_command("prev_track")

    async def async_media_next_track(self):
        """Send next track command."""
        if self._xboxone.active_app == "TV":
            await self._xboxone.ir_command("stb", "btn.ch_up")
        else:
            await self._xboxone.media_command("next_track")

    async def async_select_source(self, source):
        """Select input source."""
        await self._xboxone.launch_title(source)
