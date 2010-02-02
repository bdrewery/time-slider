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

import smfmanager
import autosnapsmf
import util

PLUGINBASEFMRI = "svc:/application/time-slider/plugin"


class Plugin(Exception):

    def __init__(self, instance, debug=False):
        self.verbose = debug
        self.instance = instance
        self.triggers = []
        self._proc = None
        util.debug("Instantiating plugin for:\t%s" % (instance), self.verbose)

        self.fmri = "%s:%s" % (PLUGINBASEFMRI, self.instance)
        cmd = [smfmanager.SVCPROPCMD, "-c", "-p", "plugin/command", self.fmri]
        outdata,errdata = util.run_command(cmd)
        self._command = outdata.strip()
        # Note that the associated plugin service's start method checks
        # that the command is defined and executable. But SMF doesn't 
        # bother to do this for offline services until all dependencies
        # (ie. time-slider) are brought online.
        # So we also check the permissions here.
        try:
            statinfo = os.stat(self._command)
            other_x = (statinfo.st_mode & 01)
            if other_x == 0:
              raise RuntimeError, 'Plugin: %s:\nConfigured command is not ' \
                                  'executable:\n%s' \
                                  % (self.fmri, self._command)  
        except OSError:
            raise RuntimeError, 'Plugin: %s:\nCan not access the configured ' \
                                'plugin/command:\n%s' \
                                % (self.fmri, self._command)      

        cmd = [smfmanager.SVCPROPCMD, "-c", "-p", "plugin/trigger_on", \
               self.fmri]
        outdata,errdata = util.run_command(cmd)
        # Strip out '\' characters inserted by svcprop
        triggerlist = outdata.strip().replace('\\', '').split(',')
        for trigger in triggerlist:
            self.triggers.append(trigger.strip())

    def execute(self, schedule, label):

        try:
            self.triggers.index("all")
        except ValueError:
            try:
                self.triggers.index(schedule)
            except ValueError:
                return

        # Skip if already running
        if self.is_running() == True:
            util.debug("Plugin: %s is already running. Skipping execution" \
                       % (self.instance), \
                       self.verbose)
            return
        # Skip if plugin FMRI has been disabled or placed into maintenance
        cmd = [smfmanager.SVCSCMD, "-H", "-o", "state", self.fmri]
        outdata,errdata = util.run_command(cmd)
        state = outdata.strip()
        if state == "disabled" or state == "maintenance":
            util.debug("Plugin: %s is in %s state. Skipping execution" \
                       % (self.instance, state), \
                       self.verbose)
            return

        cmd = self._command
        util.debug("Executing plugin command: %s" % str(cmd), self.verbose)
        svcFmri = "%s:%s" % (autosnapsmf.BASESVC, schedule)

        os.putenv("AUTOSNAP_FMRI", svcFmri)
        os.putenv("AUTOSNAP_LABEL", label)
        try:
            os.putenv("PLUGIN_FMRI", self.fmri) 
            self._proc = subprocess.Popen(cmd,
                                          stdout=subprocess.PIPE,
                                          stderr=subprocess.PIPE,
                                          close_fds=True)
        except OSError, message:
            raise RuntimeError, "%s subprocess error:\n %s" % \
                                (cmd, str(message))
            self._proc = None

    def is_running(self):
        if self._proc == None:
            return False
        else:
            self._proc.poll()
            if self._proc.returncode == None:
                return True
            else:
                return False


class PluginManager():

    def __init__(self, debug=False):
        self.plugins = []
        self.verbose = debug

    def execute_plugins(self, schedule, label):
        util.debug("Executing plugins for \"%s\" with label: \"%s\"" \
                   % (schedule, label), \
                   self.verbose)
        for plugin in self.plugins:
            plugin.execute(schedule, label)


    def refresh(self):
        self.plugins = []
        cmd = [smfmanager.SVCSCMD, "-H", "-o", "state,FMRI", PLUGINBASEFMRI]

        p = subprocess.Popen(cmd,
                             stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE,
                             close_fds=True)
        outdata,errdata = p.communicate()
        err = p.wait()
        if err != 0:
            self._refreshLock.release()
            raise RuntimeError, '%s failed with exit code %d\n%s' % \
                                (str(cmd), err, errdata)
        for line in outdata.rstrip().split('\n'):
            line = line.rstrip().split()
            state = line[0]
            fmri = line[1]
            fmri = fmri.rsplit(":", 1)
            label = fmri[1]

            # Note that the plugins, being dependent on the time-slider service
            # themselves will typically be in an offline state when enabled. They will
            # transition to an "online" state once time-slider itself comes
            # "online" to satisfy it's dependency
            if state == "online" or state == "offline" or state == "degraded":
                util.debug("Found enabled plugin:\t%s" % (label), self.verbose)
                try:
                    plugin = Plugin(label, self.verbose)
                    self.plugins.append(plugin)
                except RuntimeError, message:
                    sys.stderr.write("Ignoring misconfigured plugin: %s\n" \
                                     % (label))
                    sys.stderr.write("Reason:\n%s\n" % (message))
            else:
                util.debug("Found disabled plugin:\t%s" + label, self.verbose)

