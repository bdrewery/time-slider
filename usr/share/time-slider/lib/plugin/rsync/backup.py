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
import time
import threading
import math
import syslog
import gobject
import dbus
import shutil
from bisect import insort

from time_slider import util, zfs, dbussvc, autosnapsmf, timeslidersmf
import rsyncsmf


# Set to True if SMF property value of "plugin/command" is "true"
verboseprop = "plugin/verbose"
propbasename = "org.opensolaris:time-slider-plugin"

class RsyncError(Exception):
    """Generic base class for RsyncError

    Attributes:
        msg -- explanation of the error
    """
    def __init__(self, msg):
        self.msg = msg
    def __str__(self):
        return repr(self.msg)


class RsyncTargetDisconnectedError(RsyncError):
    """Exception raised when the backup device goes offline during
       the rsync transfer.

    Attributes:
        msg -- explanation of the error
    """
    def __init__(self, source, dest, message):
        msg = "Target directory error during rsync backup from " \
              "%s to target \'%s\' Rsync error details:\n%s" \
              % (source, dest, message)
        RsyncError.__init__(self, msg)


class RsyncTransferInterruptedError(RsyncError):
    """Exception raised when the rsync transfer process pid was
       interrupted or killed during the rsync transfer.

    Attributes:
        msg -- explanation of the error
    """
    def __init__(self, source, dest, message):
        msg = "Interrputed rsync transfer from %s to %s " \
              "Rsync error details:\n%s" % (source, dest, message)
        RsyncError.__init__(self, msg)


class RsyncSourceVanishedError(RsyncError):
    """Exception raised when rsync could only partially transfer
       due to the contents of the source directory being removed.
       Possibly due to a snapshot being destroyed during transfer
       because of immediate or deferred (holds released) destruction.

    Attributes:
        msg -- explanation of the error
    """
    def __init__(self, source, dest, message):
        msg = "Rsync source directory vanished during transfer of %s to %s" \
              "Rsync error details:\n%s" % (source, dest, message)
        RsyncError.__init__(self, msg)


class RsyncBackup(threading.Thread):


    def __init__(self, source, target, latest=None, verbose=False, logfile=None):

        self._sourceDir = source
        self._backupDir = target
        self._latest = latest
        self.verbose = verbose
        self._proc = None
        self._forkError = None
        self._logFile = logfile
        # Init done. Now initiaslise threading.
        threading.Thread.__init__ (self)

    def run(self):
        try:
            self._proc = subprocess.Popen(self._cmd,
                                          stderr=subprocess.PIPE,
                                          close_fds=True)
        except OSError as e:
            # _check_exit_code() will pick up this and raise an
            # exception in the original thread.
            self._forkError = "%s: %s" % (self._cmd[0], str(e))
        else:
            self.stdout,self.stderr = self._proc.communicate()
            self.exitValue = self._proc.wait()

    def _check_exit_code(self):
        if self._forkError:
            # The rsync process failed to execute, probably
            # received an OSError exception. Pass it up.
            raise RsyncError(self._forkError)

        if self.exitValue == 0:
            return
        # Non zero return code means rsync encountered an
        # error which may be transient or require sys-admin
        # intervention to fix.
        
        # This method basically just maps known rsync exit codes
        # to exception classes.
        
        # Rsync exit value codes (non-zero)
        
        # 11/12 Indicates backup drive was disconnected during
        # transfer. Recoverable once drive reconnected:
        # 11   Error in file I/O
        # 12   Error in rsync protocol data stream
        if self.exitValue == 11 or \
            self.exitValue == 12:
            raise RsyncTargetDisconnectedError(self._sourceDir,
                                               self._backupDir,
                                               self.stderr)
        # Transfer pid interrupted by SIGUSR1 or SIGINT. Recoverable:
        # 20   Received SIGUSR1 or SIGINT
        elif self._proc.returncode == 20:
            raise RsyncTransferInterruptedError(self._sourceDir,
                                                self._backupDir,
                                                self.stderr)

        # For everything else unknown or unexpected, treat it as 
        # fatal and provide the rsync stderr output.
        else:
            raise RsyncError(self.stderr)

    def start_backup(self):
        # First, check to see if the rsync destination
        # directory is accessible.
        try:
            os.stat(self._backupDir)
        except OSError:
            util.debug("Backup directory is not " \
                       "currently accessible: %s" \
                       % (self._backupDir),
                       self.verbose)
            #FIXME exit/exception needs to be raise here
            # or status needs to be set.
            return

        try:
            os.stat(self._sourceDir)
        except OSError:
            util.debug("Backup source directory is not " \
                       "currently accessible: %s" \
                       % (self._sourceDir),
                       self.verbose)
            #FIXME exit/excpetion needs to be raise here
            # or status needs to be set.
            return

        if self._latest:
            self._cmd = ["/usr/bin/rsync", "-a", "--inplace", "--progress",\
                   "%s/." % (self._sourceDir), \
                   "--link-dest=%s" % (self._latest), \
                   self._backupDir]
        else:
            self._cmd = ["/usr/bin/rsync", "-a", "--inplace", "--progress",\
                   "%s/." % (self._sourceDir), \
                   self._backupDir]

        if self._logFile:
            self._cmd.insert(1, "--log-file=%s" % (self._logFile))

        self.start()


