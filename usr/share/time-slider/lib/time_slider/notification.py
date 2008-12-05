#!/usr/bin/env python
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

import sys
import os
import getopt

from smfmanager import SMFManager

STATUSOK = 0 # Everything was OK
STATUSWARNING = 1 # Above USER threshhold level
STATUSCRITICAL = 2 # Above CRITICAL level
STATSEMERGENCY = 3 # Above EMERGENCY level

class NotificationContext:

    def __init__(self, pid, zpools, poolstatus):
        smfmanager = SMFManager('svc:/application/time-slider:default')
        self.warningLevel = smfmanager.get_warning_level()
        self.criticalLevel = smfmanager.get_critical_level()
        self.emergencyLevel = smfmanager.get_emergency_level()
        self.pools = []
        self.pooldata = {}
        for pool in zpools:
            self.pools.append(pool)
            self.pooldata[pool] = int(poolstatus[zpools.index(pool)])

        pargs = "pargs -e " + pid + " | grep DISPLAY"
        fin,fout = os.popen4(pargs)
        result = fout.read()
        details = result.split()
        if len(details) < 2:
            self.displayenv = None
        else:
            self.displayenv = details[1]

        pargs = "pargs -e " + pid + " | grep DBUS_SESSION_BUS_ADDRESS"
        fin,fout = os.popen4(pargs)
        result = fout.read()
        details = result.split()
        if len(details) < 2:
            self.dbusenv = None
        else:
            self.dbusenv = details[1]

    def send_to_desktop(self):
        level = 0;
        worstpool = None
        expiry = 20000
        urgency = None
        head = None
        body = None
        # Only report the most significant warning level
        # Other, lesser problems can be dealt with later if not
        # fixed after user intervention
        for pool in self.pools:
            if self.pooldata[pool] > level:
                level = self.pooldata[pool]
                worstpool = pool

        if worstpool == None:
            sys.exit(0)

        if self.pooldata[worstpool] == 4:
            # Leave the notification up for 15 minutes (15 * 60 * 1000) so that
            # notifications don't stack up on the desktop.
            expiry = "900000"
            urgency = "critical"
            head = _("Emergency: \'%s\' is full!") % worstpool
            body = _("The file system: \'%s\', is over %s%% full.\n"
                     "As an emergency measure, Time Slider has "
                     "destroyed all of its backups.\nTo fix this problem, "
                     "delete any unnecessary files on \'%s\', or add "
                     "disk space (see ZFS documentation).") \
                      % (worstpool, self.emergencyLevel, worstpool)
        elif self.pooldata[worstpool] == 3:
            expiry = "900000"
            urgency = "critical"
            head = _("Emergency: \'%s\' is almost full!") % worstpool
            body = _("The file system: \'%s\', exceeded %s%% "
                     "of its total capacity. As an emerency measure, "
                     "Time Slider has has destroyed most or all of its "
                     "backups to prevent the disk becoming full. "
                     "To prevent this from happening again, delete "
                     "any unnecessary files on \'%s\', or add disk "
                     "space (see ZFS documentation).\n") \
                      % (worstpool, self.emergencyLevel, worstpool)
        elif self.pooldata[worstpool] == 2:
            expiry = "900000"
            urgency = "critical"
            head = _("Urgent: \'%s\' is almost full!") % worstpool
            body = _("The file system: \'%s\', exceeded %s%% "
                     "of its total capacity. As a remedial measure, "
					 "Time Slider has destroyed some backups, and will "
					 "destroy more, eventually all, as capacity continues "
					 "to diminish.\nTo prevent this from happening again, "
					 "delete any unnecessary files on \'%s\', or add disk "
					 "space (see ZFS documentation).") \
                      % (worstpool, self.criticalLevel, worstpool)
        elif self.pooldata[worstpool] == 1:
            expiry = 20000
            urgency = "normal"
            head = _("Warning: \'%s\' is getting full") % worstpool
            body = _("\'%s\' exceeded %s%% of its total "
                     "capacity. To fix this, Time Slider has destroyed "
					 "some recent backups, and will destroy more as "
					 "capacity continues to diminish.\nTo prevent "
                     "this from happening again, delete any "
                     "unnecessary files on \'%s\', or add disk space "
                     "(see ZFS documentation).") \
                      % (worstpool, self.warningLevel, worstpool)
        else: # No other values currently supported
            return
        if self.dbusenv != None:
            cmd = "%s %s /usr/bin/notify-send --urgency=%s " \
                  "--expire-time=%s --icon=%s %s %s" \
                  % (self.displayenv, self.dbusenv, urgency, expiry,\
                  "gnome-dev-harddisk", \
                  "\"%s\"" %head, "\"%s\"" % body)
        else:
            cmd = "%s /usr/bin/notify-send --urgency=%s " \
                  "--expire-time=%s --icon=%s %s %s" \
                  % (self.displayenv, urgency, expiry,\
                  "gnome-dev-harddisk", \
                  "\"%s\"" %head, "\"%s\"" % body)
        fin,fout = os.popen4(cmd)

def main(filepath):
    pid = None
    zpools = None
    poolstatus = None

    try:
        opts,args = getopt.getopt(sys.argv[1:], "p:z:s:", \
                                  ["pid=", "--zpools=", "status="])
    except getopt.GetoptError:
        sys.exit(2)

    for opt, arg in opts:
        if opt in ("-p", "--pid"):
            pid = arg
        elif opt in ("-z", "--zpools"):
            # zpools is of the form "<pool1>,<pool2>,..."
            zpools = arg.split(",")
        elif opt in ("-s", "--status"):
            # pool status is of the form "<pool1status,<pool2status>..."
            poolstatus = arg.split(",")
    if pid == None or zpools == None or poolstatus == None:
        sys.exit(2)

    notification = NotificationContext(pid, zpools, poolstatus)
    notification.send_to_desktop()
    sys.exit(0)

