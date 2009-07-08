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

import os
import re

BYTESPERMB = 1048576

# Commonly used command paths
PFCMD = "/usr/bin/pfexec "
ZFSCMD = "/usr/sbin/zfs "
ZPOOLCMD = "/usr/sbin/zpool "


class Datasets:
    """
    Container class for all zfs datasets. Maintains a centralised
    list of datasets (generated on demand) and accessor methods. 
    Also allows clients to notify when a refresh might be necessary.
    """
    # Class wide instead of per-instance in order to avoid duplication
    filesystems = None
    volumes = None
    snapshots = None

    def list_filesystems(self, pattern = None):
        """
        List pattern matching filesystems sorted by name.
        
        Keyword arguments:
        pattern -- Filter according to pattern (default None)
        """
        filesystems = []
        if Datasets.filesystems == None:
            Datasets.filesystems = []
            cmd = ZFSCMD + "list -H -t filesystem -o name,mountpoint -s name"
            fin,fout = os.popen4(cmd)
            for line in fout:
                line = line.rstrip().split()
                Datasets.filesystems.append([line[0], line[1]])

        if pattern == None:
            filesystems = Datasets.filesystems[:]
        else:
            # Regular expression pattern to match "pattern" parameter.
            regexpattern = ".*%s.*" % pattern
            patternobj = re.compile(regexpattern)

            for fsname,fsmountpoint in Datasets.filesystems:
                patternmatchobj = re.match(patternobj, fsname)
                if patternmatchobj != None:
                    filesystems.append(fsname, fsmountpoint)
        return filesystems

    def list_volumes(self, pattern = None):
        """
        List pattern matching volumes sorted by name.
        
        Keyword arguments:
        pattern -- Filter according to pattern (default None)
        """
        volumes = []
        if Datasets.volumes == None:
            Datasets.volumes = []
            cmd = ZFSCMD + "list -H -t volume -o name -s name"
            fin,fout = os.popen4(cmd)
            for line in fout:
                Datasets.volumes.append(line.rstrip())

        if pattern == None:
            volumes = Datasets.volumes[:]
        else:
            # Regular expression pattern to match "pattern" parameter.
            regexpattern = ".*%s.*" % pattern
            patternobj = re.compile(regexpattern)

            for volname in Datasets.volumes:
                patternmatchobj = re.match(patternobj, volname)
                if patternmatchobj != None:
                    volumes.append(volname)
        return volumes

    def list_snapshots(self, pattern = None):
        """
        List pattern matching snapshots sorted by creation date.
        Oldest listed first
        
        Keyword arguments:
        pattern -- Filter according to pattern (default None)
        """
        snapshots = []
        if Datasets.snapshots == None:
            Datasets.snapshots = []
            cmd = ZFSCMD + "get -H -p -o value,name creation | grep @ | sort"
            fin,fout = os.popen4(cmd)
            for line in fout:
                line = line.rstrip().split()
                Datasets.snapshots.append([line[1], long(line[0])])

        if pattern == None:
            snapshots = Datasets.snapshots[:]
        else:
            # Regular expression pattern to match "pattern" parameter.
            regexpattern = "@.*%s" % pattern
            patternobj = re.compile(regexpattern)

            for snapname,snaptime in Datasets.snapshots:
                patternmatchobj = re.match(patternobj, snapname)
                if patternmatchobj != None:
                    snapshots.append([snapname, snaptime])
        return snapshots

    def list_cloned_snapshots(self):
        """
        Returns a list of snapshots that have cloned filesystems
        dependent on them.
        Snapshots with cloned filesystems can not be destroyed
        unless dependent cloned filesystems are first destroyed.
        """
        cmd = ZFSCMD + "list -H -o origin"
        fin,fout,ferr = os.popen3(cmd)
        result = []
        for line in fout:
            details = line.rstrip()
            if details != "-":
                try:
                    result.index(details)
                except ValueError:
                    result.append(details)
        return result

    def refresh_snapshots(self):
        """
        Should be called when snapshots have been created or deleted
        and a rescan should be performed. Rescan gets deferred until
        next invocation of zfs.Dataset.list_snapshots()
        """
        # FIXME in future.
        # This is a little sub-optimal because we should be able to modify
        # the snapshot list in place in some situations and regenerate the 
        # snapshot list without calling out to zfs(1m). But on the
        # pro side, we will pick up any new snapshots since the last
        # scan that we would be otherwise unaware of.
        Datasets.snapshots = None


