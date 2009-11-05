#!/usr/bin/env python2.6
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

#SMF EXIT CODES
SMF_EXIT_OK          = 0
SMF_EXIT_ERR_FATAL   = 95
SMF_EXIT_ERR_CONFIG  = 96
SMF_EXIT_MON_DEGRADE = 97
SMF_EXIT_MON_OFFLINE = 98
SMF_EXIT_ERR_NOSMF   = 99
SMF_EXIT_ERR_PERM    = 100
#SMF_EXIT_ERR_OTHER = non-zero

cleanupTypes = ("warning", "critical", "emergency")

SMFNAME = 'svc:/application/time-slider'
ZFSPROPGROUP = "zfs"
ZPOOLPROPGROUP = "zpool"
DAEMONPROPGROUP = "daemon"

# Commonly used command paths
PFCMD = "/usr/bin/pfexec"
SVCSCMD = "/usr/bin/svcs"
SVCADMCMD = "/usr/sbin/svcadm"
SVCCFGCMD = "/usr/sbin/svccfg"
SVCPROPCMD = "/usr/bin/svcprop"


class SMFManager(Exception):

    def __init__(self, instance_name=SMFNAME):
        self.instance_name = instance_name
        self.svccode,self.svcstate = self.__get_service_state()
        self.svcdeps = self.get_service_dependencies()
        self.customselection = self.get_selection_propval()
        self._cleanupLevels = {}
        self._cleanupLevelsLock = threading.Lock()

    def get_keep_empties(self):
        cmd = [SVCPROPCMD, "-c", "-p", \
               ZFSPROPGROUP + '/' + "keep-empties",\
               self.instance_name]
        try:
            p = subprocess.Popen(cmd,
                                 stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE,
                                 close_fds=True) 
            outdata,errdata = p.communicate()
            err = p.wait()
        except OSError, message:
            raise RuntimeError, "%s subprocess error:\n %s" % \
                                (cmd, str(message))
        if err != 0:
            raise RuntimeError, '%s failed with exit code %d\n%s' % \
                                (str(cmd), err, errdata)
        result = outdata.rstrip()
        if result == "true":
            return True
        else:
            return False

    def get_selection_propval(self):
        cmd = [SVCPROPCMD, "-c", "-p", \
               ZFSPROPGROUP + '/' + "custom-selection",\
               self.instance_name]
        try:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, close_fds=True) 
            outdata,errdata = p.communicate()
            err = p.wait()
        except OSError, message:
            raise RuntimeError, "%s subprocess error:\n %s" % \
                                (cmd, str(message))
        if err != 0:
            raise RuntimeError, '%s failed with exit code %d\n%s' % \
                                (str(cmd), err, errdata)

        result = outdata.rstrip()
        return result

    def get_cleanup_level(self, cleanupType):
        if cleanupType not in cleanupTypes:
            raise KeyError("\'%s\' is not a valid cleanup type" % \
                           (cleanupType))
        self._cleanupLevelsLock.acquire()

        cmd = [SVCPROPCMD, "-c", "-p", \
               ZPOOLPROPGROUP + '/' + "%s-level" % (cleanupType), \
               self.instance_name]
        try:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, close_fds=True)
            outdata,errdata = p.communicate()
            err = p.wait()
        except OSError, message:
            raise RuntimeError, "%s subprocess error:\n %s" % \
                                (cmd, str(message))
        finally:
            self._cleanupLevelsLock.release()
        if err != 0:
            raise RuntimeError, '%s failed with exit code %d\n%s' % \
                                (str(cmd), err, errdata)
        level = int(outdata.rstrip())

        return level

    def set_cleanup_level(self, cleanupType, level):
        if cleanupType not in cleanupTypes:
            raise KeyError("\'%s\' is not a valid cleanup type" % \
                           (cleanupType))
        if level < 0:
            raise ValueError("Cleanup level value can not not be negative")
        if cleanupType == "warning" and \
            level > self.get_cleanup_level("critical"):
            raise ValueError("Warning cleanup level value can not exceed " + \
                             "critical cleanup level value")
        elif cleanupType == "critical" and \
            level > self.get_cleanup_level("emergency"):
            raise ValueError("Critical cleanup level value can not " + \
                             "exceed emergency cleanup level value")
        elif level > 100: # Emergency type value
            raise ValueError("Cleanup level value can not exceed 100")

        self._cleanupLevelsLock.acquire()
        propname = "%s-level" % (cleanupType)
        try:
            cmd = [PFCMD, SVCCFGCMD, "-s", self.instance_name, "setprop", \
               ZPOOLPROPGROUP + '/' + propname, "=", "integer: ", \
               str(level)]
            p = subprocess.Popen(cmd,
                                 stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE,
                                 close_fds=True)
            outdata,errdata = p.communicate()
            err = p.wait()
        except OSError, message:
            raise RuntimeError, "%s subprocess error:\n %s" % \
                                (cmd, str(message))
        else:
            if err != 0:
                raise RuntimeError, '%s failed with exit code %d\n%s' % \
                                    (str(cmd), err, errdata)
            self._cleanupLevels[cleanupType] = level
        finally:
            self._cleanupLevelsLock.release()
        self.refresh_service()

    def set_selection_propval(self, value):
        cmd = [PFCMD, SVCCFGCMD, "-s", self.instance_name, "setprop", \
               ZFSPROPGROUP + '/' + "custom-selection", "=", "boolean: ", \
               value]
        p = subprocess.Popen(cmd, close_fds=True)
        self.refresh_service()

    def get_service_dependencies(self):
        cmd = [SVCSCMD, "-H", "-o", "fmri", "-d", self.instance_name]
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, close_fds=True)
        result = p.stdout.read().rstrip().split("\n")
        return result

    def get_verbose(self):
        cmd = [SVCPROPCMD, "-c", "-p", \
               DAEMONPROPGROUP + '/' + "verbose", \
               self.instance_name]
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, close_fds=True)
        result = p.stdout.read().rstrip()
        if result == "true":
            return True
        else:
            return False

    def find_dependency_errors(self):
        errors = []
        #FIXME - do this in one pass.
        for dep in self.svcdeps:
            cmd = [SVCSCMD, "-H", "-o", "state", dep]
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, close_fds=True)
            result = p.stdout.read().rstrip()
            if result != "online":
                errors.append("%s\t%s" % (result, dep))
        return errors

    def __get_service_state(self):
        cmd = [SVCSCMD, "-H", "-o", "state", self.instance_name]
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, close_fds=True)
        code = p.wait()
        result = p.stdout.read().rstrip()
        return code,result

    def refresh_service(self):
        cmd = [PFCMD, SVCADMCMD, "refresh", self.instance_name]
        p = subprocess.Popen(cmd, close_fds=True)

    def disable_service (self):
        if self.svcstate == "disabled":
            return
        cmd = [PFCMD, SVCADMCMD, "disable", self.instance_name]
        p = subprocess.Popen(cmd, close_fds=True)
        self.svccode,self.svcstate = self.__get_service_state()

    def enable_service (self):
        if (self.svcstate == "online" or self.svcstate == "degraded"):
            return
        cmd = [PFCMD, SVCADMCMD, "enable", self.instance_name]
        p = subprocess.Popen(cmd, close_fds=True)
        self.svccode,self.svcstate = self.__get_service_state()

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
              "\tWarning Level:\t\t%d\n" % (self.get_cleanup_level("warning")) + \
              "\tCritical Level:\t\t%d\n" % (self.get_cleanup_level("critical")) + \
              "\tEmergency Level:\t%d" % (self.get_cleanup_level("emergency"))
        return ret

def get_verbose ():
    cmd = [SVCPROPCMD, "-c", "-p", \
           DAEMONPROPGROUP + '/' + "verbose", \
           SMFNAME]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, close_fds=True)
    result = p.stdout.read().rstrip()
    if result == "true":
        return True
    else:
        return False

if __name__ == "__main__":
  S = SMFManager('svc:/application/time-slider')
  S.set_cleanup_level("warning", 90)
  print S

