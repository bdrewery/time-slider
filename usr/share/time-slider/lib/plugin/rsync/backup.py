#!/usr/bin/python2.6
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

import os
import os.path
import fcntl
import tempfile
import sys
import subprocess
import statvfs
import math
import syslog
import gobject
import dbus
from bisect import insort

from time_slider import util, zfs, dbussvc
import rsyncsmf


# Set to True if SMF property value of "plugin/command" is "true"
verboseprop = "plugin/verbose"
propbasename = "org.opensolaris:time-slider-plugin"

class BackupQueue():

    def __init__(self, fmri, dbus, mainLoop=None):
        self.started = False
        self.pluginFMRI = fmri
        self.propName = "%s:%s" % (propbasename, fmri.rsplit(':', 1)[1])
        self._bus = dbus
        self.smfInst = rsyncsmf.RsyncSMF(self.pluginFMRI)
        self.verbose = self.smfInst.get_verbose()
        self.pendingList = list_pending_snapshots(self.propName)
        self.mainLoop = mainLoop

        # Determine the rsync backup dir. This is the target dir
        # defined by the SMF instance plus the .time-slider/rsync
        # suffiz
        baseDir = self.smfInst.get_target_dir()
        self.rsyncDir = os.path.join(baseDir, rsyncsmf.RSYNCDIRSUFFIX)

    def backup_snapshot(self):
        if len(self.pendingList) == 0:
            self._bus.rsync_synced()
            # Nothing to do exit
            if self.mainLoop:
                self.mainLoop.quit()
            sys.exit(0)

        # Check to see if the rsync destination directory is accessible.
        try:
            statinfo = os.stat(self.rsyncDir)
        except OSError:
            util.debug("Plugin %s: Backup target directory is not " \
                       "accessible right now: %s" \
                       % (self.pluginFMRI, self.rsyncDir))
            self._bus.rsync_unsynced(len(self.pendingList))
            if self.mainLoop:
                self.mainLoop.quit()
            sys.exit(0)

        # Check how much capacity is in use on the destination directory
        # FIXME - then do something useful with this data later
        capacity = util.get_filesystem_capacity(self.rsyncDir)
        used = util.get_used_size(self.rsyncDir)
        avail = util.get_available_size(self.rsyncDir)
        total = util.get_total_size(self.rsyncDir)

        if self.started == False:
            self.started = True
            self._bus.rsync_started(self.rsyncDir)

        ctime,snapname = self.pendingList[0]
        snapshot = zfs.Snapshot(snapname, long(ctime))
        # Make sure the snapshot didn't get destroyed since we last
        # checked it.
        remainingList = self.pendingList[1:]
        if snapshot.exists() == False:
            util.debug("Snapshot: %s no longer exists. Skipping" \
                        % (snapname), self.verbose)
            self.pendingList = remainingList
            return True

        # Place a hold on the snapshot so it doesn't go anywhere
        # while rsync is trying to back it up.
        # If a hold already exists, it's probably from a 
        # botched previous attempt to rsync
        try:
            snapshot.holds().index(self.propName)
        except ValueError:
            snapshot.hold(self.propName)

        fs = zfs.Filesystem(snapshot.fsname)

        if fs.is_mounted() == True:
            # Get the mountpoint
            mountPoint = fs.get_mountpoint()
            sourcedir = "%s/.zfs/snapshot/%s" \
                        % (mountPoint, snapshot.snaplabel)
        else:
            # If the filesystem is not mounted just skip it. If it's
            # not mounted then nothing is being written to it. And
            # we can just catch up with it again later if it doesn't
            # get expired by time-sliderd
            util.debug("%s is not mounted. Skipping." \
                        % (snapshot.fsname), self.verbose)
            snapshot.release(self.propName)
            self.pendingList = remainingList
            return True

        rootDir = "%s/%s" % (self.rsyncDir, snapshot.fsname)
        dirlist = []
        if not os.path.exists(rootDir):
            os.makedirs(rootDir, 0755)
            os.chdir(rootDir)
        else:
            # List the directory contents of rootDir
            # FIXME The list will be inspected later
            os.chdir(rootDir)
            dirlist = [d for d in os.listdir(rootDir) \
                        if os.path.isdir(d) and
                        not os.path.islink(d)]

        # FIXME - check free space on rootDir

        # Get previous backup dir if it exists
        linkFile = ".latest-rsync"
        latest = None

        if os.path.lexists(linkFile):
            # We've confirmed that the symlink exists
            # but we need to check if it's dangling.
            if os.path.exists(linkFile):
                latest = os.path.realpath(linkFile)
            else:
                # FIXME - create a link to the latest dir
                # so we can avoid doing a full backup.
                # Remove the dangling link
                os.unlink(linkFile)

        destdir = "%s/%s" % (rootDir, snapshot.snaplabel)

        if latest:
            cmd = ["/usr/bin/rsync", "-a", "%s/." % (sourcedir), \
                    "--link-dest=%s" % (latest), destdir]
        else:
            cmd = ["/usr/bin/rsync", "-a", "%s/." % (sourcedir), \
                    destdir]

        # Notify the applet of current status via dbus
        self._bus.rsync_current(snapshot.name, len(remainingList))

        # Set umask temporarily so that rsync backups are read-only to
        # the owner by default. Rync will override this to match the
        # permissions of each snapshot as appropriate.
        origmask = os.umask(0222)
        util.run_command(cmd)
        os.umask(origmask)

        # Create a symlink pointing to the latest backup. Remove
        # the old one first.
        if latest:
            os.unlink(linkFile)            
        os.symlink(snapshot.snaplabel, linkFile)

        # Reset the mtime and atime properties of the backup directory so that
        # they match the snapshot creation time.
        os.utime(destdir, (long(ctime), long(ctime)))
        snapshot.set_user_property(self.propName, "completed")

        self.pendingList = remainingList
        snapshot.release(self.propName)
        if len(remainingList) >= 1:
            return True
        else:
            self._bus.rsync_complete(self.rsyncDir)
            self._bus.rsync_synced()
            if self.mainLoop:
                self.mainLoop.quit()
            sys.exit(0)
            return False

