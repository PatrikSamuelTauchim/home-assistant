"""
Support for Jablotron sensors.
"""

import logging
import threading
from time import sleep

from pydispatch import dispatcher

import homeassistant.components.jablo_dongle as jablo_dongle
from homeassistant.components.jablo_dongle import JaMtype
from homeassistant.helpers.entity import Entity
from homeassistant.const import (STATE_ON, STATE_OFF, ATTR_BATTERY_LEVEL)


_LOGGER = logging.getLogger(__name__)

STATE_UNKNOWN = '-'

dev_conf_list = None


def setup_platform(hass, config, add_devices, discovery_info=None):
    """ Create discovered devices """
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
            if model == "JA-83M" or model == "JA-81M":
                sensors.append(JabloSensor(did, 0, 0, (JaMtype.SENSOR,), "%s_%d_SENSOR" % (model, did)))
                sensors.append(JabloSensor(did, 1, 0, (JaMtype.TAMPER,), "%s_%d_TAMPER" % (model, did)))
            elif model == "JA-83P" or model == "JA-82SH":
                sensors.append(JabloSensor(did, 0, 60, (JaMtype.SENSOR,), "%s_%d_SENSOR" % (model, did)))
                sensors.append(JabloSensor(did, 1, 60, (JaMtype.TAMPER,), "%s_%d_TAMPER" % (model, did)))
            elif model == "JA-85ST":
                sensors.append(JabloSensor(did, 0, 60, (JaMtype.SENSOR,), "%s_%d_SENSOR" % (model, did)))
            elif model == "RC-86K":
                sensors.append(JabloSensor(did, 0, 0, (JaMtype.ARM, JaMtype.DISARM), "%s_%d_ARM" % (model, did)))
            elif model == "JA-80L":
                sensors.append(JabloSensor(did, 0, 0, (JaMtype.BUTTON,), "%s_%d_BUTTON" % (model, did)))
                sensors.append(JabloSensor(did, 1, 60, (JaMtype.TAMPER,), "%s_%d_TAMPER" % (model, did)))
        # Use device names and options as specified in config file
        else:
            if dev_conf_list.get(did):
                dev_config = dev_conf_list.get(did)
            else:
                # Device is not configured
                return

            custom_name = None
            custom_outputs = None
            custom_off_delay = 60

            if dev_config.get('name'):
                custom_name = dev_config.get('name')
            if dev_config.get('outputs'):
                custom_outputs = dev_config.get('outputs')
            if dev_config.get('off_delay'):
                custom_off_delay = dev_config.get('off_delay')

            # Name and outputs fields in device config are obligatory
            if custom_name is None or custom_outputs is None:
                return

            if model == "JA-83M" or model == "JA-81M" or model == "JA-83P" or model == "JA-82SH":
                if 'sensor' in custom_outputs:
                    sensors.append(
                        JabloSensor(
                            did, 0, custom_off_delay, (JaMtype.SENSOR,),
                            (custom_name + " (sensor)") if len(custom_outputs) > 1 else custom_name
                        )
                    )
                if 'tamper' in custom_outputs:
                    sensors.append(
                        JabloSensor(
                            did, 1, 0, (JaMtype.TAMPER,),
                            (custom_name + " (tamper)") if len(custom_outputs) > 1 else custom_name
                        )
                    )
            elif model == "JA-85ST":
                if 'sensor' in custom_outputs:
                    sensors.append(JabloSensor(did, 0, custom_off_delay, (JaMtype.SENSOR,), custom_name))
            elif model == "RC-86K":
                if 'arm' in custom_outputs:
                    sensors.append(JabloSensor(did, 0, 0, (JaMtype.ARM, JaMtype.DISARM), custom_name))
            elif model == "JA-80L":
                if 'button' in custom_outputs:
                    sensors.append(
                        JabloSensor(
                            did, 0, custom_off_delay, (JaMtype.BUTTON,),
                            (custom_name + " (button)") if len(custom_outputs) > 1 else custom_name
                        )
                    )
                if 'tamper' in custom_outputs:
                    sensors.append(
                        JabloSensor(
                            did, 1, custom_off_delay, (JaMtype.TAMPER,),
                            (custom_name + " (tamper)") if len(custom_outputs) > 1 else custom_name
                        )
                    )

        add_devices(sensors)
        _LOGGER.info("New device discovered")


class JabloSensor(Entity):
    # pylint: disable=too-many-arguments
    """ Represents a sensor """

    def __init__(self, did, subdev_id, off_delay, react_mtypes, name):
        self._name = name
        self._did = did
        self._subdev_id = subdev_id
        self._off_delay = off_delay
        self._react_mtypes = react_mtypes
        self._is_on = STATE_UNKNOWN
        self._lb = None
        self._state_lock = threading.Lock()
        dispatcher.connect(self._process_message, jablo_dongle.MESSAGE_RECEIVED_SIGNAL)

    @property
    def should_poll(self):
        """ No polling required"""
        return False

    @property
    def state(self):
        """ Returns the state of the sensor. """
        return self._is_on

    @property
    def state_attributes(self):
        """ Returns the state attributes. """
        attrs = {}

        if self._lb is not None:
            attrs[ATTR_BATTERY_LEVEL] = '100%' if self._lb == 0 else '5%'

        return attrs

    @property
    def name(self):
        """ Get the name of the sensor. """
        return self._name

    def _turn_off_momentary(self):
        sleep(self._off_delay)
        _LOGGER.info("Turning off momentary switch \"%s\"" % self._name)
        self._state_lock.acquire()
        self._is_on = STATE_OFF
        self.update_ha_state()
        self._state_lock.release()

    def _process_message(self, jmsg):
        if jmsg.did != self._did:
            return

        # Only react to specified messages and beacons
        if (jmsg.mtype not in self._react_mtypes) and (jmsg.mtype != JaMtype.BEACON):
            return

        self._state_lock.acquire()
        if jmsg.mtype == JaMtype.ARM:
            self._is_on = STATE_ON
        elif jmsg.mtype == JaMtype.DISARM:
            self._is_on = STATE_OFF
        elif jmsg.mtype in (JaMtype.SENSOR, JaMtype.TAMPER, JaMtype.BUTTON):
            if jmsg.act is None:
                # Momentary switces
                self._is_on = STATE_ON
                if self._off_delay >= 1:
                    _LOGGER.info("Starting turn-off delay thread")
                    threading.Thread(target=self._turn_off_momentary).start()
            else:
                # Bistable switches
                self._is_on = STATE_ON if jmsg.act else STATE_OFF

        # Update battery status (if sensor reports this)
        if jmsg.lb is not None:
            self._lb = jmsg.lb

        self.update_ha_state()
        self._state_lock.release()