class BackupQueue():

    def __init__(self, fmri, dbus, mainLoop=None):
        self.started = False
        self.pluginFMRI = fmri
        self.smfInst = rsyncsmf.RsyncSMF(self.pluginFMRI)
        self.verbose = self.smfInst.get_verbose()
        self.propName = "%s:%s" % (propbasename, fmri.rsplit(':', 1)[1])
        released = release_held_snapshots(self.propName)
        for snapName in released:
            util.debug("Released dangling userref on: " + snapName,
                       self.verbose)
        self._bus = dbus

        self.pendingList = list_pending_snapshots(self.propName)
        self.mainLoop = mainLoop

        # Determine the rsync backup dir. This is the target dir
        # defined by the SMF instance plus the "TIMESLIDER/<nodename>
        # suffix
        self.rsyncBaseDir = self.smfInst.get_target_dir()
        sys,nodeName,rel,ver,arch = os.uname()
        self.rsyncDir = os.path.join(self.rsyncBaseDir,
                                     rsyncsmf.RSYNCDIRPREFIX,
                                     nodeName)
        tsSMF = timeslidersmf.TimeSliderSMF()
        self._labelSeparator = tsSMF.get_separator()
        del tsSMF


    def _cleanup_rsync_target(self):

        # Delete non archival type backups according to the same retention
        # rules defined in:
        # svc://system/filesystem/zfs/auto-snapshot:<schedule>
        archived = self.smfInst.get_archived_schedules()
        triggers = self.smfInst.get_trigger_list()
        try:
            triggers.index('all')
            # Expand the wildcard value 'all' 
            defScheds = [sched for sched,i,p,k in \
                         autosnapsmf.get_default_schedules()]
            customScheds = [sched for sched,i,p,k in \
                            autosnapsmf.get_custom_schedules()]
            triggers = defScheds[:]
            triggers.extend(customScheds)
        except ValueError:
            pass
        tempSchedules = [schedule for schedule in triggers if \
                        schedule not in archived]

        #FIXME write a function to do this and don't hardcode the zfs prop
        filesystems = []
        cmd = [zfs.ZFSCMD, "list", "-H", "-t", "filesystem", \
                "-s", "name", \
                "-o","name,org.opensolaris:time-slider-rsync"]
        outdata,errdata = util.run_command(cmd)
        for line in outdata.rstrip().split('\n'):
            line = line.split()
            if line[1] == "true":
                filesystems.append(line[0])

        for fsName in filesystems:   
            fsRootDir = "%s/%s/%s" % (self.rsyncDir,
                                      fsName,
                                      rsyncsmf.RSYNCDIRSUFFIX)
            dirList = []
            if os.path.exists(fsRootDir):
                os.chdir(fsRootDir)
                # List the directory contents of fsRootDir
                dirList = [d for d in os.listdir(fsRootDir) \
                            if os.path.isdir(d) and
                            not os.path.islink(d)]
                for schedule in tempSchedules:
                    util.debug("Checking for expired '%s' backups in %s" \
                               % (schedule, fsRootDir), self.verbose)
                    label = "%s%s%s" % (autosnapsmf.SNAPLABELPREFIX,
                                        self._labelSeparator,
                                        schedule)
                    schedBackups = [d for d in dirList if 
                                    d.find(label) == 0]
                    # The minimum that can be kept around is one:
                    # keeping zero is stupid since it might trigger
                    # a total replication rather than an incremental
                    # rsync replication.
                    if len(schedBackups) <= 1:
                        continue
                    smfInst = autosnapsmf.AutoSnap(schedule)
                    s,i,p,keep = smfInst.get_schedule_details()
                    if len(schedBackups) <= keep:
                        continue

                    sortedBackupList = []
                    for backup in schedBackups:
                        stInfo = os.stat(backup)
                        # List is sorted by mtime, oldest first
                        insort(sortedBackupList, [stInfo.st_mtime, backup])
                    purgeList = sortedBackupList[0:-keep]
                    for mtime,dirName in purgeList:
                        # Perform a final sanity check to make sure a backup
                        # directory and not a system directory is being deleted.
                        # If it doesn't contain the RSYNCDIRSUFFIX string a
                        # ValueError will be raised.
                        try:
                            os.getcwd().index(rsyncsmf.RSYNCDIRSUFFIX)
                            util.debug("Deleting expired rsync backup: %s" \
                                       % (dirName), self.verbose)
                            shutil.rmtree(dirName)
                            # Log file needs to be deleted too.
                            logFile = os.path.join(".partial",
                                                dirName + ".log")
                            try:
                                os.stat(logFile)
                                util.debug("Deleting rsync log file: %s" \
                                           % (os.path.abspath(logFile)),
                                           self.verbose)
                                os.unlink(logFile)
                            except OSError:
                                util.debug("Expected rsync log file not " \
                                           "found: %s"\
                                           % (os.path.abspath(logFile)),
                                           self.verbose)
                                                       
                        except ValueError:
                            util.log_error(syslog.LOG_ALERT,
                                           "Invalid attempt to delete " \
                                           "non-backup directory: %s\n" \
                                           "Placing plugin into " \
                                           "maintenance state" % (dirName))
                            self.smfInst.mark_maintenance()
                            sys.exit(-1)  

    def _recover_space(self):
        backupDirs = []
        backups = []
        capacity = util.get_filesystem_capacity(self.rsyncDir)
        if capacity <= 90:
            return
        #Delete oldest first.

        os.chdir(self.rsyncDir)
        for root, dirs, files in os.walk(self.rsyncDir):
            if '.time-slider' in dirs:
                dirs.remove('.time-slider')
                backupDirs.append(os.path.join(root, rsyncsmf.RSYNCDIRSUFFIX))
        for dir in backupDirs:
            os.chdir(dir)
            dirList = [d for d in os.listdir(dir) \
                        if os.path.isdir(d) and
                        not os.path.islink(d)]
            for d in dirList:
                #FIXME catch OS/IO Error
                dStat = os.stat(d)
                insort(backups, [dStat.st_mtime, os.path.abspath(d)])
        while util.get_filesystem_capacity(self.rsyncDir) > 90:
            mtime,dirName = backups[0]
            remaining = backups[1:]
            util.debug("Deleting rsync backup: %s" \
                       % (dirName), self.verbose)
            shutil.rmtree(dirName)
            # Remove log file too
            head,tail = os.path.split(dirName)
            logFile = os.path.join(head,
                                   ".partial",
                                   tail + ".log")
            try:
                os.stat(logFile)
                util.debug("Deleting rsync log file: %s" \
                            % (os.path.abspath(logFile)),
                            self.verbose)
                os.unlink(logFile)
            except OSError:
                util.debug("Expected rsync log file not " \
                            "found: %s"\
                            % (os.path.abspath(logFile)),
                            self.verbose)    
            backups = remaining

    def backup_snapshot(self):

        # First, check to see if the rsync destination
        # directory is accessible.
        try:
            statinfo = os.stat(self.rsyncDir)
        except OSError:
            util.debug("Backup target directory is not " \
                       "accessible right now: %s" \
                       % (self.rsyncDir),
                       self.verbose)
            self._bus.rsync_unsynced(len(self.pendingList))
            if self.mainLoop:
                self.mainLoop.quit()
            sys.exit(0)

        # Before getting started. See what needs to be cleaned up on 
        # the backup target.
        if self.started == False:
            self._cleanup_rsync_target()
            
        # Check how much capacity is in use on the destination directory
        # FIXME - then do something useful with this data later
        capacity = util.get_filesystem_capacity(self.rsyncDir)
        #FIXME - first cut hack.
        if capacity > 90:
            self._recover_space()
        used = util.get_used_size(self.rsyncDir)
        avail = util.get_available_size(self.rsyncDir)
        total = util.get_total_size(self.rsyncDir)

        if len(self.pendingList) == 0:
            self._bus.rsync_synced()
            # Nothing to do exit
            if self.mainLoop:
                self.mainLoop.quit()
            sys.exit(0)

        if self.started == False:
            self.started = True
            self._bus.rsync_started(self.rsyncBaseDir)

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
        snapshot.hold(self.propName)

        fs = zfs.Filesystem(snapshot.fsname)
        sourceDir = None
        if fs.is_mounted() == True:
            # Get the mountpoint
            mountPoint = fs.get_mountpoint()
            sourceDir = "%s/.zfs/snapshot/%s" \
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


        # targetDir is the parent folder of all backups
        # for a given filesystem
        targetDir = os.path.join(self.rsyncDir,
                                 snapshot.fsname,
                                 rsyncsmf.RSYNCDIRSUFFIX)
        # partialDir is a subdirectory in the targetDir where
        # snapshots are initially backed up to. Upon successful
        # completion they are moved to the backupDir
        partialDir = os.path.join(targetDir, ".partial", snapshot.snaplabel)
        logFile = os.path.join(targetDir,
                               ".partial",
                               snapshot.snaplabel + ".log")
        
        # backupDir is the full directory path where the new
        # backup will be located ie <targetDir>/<snapshot label>
        backupDir = os.path.join(targetDir, snapshot.snaplabel)

        dirlist = []
        if not os.path.exists(partialDir):
            os.makedirs(partialDir, 0755)
            os.chdir(targetDir)
        else:
            # List the directory contents of targetDir
            # FIXME The list will be inspected later
            # FIXME is chdir necessary?
            os.chdir(targetDir)
            dirlist = [d for d in os.listdir(targetDir) \
                        if os.path.isdir(d) and
                        d != ".partial" and
                        not os.path.islink(d)]

        # FIXME - check free space on targetDir

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

        self.rsyncBackup = RsyncBackup(sourceDir, partialDir, latest, logfile=logFile)

        # Notify the applet of current status via dbus
        self._bus.rsync_current(snapshot.name, len(remainingList))

        # Set umask temporarily so that rsync backups are read-only to
        # the owner by default. Rync will override this to match the
        # permissions of each snapshot as appropriate.
        origmask = os.umask(0222)
        util.debug("Starting rsync backup of '%s' to: %s" \
                   % (sourceDir, partialDir),
                   self.verbose)

        self.rsyncBackup.start_backup()

        while self.rsyncBackup.is_alive():
            time.sleep(1)

        try:
            self.rsyncBackup._check_exit_code()
        except (RsyncTransferInterruptedError,
                RsyncTargetDisconnectedError,
                RsyncSourceVanishedError) as e:
            snapshot.release(self.propName)
            util.log_error(syslog.LOG_ERR, str(e))
            # These are recoverable, so exit for now and try again
            # later
            sys.exit(-1)

        except RsyncError as e:
            snapshot.release(self.propName)
            util.log_error(syslog.LOG_ERR,
                           "Unexpected rsync error encountered: \n" + \
                           str(e))
            util.log_error(syslog.LOG_ERR,
                           "Rsync log file location: %s" \
                           % (os.path.abspath(logFile)))
            util.log_error(syslog.LOG_ERR,
                           "Placing plugin into maintenance mode")
            self.smfInst.mark_maintenance()
            sys.exit(-1)

        util.debug("Rsync process exited", self.verbose)
        os.umask(origmask)

        # Move the completed backup from the partial dir to the
        # the propert backup directory 
        util.debug("Renaming completed backup from %s to %s" \
                   % (partialDir, backupDir), self.verbose)
        os.rename(partialDir, backupDir)

        # Create a symlink pointing to the latest backup. Remove
        # the old one first.
        if latest:
            os.unlink(linkFile)         
        os.symlink(snapshot.snaplabel, linkFile)

        # Reset the mtime and atime properties of the backup directory so that
        # they match the snapshot creation time.
        os.utime(backupDir, (long(ctime), long(ctime)))
        snapshot.set_user_property(self.propName, "completed")

        self.pendingList = remainingList
        snapshot.release(self.propName)
        if len(remainingList) >= 1:
            return True
        else:
            self._bus.rsync_complete(self.rsyncBaseDir)
            self._bus.rsync_synced()
            if self.mainLoop:
                self.mainLoop.quit()
            sys.exit(0)
            return False