def list_pending_snapshots(propName):
    """
    Lists all snaphots which have 'prop" set locally.
    Resulting list is returned in ascending sorted order
    of creation time. Each element in the returned list
    is tuple of the form: [creationtime, snapshotname]
    """
    results = []
    snaplist = []
    sortsnaplist = []
    # The process for backing up snapshots is:
    # Identify all filesystem snapshots that have the (propName)
    # property set to "pending" on them. Back them up starting
    # with the oldest first.
    #
    # Unfortunately, there's no single zfs command that can
    # output a locally set user property and a creation timestamp
    # in one go. So this is done in two passes. The first pass
    # identifies snapshots that are tagged as "pending". The 
    # second pass uses the filtered results from the first pass
    # as arguments to zfs(1) to get creation times.
    cmd = [zfs.ZFSCMD, "get", "-H",
            "-s", "local",
            "-o", "name,value",
            propName]
    outdata,errdata = util.run_command(cmd)
    for line in outdata.rstrip().split('\n'):
        line = line.split()
        results.append(line)

    for name,value in results:
        if value != "pending":
            # Already backed up. Skip it."
            continue
        if name.find('@') == -1:
            # Not a snapshot, and should not be set on a filesystem/volume
            # Ignore it.
            util.debug("Dataset: %s shouldn't have local property: %s" \
                        % (name, propName), verbose)
            continue
        snaplist.append(name)

    # Nothing pending so just return the empty list
    if len(snaplist) == 0:
        return snaplist

    cmd = [zfs.ZFSCMD, "get", "-p", "-H",
            "-o", "value,name",
            "creation"]
    cmd.extend(snaplist)

    outdata,errdata = util.run_command(cmd)
    for line in outdata.rstrip().split('\n'):
        insort(sortsnaplist, tuple(line.split()))
    return sortsnaplist


def main(argv):

    # This process needs to be run as a system wide single instance
    # only at any given time. So create a lockfile in /tmp and try
    # to obtain an exclusive lock on it. If we can't then another 
    # instance is running and already has a lock on it so just exit.
    lockFile = os.path.normpath(tempfile.gettempdir() + '/' + \
                                os.path.basename(sys.argv[0]) + '.lock')
    lockFp = open(lockFile, 'w')
    try:
        fcntl.flock(lockFp, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except IOError:
        print "Another instance is running"
        sys.exit(0)

    # The SMF fmri of the time-slider plugin instance associated with
    # this command needs to be supplied as the argument immeditately
    # proceeding the command. ie. argv[1]
    try:
        pluginFMRI = sys.argv[1]
    except IndexError:
        # No FMRI provided. Probably a user trying to invoke the command
        # from the command line.
        sys.stderr.write("No time-slider plugin SMF instance FMRI defined. " \
                            "This plugin does not support command line "
                            "execution. Exiting\n")
        sys.exit(-1)

    # FIXME - better to log using command name or the SMF FMRI?
    syslog.openlog(pluginFMRI, 0, syslog.LOG_DAEMON)

    gobject.threads_init()
    # Tell dbus to use the gobject mainloop for async ops
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    dbus.mainloop.glib.threads_init()
    # Register a bus name with the system dbus daemon
    sysbus = dbus.SystemBus()
    busName = dbus.service.BusName("org.opensolaris.TimeSlider.plugin.rsync", sysbus)
    dbusObj = dbussvc.RsyncBackup(sysbus, \
        "/org/opensolaris/TimeSlider/plugin/rsync")

    mainLoop = gobject.MainLoop()
    backupQueue = BackupQueue(pluginFMRI, dbusObj, mainLoop)
    gobject.idle_add(backupQueue.backup_snapshot)
    mainLoop.run()
    sys.exit(0)

def log_error(loglevel, message):
    syslog.syslog(loglevel, message + '\n')
    sys.stderr.write(message + '\n')

