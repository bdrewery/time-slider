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

    def __init__(self, name):
        self.name = name
        self.health = self.__get_health()
        # It's not safe to store pool size, availability
        # locally since they are volatile values.

    def get_capacity(self):
        used = self.get_used_size()
        size = self.get_total_size()
        return 100 * float(used) / float(size)

    def get_available_size(self):
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
        # Same as ZPool.get_available_size(): zpool(1)
        # doesn't generate suitable out put so use
        # zfs(1) on the toplevel filesystem
        if self.health == "FAULTED":
            raise "PoolFaulted"
        filesystems = self.list_filesystems()
        poolfs = Filesystem(filesystems[0])
        used = poolfs.get_used_size()
        return used

    def get_total_size(self):
        if self.health == "FAULTED":
            raise "PoolFaulted"
        used = self.get_used_size()
        avail = self.get_available_size()
        return used + avail

    def list_filesystems(self):
        result = []
        cmd = ZFSCMD + "list -t filesystem -H -o name"
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
        # We want pattern matching snapshots sorted by creation date.
        # Oldest snapshots get listed first
        if pattern != None:
            cmd = ZFSCMD + "list -t snapshot -o name -s creation | grep @%s" \
                   % (pattern)
        else:
            cmd = ZFSCMD + "list -t snapshot -o name -s creation"
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

    def __get_health(self):
        """ Gets pool health status: ("ONLINE", "DEGRADED" or "FAULTED")"""
        cmd = ZPOOLCMD + "list -H -o health %s" % (self.name)
        fin,fout = os.popen4(cmd)
        result = fout.read().rstrip()
        return result

    def __repr__(self):
        return_string = "ZPool name: " + self.name
        return_string = return_string + "\n\tHealth: " + self.health
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


class Snapshot(Exception):

    def __init__(self, name, creation = None):
        self.name = name
        self.fsname, self.snaplabel = self.__split_snapshot_name()
        self.poolname = self.__get_pool_name()
        self.__creationTime = None
        if creation:
            self.__creationTime = creation

    def get_creation_time(self):
        if self.__creationTime == None:
            cmd = ZFSCMD + "get -H -p -o value creation %s" % (self.name)
            fin,fout = os.popen4(cmd)
            self.__creationTime = long(fout.read().rstrip())
        return self.__creationTime

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

    def exists(self):
        """Returns True if the snapshots is still present on the system.
           False otherwise"""
        # Test existance of the snapshot by checking the output of a 
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
        result = fout.read().rstrip()
        return long(result)

    def get_referenced_size(self):
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

    def destroy_snapshot(self, recursive = False):
        cmd = PFCMD + ZFSCMD + "destroy %s" % self.name
        fin,fout,ferr = os.popen3(cmd)
        # Check for any error output generated and
        # return it to caller if so.
        error = ferr.read()
        if len(error) > 0:
            return error
        else:
            return

    def __repr__(self):
        return_string = "Snapshot name: " + self.name
        return_string = return_string + "\n\tCreation time: " + str(self.get_creation_time())
        #return_string = return_string + "\n\tUsed Size: " + str(self.usedSize)
        #return_string = return_string + "\n\tReferenced Size: " + str(self.referencedSize)
        return return_string


class Filesystem:
      
    def __init__(self, name):
        self.name = name
        self.mountpoint = self.__get_mountpoint()
        self.included = self.__is_included()

    def __repr__(self):
        return_string = "Filesystem name: " + self.name + ", mountpoint " + self.mountpoint + ", "
        if self.included:
            return_string = return_string + "is INCLUDED"
        else:
            return_string = return_string + "is NOT INCLUDED"
        return_string = return_string + "\n"
        return return_string

    def __is_included(self):
        cmd = ZFSCMD + "get -H -o value com.sun:auto-snapshot %s" % (self.name)
        fin,fout = os.popen4(cmd)
        if fout.read().rstrip() == "true":
            return True
        else:
            return False

    def __get_mountpoint(self):
        cmd = ZFSCMD + "get -H -o value mountpoint %s" % (self.name)
        fin,fout = os.popen4(cmd)
        result = fout.read().rstrip()
        return result

    def get_used_size(self):
        cmd = ZFSCMD + "get -H -p -o value used %s" % (self.name)
        fin,fout = os.popen4(cmd)
        return long(fout.read().rstrip())

    def get_available_size(self):
        cmd = ZFSCMD + "get -H -p -o value available %s" % (self.name)
        fin,fout = os.popen4(cmd)
        return long(fout.read().rstrip())

    def commit_state(self, include, inherit = False):
        if inherit == True:
            cmd = PFCMD + ZFSCMD + "inherit com.sun:auto-snapshot %s" % (self.name)
        elif include == True:
            cmd = PFCMD + ZFSCMD + "set com.sun:auto-snapshot=true %s" % (self.name)
        else:
            cmd = PFCMD + ZFSCMD + "set com.sun:auto-snapshot=false %s" % (self.name)
        fin,fout = os.popen4(cmd)
        return

    def list_snapshots(self, pattern = None):
        # We want pattern matching snapshots sorted by creation date.
        # Oldest snapshots get listed first
        if pattern != None:
            cmd = ZFSCMD + "list -t snapshot -o name -s creation | grep %s@%s" \
                    % (self.name, pattern)
        else:
            cmd = ZFSCMD + "list -t snapshot -o name -s creation | grep %s@" \
                    %(self.name)
        fin,fout = os.popen4(cmd)
        snapshots = []
        for line in fout:
            snapshots.append(line.rstrip())
        return snapshots

    def is_included(self):
        return self.included

    def list_children(self):
        cmd = ZFSCMD + "list -H -r -t filesystem -o name %s" % (self.name)
        fin,fout = os.popen4(cmd)
        result = []
        for line in fout:
            if line.rstrip() != self.name:
                result.append(line.rstrip())
        return result

def list_filesystems(pattern = None):
    # We want pattern matching filesystems sorted by name.
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
    
def list_snapshots(pattern = None):
    # We want pattern matching snapshots sorted by creation date.
    # Oldest snapshots get listed first. We use zfs get instead
    # of zfs list since it allows creation time to be output in
    # machine usable format. This is faster than calling zfs get
    # for each snapshot (of which there could be thousands)
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
    """Returns a list of snapshots that have
       cloned filesystems associated with them. Cloned filesystems
       should not be displayed to the user for deletion"""
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
    result = []
    cmd = ZPOOLCMD + "list -H -o name"
    fin,fout = os.popen4(cmd)
    for line in fout:
        result.append(line.rstrip())
    return result

if __name__ == "__main__":
    for zpool in list_zpools():
        pool = ZPool(zpool)
        print pool.__repr__()
