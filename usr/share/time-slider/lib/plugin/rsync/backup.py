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
import sys
import subprocess
import statvfs
import math
import syslog

import rsyncsmf

from bisect import insort

from time_slider import util, zfs

# Set to True if SMF property value of "plugin/command" is "true"
verboseprop = "plugin/verbose"

propbasename = "org.opensolaris:time-slider-plugin"

def main(argv):

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

    # FIXME - better to log as command than FMRI?
    syslog.openlog(pluginFMRI, 0, syslog.LOG_DAEMON)

    smfInst = rsyncsmf.RsyncSMF(pluginFMRI)
    verbose = smfInst.get_verbose()

    # Determine the rsync backup dir.
    rsyncDir = smfInst.get_target_dir()

    # FIXME - delete this check block
    # Check to see if the rsync destination directory is accessible.
    #testdir = "/media/External"
    #try:
    #    statinfo = os.stat(testdir)
    #except OSError:
    #    log_error(syslog.LOG_ERR,
    #              "Plugin: %s: Can not access the configured " \
    #              "rsync backup destination directory: %s" \
    #              % (pluginFMRI, testdir))    
    #    sys.exit(0)

    # FIXME - delete this check block
    # Check to see if the rsync destination directory is writable.
    #testfile = "/export/home/niall/tmp/rsync-test-file"
    #testf = open(testfile, "w")
    #testf.close()
    #os.link(testfile, "/export/home/niall/tmp/testfilelink")
    #os.remove(testfile)
    #os.remove("/export/home/niall/tmp/testfilelink")
    #sys.exit(0)

    # Check to see if the rsync destination directory is accessible.
    try:
        statinfo = os.stat(rsyncDir)
    except OSError:
        util.debug("Plugin %s: Backup target directory is not " \
                   "accessible right now: %s" \
                   % (pluginFMRI, rsyncDir))  
        sys.exit(0)

    # Check how much capacity is in use on the destination directory
    capacity = get_filesystem_capacity(rsyncDir)
    used = get_used_size(rsyncDir)
    avail = get_available_size(rsyncDir)
    total = get_total_size(rsyncDir)

    print "Capacity: " + str(capacity) + '%'
    print "Used: " + str(used)
    print "Available: " + str(avail)
    print "Total: " + str(total)

    # The user property used by this plugin's trigger script
    # to tag zfs filesystem snapshots
    propname = "%s:%s" % (propbasename, pluginFMRI.rsplit(':', 1)[1])

    # The process for backing up snapshots is:
    # Identify all filesystem snapshots that have the (propname)
    # property set to "pending" on them. Back them up starting
    # with the oldest first.

    pendinglist = list_pending_snapshots(propname)
    for ctime,snapname in pendinglist:
        snapshot = zfs.Snapshot(snapname, long(ctime))
        # Make sure the snapshot didn't get destroyed since we last
        # checked it.
        if snapshot.exists() == False:
            util.debug("Snapshot: %s no longer exists. Skipping" \
                       % (snapname), verbose)
            continue

        # Place a hold on the snapshot so it doesn't go anywhere
        # while rsync is trying to back it up.
        # If a hold already exists, it's probably from a 
        # botched previous attempt to rsync
        try:
            snapshot.holds().index(propname)
        except ValueError:
            snapshot.hold(propname)

        fs = zfs.Filesystem(snapshot.fsname)

        # Optimisation: FIXME - Experimental
        # Similar to time-sliderd deleting 0 (used) sized snaphots,
        # we can avoid rsyncing zero sized snapshots. Snapshots that
        # are not the most recent for their filesystem/volume and have
        # a used size of zero will not provide any unique restore points.
        #fssnaps = fs.list_snapshots()
        #newest,ctime = fssnaps[-1]
        #if snapshot.name != newest and snapshot.get_used_size() == 0:
        #    print snapshot.name + " is zero sized. Skipping"
        #    snapshot.release(propname)
        #    continue

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
                       % (snapshot.fsname), verbose)
            snapshot.release(propname)
            continue

        rootDir = "%s/%s" % (rsyncDir, snapshot.fsname)
        dirlist = []
        if not os.path.exists(rootDir):
            os.makedirs(rootDir, 0755)
            os.chdir(rootDir)
        else:
            # FIXME - List the directory contents of rootDir
            os.chdir(rootDir)
            dirlist = [d for d in os.listdir(rootDir) \
                       if os.path.isdir(d) and
                       not os.path.islink(d)]
            print dirlist

        for d in dirlist:
            print os.path.getmtime(d)


        # FIXME - check free space on rootDir

        # Get previous backup dir if it exists
        linkFile = ".latest-rsync"
        latest = None

        if os.path.lexists(linkFile):
            # We've confirmed that the symlink exists
            # but we need to check if it's dangling.
            if os.path.exists(linkFile):
                latest = os.path.realpath(linkFile)

        destdir = "%s/%s" % (rootDir, snapshot.snaplabel)

        if latest:
            cmd = ["/usr/bin/rsync", "-rlpogtD", "%s/." % (sourcedir), \
                   "--link-dest=%s" % (latest), destdir]
        else:
            cmd = ["/usr/bin/rsync", "-rlpogtD", "%s/." % (sourcedir), \
                   destdir]
        
        # Set umask temporarily so that rsync backups are read-only to
        # the owner  - FIXME not working
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
        snapshot.set_user_property(propname, "completed")
        snapshot.release(propname)

