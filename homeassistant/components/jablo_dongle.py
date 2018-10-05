"""
homeassistant.components.jablo_dongle
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Implements support for Turris Dongle by Jablotron Alarms, a.s.
"""

from enum import Enum
import logging
import threading
from threading import Condition, Lock

from pydispatch import dispatcher
import serial
from serial.serialutil import SerialException

from homeassistant.const import (EVENT_HOMEASSISTANT_START, EVENT_HOMEASSISTANT_STOP, EVENT_PLATFORM_DISCOVERED,
                                 ATTR_SERVICE, ATTR_DISCOVERED)
from homeassistant.helpers.entity_component import EntityComponent


oldfw = False

DOMAIN = "jablo_dongle"

DEPENDENCIES = []

SERIAL_PORT = "port"

MESSAGE_RECEIVED_SIGNAL = 'ja_msg_recv_sig'

_LOGGER = logging.getLogger(__name__)

NETWORK = None
DISCOVER_SENSORS = "jablo_dongle.sensors"
DISCOVER_THERMOSTATS = "jablo_dongle.thermostats"


def peripheries_setup(hass, config):
    """ This method does initialization of components that use discovery.

    Calling component setup from here is maybe a bit hacky, however current version
    of HA does not allow any simple way of doing this from third-party components
    (i.e. modification sensor.__init__/thermostat.__init__ is needed otherwise).
    """
    from homeassistant.components.thermostat import (
        SCAN_INTERVAL as THERMOSTAT_SCAN_INTERVAL,
        DOMAIN as THERMOSTAT_DOMAIN
    )
    thermostats = EntityComponent(_LOGGER, THERMOSTAT_DOMAIN, hass, THERMOSTAT_SCAN_INTERVAL, discovery_platforms={
        DISCOVER_THERMOSTATS: 'jablo_dongle'
    })
    thermostats.setup(config)

    from homeassistant.components.sensor import (
        SCAN_INTERVAL as SENSOR_SCAN_INTERVAL,
        DOMAIN as SENSOR_DOMAIN
    )
    sensors = EntityComponent(_LOGGER, SENSOR_DOMAIN, hass, SENSOR_SCAN_INTERVAL, discovery_platforms={
        DISCOVER_SENSORS: 'jablo_dongle'
    })
    sensors.setup(config)


def setup(hass, config):
    """ Setup component. """
    global NETWORK

    NETWORK = JabloDongle(hass, config[DOMAIN][SERIAL_PORT])

    def stop_dongle(event):
        """ Stop Modbus service. """
        NETWORK.disconnect()

    def start_dongle(event):
        """ Start Modbus service. """

        if NETWORK.connect() is False:
            return False
        NETWORK.read_slots()
        NETWORK.insert_devices()
        hass.bus.listen_once(EVENT_HOMEASSISTANT_STOP, stop_dongle)
        return True

    hass.bus.listen_once(EVENT_HOMEASSISTANT_START, start_dongle)

    peripheries_setup(hass, config)

    # Tells the bootstrapper that the component was successfully initialized
    return True


class TxState:
    def __init__(self):
        self.enroll = False
        self.pgx = False
        self.pgy = False
        self.alarm = False
        self.beep = 'NONE'


