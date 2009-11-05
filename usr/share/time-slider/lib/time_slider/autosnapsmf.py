#!/usr/bin/env python2.6
#
# CDDL HEADER START
#
# The contents of this file are subject to the terms of the
# Common Development and Distribution License (the "License").
# You may not use this file except in compliance with the License.
#
# You can obtain a copy of the license at usr/src/OPENSOLARIS.LICENSE
# or http://www.opensolaris.org/os/licensing.
# See the License for the specific language governing permissions
# and limitations under the License.
#
# When distributing Covered Code, include this CDDL HEADER in each
# file and include the License file at usr/src/OPENSOLARIS.LICENSE.
# If applicable, add the following below this CDDL HEADER, with the
# fields enclosed by brackets "[]" replaced with your own identifying
# information: Portions Copyright [yyyy] [name of copyright owner]
#
# CDDL HEADER END
#

import subprocess
import threading
import smfmanager


factoryDefaultSchedules = ("monthly", "weekly", "daily", "hourly", "frequent")

BASESVC= "svc:/system/filesystem/zfs/auto-snapshot"
ZFSPROPGROUP = "zfs"


# Bombarding the class with schedule queries causes the occasional
# OSError exception due to interrupted system calls.
# Serialising them helps prevent this unlikely event from occuring.
_scheddetaillock = threading.RLock()

class AutoSnap:


    def __init__(self, schedule):
        self.schedule = schedule

    def get_schedule_details(self):
        svc= "%s:%s" % (BASESVC, self.schedule)
        intervalcmd = [smfmanager.SVCPROPCMD, "-c", "-p", "zfs/interval", svc]
        periodcmd = [smfmanager.SVCPROPCMD, "-c", "-p", "zfs/period", svc]
        keepcmd = [smfmanager.SVCPROPCMD, "-c", "-p", "zfs/keep", svc]
        _scheddetaillock.acquire()
        try:
            cmd = intervalcmd
            p = subprocess.Popen(cmd,
                             stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE,
                             close_fds=True)
            outdata,errdata = p.communicate()
            err = p.wait()
            if err != 0:
                raise RuntimeError, '%s failed with exit code %d\n%s' % \
                                    (str(cmd), err, errdata)

            interval = outdata.strip()
            cmd = periodcmd
            p = subprocess.Popen(cmd,
                                 stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE,
                                 close_fds=True)
            outdata,errdata = p.communicate()
            err = p.wait()
            if err != 0:
                raise RuntimeError, '%s failed with exit code %d\n%s' % \
                                (str(cmd), err, errdata)

            period = int(outdata.strip())
            cmd = keepcmd
            p = subprocess.Popen(cmd,
                                 stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE,
                                 close_fds=True)
            outdata,errdata = p.communicate()
            err = p.wait()
            if err != 0:
                raise RuntimeError, '%s failed with exit code %d\n%s' % \
                                (str(cmd), err, errdata)
        except OSError, message:
            raise RuntimeError, "%s subprocess error:\n %s" % \
                                (cmd, str(message))
        finally:
            _scheddetaillock.release()
        keep = int(outdata)        
        return [self.schedule, interval, period, keep]

# FIXME - merge with enable_default_schedules()
def disable_default_schedules():
    """
    Disables the default auto-snapshot SMF instances corresponding
    to: "frequent", "hourly", "daily", "weekly" and "monthly"
    schedules
    Raises RuntimeError exception if unsuccessful
    """

    for s in factoryDefaultSchedules:
        # Acquire the scheddetail lock since their status will
        # likely be changed as a result of enabling the instances.
        _scheddetaillock.acquire()
        instanceName = "%s:%s" % (BASESVC,s)
        cmd = [smfmanager.PFCMD,
               smfmanager.SVCADMCMD,
               "disable",
               instanceName]
        try:
            p = subprocess.Popen(cmd,
                                 stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE,
                                 close_fds=True)
            outdata,errdata = p.communicate()
            err = p.wait()
            if err != 0:
                raise RuntimeError, '%s failed with exit code %d\n%s' % \
                                (str(cmd), err, errdata)
        finally:
            _scheddetaillock.release()

