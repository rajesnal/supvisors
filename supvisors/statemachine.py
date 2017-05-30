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

from time import time

from supvisors.strategy import conciliate
from supvisors.ttypes import AddressStates, SupvisorsStates
from supvisors.utils import supvisors_short_cuts


class AbstractState(object):
    """ Base class for a state with simple entry / next / exit actions """

    def __init__(self, supvisors):
        """ Initialization of the attributes. """
        self.supvisors = supvisors
        supvisors_short_cuts(self, ['context', 'logger', 'starter', 'stopper'])
        self.address = supvisors.address_mapper.local_address

    def enter(self):
        """ Actions performed when reaching the state. """

    def next(self):
        """ Actions performed upon event. """

    def exit(self):
        """ Actions performed when leaving the state. """

    def apply_addresses_func(self, func):
        """ Perform the action func on all addresses.
        The local address is the last to be performed. """
        # send func request to all locals (but self address)
        for status in self.context.addresses.values():
            if status.address_name != self.address:
                if status.state == AddressStates.RUNNING:
                    func(status.address_name)
                    self.logger.warn('supervisord {} on {}'.format(func.__name__, status.address_name))
                else:
                    self.logger.info('cannot {} supervisord on {}: Remote state is {}'.format(func.__name__, status.address_name, status.state_string()))
        # send request to self supervisord
        func(self.address)


class InitializationState(AbstractState):
    """ In the INITIALIZATION state, Supvisors synchronizes to all known instances. """

    def enter(self):
        """ When entering in the INITIALIZATION state, reset the status of addresses. """
        self.context.master_address = ''
        self.start_date = int(time())
        # re-init addresses that are not isolated
        for status in self.context.addresses.values():
            if not status.in_isolation():
                # do NOT use state setter as transition may be rejected
                status._state = AddressStates.UNKNOWN

    def next(self):
        """ Wait for addresses to publish until all are active or timeout. """
        # cannot get out of this state without local supervisor RUNNING
        addresses = self.context.running_addresses()
        if self.address in addresses:
            if len(self.context.unknown_addresses()) == 0:
                # synchro done if the state of all addresses is known
                return SupvisorsStates.DEPLOYMENT
            # if synchro timeout reached, stop synchro and work with known addresses
            if (time() - self.start_date) > self.supvisors.options.synchro_timeout:
                self.logger.warn('synchro timed out')
                return SupvisorsStates.DEPLOYMENT
            self.logger.debug('still waiting for remote supvisors to synchronize')
        else:
            self.logger.debug('local address {} still not RUNNING'.format(self.address))
        return SupvisorsStates.INITIALIZATION

    def exit(self):
        """ When leaving the INITIALIZATION state, the working addresses are defined.
        One of them is elected as the MASTER. """
        # force state of missing Supvisors instances
        self.context.end_synchro()
        # arbitrarily choice : master address is the 'lowest' address among running addresses
        addresses = self.context.running_addresses()
        self.logger.info('working with boards {}'.format(addresses))
        self.context.master_address = min(addresses)


class DeploymentState(AbstractState):
    """ In the DEPLOYMENT state, Supvisors starts automatically the applications having a deployment definition. """

    def enter(self):
        """ When entering in the DEPLOYMENT state, define the start sequencing.
        Only the MASTER can perform the automatic starting. """
        # TODO: make a restriction of addresses in process rules, iaw process location in Supervisor instances
        # define ordering iaw Addresses
        for application in self.context.applications.values():
            application.update_sequences()
            application.update_status()
        # only the Supvisors master deploys applications
        if self.context.master:
            self.starter.start_applications()

    def next(self):
        """ Wait for applications to be started. """
        if not self.context.master or self.starter.check_starting():
                return SupvisorsStates.CONCILIATION if self.context.conflicting() else SupvisorsStates.OPERATION
        return SupvisorsStates.DEPLOYMENT


class OperationState(AbstractState):
    """ In the OPERATION state, Supvisors is waiting for requests. """

    def next(self):
        """ Check that all addresses are still active.
        Look after possible conflicts due to multiple running instances of the same program. """
        # check eventual jobs in progress
        if self.starter.check_starting() and self.stopper.check_stopping():
            # check if master and local are still RUNNING
            if self.context.addresses[self.address].state != AddressStates.RUNNING:
                return SupvisorsStates.INITIALIZATION
            if self.context.addresses[self.context.master_address].state != AddressStates.RUNNING:
                return SupvisorsStates.INITIALIZATION
            # check duplicated processes
            if self.context.conflicting():
                return SupvisorsStates.CONCILIATION
        return SupvisorsStates.OPERATION


