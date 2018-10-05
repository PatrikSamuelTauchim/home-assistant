"""
homeassistant.components.switch.modbus
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
"""

import logging

import homeassistant.components.jablo_dongle as jablo_dongle
from homeassistant.helpers.entity import ToggleEntity

_LOGGER = logging.getLogger(__name__)

jablo_outputs_binary = {
    'enroll': {'id': 0x1000000, 'name': "ENROLL"},
    'pgx': {'id': 0x1000001, 'name': "PGX"},
    'pgy': {'id': 0x1000002, 'name': "PGY"},
    'alarm': {'id': 0x1000003, 'name': "SIREN_LOUD"},
}


def setup_platform(hass, config, add_devices, discovery_info=None):
    """ Create binary switches """
    switches = []
    dev_conf_list = None

    if config.get('devices'):
        dev_conf_list = config.get('devices')

    # Use default switch names if user does not specify any configuration
    if dev_conf_list is None:
        for device in jablo_outputs_binary.values():
            switches.append(JabloSwitch(device['id'], device['name']))
    # Use device names as specified in config file
    else:
        for dev, dev_config_default in jablo_outputs_binary.items():
            # Is device present in config file?
            if dev_conf_list.get(dev):
                dev_config = dev_conf_list.get(dev)
                # Name field in device config is obligatory
                if dev_config.get('name'):
                    custom_name = dev_config.get('name')
                    switches.append(JabloSwitch(dev_config_default.get('id'), custom_name))

    add_devices(switches)


class JabloSwitch(ToggleEntity):
    """ Represents a Modbus switch. """

    def __init__(self, did, name):
        self._is_on = None
        self._did = did
        self._name = name

    @property
    def should_poll(self):
        """ No polling required """
        return False

    @property
    def is_on(self):
        """ Returns True if switch is on. """
        return self._is_on

    @property
    def name(self):
        """ Get the name of the switch. """
        return self._name

    def turn_on(self, **kwargs):
        if self._did == jablo_outputs_binary['pgx']['id']:
            jablo_dongle.NETWORK.tx_state.pgx = True
        elif self._did == jablo_outputs_binary['pgy']['id']:
            jablo_dongle.NETWORK.tx_state.pgy = True
        elif self._did == jablo_outputs_binary['enroll']['id']:
            jablo_dongle.NETWORK.tx_state.enroll = True
        elif self._did == jablo_outputs_binary['alarm']['id']:
            jablo_dongle.NETWORK.tx_state.alarm = True

        jablo_dongle.NETWORK.transmit_state()
        self._is_on = True
        self.update_ha_state()

    def turn_off(self, **kwargs):
        if self._did == jablo_outputs_binary['pgx']['id']:
            jablo_dongle.NETWORK.tx_state.pgx = False
        elif self._did == jablo_outputs_binary['pgy']['id']:
            jablo_dongle.NETWORK.tx_state.pgy = False
        elif self._did == jablo_outputs_binary['enroll']['id']:
            jablo_dongle.NETWORK.tx_state.enroll = False
        elif self._did == jablo_outputs_binary['alarm']['id']:
            jablo_dongle.NETWORK.tx_state.alarm = False

        jablo_dongle.NETWORK.transmit_state()
        self._is_on = False
        self.update_ha_state()
