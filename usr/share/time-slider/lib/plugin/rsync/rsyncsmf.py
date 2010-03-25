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

import subprocess
import threading
from plugin import pluginsmf

RSYNCPROPGROUP = "rsync"
RSYNCDIRSUFFIX = ".time-slider/rsync"
RSYNCFSTAG = "org.opensolaris:time-slider-rsync"

class RsyncSMF(pluginsmf.PluginSMF):

    def __init__(self, instanceName):
        pluginsmf.PluginSMF.__init__(self, instanceName)

    def get_target_dir(self):
        return self.get_prop(RSYNCPROPGROUP, "target_dir").strip()

    def set_target_dir(self, path):
        self.set_prop(RSYNCPROPGROUP, "target_dir", "astring", path) 

    def __str__(self):
        ret = "SMF Instance:\n" +\
              "\tName:\t\t\t%s\n" % (self.instance_name) +\
              "\tState:\t\t\t%s\n" % (self.svcstate) + \
              "\tTriggers:\t\t%s\n" % str(self.get_triggers()) + \
              "\tTarget Dir:\t%s\n" % self.get_target_dir() + \
              "\tVerbose:\t\t\'%s\'" % str((self.get_verbose()))
        return ret

