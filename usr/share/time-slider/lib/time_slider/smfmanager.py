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
import popen2


SMFNAME = 'svc:/application/time-slider'
ZFSPROPGROUP = "zfs"
ZPOOLPROPGROUP = "zpool"

# Commonly used command paths
PFCMD = "/usr/bin/pfexec "
SVCSCMD = "/usr/bin/svcs "
SVCADMCMD = "/usr/sbin/svcadm "
SVCCFGCMD = "/usr/sbin/svccfg "
SVCPROPCMD = "/usr/bin/svcprop "


class SMFManager(Exception):

    def __init__(self, instance_name=SMFNAME):
        self.instance_name = instance_name
        self.svccode,self.svcstate = self.get_service_state()
        depcode,self.svcdeps = self.get_service_dependencies()
        self.customselection = self.get_selection_propval()

    def get_selection_propval(self):
        cmd = SVCPROPCMD + "-c -p %s/%s %s" \
               % (ZFSPROPGROUP, "custom-selection", self.instance_name)
        fin,fout = os.popen4(cmd)
        result = fout.read().rstrip ()
        return result

    def get_warning_level(self):
        cmd = SVCPROPCMD + "-c -p %s/%s %s" \
               % (ZPOOLPROPGROUP, "warning-level", self.instance_name)
        fin,fout = os.popen4(cmd)
        result = fout.read().rstrip ()
        return int(result)

    def set_warning_level(self, value):
        if value > self.get_critical_level():
            raise ValueError, "Warning level can not exceed critical level"
        cmd = PFCMD + SVCCFGCMD + "-s %s setprop " \
              " %s/warning-level = integer: %s" \
               % (self.instance_name, ZPOOLPROPGROUP, value)
        fin,fout = os.popen4(cmd)
        result = fout.read().rstrip()
        self.refresh_service()
        return result

    def get_critical_level(self):
        cmd = SVCPROPCMD + "-c -p %s/%s %s" \
               % (ZPOOLPROPGROUP, "critical-level", self.instance_name)
        fin,fout = os.popen4(cmd)
        result = fout.read().rstrip ()
        return int(result)

    def set_critical_level(self, value):
        if value > self.get_emergency_level():
            raise ValueError, "Critical level can not exceed emergency level"
        cmd = PFCMD + SVCCFGCMD + "-s %s setprop " \
              " %s/critical-level = integer: %s" \
               % (self.instance_name, ZPOOLPROPGROUP, value)
        fin,fout = os.popen4(cmd)
        result = fout.read().rstrip()
        self.refresh_service()
        return result

    def get_emergency_level(self):
        cmd = SVCPROPCMD + "-c -p %s/%s %s" \
               % (ZPOOLPROPGROUP, "emergency-level", self.instance_name)
        fin,fout = os.popen4(cmd)
        result = fout.read().rstrip ()
        return int(result)

    def set_emergency_level(self, value):
        if value > 100:
            raise ValueError, "Emergency level can not exceed emergency 100"
        cmd = PFCMD +  SVCCFGCMD + "-s %s setprop " \
              " %s/emergency-level = integer: %s" \
               % (self.instance_name, ZPOOLPROPGROUP, value)
        fin,fout = os.popen4(cmd)
        result = fout.read().rstrip()
        self.refresh_service()
        return result

    def set_selection_propval(self, value):
        cmd = PFCMD + SVCCFGCMD + "-s %s setprop " \
              "%s/custom-selection = boolean: \'%s\'" \
               % (self.instance_name, ZFSPROPGROUP, value)
        fin,fout = os.popen4(cmd)
        result = fout.read().rstrip()
        self.refresh_service()
        return result

    def get_service_dependencies(self):
        cmd = SVCSCMD + "-H -o fmri -d " + self.instance_name
        child = popen2.Popen4(cmd)
        ec = os.WEXITSTATUS(child.wait())
        result = child.fromchild.read().rstrip().split("\n")
        return ec,result

    def find_dependency_errors(self):
        errors = []
        for dep in self.svcdeps:
            cmd = SVCSCMD + "-H -o state " + dep
            fin,fout = os.popen4(cmd)
            result = fout.read().rstrip()
            if result != "online":
                errors.append("%s\t%s" % (result, dep))
        return errors

    def get_service_state(self):
        cmd = SVCSCMD + "-H -o state " + self.instance_name
        child = popen2.Popen4(cmd)
        ec = os.WEXITSTATUS(child.wait())
        # A return exit code of 1 indicates that svcadm has no knowledge
        # of the specified service
        result = child.fromchild.read().rstrip()
        return ec,result

    def refresh_service(self):
        cmd = PFCMD + SVCADMCMD + "refresh " + self.instance_name
        fin,fout = os.popen4(cmd)
        result = fout.read().rstrip()
        return result

    def disable_service (self):
        if self.svcstate == "disabled":
            return
        cmd = PFCMD + SVCADMCMD + "disable " + self.instance_name
        fin,fout = os.popen4(cmd)
        self.svccode,self.svcstate = self.get_service_state()
        for dep in self.svcdeps:
            cmd = PFCMD + SVCADMCMD + "disable " + dep
            fin,fout = os.popen4(cmd)
        #FIXME: Check return value/command output

    def enable_service (self):
        if (self.svcstate == "online" or self.svcstate == "degraded"):
            return
        cmd = PFCMD + SVCADMCMD + "enable -r " + self.instance_name
        child = popen2.Popen4(cmd)
        ec = os.WEXITSTATUS(child.wait())
        result = child.fromchild.read().rstrip()
        self.svccode,self.svcstate = self.get_service_state()
        #raise Exception, "Enabling the service failed"
        #FIXME: Check return value/command output


    def __eq__(self, other):
        if self.fs_name == other.fs_name and \
           self.interval == other.interval and \
           self.period == other.period:
            return True
        return False
	
    def __str__(self):
        ret = "SMF Instance:\n" +\
              "\tName:\t\t\t%s\n" % (self.instance_name) +\
              "\tCustom Selction:\t%s\n" % (self.customselection) +\
              "\tState:\t\t\t%s\n" % (self.svcstate) + \
              "\tWarning Level:\t\t%d\n" % (self.get_warning_level()) + \
              "\tCritical Level:\t\t%d\n" % (self.get_critical_level()) + \
              "\tEmergency Level:\t%d" % (self.get_emergency_level())
        return ret


if __name__ == "__main__":
  S = SMFManager('svc:/application/time-slider')
  print S