def release_held_snapshots(propName):
    """
    Releases dangling user snapshot holds that could
    have occured during abnormal termination of a
    previous invocation of this command during a 
    previous rsync transfer.
    Returns a list of snapshots that had holds mathcing
    propName released.
    """ 
    # First narrow the list down by finding snapshots
    # with userref count > 0
    heldList = []
    released = []
    cmd = [zfs.ZFSCMD, "list", "-H",
           "-t", "snapshot",
           "-o", "userrefs,name"]
    outdata,errdata = util.run_command(cmd)
    for line in outdata.rstrip().split('\n'):
        holdCount,name = line.split()
        if int(holdCount) > 0:
            heldList.append(name)
    # Now check to see if any of those holds
    # match 'propName'
    for snapName in heldList:
        snapshot = zfs.Snapshot(snapName)
        holds = snapshot.holds()
        try:
            holds.index(propName)
            snapshot.release(propName)
            released.append(snapName)
        except ValueError:
            pass
    return released

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
            util.log_error(syslog.LOG_WARNING,
                           "Dataset: %s shouldn't have local property: %s" \
                           % (name, propName))
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
    # This command needs to be executed by the super user (root) to
    # ensure that rsync has permissions to access all local filesystem
    # snapshots and to replicate permissions and ownership on the target
    # device
    if os.geteuid() != 0:
        head,tail = os.path.split(sys.argv[0])
        sys.stderr.write(tail + " can only be executed by root")
        sys.exit(-1)

    # This process needs to be run as a system wide single instance
    # only at any given time. So create a lockfile in /tmp and try
    # to obtain an exclusive lock on it. If we can't then another 
    # instance is running and already has a lock on it so just exit.
    lockFileDir = os.path.normpath(tempfile.gettempdir() + '/' + \
    							".time-slider")
    if not os.path.exists(lockFileDir):
            os.makedirs(lockFileDir, 0755)
    lockFile = os.path.join(lockFileDir, 'rsync-backup.lock')

    lockFp = open(lockFile, 'w')
    try:
        fcntl.flock(lockFp, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except IOError:
        sys.stderr.write("Another instance is already running")
        sys.exit(1)

    # The SMF fmri of the time-slider plugin instance associated with
    # this command needs to be supplied as the argument immeditately
    # proceeding the command. ie. argv[1]
    try:
        pluginFMRI = sys.argv[1]
    except IndexError:
        # No FMRI provided. Probably a user trying to invoke the command
        # from the command line.
        sys.stderr.write("No time-slider plugin SMF instance FMRI defined. " \
                         "This plugin does not support command line " \
                         "execution. Exiting\n")
        sys.exit(-1)

    # Open up a syslog session
    syslog.openlog(sys.argv[0], 0, syslog.LOG_DAEMON)

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