def list_pending_snapshots(prop):
    """
    Lists all snaphots which have 'prop" set locally.
    Resulting list is returned in ascending sorted order
    of creation time. Each element in the returned list
    is tuple of the form: [creationtime, snapshotname]
    """
    results = []
    snaplist = []
    sortsnaplist = []

    # Unfortunately, there's no single zfs command that can
    # output a locally set user property and a creation timestamp
    # in one go. So this is done in two passes. The first pass
    # identifies snapshots that are tagged as "pending". The 
    # second pass uses the filtered results from the first pass
    # as arguments to zfs(1) to get creation times.
    cmd = [zfs.ZFSCMD, "get", "-H",
           "-s", "local",
           "-o", "name,value",
           prop]
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
                       % (name, propname), verbose)
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

def get_filesystem_capacity(path):
    """Returns filesystem space usage of path as an integer percentage of
       the entire capacity of path.
    """
    if not os.path.exists(path):
        raise ValueError("%s is a non-existent path" % path)
    f = os.statvfs(path)

    unavailBlocks = f[statvfs.F_BLOCKS] - f[statvfs.F_BAVAIL]
    capacity = int(math.ceil(100 * (unavailBlocks / float(f[statvfs.F_BLOCKS]))))

    return capacity

def get_available_size(path):
    """Returns the available space in bytes of path"""
    if not os.path.exists(path):
        raise ValueError("%s is a non-existent path" % path)
    f = os.statvfs(path)
    free = long(f[statvfs.F_BAVAIL] * f[statvfs.F_FRSIZE])
    
    return free


def get_used_size(path):
    """Returns the used space in bytes of path"""
    if not os.path.exists(path):
        raise ValueError("%s is a non-existent path" % path)
    f = os.statvfs(path)

    unavailBlocks = f[statvfs.F_BLOCKS] - f[statvfs.F_BAVAIL]
    used = long(unavailBlocks * f[statvfs.F_FRSIZE])

    return used

def get_total_size(path):
    """Returns the total storage space in bytes of path"""
    if not os.path.exists(path):
        raise ValueError("%s is a non-existent path" % path)
    f = os.statvfs(path)
    total = long(f[statvfs.F_BLOCKS] * f[statvfs.F_FRSIZE])

    return total

def log_error(loglevel, message):
    syslog.syslog(loglevel, message + '\n')
    sys.stderr.write(message + '\n')

