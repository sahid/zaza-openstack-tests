#!/usr/bin/env python3

# Copyright 2018 Canonical Ltd.
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
"""Module for interacting with juju."""
import os
from pathlib import Path
import yaml

from zaza import (
    model,
    controller,
)
from zaza.openstack.utilities import generic as generic_utils


def get_application_status(application=None, unit=None):
    """Return the juju status for an application.

    :param application: Application name
    :type application: string
    :param unit: Specific unit
    :type unit: string
    :returns: Juju status output for an application
    :rtype: dict
    """
    status = get_full_juju_status()

    if unit and not application:
        application = unit.split("/")[0]

    if application:
        status = status.applications.get(application)
    if unit:
        status = status.get("units").get(unit)
    return status


def get_cloud_configs(cloud=None):
    """Get cloud configuration from local clouds.yaml.

    libjuju does not yet have cloud information implemented.
    Use libjuju as soon as possible.

    :param cloud: Name of specific cloud
    :type remote_cmd: string
    :returns: Dictionary of cloud configuration
    :rtype: dict
    """
    home = str(Path.home())
    cloud_config = os.path.join(home, ".local", "share", "juju", "clouds.yaml")
    if cloud:
        return generic_utils.get_yaml_config(cloud_config)["clouds"].get(cloud)
    else:
        return generic_utils.get_yaml_config(cloud_config)


def get_full_juju_status():
    """Return the full juju status output.

    :returns: Full juju status output
    :rtype: dict
    """
    status = model.get_status()
    return status


def get_machines_for_application(application):
    """Return machines for a given application.

    :param application: Application name
    :type application: string
    :returns: machines for an application
    :rtype: Iterator[str]
    """
    status = get_application_status(application)
    if not status:
        raise StopIteration

    # libjuju juju status no longer has units for subordinate charms
    # Use the application it is subordinate-to to find machines
    if status.get("units") is None and status.get("subordinate-to"):
        status = get_application_status(status.get("subordinate-to")[0])

    for unit in status.get("units").keys():
        yield status.get("units").get(unit).get("machine")


def get_unit_name_from_host_name(host_name, application):
    """Return the juju unit name corresponding to a hostname.

    :param host_name: Host name to map to unit name.
    :type host_name: string
    :param application: Application name
    :type application: string
    """
    # Assume that a juju managed hostname always ends in the machine number.
    machine_number = host_name.split('-')[-1]
    unit_names = [
        u.entity_id
        for u in model.get_units(application_name=application)
        if int(u.data['machine-id']) == int(machine_number)]
    return unit_names[0]


def get_machine_status(machine, key=None):
    """Return the juju status for a machine.

    :param machine: Machine number
    :type machine: string
    :param key: Key option requested
    :type key: string
    :returns: Juju status output for a machine
    :rtype: dict
    """
    status = get_full_juju_status()
    status = status.machines.get(machine)
    if key:
        status = status.get(key)
    return status


def get_machine_series(machine):
    """Return the juju series for a machine.

    :param machine: Machine number
    :type machine: string
    :returns: Juju series
    :rtype: string
    """
    return get_machine_status(
        machine=machine,
        key='series'
    )


def get_machine_uuids_for_application(application):
    """Return machine uuids for a given application.

    :param application: Application name
    :type application: string
    :returns: machine uuuids for an application
    :rtype: Iterator[str]
    """
    for machine in get_machines_for_application(application):
        yield get_machine_status(machine, key="instance-id")


def get_provider_type():
    """Get the type of the undercloud.

    :returns: Name of the undercloud type
    :rtype: string
    """
    cloud = controller.get_cloud()
    if cloud:
        # If the controller was deployed from this system with
        # the cloud configured in ~/.local/share/juju/clouds.yaml
        # Determine the cloud type directly
        return get_cloud_configs(cloud)["type"]
    else:
        # If the controller was deployed elsewhere
        # For now assume openstack
        return "openstack"


def remote_run(unit, remote_cmd, timeout=None, fatal=None):
    """Run command on unit and return the output.

    NOTE: This function is pre-deprecated. As soon as libjuju unit.run is able
    to return output this functionality should move to model.run_on_unit.

    :param remote_cmd: Command to execute on unit
    :type remote_cmd: string
    :param timeout: Timeout value for the command
    :type arg: int
    :param fatal: Command failure condidered fatal or not
    :type fatal: boolean
    :returns: Juju run output
    :rtype: string
    :raises: model.CommandRunFailed
    """
    if fatal is None:
        fatal = True
    result = model.run_on_unit(unit, remote_cmd, timeout=timeout)
    if result:
        if int(result.get("Code")) == 0:
            return result.get("Stdout")
        else:
            if fatal:
                raise model.CommandRunFailed(remote_cmd, result)
            return result.get("Stderr")


def _get_unit_names(names):
    """Resolve given application names to first unit name of said application.

    Helper function that resolves application names to first unit name of
    said application.  Any already resolved unit names are returned as-is.

    :param names: List of units/applications to translate
    :type names: list(str)
    :returns: List of units
    :rtype: list(str)
    """
    result = []
    for name in names:
        if '/' in name:
            result.append(name)
        else:
            result.append(model.get_first_unit_name(name))
    return result


def get_relation_from_unit(entity, remote_entity, remote_interface_name):
    """Get relation data passed between two units.

    Get relation data for relation with `remote_interface_name` between
    `entity` and `remote_entity` from the perspective of `entity`.

    `entity` and `remote_entity` may refer to either a application or a
    specific unit. If application name is given first unit is found in model.

    :param entity: Application or unit to get relation data from
    :type entity: str
    :param remote_entity: Application or Unit in the other end of the relation
                          we want to query
    :type remote_entity: str
    :param remote_interface_name: Name of interface to query on remote end of
                                  relation
    :type remote_interface_name: str
    :returns: dict with relation data
    :rtype: dict
    :raises: model.CommandRunFailed
    """
    application = entity.split('/')[0]
    remote_application = remote_entity.split('/')[0]
    rid = model.get_relation_id(application, remote_application,
                                remote_interface_name=remote_interface_name)
    (unit, remote_unit) = _get_unit_names([entity, remote_entity])
    cmd = 'relation-get --format=yaml -r "{}" - "{}"' .format(rid, remote_unit)
    result = model.run_on_unit(unit, cmd)
    if result and int(result.get('Code')) == 0:
        return yaml.safe_load(result.get('Stdout'))
    else:
        raise model.CommandRunFailed(cmd, result)


def leader_get(application, key=''):
    """Get leader settings from leader unit of named application.

    :param application: Application to get leader settings from.
    :type application: str
    :returns: dict with leader settings
    :rtype: dict
    :raises: model.CommandRunFailed
    """
    cmd = 'leader-get --format=yaml {}'.format(key)
    result = model.run_on_leader(application, cmd)
    if result and int(result.get('Code')) == 0:
        return yaml.safe_load(result.get('Stdout'))
    else:
        raise model.CommandRunFailed(cmd, result)
