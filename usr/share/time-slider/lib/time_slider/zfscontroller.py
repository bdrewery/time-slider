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

from zfs import Filesystem, ZFSCMD


class ZFSController:

    def __init__(self):
        self.zfs_fs = []
        if self.__are_zfs_datasets_available() == True:
            self.zfs_fs = self.__get_zfs_fs()

    def __are_zfs_datasets_available(self):
        cmd = ZFSCMD + "list"
        fin,fout = os.popen4(cmd)
        result = fout.read().rstrip()
        if result == "no datasets available":
            return False
        return True

    def __get_zfs_fs(self):
        """ Return a list of Filesystem objects, sorted by mountpoint """
        cmd = ZFSCMD + "list -H -t filesystem -o name -s mountpoint"
        fin,fout = os.popen4(cmd)
        result = fout.read()
        list_fs = []
        for line in result.rstrip().split("\n"):
            list_fs.append(Filesystem(line))
        return list_fs


if __name__ == "__main__":
    C = ZFSController()
    print "fs :" 
    print C.zfs_fs
    print "\nExcluded fs :"
    print C.excluded_fs