class ZPool(Exception):
    """
    Base class for ZFS storage pool objects
    """
    def __init__(self, name):
        self.name = name
        self.health = self.__get_health()
        self.__datasets = Datasets()
        self.__filesystems = None
        self.__volumes = None
        self.__snapshots = None

    def __get_health(self):
        """
        Returns pool health status: 'ONLINE', 'DEGRADED' or 'FAULTED'
        """
        cmd = ZPOOLCMD + "list -H -o health %s" % (self.name)
        fin,fout = os.popen4(cmd)
        result = fout.read().rstrip()
        return result

    def get_capacity(self):
        """
        Returns the percentage of total pool storage in use.
        Calculated based on the "used" and "available" properties
        of the pool's top-level filesystem because the values account
        for reservations and quotas of children in their calculations,
        giving a more practical indication of how much capacity is used
        up on the pool.
        """
        if self.health == "FAULTED":
            raise "PoolFaulted"

        cmd = ZFSCMD + "get -H -p -o value used,available %s" % (self.name)
        fin,fout,ferr = os.popen3(cmd)
        used = float(fout.readline().rstrip())
        available = float(fout.readline().rstrip())
        return 100.0 * used/(used + available)

    def get_available_size(self):
        """
        How much unused space is available for use on this Zpool.
        Answer in bytes.
        """
        # zpool(1) doesn't report available space in
        # units suitable for calulations but zfs(1)
        # can so use it to find the value for the
        # filesystem matching the pool.
        # The root filesystem of the pool is simply
        # the pool name.
        poolfs = Filesystem(self.name)
        avail = poolfs.get_available_size()
        return avail

    def get_used_size(self):
        """
        How much space is in use on this Zpool.
        Answer in bytes
        """
        # Same as ZPool.get_available_size(): zpool(1)
        # doesn't generate suitable out put so use
        # zfs(1) on the toplevel filesystem
        if self.health == "FAULTED":
            raise "PoolFaulted"
        poolfs = Filesystem(self.name)
        used = poolfs.get_used_size()
        return used

    def list_filesystems(self):
        """
        Return a list of filesystems on this Zpool.
        List is sorted by name.
        """
        if self.__filesystems == None:
            result = []
            regexpattern = "^%s" % self.name
            patternobj = re.compile(regexpattern)
            for fsname,fsmountpoint in self.__datasets.list_filesystems():
                patternmatchobj = re.match(patternobj, fsname)
                if patternmatchobj != None:
                    result.append([fsname, fsmountpoint])
            result.sort()
            self.__filesystems = result
        
        return self.__filesystems

    def list_volumes(self):
        """
        Return a list of volumes (zvol) on this Zpool
        List is sorted by name
        """
        if self.__volumes == None:
            result = []
            regexpattern = "^%s" % self.name
            patternobj = re.compile(regexpattern)
            for volname in self.__datasets.list_volumes():
                patternmatchobj = re.match(patternobj, volname)
                if patternmatchobj != None:
                    result.append(volname)
            result.sort()
            self.__volumes = result
        return self.__volumes

    def list_snapshots(self, pattern = None):
        """
        List pattern matching snapshots sorted by creation date.
        Oldest listed first
           
        Keyword arguments:
        pattern -- Filter according to pattern (default None)   
        """
        # If there isn't a list of snapshots for this dataset
        # already, create it now and store it in order to save
        # time later for potential future invocations.
        if Datasets.snapshots == None:
            self.__snapshots = None
        if self.__snapshots == None:
            result = []
            regexpattern = "^%s.*@"  % self.name
            patternobj = re.compile(regexpattern)
            for snapname,snaptime in self.__datasets.list_snapshots():
                patternmatchobj = re.match(patternobj, snapname)
                if patternmatchobj != None:
                    result.append([snapname, snaptime])
            # Results already sorted by creation time
            self.__snapshots = result
        if pattern == None:
            return self.__snapshots
        else:
            snapshots = []
            regexpattern = "^%s.*@.*%s" % (self.name, pattern)
            patternobj = re.compile(regexpattern)
            for snapname,snaptime in self.__snapshots:
                patternmatchobj = re.match(patternobj, snapname)
                if patternmatchobj != None:
                    snapshots.append([snapname, snaptime])
            return snapshots

    def __str__(self):
        return_string = "ZPool name: " + self.name
        return_string = return_string + "\n\tHealth: " + self.health
        try:
            return_string = return_string + \
                            "\n\tUsed: " + \
                            str(self.get_used_size()/BYTESPERMB) + "Mb"
            return_string = return_string + \
                            "\n\tAvailable: " + \
                            str(self.get_available_size()/BYTESPERMB) + "Mb"
            return_string = return_string + \
                            "\n\tCapacity: " + \
                            str(self.get_capacity()) + "%"
        except "PoolFaulted":
            pass
        return return_string


