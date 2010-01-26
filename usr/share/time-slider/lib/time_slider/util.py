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
import sys
import syslog

def run_command(command):
    """
    Wrapper function around subprocess.Popen
    Returns a tuple of standard out and stander error.
    Throws a RunTimeError if the command failed to execute or
    if the command returns a non-zero exit status.
    """
    try:
        p = subprocess.Popen(command,
                             stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE,
                             close_fds=True)
        outdata,errdata = p.communicate()
        err = p.wait()
    except OSError, message:
        raise RuntimeError, "%s subprocess error:\n %s" % \
                            (command, str(message))
    if err != 0:
        raise RuntimeError, '%s failed with exit code %d\n%s' % \
                            (str(command), err, errdata)
    return outdata,errdata

def debug(message, verbose=False):
    """
    Prints message out to standard error and syslog if
    verbose = True.
    Note that the caller needs to first establish a syslog
    context using syslog.openlog()
    """
    if verbose:
        syslog.syslog(syslog.LOG_NOTICE, message + '\n')
        sys.stderr.write(message + '\n')