class ConciliationState(AbstractState):
    """ In the CONCILIATION state, Supvisors conciliates the conflicts. """

    def enter(self):
        """ When entering in the CONCILIATION state, conciliate automatically the conflicts.
        Only the MASTER can conciliate conflicts. """
        if self.context.master:
            conciliate(self.supvisors, self.supvisors.options.conciliation_strategy, self.context.conflicts())

    def next(self):
        """ Check that all addresses are still active.
        Wait for all conflicts to be conciliated. """
        # check eventual jobs in progress
        if self.starter.check_starting() and self.stopper.check_stopping():
            # check if master and local are still RUNNING
            if self.context.addresses[self.address].state != AddressStates.RUNNING:
                return SupvisorsStates.INITIALIZATION
            if self.context.addresses[self.context.master_address].state != AddressStates.RUNNING:
                return SupvisorsStates.INITIALIZATION
            # check conciliation
            if not self.context.conflicting():
                return SupvisorsStates.OPERATION
        return SupvisorsStates.CONCILIATION


class RestartingState(AbstractState):
    """ In the RESTARTING state, Supvisors stops all applications before triggering a full restart. """

    def enter(self):
        """ When entering in the RESTARTING state, stop all applications. """
        self.starter.abort()
        self.stopper.stop_applications()

    def next(self):
        """ Wait for all processes to be stopped. """
        # check eventual jobs in progress
        if self.stopper.check_stopping():
            return SupvisorsStates.SHUTDOWN
        return SupvisorsStates.RESTARTING

    def exit(self):
        """ When leaving the RESTARTING state, request the full restart. """
        self.apply_addresses_func(self.supvisors.zmq.pusher.send_restart)


class ShuttingDownState(AbstractState):
    """ In the SHUTTING_DOWN state, Supvisors stops all applications before triggering a full shutdown. """

    def enter(self):
        """ When entering in the SHUTTING_DOWN state, stop all applications. """
        self.starter.abort()
        self.stopper.stop_applications()

    def next(self):
        """ Wait for all processes to be stopped. """
        # check eventual jobs in progress
        if self.stopper.check_stopping():
            return SupvisorsStates.SHUTDOWN
        return SupvisorsStates.SHUTTING_DOWN

    def exit(self):
        """ When leaving the SHUTTING_DOWN state, request the full shutdown. """
        self.apply_addresses_func(self.supvisors.zmq.pusher.send_shutdown)


class ShutdownState(AbstractState):
    """ This is the final state. """


