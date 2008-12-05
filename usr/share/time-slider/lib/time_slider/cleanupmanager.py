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
import time
import re
import getopt
import syslog


import zfs
from smfmanager import SMFManager
from rbac import RBACprofile

STATUSOK = 0 # Everything was OK
STATUSWARNING = 1 # Above USER threshold level
STATUSCRITICAL = 2 # Above CRITICAL lebel
STATSEMERGENCY = 3 # Above EMERGENCY level

class CleanupManager:
    def __init__(self, execpath, debug = False):
        self.debug = debug
        self.execpath = execpath
        self.zpools = []
        self.poolstatus = {}
        self.destroyedsnaps = []
        smfmanager = SMFManager('svc:/application/time-slider:default')
        self.warningLevel = smfmanager.get_warning_level()
        self.__debug("Warning level value is:   %d%%" % self.warningLevel)
        self.criticalLevel = smfmanager.get_critical_level()
        self.__debug("Critical level value is:  %d%%" % self.criticalLevel)
        self.emergencyLevel = smfmanager.get_emergency_level()
        self.__debug("Emergency level value is: %d%%" % self.emergencyLevel)
        for poolname in zfs.list_zpools():
            # Do not try to examine FAULTED pools
            zpool = zfs.ZPool(poolname)
            if zpool.health == "FAULTED":
                pass
            else:
                self.zpools.append(zpool)
            self.__debug(zpool.__repr__())

    def perform_purge(self):
        """ Cleans out zero sized snapshots, kind of cautiously"""
        deletelist = []
        # Need to seperate out snapshots by filesystem.
        for fsname in zfs.list_filesystems():
            fs = zfs.Filesystem(fsname)
            # We also split out by schedule. We want to delete 0 sized
            # snapshots but we need to keep at least one around (the most
            # recent one) for each schedule so that that overlap is 
            # maintained from frequent -> hourly -> daily etc.
            # We start off with the smallest interval schedule first and
            # move up. This increases the amount of data retained where
            # several snapshots are taken together like a frequent hourly
            # and daily snapshot taken at 12:00am. If 3 snapshots are all
            # identical and reference the same identical data they will all
            # be initially reported as zero for used size. Deleting the
            # daily first then the hourly would shift make the data referenced
            # by all 3 snapshots unique to the frequent scheduled snapshot.
            # This snapshot would probably be purged within an how ever and the
            # data referenced by it would be gone for good.
            # Doing it the other way however ensures that the data should remain
            # accessible to the user for at least a week as long as the pool 
            # doesn't run low on available space before that.
            for schedule in ["frequent", "hourly", "daily", "weekly", "monthly"]:
                snaps = fs.list_snapshots("zfs-auto-snap:%s" % schedule)
                try: # remove the newest one from the list.
                    snaps.pop()
                except IndexError:
                    continue
                for snapname in snaps:
                    snapshot = zfs.Snapshot(snapname)
                    if snapshot.get_used_size() == 0:
                        deletelist.append(snapname)
                        snapshot.destroy_snapshot()
        self.__debug("The following %d snapshots were deleted:" % len(deletelist))
        if self.debug == True and len(deletelist) > 0:
            for item in deletelist:
                self.__debug(item)

    def needs_cleanup(self):
        for zpool in self.zpools:
            if zpool.get_capacity() > self.warningLevel:
                return True
                self.__debug("%s needs a cleanup" % zpool.name)
        return False

    def perform_cleanup(self):
        for zpool in self.zpools:
            self.poolstatus[zpool.name] = 0
            capacity = zpool.get_capacity()
            if capacity > self.warningLevel:
                self.run_warning_cleanup(zpool)
                self.poolstatus[zpool.name] = 1
            capacity = zpool.get_capacity()
            if capacity > self.criticalLevel:
                self.run_critical_cleanup(zpool)
                self.poolstatus[zpool.name] = 2
            capacity = zpool.get_capacity()
            if capacity > self.emergencyLevel:
                self.run_emergency_cleanup(zpool)
                self.poolstatus[zpool.name] = 3
            capacity = zpool.get_capacity()
            if capacity > self.emergencyLevel:
                self.run_emergency_cleanup(zpool)
                self.poolstatus[zpool.name] = 4
            # Wow, that's pretty screwed. But, there's no
            # more snapshots left so it's no longer our 
            # problem. We don't disable the service since 
            # it will permit self recovery and snapshot
            # retention when space becomes available on
            # the pool (hopefully).
            self.__debug("%s pool status after cleanup:" \
                         % zpool.name)
            self.__debug(zpool.__repr__())
        self.__debug("Cleanup completed. %d snapshots were destroyed" \
                     % len(self.destroyedsnaps))
        # Avoid needless list iteration for non-debug mode
        if self.debug == True and len(self.destroyedsnaps) > 0:
            print "The following snapshots were destroyed:"
            for snap in self.destroyedsnaps:
                print ("\t%s" % snap)
			

    def run_warning_cleanup(self, zpool):
        self.__debug("Performing warning level cleanup on %s" % \
                     zpool.name)
        if zpool.get_capacity() > self.warningLevel:
            self.run_cleanup(zpool, "daily", self.warningLevel)
        if zpool.get_capacity() > self.warningLevel:
            self.run_cleanup(zpool, "hourly", self.warningLevel)

    def run_critical_cleanup(self, zpool):
        self.__debug("Performing critical level cleanup on %s" % \
                     zpool.name)
        if zpool.get_capacity() > self.criticalLevel:
            self.run_cleanup(zpool, "weekly", self.criticalLevel)
        if zpool.get_capacity() > self.criticalLevel:
            self.run_cleanup(zpool, "daily", self.criticalLevel)
        if zpool.get_capacity() > self.criticalLevel:
            self.run_cleanup(zpool, "hourly", self.criticalLevel)

    def run_emergency_cleanup(self, zpool):
        self.__debug("Performing emergency level cleanup on %s" % \
                     zpool.name)
        if zpool.get_capacity() > self.emergencyLevel:
            self.run_cleanup(zpool, "monthly", self.emergencyLevel)
        if zpool.get_capacity() > self.emergencyLevel:
            self.run_cleanup(zpool, "weekly", self.emergencyLevel)
        if zpool.get_capacity() > self.emergencyLevel:
            self.run_cleanup(zpool, "daily", self.emergencyLevel)
        if zpool.get_capacity() > self.emergencyLevel:
            self.run_cleanup(zpool, "hourly", self.emergencyLevel)
        if zpool.get_capacity() > self.emergencyLevel:
            self.run_cleanup(zpool, "frequent", self.emergencyLevel)

    def run_cleanup(self, zpool, schedule, threshold):
        clonedsnaps = zfs.list_cloned_snapshots()

        # Build a list of snapshots in the given schedule, that are not
        # cloned, and sort the result in reverse chronological order.
        snapshots = [s for s in \
                        zpool.list_snapshots("zfs-auto-snap:%s" % schedule) \
                        if not s in clonedsnaps]
        snapshots.reverse()
        while zpool.get_capacity() > threshold:
            if len(snapshots) == 0:
                syslog.syslog(syslog.LOG_NOTICE,
                              "No more %s snapshots left" \
                               % schedule)
                return

            percentover = zpool.get_capacity() - threshold
            sizeover = zpool.get_total_size() * percentover / 100

            """This is not an exact science. Deleteing a zero sized 
            snapshot can have unpredictable results. For example a
            pair of snapshots may share exclusive reference to a large
            amount of data (eg. a large core file). The usage of both
            snapshots will initially be seen to be 0 by zfs(1). Deleting
            one of the snapshots will make the data become unique to the
            single remaining snapshot that references it uniquely. The
            remaining snapshot's size will then show up as non zero. So
            deleting 0 sized snapshot is not as pointless as it might seem.
            It also means we have to loop through this, each snapshot set
            at a time and observe the before and after results. Perhaps
            better way exists...."""

            # Start with the oldest first
            snapname = snapshots.pop()
            snapshot = zfs.Snapshot(snapname)
            # It would be nicer, for performance purposes, to delete sets
            # of snapshots recursively but this might destroy more data than
            # absolutely necessary, plus the previous purging of zero sized
            # snapshots can easily break the recursion chain between
            # filesystems.
            # On the positive side there should be fewer snapshots and they
            # will mostly non-zero so we should get more effectiveness as a
            # result of deleting snapshots since they should be nearly always
            # non zero sized.
            self.__debug("Destroying %s" % snapname)
            snapshot.destroy_snapshot()
            self.destroyedsnaps.append(snapname)
            # Give zfs some time to recalculate.
            time.sleep(3)
        
    def send_to_syslog(self):
        for zpool in self.zpools:
            status = self.poolstatus[zpool.name]
            if status == 4:
                syslog.syslog(syslog.LOG_EMERG,
                              "%s is over %d%% capacity. " \
                              "All automatic snapshots were destroyed" \
                               % (zpool.name, self.emergencyLevel))
            elif status == 3:
                syslog.syslog(syslog.LOG_ALERT,
                              "%s exceeded %d%% capacity. " \
                              "Automatic snapshots over 1 hour old were destroyed" \
                               % (zpool.name, self.emergencyLevel))
            elif status == 2:
                syslog.syslog(syslog.LOG_CRIT,
                              "%s exceeded %d%% capacity. " \
                              "Weekly, hourly and daily automatic snapshots were destroyed" \
                               % (zpool.name, self.criticalLevel))                             
            elif status == 1:
                syslog.syslog(syslog.LOG_WARNING,
                              "%s exceeded %d%% capacity. " \
                              "Hourly and daily automatic snapshots were destroyed" \
                               % (zpool.name, self.warningLevel))

        if len(self.destroyedsnaps) > 0:
            syslog.syslog(syslog.LOG_NOTICE,
                          "%d automatic snapshots were destroyed" \
                           % len(self.destroyedsnaps))

    def send_notification(self):
        pgrepcmd = "pgrep gnome-session"
        fin,fout = os.popen4(pgrepcmd)
        procs = fout.read().rstrip().rsplit("\n")
        pscmd = "ps -ef|egrep \"gnome-session$\" |grep -v grep"
        fin,fout = os.popen4(pscmd)
        lines = fout.read().rstrip().split("\n")
        userpids=[]

        for line in lines:
            linedetails = line.split()
            if linedetails[1]:
                # We're highly unlikely to match more than 1
                # gnome-session process per user, but if we
                # do, no harm done.
                username = linedetails[0]
                pid = linedetails [1]
                # Dont't bother with notification if the user is not authorised
                # to take any action about it.
                try:
                    procs.index(pid)
                    rbacp = RBACprofile(username)
                    if rbacp.has_profile("Primary Administrator") or \
                        rbacp.has_profile("ZFS File System Management"):
                        userpids.append([username, pid])
                except ValueError:
                    continue

        for name, pid in userpids:
            # All this because there's no proper way to send a notification
            # from a system process to a user's desktop using libnotification.

            # We need to send the notification in the proper language and
            # locale environments. So we need to examine the user's
            # gnome-session process to determine this.
            envcmd = "pargs -e " + pid
            fin,fout = os.popen4(envcmd)
            lines = fout.read().rstrip().split("\n")

            # Regular expression pattern to match "LANG"
            langpattern = "(^LANG=.*)"
            langpattobj = re.compile(langpattern)
            langenv = ""

            # Regular expression pattern to match "LC_MESSAGES"
            lcmsgpattern = "(^LC_MESSAGES=.*)"
            lcmsgpattobj = re.compile(lcmsgpattern)
            lcmsgenv = ""
            env = ""

            for line in lines:
                # Each line is of the format:
                # envp[N]: ENVVARIABLE=VALUE
                # except the first but it will be filtered
                # out by the RE matching anyway.
                details = line.split()
                langmatchobj = re.match(langpattobj, details[1])
                lcmsgmatchobj = re.match(lcmsgpattobj, details[1])
                if langmatchobj != None:
                    langenv = details[1][langmatchobj.start(): \
                                         langmatchobj.end()]
                    env = env + langenv + " "

                if lcmsgmatchobj != None:
                    lcmsgenv = details[1][lcmsgmatchobj.start(): \
                                          lcmsgmatchobj.end()]
                    env = env + lcmsgenv + " "

            cmdargs = " -p " + pid
            poolarg = None
            statusarg = None
            for zpool in self.zpools:
                if poolarg == None:
                    poolarg = zpool.name
                    statusarg = str(self.poolstatus[zpool.name])
                else:
                    poolarg = poolarg + ",%s" % zpool.name
                    statusarg = statusarg + ",%s" % str(self.poolstatus[zpool.name])

            cmdargs = cmdargs + " -z " + poolarg
            cmdargs = cmdargs + " -s " + statusarg

            path = os.path.join(os.path.dirname(self.execpath), \
                                "time-slider-notify")
            cmd = "/usr/bin/su - " + username + \
                  " -c \"" + env + path + cmdargs + "\""
            fin,fout = os.popen4(cmd)

    def __debug(self, message):
        if self.debug == True:
            print (message)

def main(execpath):

    seriously = False
    try:
        opts,args = getopt.getopt(sys.argv[1:], "y", [])

    except getopt.GetoptError:
        sys.stderr.write("time-slider-cleanup is not a user executable program")
        sys.exit(1)

    for opt,arg in opts:
        if opt == "-y":
            seriously = True

    if seriously == False:
        sys.exit(1)

    # The user security attributes checked are the following:
    # 1. The "Primary Administrator" profile
    # Note that UID == 0 will match any profile search so
    # no need to check it explicitly.
    syslog.openlog("time-slider-cleanup", 0, syslog.LOG_DAEMON)
    rbacp = RBACprofile()
    if rbacp.has_profile("Primary Administrator"):
        cleanup = CleanupManager(execpath)
        cleanup.perform_purge()
        if cleanup.needs_cleanup() == True:
            cleanup.perform_cleanup()
            cleanup.send_notification()
            cleanup.send_to_syslog()
    else:
        syslog.syslog(syslog.LOG_ERROR,
               "%s has insufficient privileges to run time-slider-cleanup!" \
               % rbacp.name)
        syslog.closelog()    
        sys.exit(2)
    syslog.closelog()
    sys.exit(0)
