"""
Support for Jablotron siren (implemented as dimmable light).
"""

import homeassistant.components.jablo_dongle as jablo_dongle
from homeassistant.components.light import (Light, ATTR_BRIGHTNESS)


def setup_platform(hass, config, add_devices_callback, discovery_info=None):
    """ Find and return demo lights. """
    add_devices_callback([
        JabloLight(0x1000004, "SIREN_BEEP"),
    ])


class JabloLight(Light):
    """ Provides a demo switch. """
    def __init__(self, did, name):
        self._did = did
        self._name = name
        self._state = False
        self._brightness = 64

    @property
    def should_poll(self):
        """ No polling needed for a demo light. """
        return False

    @property
    def name(self):
        """ Returns the name of the device if any. """
        return self._name

    @property
    def brightness(self):
        """ Brightness of this light between 0..255. """
        return self._brightness

    @property
    def is_on(self):
        """ True if device is on. """
        return self._state

    def turn_on(self, **kwargs):
        """ Turn the device on. """
        # Check if device is the siren
        if self._did != 0x1000004:
            return

        self._state = True

        if ATTR_BRIGHTNESS in kwargs:
            self._brightness = kwargs[ATTR_BRIGHTNESS]

        if (self._brightness > 0) and (self._brightness < 128):
            jablo_dongle.NETWORK.tx_state.beep = "SLOW"
            jablo_dongle.NETWORK.transmit_state()
        elif self._brightness >= 128:
            jablo_dongle.NETWORK.tx_state.beep = "FAST"
            jablo_dongle.NETWORK.transmit_state()

        self.update_ha_state()

    def turn_off(self, **kwargs):
        """ Turn the device off. """
        # Check if device is the siren
        if self._did != 0x1000004:
            return

        self._state = False
        jablo_dongle.NETWORK.tx_state.beep = "NONE"
        jablo_dongle.NETWORK.transmit_state()
        self.update_ha_state()