class FiniteStateMachine:
    """ This class implements a very simple behaviour of FiniteStateMachine based on a single event.
    A state is able to evaluate itself for transitions. """

    def __init__(self, supvisors):
        """ Reset the state machine and the associated context """
        self.supvisors = supvisors
        supvisors_short_cuts(self, ['context', 'starter', 'stopper', 'logger'])
        self.update_instance(SupvisorsStates.INITIALIZATION)
        self.instance.enter()

    def state_string(self):
        """ Return the supvisors state as a string. """
        return SupvisorsStates._to_string(self.state)

    def next(self):
        """ Send the event to the state and transitions if possible.
        The state machine re-sends the event as long as it transitions. """
        self.set_state(self.instance.next())

    def set_state(self, next_state):
        """ Send the event to the state and transitions if possible.
        The state machine re-sends the event as long as it transitions. """
        while next_state != self.state and next_state in self.__Transitions[self.state]:
            self.instance.exit()
            self.update_instance(next_state)
            self.logger.info('Supvisors in {}'.format(self.state_string()))
            self.instance.enter()
            next_state = self.instance.next()

    def update_instance(self, state):
        """ Change the current state.
        The method also triggers the publication of the change. """
        self.state = state
        self.instance = self.__StateInstances[state](self.supvisors)
        # publish SupvisorsStatus event
        if hasattr(self.supvisors, 'zmq'):
            self.supvisors.zmq.publisher.send_supvisors_status(self)

    def on_timer_event(self):
        """ Periodic task used to check if remote Supvisors instances are still active.
        This is also the main event on this state machine. """
        self.context.on_timer_event()
        self.next()
        # fix inconsistencies if any
        # processes can be marked by the Supvisors master after an address is invalidated
        # or by any instance upon request from ui
        self.starter.start_marked_processes(self.context.marked_processes())
        # check if new isolating remotes and return the list of newly isolated addresses
        return self.context.handle_isolation()

    def on_tick_event(self, address, when):
        """ This event is used to refresh the data related to the address. """
        self.context.on_tick_event(address, when)
        # could call the same behaviour as on_timer_event if necessary

    def on_process_event(self, address, event):
        """ This event is used to refresh the process data related to the event and address.
        This event also triggers the application starter. """
        process = self.context.on_process_event(address, event)
        if process:
            starting_application = self.starter.has_application(process.application_name)
            stopping_application = self.stopper.has_application(process.application_name)
            # wake up starter if needed
            if starting_application:
                self.starter.on_event(process)
            # wake up stopper if needed
            if stopping_application:
                self.stopper.on_event(process)
            # TODO: on_xxx

    def on_xxx(self, address, event):
        """ TODO. """
        # FIXME: this is not the right place
        # if event FATAL or EXIT unexpected and process required
        # use running failure strategy
        if not starting_application and not stopping_application:
            from supvisors.ttypes import RunningFailureStrategies
            # add mark_for_restart to application ?
            application_name = process.application_name
            # impact of failure upon application deployment
            if process.rules.required:
                # get starting failure strategy of related application
                application = self.context.applications[application_name]
                running_strategy = application.rules.running_failure_strategy
                # apply strategy
                if running_strategy == RunningFailureStrategies.STOP:
                    self.logger.error('failure with running failed required {}: stop application {}'.format(process.process_name, application_name))
                    self.supvisors.stopper.stop_application(application)
                elif running_strategy == RunningFailureStrategies.RESTART:
                    self.logger.error('failure with running failed required {}: restart application {}'.format(process.process_name, application_name))
                    # remove failed application from deployment
                    # do not remove application from current_jobs as requests have already been sent
                    self.planned_jobs.pop(application_name, None)
                elif running_strategy == RunningFailureStrategies.CONTINUE:
                    self.logger.warn('failure with running failed for required {}: continue application {}'.format(process.process_name, application_name))

    def on_process_info(self, address_name, info):
        """ This event is used to fill the internal structures with processes available on address. """
        self.context.load_processes(address_name, info)

    def on_authorization(self, address_name, authorized):
        """ This event is used to finalize the port-knocking between Supvisors instances. """
        self.context.on_authorization(address_name, authorized)

    def on_restart(self):
        """ This event is used to transition the state machine to the RESTARTING state. """
        self.set_state(SupvisorsStates.RESTARTING)

    def on_shutdown(self):
        """ This event is used to transition the state machine to the SHUTTING_DOWN state. """
        self.set_state(SupvisorsStates.SHUTTING_DOWN)

    # serialization
    def serial(self):
        """ Return a serializable form of the SupvisorsState """
        return {'statecode': self.state, 'statename': self.state_string()}

    # Map between state enumerations and classes
    __StateInstances = {
        SupvisorsStates.INITIALIZATION: InitializationState,
        SupvisorsStates.DEPLOYMENT: DeploymentState,
        SupvisorsStates.OPERATION: OperationState,
        SupvisorsStates.CONCILIATION: ConciliationState,
        SupvisorsStates.RESTARTING: RestartingState,
        SupvisorsStates.SHUTTING_DOWN: ShuttingDownState,
        SupvisorsStates.SHUTDOWN: ShutdownState
    }

    # Transitions allowed between states
    __Transitions = {
        SupvisorsStates.INITIALIZATION: [SupvisorsStates.DEPLOYMENT],
        SupvisorsStates.DEPLOYMENT: [SupvisorsStates.OPERATION, SupvisorsStates.CONCILIATION, SupvisorsStates.RESTARTING, SupvisorsStates.SHUTTING_DOWN],
        SupvisorsStates.OPERATION: [SupvisorsStates.CONCILIATION, SupvisorsStates.INITIALIZATION, SupvisorsStates.RESTARTING, SupvisorsStates.SHUTTING_DOWN],
        SupvisorsStates.CONCILIATION: [SupvisorsStates.OPERATION, SupvisorsStates.INITIALIZATION, SupvisorsStates.RESTARTING, SupvisorsStates.SHUTTING_DOWN],
        SupvisorsStates.RESTARTING: [SupvisorsStates.SHUTDOWN],
        SupvisorsStates.SHUTTING_DOWN: [SupvisorsStates.SHUTDOWN],
        SupvisorsStates.SHUTDOWN: []
   }