class JabloDongle:
    def __init__(self, hass, port):
        self._hass = hass
        self._portname = port
        self._serial = None
        self._readthread = None
        self.last_mid = 0
        self.last_mtype = JaMtype.UNDEF
        self.tx_state = TxState()
        self.slots = []
        self.slot_read_cond = Condition()
        self._tx_lock = Lock()

    def serial_read_loop(self):
        while True:
            data = self._serial.readline().decode('ascii', 'replace')

            if len(data) == 1:
                continue

            # _LOGGER.error("Received data: %s" % (data))
            jmsg = JaMessage(data)

            if jmsg.mid is None and \
                    (jmsg.mtype != NETWORK.last_mtype or (jmsg.mtype != JaMtype.SET and jmsg.mtype != JaMtype.INT)):
                NETWORK.process_message(jmsg)
                NETWORK.last_mtype = jmsg.mtype
            elif jmsg.mid != NETWORK.last_mid:
                NETWORK.process_message(jmsg)
                NETWORK.last_mid = jmsg.mid

    def connect(self):
        try:
            self._serial = serial.Serial(self._portname, 57600)
        except SerialException as ex:
            _LOGGER.error("Cannot open serial port %s (%s)" % (self._portname, ex))
            return False

        # self._serial.flush()
        _LOGGER.info("Serial port %s opened" % self._portname)

        self._readthread = threading.Thread(target=self.serial_read_loop)
        self._readthread.start()
        _LOGGER.info("Receiving thread started")
        return True
        # self.transmit_state()

    def disconnect(self):
        self._serial.close()

    def process_message(self, jmsg):
        if jmsg.mtype == JaMtype.UNDEF:
            _LOGGER.warning("Unknown message received: '%s'", jmsg.text.encode('utf-8'))
            return

        if jmsg.mtype != JaMtype.SLOT \
                and jmsg.mtype != JaMtype.VERSION \
                and jmsg.mtype != JaMtype.OK \
                and jmsg.mtype != JaMtype.ERR:
            _LOGGER.info("Received message of type %s from device %d (%s)" % (jmsg.mtype, jmsg.did, jmsg.devmodel))

        if jmsg.mtype == JaMtype.SLOT:
            if jmsg.slotval is not None:
                _LOGGER.info(
                    "Slot %d: %d (%s)" % (jmsg.slotnum, jmsg.slotval, JaDevice.get_model_from_id(jmsg.slotval)))
                self.slots.append({'num': jmsg.slotnum, 'dev': JaDevice(jmsg.slotval)})

            self.slot_read_cond.acquire()
            self.slot_read_cond.notify()
            self.slot_read_cond.release()
        else:
            dispatcher.send(MESSAGE_RECEIVED_SIGNAL, **{'jmsg': jmsg})

    def transmit_state(self):
        tx_string = "\nTX ENROLL:%d PGX:%d PGY:%d ALARM:%d BEEP:%s\n" % (
            self.tx_state.enroll, self.tx_state.pgx, self.tx_state.pgy, self.tx_state.alarm, self.tx_state.beep
        )
        self._tx_lock.acquire()
        self._serial.write(tx_string.encode())
        self._serial.flush()
        self._tx_lock.release()

    def read_slots(self):
        for i in range(32):
            self._serial.write(("\nGET SLOT:%02d\n" % i).encode())
            self._serial.flush()
            self.slot_read_cond.acquire()
            self.slot_read_cond.wait()
            self.slot_read_cond.release()

    def insert_devices(self):
        for slot in self.slots:
            jdev = slot['dev']

            if jdev.model == "TP-82N":
                self._hass.bus.fire(EVENT_PLATFORM_DISCOVERED, {
                    ATTR_SERVICE: DISCOVER_THERMOSTATS,
                    ATTR_DISCOVERED: {
                        'did': jdev.did,
                        'model': jdev.model
                    }
                })
            else:
                self._hass.bus.fire(EVENT_PLATFORM_DISCOVERED, {
                    ATTR_SERVICE: DISCOVER_SENSORS,
                    ATTR_DISCOVERED: {
                        'did': jdev.did,
                        'model': jdev.model
                    }
                })


class JaMtype(Enum):
    UNDEF = 0
    ARM = 1
    DISARM = 2
    BEACON = 3
    SENSOR = 4
    TAMPER = 5
    PANIC = 6
    DEFECT = 7
    BUTTON = 8
    SET = 9
    INT = 10
    OK = 11
    ERR = 12
    SLOT = 13
    VERSION = 14