def enable_default_schedules():
    """
    Enables the default auto-snapshot SMF instances corresponding
    to: "frequent", "hourly", "daily", "weekly" and "monthly"
    schedules
    Raises RuntimeError exception if unsuccessful
    """
    for s in factoryDefaultSchedules:
        # Acquire the scheddetail lock since their status will
        # likely be changed as a result of enabling the instances.
        _scheddetaillock.acquire()
        instanceName = "%s:%s" % (BASESVC,s)
        cmd = [smfmanager.PFCMD,
               smfmanager.SVCADMCMD,
               "enable",
               instanceName]
        try:
            p = subprocess.Popen(cmd,
                                 stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE,
                                 close_fds=True)
            outdata,errdata = p.communicate()
            err = p.wait()
            if err != 0:
                raise RuntimeError, '%s failed with exit code %d\n%s' % \
                                (str(cmd), err, errdata)
        finally:
            _scheddetaillock.release()

def get_default_schedules():
    """
    Finds the default schedules that are enabled (online or degraded)
    """
    #This is not the fastest method but it is the safest, we need
    #to ensure that default schedules are processed in the pre-defined
    #order to ensure that the overlap between them is adhered to
    #correctly. monthly->weekly->daily->hourly->frequent. They have
    #to be processed first and they HAVE to be in the correct order.
    _defaultSchedules = []
    for s in factoryDefaultSchedules:
        instanceName = "%s:%s" % (BASESVC,s)
        cmd = [smfmanager.SVCSCMD, "-H", "-o", "state", instanceName]
        _scheddetaillock.acquire()
        try:
            p = subprocess.Popen(cmd,
                                 stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE,
                                 close_fds=True)
            outdata,errdata = p.communicate()
            err = p.wait()
            if err != 0:
                raise RuntimeError, '%s failed with exit code %d\n%s' % \
                                (str(cmd), err, errdata)
        finally:
            _scheddetaillock.release()
        result = outdata.rstrip()
        if result == "online" or result == "degraded":
            instance = AutoSnap(s)
            try:
                _defaultSchedules.append(instance.get_schedule_details())
            except RuntimeError, message:
                raise RuntimeError, "Error getting schedule details for " + \
                                    "default auto-snapshot SMF instance:" + \
                                    "\n\t" + instanceName + "\nDetails:\n" + \
                                    str(message)
    return _defaultSchedules

def get_custom_schedules():
    """
    Finds custom schedules ie. not the factory default
    'monthly', 'weekly', 'hourly', 'daily' and 'frequent' schedules
    """
    _customSchedules = []
    cmd = [smfmanager.SVCSCMD, "-H", "-o", "state,FMRI", BASESVC]
    _scheddetaillock.acquire()
    try:
        p = subprocess.Popen(cmd,
                             stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE,
                             close_fds=True)
        outdata,errdata = p.communicate()
        err = p.wait()
        if err != 0:
            _scheddetaillock.release()
            raise RuntimeError, '%s failed with exit code %d\n%s' % \
                                (str(cmd), err, errdata)
    finally:
        _scheddetaillock.release()

    for line in outdata.rstrip().split('\n'):
        line = line.rstrip().split()
        state = line[0]
        fmri = line[1]
        fmri = fmri.rsplit(":", 1)
        label = fmri[1]
        if label not in factoryDefaultSchedules:
            if state == "online" or state == "degraded":
                instance = AutoSnap(label)
                try:
                    _customSchedules.append(instance.get_schedule_details())
                except RuntimeError, message:
                    raise RuntimeError, "Error getting schedule details " + \
                                        "for custom auto-snapshot SMF " + \
                                        "instance:\n\t" + label + "\n" + \
                                        "Details:\n" + str(message) 
    return _customSchedules


if __name__ == "__main__":
  S = SMFAutoSnap()
  print S

