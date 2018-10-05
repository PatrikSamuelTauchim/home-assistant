"""
Support for Jablotron thermostats.
"""
import logging

from pydispatch import dispatcher

from homeassistant.components.thermostat import ThermostatDevice
from homeassistant.components.jablo_dongle import JaMtype
import homeassistant.components.jablo_dongle as jablo_dongle
from homeassistant.const import TEMP_CELCIUS


_LOGGER = logging.getLogger(__name__)

dev_conf_list = None


def setup_platform(hass, config, add_devices, discovery_info=None):
    """ Create discovered thermostats """
    # On startup
    if discovery_info is None:
        # Save configuration so we can use it later
        global dev_conf_list
        if config.get('devices'):
            dev_conf_list = config.get('devices')

    # On device discovery
    else:
        sensors = []
        did = discovery_info['did']
        model = discovery_info['model']

        # Use default sensor names if user does not specify any configuration
        if dev_conf_list is None:
            if model == "TP-82N":
                sensors.append(JabloThermostat(did, "%s_%d" % (model, did)))
        # Use device names and options as specified in config file
        else:
            if dev_conf_list.get(did):
                dev_config = dev_conf_list.get(did)
            else:
                # Device is not configured
                return

            custom_name = None

            if dev_config.get('name'):
                custom_name = dev_config.get('name')

            # Name field in device config is obligatory
            if custom_name is None:
                return

            if model == "TP-82N":
                sensors.append(JabloThermostat(did, custom_name))

        add_devices(sensors)
        _LOGGER.info("New thermostat discovered")


# pylint: disable=too-many-arguments
class JabloThermostat(ThermostatDevice):
    """ Represents a thermostat """

    def __init__(self, did, name):
        self._did = did
        self._name = name
        self._target_temperature = 0
        self._unit_of_measurement = TEMP_CELCIUS
        self._current_temperature = 0
        dispatcher.connect(self._process_message, jablo_dongle.MESSAGE_RECEIVED_SIGNAL)

    @property
    def should_poll(self):
        """ No polling needed """
        return False

    @property
    def name(self):
        """ Returns the name. """
        return self._name

    @property
    def unit_of_measurement(self):
        """ Returns the unit of measurement. """
        return self._unit_of_measurement

    @property
    def current_temperature(self):
        """ Returns the current temperature. """
        return self._current_temperature

    @property
    def target_temperature(self):
        """ Returns the temperature we try to reach. """
        return self._target_temperature

    def _process_message(self, jmsg):
        if jmsg.did != self._did:
            return

        if jmsg.mtype == JaMtype.SET:
            self._target_temperature = jmsg.temp
        elif jmsg.mtype == JaMtype.INT:
            self._current_temperature = jmsg.temp

        # Update battery status (if sensor reports this)
        if jmsg.lb is not None:
            self._lb = jmsg.lb

        self.update_ha_state()