class ReadableDataset:
    """
    Base class for Filesystem, Volume and Snapshot classes
    Provides methods for read only operations common to all.
    """
    def __init__(self, name, creation = None):
        self.name = name
        self.__creationTime = creation
        self.datasets = Datasets()

    def __str__(self):
        return_string = "ReadableDataset name: " + self.name + "\n"
        return return_string

    def get_creation_time(self):
        if self.__creationTime == None:
            cmd = ZFSCMD + "get -H -p -o value creation %s" % (self.name)
            fin,fout = os.popen4(cmd)
            self.__creationTime = long(fout.read().rstrip())
        return self.__creationTime

    def exists(self):
        """
        Returns True if the dataset is still existent on the system.
        False otherwise
        """
        # Test existance of the dataset by checking the output of a 
        # simple zfs get command on the snapshot
        cmd = ZFSCMD + "get -H -o name type %s" % self.name
        fin,fout,ferr = os.popen3(cmd)
        result = fout.read().rstrip()
        if result == self.name:
            return True
        else:
            return False

    def get_used_size(self):
        cmd = ZFSCMD + "get -H -p -o value used %s" % (self.name)
        fin,fout = os.popen4(cmd)
        return long(fout.read().rstrip())


class Snapshot(ReadableDataset, Exception):
    """
    ZFS Snapshot object class.
    Provides information and operations specfic to ZFS snapshots
    """    
    def __init__(self, name, creation = None):
        """
        Keyword arguments:
        name -- Name of the ZFS snapshot
        creation -- Creation time of the snapshot if known (Default None)
        """
        ReadableDataset.__init__(self, name, creation)
        self.fsname, self.snaplabel = self.__split_snapshot_name()
        self.poolname = self.__get_pool_name()

    def __get_pool_name(self):
        name = self.fsname.split("/", 1)
        return name[0]

    def __split_snapshot_name(self):
        name = self.name.split("@", 1)
        # Make sure this is really a snapshot and not a
        # filesystem otherwise a filesystem could get 
        # destroyed instead of a snapshot. That would be
        # really really bad.
        if name[0] == self.name:
            raise 'SnapshotError'
        return name[0],name[1]

    def get_referenced_size(self):
        """
        How much unique storage space is used by this snapshot.
        Answer in bytes
        """
        cmd = ZFSCMD + "get -H -p -o value referenced %s" % (self.name)
        fin,fout = os.popen4(cmd)
        result = fout.read().rstrip()
        return long(result)

    def list_children(self):
        """Returns a recursive list of child snapshots of this snapshot"""
        cmd = ZFSCMD + "list -t snapshot -H -r -o name %s | grep @%s" \
              % (self.fsname, self.snaplabel)
        fin,fout = os.popen4(cmd)
        result = []
        for line in fout:
            # Filter out the parent snapshot from the list.
            if line.rstrip() != self.name:
                result.append(line.rstrip())
        return result

    def has_clones(self):
        """Returns true if the snapshot as any dependent clones"""
        cmd = ZFSCMD + "list -H -o origin,name"
        fin,fout = os.popen4(cmd)
        for line in fout:
            details = line.rstrip().split()
            if details[0] == self.name and \
                details[1] != '-':
                return True
        return False

    def destroy_snapshot(self):
        """Permanently remove this snapshot from the filesystem"""
        cmd = PFCMD + ZFSCMD + "destroy %s" % self.name
        fin,fout,ferr = os.popen3(cmd)
        # Clear the global snapshot cache so that a rescan will be
        # triggered on the next call to Datasets.list_snapshots()
        self.datasets.refresh_snapshots()
        
        # Check for any error output generated and
        # return it to caller if so.
        error = ferr.read()
        if len(error) > 0:
            return error
        else:
            return

    def __str__(self):
        return_string = "Snapshot name: " + self.name
        return_string = return_string + "\n\tCreation time: " \
                        + str(self.get_creation_time())
        return_string = return_string + "\n\tUsed Size: " \
                        + str(self.get_used_size())
        return_string = return_string + "\n\tReferenced Size: " \
                        + str(self.get_referenced_size())
        return return_string


