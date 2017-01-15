#!/usr/bin/python
#-*- coding: utf-8 -*-

# ======================================================================
# Copyright 2016 Julien LE CLEACH
# 
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
# 
#     http://www.apache.org/licenses/LICENSE-2.0
# 
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ======================================================================

import zmq

from supvisors.utils import *


class InternalEventPublisher(object):
    """ This class is the wrapper of the ZeroMQ socket that publishes the events
    to the Supvisors instances.
    
    Attributes are:
        - supvisors: a reference to the Supervisor context,
        - address: the address name where this process is running,
        - socket: the ZeroMQ socket with a PUBLISH pattern, bound on the internal_port defined
            in the ['supvisors'] section of the Supervisor configuration file.
    """

    def __init__(self, supvisors, zmq_context):
        """ Initialization of the attributes. """
        # keep a reference to supvisors
        self.supvisors = supvisors
        # shortcuts for source code readability
        supvisors_short_cuts(self, ['logger'])
        # get local address
        self.address = supvisors.address_mapper.local_address
        # create ZMQ socket
        self.socket = zmq_context.socket(zmq.PUB)
        url = 'tcp://*:{}'.format(supvisors.options.internal_port)
        self.logger.info('binding InternalEventPublisher to %s' % url)
        self.socket.bind(url)

    def close(self):
        """ This method closes the PyZMQ socket. """
        self.socket.close()

    def send_tick_event(self, payload):
        """ Publishes the tick event with ZeroMQ. """
        self.logger.debug('send TickEvent {}'.format(payload))
        self.socket.send_pyobj((EventHeaders.TICK, self.address, payload))

    def send_process_event(self, payload):
        """ Publishes the process event with ZeroMQ. """
        self.logger.debug('send ProcessEvent {}'.format(payload))
        self.socket.send_pyobj((EventHeaders.PROCESS, self.address, payload))

    def send_statistics(self, payload):
        """ Publishes the statistics with ZeroMQ. """
        self.logger.debug('send Statistics {}'.format(payload))
        self.socket.send_pyobj((EventHeaders.STATISTICS, self.address, payload))


class InternalEventSubscriber(object):
    """ Class for subscription to Listener events.

    Attributes:
        - supvisors: a reference to the Supvisors context,
        - socket: the PyZMQ subscriber.
    """

    def __init__(self, supvisors, zmq_context):
        """ Initialization of the attributes. """
        self.supvisors = supvisors
        self.socket = zmq_context.socket(zmq.SUB)
        # connect all EventPublisher to Supvisors addresses
        for address in supvisors.address_mapper.addresses:
            url = 'tcp://{}:{}'.format(address, supvisors.options.internal_port)
            supvisors.logger.info('connecting InternalEventSubscriber to %s' % url)
            self.socket.connect(url)
        supvisors.logger.debug('InternalEventSubscriber connected')
        self.socket.setsockopt(zmq.SUBSCRIBE, '')
 
    def close(self):
        """ This method closes the PyZMQ socket. """
        self.socket.close()

    def receive(self):
        """ Reception and pyobj unserialization of one message including:
        - the message header,
        - the origin,
        - the body of the message. """
        return self.socket.recv_pyobj()

    def disconnect(self, addresses):
        """ This method disconnects from the PyZMQ socket all addresses passed in parameter. """
        for address in addresses:
            url = 'tcp://{}:{}'.format(address, self.supvisors.options.internal_port)
            self.supvisors.logger.info('disconnecting InternalEventSubscriber from %s' % url)
            self.socket.disconnect(url)


class EventPublisher(object):
    """ Class for ZMQ publication of Supvisors events. """

    def __init__(self, supvisors, zmq_context):
        self.supvisors = supvisors
        self.socket = zmq_context.socket(zmq.PUB)
        # WARN: this is a local binding, only visible to processes located on the same address
        url = 'tcp://127.0.0.1:{}'.format(self.supvisors.options.event_port)
        supvisors.logger.info('binding local Supvisors EventPublisher to %s' % url)
        self.socket.bind(url)

    def close(self):
        """ This method closes the PyZMQ socket. """
        self.socket.close()

    def send_supvisors_status(self, status):
        if self.socket:
            self.supvisors.logger.debug('send SupvisorsStatus {}'.format(status))
            self.socket.send_string(SUPVISORS_STATUS_HEADER, zmq.SNDMORE)
            self.socket.send_json(status.serial())

    def send_address_status(self, status):
        if self.socket:
            self.supvisors.logger.debug('send RemoteStatus {}'.format(status))
            self.socket.send_string(ADDRESS_STATUS_HEADER, zmq.SNDMORE)
            self.socket.send_json(status.serial())

    def send_application_status(self, status):
        if self.socket:
            self.supvisors.logger.debug('send ApplicationStatus {}'.format(status))
            self.socket.send_string(APPLICATION_STATUS_HEADER, zmq.SNDMORE)
            self.socket.send_json(status.serial())

    def send_process_status(self, status):
        if self.socket:
            self.supvisors.logger.debug('send ProcessStatus {}'.format(status))
            self.socket.send_string(PROCESS_STATUS_HEADER, zmq.SNDMORE)
            self.socket.send_json(status.serial())


