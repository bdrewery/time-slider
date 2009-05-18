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
BYTESPERMB = 1048576

# Commonly used command paths
PFCMD = "/usr/bin/pfexec "
ZFSCMD = "/usr/sbin/zfs "
ZPOOLCMD = "/usr/sbin/zpool "

class ZPool(Exception):
    """
    Base class for ZFS storage pool objects
    """
    def __init__(self, name):
        self.name = name

    def get_capacity(self):
        """
        Returns the percentage of total pool storage in use.
        """
        used = self.get_used_size()
        size = self.get_total_size()
        return 100 * float(used) / float(size)

    def get_available_size(self):
        """
        How much unused space is available for use on this Zpool.
        Answer in bytes.
        """
        # zpool(1) doesn't report available space in
        # units suitable for calulations but zfs(1)
        # can so use it to find the value for the
        # filesystem matching the pool. The values
        # are close enough that they can be treated
        # as the same thing.
        filesystems = self.list_filesystems()
        poolfs = Filesystem(filesystems[0])
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
        if self.get_health() == "FAULTED":
            raise "PoolFaulted"
        filesystems = self.list_filesystems()
        poolfs = Filesystem(filesystems[0])
        used = poolfs.get_used_size()
        return used

    def get_total_size(self):
        """
        Get total size of this Zpool.
        Answer in bytes.
        """
        if self.get_health() == "FAULTED":
            raise "PoolFaulted"
        used = self.get_used_size()
        avail = self.get_available_size()
        return used + avail

    def list_filesystems(self):
        """
        Return a list of filesystems on this Zpool.
        List is sorted by name.
        """
        result = []
        cmd = ZFSCMD + "list -t filesystem -H -o name | egrep ^%s" \
            % (self.name)
        fin,fout = os.popen4(cmd)
        for line in fout:
            try:
                index = line.index(self.name)
                if index == 0:
                    result.append(line.rstrip())
            except ValueError:
                pass
        result.sort()
        return result

    def list_volumes(self):
        """
        Return a list of volumes (zvol) on this Zpool
        List is sorted by name
        """
        result = []
        cmd = ZFSCMD + "list -t volume -H -o name | egrep ^%s" \
            % (self.name)
        fin,fout = os.popen4(cmd)
        for line in fout:
            try:
                index = line.index(self.name)
                if index == 0:
                    result.append(line.rstrip())
            except ValueError:
                pass
        result.sort()
        return result

    def list_snapshots(self, pattern=None):
        """
        List pattern matching snapshots sorted by ascending creation date.
        
           
        Keyword arguments:
        pattern -- Filter according to pattern (default None)
        """
        if pattern != None:
            cmd = ZFSCMD + "list -t snapshot -o name " + \
                  "-s creation | egrep ^%s.*@.*%s" \
                  % (self.name, pattern)
        else:
            cmd = ZFSCMD + "list -t snapshot -o name " + \
                  "-s creation | egrep ^%s.*@" \
                  % (self.name)
        fin,fout = os.popen4(cmd)
        snapshots = []
        for line in fout:
            try:
                index = line.index(self.name)
                if index == 0:
                    snapshots.append(line.rstrip())
            except ValueError:
                pass
        return snapshots

    def get_health(self):
        """
        Returns pool health status: 'ONLINE', 'DEGRADED' or 'FAULTED'
        """
        cmd = ZPOOLCMD + "list -H -o health %s" % (self.name)
        fin,fout = os.popen4(cmd)
        result = fout.read().rstrip()
        return result

    def __str__(self):
        return_string = "ZPool name: " + self.name
        return_string = return_string + "\n\tHealth: " + self.get_health()
        try:
            return_string = return_string + \
                            "\n\tTotal Size: " + \
                            str(self.get_total_size()/BYTESPERMB) + "Mb"
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
        self.__creationTime = None
        if creation:
            self.__creationTime = creation

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
        # Check for any error output generated and
        # return it to caller if so.
        error = ferr.read()
        if len(error) > 0:
            return error
        else:
            return

    def __str__(self):
        return_string = "Snapshot name: " + self.name
        return_string = return_string + "\n\tCreation time: " + str(self.get_creation_time())
        return_string = return_string + "\n\tUsed Size: " + str(self.get_used_size())
        return_string = return_string + "\n\tReferenced Size: " + str(self.get_referenced_size())
        return return_string

class ReadWritableDataset(ReadableDataset):
    """
    Base class for ZFS filesystems and volumes.
    Provides methods for operations and properties
    common to both filesystems and volumes.
    """
    def __init__(self, name, creation = None):
        ReadableDataset.__init__(self, name, creation)

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
        if pattern != None:
            cmd = ZFSCMD + "list -H -t snapshot -o name " + \
                  "-s creation | egrep ^%s@.*%s" \
                  % (self.name, pattern)
        else:
            cmd = ZFSCMD + "list -H -t snapshot -o name " + \
                  "-s creation | egrep ^%s@" \
                  % (self.name)
        fin,fout = os.popen4(cmd)
        snapshots = []
        for line in fout:
            snapshots.append(line.rstrip())
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
    def __init__(self, name):
        ReadWritableDataset.__init__(self, name)

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
        cmd = ZFSCMD + "get -H -o value mountpoint %s" % (self.name)
        fin,fout = os.popen4(cmd)
        result = fout.read().rstrip()
        return result

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
        ReadableDataset.__init__(self, name)

    def __str__(self):
        return_string = "Volume name: " + self.name + "\n"
        return return_string

def list_filesystems(pattern = None):
    """
    List pattern matching filesystems sorted by name.
    
    Keyword arguments:
    pattern -- Filter according to pattern (default None)
    """
    if pattern != None:
        cmd = ZFSCMD + "list -H -t filesystem -o name -s name | grep %s" \
              % (pattern)
    else:
        cmd = ZFSCMD + "list -H -t filesystem -o name -s name"
    fin,fout = os.popen4(cmd)
    filesystems = []
    for line in fout:
        filesystems.append(line.rstrip())
    return filesystems

def list_volumes(pattern = None):
    """
    List pattern matching volumes sorted by name.
    
    Keyword arguments:
    pattern -- Filter according to pattern (default None)
    """
    if pattern != None:
        cmd = ZFSCMD + "list -H -t volume -o name -s name | grep %s" \
              % (pattern)
    else:
        cmd = ZFSCMD + "list -H -t volume -o name -s name"
    fin,fout = os.popen4(cmd)
    volumes = []
    for line in fout:
        volumes.append(line.rstrip())
    return volumes

def list_snapshots(pattern = None):
    """
    List pattern matching snapshots sorted by creation date.
    Oldest listed first
    
    Keyword arguments:
    pattern -- Filter according to pattern (default None)
    """
    if pattern != None:
        cmd = ZFSCMD + "get -H -p -o value,name creation | grep @%s | sort"\
                % (pattern)
    else:
        cmd = ZFSCMD + "get -H -p -o value,name creation | grep @ | sort"
    fin,fout = os.popen4(cmd)
    snapshots = []
    for line in fout:
        line = line.rstrip().split()
        snapshots.append([line[1], long(line[0])])
    return snapshots

def list_cloned_snapshots():
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
        for filesys in pool.list_filesystems():
            fs = Filesystem(filesys)
            print fs
            for snapshot in fs.list_snapshots():
                snap = Snapshot(snapshot)
        for volname in pool.list_volumes():
            vol = Volume(volname)
            print vol
            for snapshot in vol.list_snapshots():
                snap = Snapshot(snapshot)