class ReadWritableDataset(ReadableDataset):
    """
    Base class for ZFS filesystems and volumes.
    Provides methods for operations and properties
    common to both filesystems and volumes.
    """
    def __init__(self, name, creation = None):
        ReadableDataset.__init__(self, name, creation)
        self.__snapshots = None

    def __str__(self):
        return_string = "ReadWritableDataset name: " + self.name + "\n"
        return return_string

    def get_auto_snap(self):
        cmd = ZFSCMD + "get -H -o value com.sun:auto-snapshot %s" \
              % (self.name)
        fin,fout = os.popen4(cmd)
        if fout.read().rstrip() == "true":
            return True
        else:
            return False

    def get_available_size(self):
        cmd = ZFSCMD + "get -H -p -o value available %s" % (self.name)
        fin,fout = os.popen4(cmd)
        return long(fout.read().rstrip())

    def list_snapshots(self, pattern = None):
        """
        List pattern matching snapshots sorted by creation date.
        Oldest listed first
           
        Keyword arguments:
        pattern -- Filter according to pattern (default None)   
        """
        # If there isn't a list of snapshots for this dataset
        # already, create it now and store it in order to save
        # time later for potential future invocations.
        if Datasets.snapshots == None:
            self.__snapshots = None
        if self.__snapshots == None:
            result = []
            regexpattern = "^%s@" % self.name
            patternobj = re.compile(regexpattern)
            for snapname,snaptime in self.datasets.list_snapshots():
                patternmatchobj = re.match(patternobj, snapname)
                if patternmatchobj != None:
                    result.append([snapname, snaptime])
            # Results already sorted by creation time
            self.__snapshots = result
        if pattern == None:
            return self.__snapshots
        else:
            snapshots = []
            regexpattern = "^%s@.*%s" % (self.name, pattern)
            patternobj = re.compile(regexpattern)
            for snapname,snaptime in self.__snapshots:
                patternmatchobj = re.match(patternobj, snapname)
                if patternmatchobj != None:
                    snapshots.append(snapname)
            return snapshots

    def set_auto_snap(self, include, inherit = False):
        if inherit == True:
            cmd = PFCMD + ZFSCMD + "inherit com.sun:auto-snapshot %s" \
                  % (self.name)
        elif include == True:
            cmd = PFCMD + ZFSCMD + "set com.sun:auto-snapshot=true %s" \
                  % (self.name)
        else:
            cmd = PFCMD + ZFSCMD + "set com.sun:auto-snapshot=false %s" \
                  % (self.name)
        fin,fout = os.popen4(cmd)
        return


class Filesystem(ReadWritableDataset):
    """ZFS Filesystem class"""
    def __init__(self, name, mountpoint = None):
        ReadWritableDataset.__init__(self, name)
        self.__mountpoint = mountpoint

    def __str__(self):
        return_string = "Filesystem name: " + self.name + \
                        "\n\tMountpoint: " + self.get_mountpoint() + \
                        "\n\tAuto snap: "
        if self.get_auto_snap():
            return_string = return_string + "TRUE"
        else:
            return_string = return_string + "FALSE"
        return_string = return_string + "\n"
        return return_string

    def get_mountpoint(self):
        if (self.__mountpoint == None):
            cmd = ZFSCMD + "get -H -o value mountpoint %s" % (self.name)
            fin,fout = os.popen4(cmd)
            result = fout.read().rstrip()
            self.__mountpoint = result
        return self.__mountpoint

    def list_children(self):
        cmd = ZFSCMD + "list -H -r -t filesystem -o name %s" % (self.name)
        fin,fout = os.popen4(cmd)
        result = []
        for line in fout:
            if line.rstrip() != self.name:
                result.append(line.rstrip())
        return result


class Volume(ReadWritableDataset):
    """
    ZFS Volume Class
    This is basically just a stub and does nothing
    unique from ReadWritableDataset parent class.
    """
    def __init__(self, name):
        ReadWritableDataset.__init__(self, name)

    def __str__(self):
        return_string = "Volume name: " + self.name + "\n"
        return return_string


def list_zpools():
    """Returns a list of all zpools on the system"""
    result = []
    cmd = ZPOOLCMD + "list -H -o name"
    fin,fout = os.popen4(cmd)
    for line in fout:
        result.append(line.rstrip())
    return result


if __name__ == "__main__":
    for zpool in list_zpools():
        pool = ZPool(zpool)
        print pool
        for filesys,mountpoint in pool.list_filesystems():
            fs = Filesystem(filesys, mountpoint)
            print fs
            print "\tSnapshots:"
            for snapshot, snaptime in fs.list_snapshots():
                snap = Snapshot(snapshot, snaptime)
                print "\t" + snap.name
            print "\n"
        for volname in pool.list_volumes():
            vol = Volume(volname)
            print vol
            print "\tSnapshots:"
            for snapshot, snaptime in vol.list_snapshots():
                snap = Snapshot(snapshot, snaptime)
                print "\t" + snap.name
            print "\n"