class RequestPuller(object):
    """ Class for pulling deferred XML-RPC.

    Attributes:
        - supvisors: a reference to the Supvisors context,
        - socket: the PyZMQ puller.
    """

    def __init__(self, supvisors, zmq_context):
        """ Initialization of the attributes. """
        self.supvisors = supvisors
        self.socket = zmq_context.socket(zmq.PULL)
        # connect RequestPuller to IPC address
        url = 'ipc://' + IPC_NAME
        supvisors.logger.info('connecting RequestPuller to %s' % url)
        self.socket.connect(url)
 
    def close(self):
        """ This method closes the PyZMQ socket. """
        self.socket.close()

    def receive(self):
        """ Reception and pyobj unserialization of one message including:
        - the message header,
        - the body of the message. """
        return self.socket.recv_pyobj()


class RequestPusher(object):
    """ Class for pushing deferred XML-RPC.

    Attributes:
        - supvisors: a reference to the Supvisors context,
        - socket: the PyZMQ pusher.
    """

    def __init__(self, supvisors, zmq_context):
        """ Initialization of the attributes. """
        self.logger = supvisors.logger
        self.socket = zmq_context.socket(zmq.PUSH)
        # connect RequestPusher to IPC address
        url = 'ipc://' + IPC_NAME
        self.logger.info('binding RequestPuller to %s' % url)
        self.socket.bind(url)
 
    def close(self):
        """ This method closes the PyZMQ socket. """
        self.socket.close()

    def send_check_address(self, address_name):
        """ Send request to check address. """
        self.logger.debug('send CHECK_ADDRESS {}'.format(address_name))
        self.socket.send_pyobj((RequestHeaders.DEF_CHECK_ADDRESS, (address_name, )))

    def send_isolate_addresses(self, address_names):
        """ Send request to isolate address. """
        self.logger.debug('send ISOLATE_ADDRESSES {}'.format(address_names))
        self.socket.send_pyobj((RequestHeaders.DEF_ISOLATE_ADDRESSES, address_names))

    def send_start_process(self, address_name, namespec, extra_args):
        """ Send request to start process. """
        self.logger.debug('send START_PROCESS {} to {} with {}'.format(namespec, address_name, extra_args))
        self.socket.send_pyobj((RequestHeaders.DEF_START_PROCESS, (address_name, namespec, extra_args)))

    def send_stop_process(self, address_name, namespec):
        """ Send request to stop process. """
        self.logger.debug('send STOP_PROCESS {} to {}'.format(namespec, address_name))
        self.socket.send_pyobj((RequestHeaders.DEF_STOP_PROCESS, (address_name, namespec)))

    def send_restart(self, address_name):
        """ Send request to restart a Supervisor. """
        self.logger.debug('send RESTART {}'.format(address_name))
        self.socket.send_pyobj((RequestHeaders.DEF_RESTART, (address_name, )))

    def send_shutdown(self, address_name):
        """ Send request to shutdown a Supervisor. """
        self.logger.debug('send SHUTDOWN {}'.format(address_name))
        self.socket.send_pyobj((RequestHeaders.DEF_SHUTDOWN, (address_name, )))


class SupvisorsZmq():
    """ Class for PyZmq context and sockets.  """

    def __init__(self, supvisors):
        """ Initialization of the attributes. """
        # ZMQ context definition
        self.zmq_context = zmq.Context()
        self.zmq_context.setsockopt(zmq.LINGER, 0)
        # create sockets
        self.publisher = EventPublisher(supvisors, self.zmq_context)
        self.internal_subscriber = InternalEventSubscriber(supvisors, self.zmq_context)
        self.internal_publisher = InternalEventPublisher(supvisors, self.zmq_context)
        self.puller = RequestPuller(supvisors, self.zmq_context)
        self.pusher = RequestPusher(supvisors, self.zmq_context)

    def close(self):
        """ This method closes the resources. """
        # close the sockets
        self.internal_publisher.close()
        self.internal_subscriber.close()
        self.pusher.close()
        self.puller.close()
        self.publisher.close()
        # close ZMQ context
        self.zmq_context.term()