class JaMessage:
    def __init__(self, msgline):
        self._text = msgline.rstrip()
        self.did = None
        self.mid = None
        self.devmodel = None
        self.mtype = JaMtype.UNDEF
        self.act = None
        self.lb = None
        self.blackout = None
        self.temp = None
        self.slotnum = None
        self.slotval = None
        self.version = None

        try:
            if self.text == "OK":
                self.mtype = JaMtype.OK
            elif self.text == "ERROR":
                self.mtype = JaMtype.ERR
            elif self.text.startswith("TURRIS DONGLE V"):
                self.mtype = JaMtype.VERSION
                self.version = self.text[15:-1]
            elif self.text.startswith("SLOT:"):
                self.mtype = JaMtype.SLOT
                self.slotnum = int(self.text[5:7], base=10)
                try:
                    self.slotval = int(self.text[9:17], base=10)
                except ValueError:
                    self.slotval = None
            else:
                tokens = self.text.split()

                self.did = int(tokens[0][1:-1], 10)

                # Hack to support old fw, remove in final version
                global oldfw
                if oldfw:
                    if tokens[1] != "ID:---":
                        self.mid = int(tokens[1][3:], 10)
                    self.devmodel = tokens[2]
                else:
                    self.devmodel = tokens[1]

                if oldfw:
                    if tokens[3] == "SENSOR":
                        self.mtype = JaMtype.SENSOR
                    elif tokens[3] == "TAMPER":
                        self.mtype = JaMtype.TAMPER
                    elif tokens[3] == "BEACON":
                        self.mtype = JaMtype.BEACON
                    elif tokens[3] == "BUTTON":
                        self.mtype = JaMtype.BUTTON
                    elif tokens[3] == "ARM:1":
                        self.mtype = JaMtype.ARM
                    elif tokens[3] == "ARM:0":
                        self.mtype = JaMtype.DISARM
                    elif tokens[3][0:4] == "SET:":
                        self.mtype = JaMtype.SET
                        if len(tokens[3]) > 4:
                            self.temp = float(tokens[3][4:8])
                        else:
                            self.temp = float(tokens[4][0:3])
                    elif tokens[3][0:4] == "INT:":
                        self.mtype = JaMtype.INT
                        if len(tokens[3]) > 4:
                            self.temp = float(tokens[3][4:8])
                        else:
                            self.temp = float(tokens[4][0:3])
                    else:
                        self.mtype = JaMtype.UNDEF
                else:
                    if tokens[2] == "SENSOR":
                        self.mtype = JaMtype.SENSOR
                    elif tokens[2] == "TAMPER":
                        self.mtype = JaMtype.TAMPER
                    elif tokens[2] == "BEACON":
                        self.mtype = JaMtype.BEACON
                    elif tokens[2] == "BUTTON":
                        self.mtype = JaMtype.BUTTON
                    elif tokens[2] == "ARM:1":
                        self.mtype = JaMtype.ARM
                    elif tokens[2] == "ARM:0":
                        self.mtype = JaMtype.DISARM
                    elif tokens[2][0:4] == "SET:":
                        self.mtype = JaMtype.SET
                        if len(tokens[2]) > 4:
                            self.temp = float(tokens[2][4:8])
                        else:
                            self.temp = float(tokens[3][0:3])
                    elif tokens[2][0:4] == "INT:":
                        self.mtype = JaMtype.INT
                        if len(tokens[2]) > 4:
                            self.temp = float(tokens[2][4:8])
                        else:
                            self.temp = float(tokens[3][0:3])
                    else:
                        self.mtype = JaMtype.UNDEF

                for token in tokens[3:]:
                    if token.startswith("LB:"):
                        self.lb = int(token[3:])
                    elif token.startswith("ACT:"):
                        self.act = int(token[4:])
                    elif token.startswith("BLACKOUT:"):
                        self.act = int(token[9:])
        except Exception:
            self.mtype = JaMtype.UNDEF

    @property
    def text(self):
        return self._text


class JaDevice:
    def __init__(self, did):
        self.did = did
        self.model = self.get_model_from_id(did)

    @staticmethod
    def get_model_from_id(did):
        if 0x800000 <= did <= 0x87FFFF:
            return "RC-86K"
        elif 0x900000 <= did <= 0x97FFFF:
            return "RC-86K"
        elif 0x180000 <= did <= 0x1BFFFF:
            return "JA-81M"
        elif 0x1C0000 <= did <= 0x1DFFFF:
            return "JA-83M"
        elif 0x640000 <= did <= 0x65FFFF:
            return "JA-83P"
        elif 0x7F0000 <= did <= 0x7FFFFF:
            return "JA-82SH"
        elif 0x760000 <= did <= 0x76FFFF:
            return "JA-85ST"
        elif 0x580000 <= did <= 0x59FFFF:
            return "JA-80L"
        elif 0xCF0000 <= did <= 0xCFFFFF:
            return "AC-88"
        elif 0x240000 <= did <= 0x25FFFF:
            return "TP-82N"
        else:
            return "Unknown"
