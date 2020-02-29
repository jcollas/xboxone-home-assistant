# Hass.io Add-on: Xbox One

Xbox One support for Home Assistant

## About

This add-on is a packaged version of the [Xbox One SmartGlass RESTful server](https://github.com/OpenXbox/xbox-smartglass-rest-python).

## Why do I need this

Xbox One smartglass python implementation is written with [gevent](http://www.gevent.org) coroutines.
Home assistant uses [asyncio](https://docs.python.org/3/library/asyncio.html) for concurrency.

To bridge that gap, the REST server comes into play.

*In an ideal world, a nice person would come along and port the smartglass python libs to asyncio.*

## Installation

You can choose to either install this add-on through Hass.io's frontend, or doing it manually.

### Through the frontend

The installation of this add-on is pretty straightforward and not different in
comparison to installing any other Hass.io add-on.

1. [Add our Hass.io add-ons repository](https://github.com/OpenXbox/xboxone-home-assistant) to your Hass.io instance.
2. Install the "Xbox One" add-on.
3. Start the "Xbox One" add-on.

### Manually

1. Enter your home assistant python virtual-environment.
1. Execute `pip install xbox-smartglass-rest`.
1. Create a service to autostart the server (e.g. for Systemd).
1. Enable / start the service.

#### Systemd service example

File location: `/etc/systemd/system/xbox-smartglass-rest@homeassistant.service`

__NOTE:__ This assumes running the service as user `homeassistant`.
If you want to run the server with a different user, change
the filename to: `xbox-smartglass-rest@<username>.service`!

Edit `ExecStart` to your needs!

```sh
#
# Service file for systems with systemd to run Xbox One SmartGlass REST server.
#

[Unit]
Description=Xbox One SmartGlass REST for %i
After=network.target

[Service]
Type=simple
User=%i
ExecStart=/path/to/bin/inside/venv/xbox-rest-server
SendSIGKILL=no

[Install]
WantedBy=multi-user.target
```

## Authors & Contributors

The original setup of this repository is by [Jason Hunter](https://github.com/hunterjm).

Huge shoutout to [Team OpenXbox](https://github.com/openxbox) for reverse engineering the SmartGlass protocol and providing the libraries and server used.

Special thanks to the contributions of [tuxuser](https://github.com/tuxuser) for answering late night questions and doing almost all of the heavy lifting on this.

Further thanks to [jmhill1287](https://github.com/jmhill1287) and [Eric LeBlanc](https://github.com/ericleb010) for forking and supporting this library for a few months.