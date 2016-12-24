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

import time
import zmq

from Queue import Empty, Queue
from threading import Thread

from supvisors.utils import EventHeaders, supvisors_short_cuts


class EventSubscriber(object):
    """ Class for subscription to Listener events.

    Attributes:
    - supvisors: a reference to the Supvisors context,
    - socket: the PyZMQ subscriber. """

    def __init__(self, supvisors, zmq_context):
        """ Initialization of the attributes. """
        self.supvisors = supvisors
        self.socket = zmq_context.socket(zmq.SUB)
        # connect all EventPublisher to Supvisors addresses
        for address in supvisors.address_mapper.addresses:
            url = 'tcp://{}:{}'.format(address, supvisors.options.internal_port)
            supvisors.logger.info('connecting EventSubscriber to %s' % url)
            self.socket.connect(url)
        supvisors.logger.debug('EventSubscriber connected')
        self.socket.setsockopt(zmq.SUBSCRIBE, '')
 
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
            self.supvisors.logger.info('disconnecting EventSubscriber from %s' % url)
            self.socket.disconnect(url)

    def close(self):
        """ This method closes the PyZMQ socket. """
        self.socket.close()


class SupvisorsMainLoop(Thread):
    """ Class for Supvisors main loop. All inputs are sequenced here.

    Attributes:
    - supvisors: a reference to the Supvisors context,
    - zmq_context: the ZeroMQ context used to create sockets,
    - subscriber: the event subscriber,
    - loop: the infinite loop flag. """

    def __init__(self, supvisors):
        """ Initialization of the attributes. """
        # thread attributes
        Thread.__init__(self)
        # shortcuts
        self.supvisors = supvisors
        supvisors_short_cuts(self, ['fsm', 'logger', 'pool', 'statistician'])
        # create queues for internal comminucation
        self.event_queue = Queue()
        self.address_queue = Queue()
        # ZMQ context definition
        self.zmq_context = zmq.Context.instance()
        self.zmq_context.setsockopt(zmq.LINGER, 0)
        # create event sockets
        self.subscriber = EventSubscriber(supvisors, self.zmq_context)
        supvisors.publisher.open(self.zmq_context)

    def close(self):
        """ This method closes the resources. """
        # close the ZeroMQ sockets
        self.supvisors.publisher.close()
        self.subscriber.close()
        # close zmq context
        self.zmq_context.term()
        # finally, close logger
        self.logger.close()

    def stop(self):
        """ Request to stop the infinite loop by resetting its flag. """
        self.logger.info('request to stop main loop')
        self.loop = False

    # main loop
    def run(self):
        """ Contents of the infinite loop. """
        # create poller
        poller = zmq.Poller()
        # register event subscriber
        poller.register(self.subscriber.socket, zmq.POLLIN) 
        timer_event_time = time.time()
        # poll events every seconds
        self.loop = True
        while self.loop:
            socks = dict(poller.poll(1000))
            # Need to test loop flag again as its value may have changed in the last second.
            if self.loop:
                # check tick and process events
                if self.subscriber.socket in socks and socks[self.subscriber.socket] == zmq.POLLIN:
                    self.logger.blather('got message on event subscriber')
                    try:
                        message = self.subscriber.receive()
                    except Exception, e:
                        self.logger.warn('failed to get data from subscriber: {}'.format(e.message))
                    else:
                        # The events received are not processed directly in this thread because it may conflict
                        # with the Supvisors functions triggered from the Supervisor thread, as they use the
                        # same data. So they are pushed into a PriorityQueue (Tick > Process > Statistics) and
                        # Supvisors uses an async RemoteCommunicationEvent to unstack and process the event
                        # from the context of the Supervisor thread.
                        self.event_queue.put_nowait(message)
                        self.pool.async_event()
                # check periodic task
                if timer_event_time + 5 < time.time():
                    self.pool.async_task()
                    # set date for next task
                    timer_event_time = time.time()
                # check isolation of addresses
                try:
                    addresses = self.address_queue.get_nowait()
                except Empty:
                    # nothing to do
                    pass
                else:
                    # disconnect isolated addresses from sockets
                    self.subscriber.disconnect(addresses)
        self.logger.info('exiting main loop')
        # close resources gracefully
        self.close()

    def unstack_event(self):
        """ Unstack and process one event from the event queue. """
        event_type, event_address, event_data = self.event_queue.get_nowait()
        if event_type == EventHeaders.TICK:
            self.logger.blather('got tick message from {}: {}'.format(event_address, event_data))
            self.fsm.on_tick_event(event_address, event_data)
        elif event_type == EventHeaders.PROCESS:
            self.logger.blather('got process message from {}: {}'.format(event_address, event_data))
            self.fsm.on_process_event(event_address, event_data)
        elif event_type == EventHeaders.STATISTICS:
            self.logger.blather('got statistics message from {}: {}'.format(event_address, event_data))
            self.statistician.push_statistics(event_address, event_data)

    def unstack_info(self):
        """ Unstack the process info received. """
        address_name, info = self.pool.info_queue.get()
        self.supvisors.context.load_processes(address_name, info)

    def periodic_task(self):
        """ Periodic task that mainly checks that addresses are still operating. """
        self.logger.blather('periodic task')
        addresses = self.fsm.on_timer_event()
        # pushes isolated addresses to main loop
        self.address_queue.put_nowait(addresses)
