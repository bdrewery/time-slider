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

import sys
import os

try:
    import pygtk
    pygtk.require("2.4")
except:
    pass
try:
    import gtk
    import gtk.glade
except:
    sys.exit(1)
try:
    import gobject
except:
    sys.exit(1)

# here we define the path constants so that other modules can use it.
# this allows us to get access to the shared files without having to
# know the actual location, we just use the location of the current
# file and use paths relative to that.
SHARED_FILES = os.path.abspath(os.path.join(os.path.dirname(__file__),
                               os.path.pardir,
                               os.path.pardir))
LOCALE_PATH = os.path.join('/usr', 'share', 'locale')
RESOURCE_PATH = os.path.join(SHARED_FILES, 'res')

# the name of the gettext domain. because we have our translation files
# not in a global folder this doesn't really matter, setting it to the
# application name is a good idea tough.
GETTEXT_DOMAIN = 'time-slider'

# set up the glade gettext system and locales
gtk.glade.bindtextdomain(GETTEXT_DOMAIN, LOCALE_PATH)
gtk.glade.textdomain(GETTEXT_DOMAIN)

from zfscontroller import ZFSController
from smfmanager import SMFManager
from rbac import RBACprofile

class SnapshotManager:

    def __init__(self, execpath):
        self.execpath = execpath
        self.controller = ZFSController()
        self.xml = gtk.glade.XML("%s/../../glade/time-slider-setup.glade" \
                                  % (os.path.dirname(__file__)))
        # signal dictionary	
        dic = {"on_ok_clicked" : self.on_ok_clicked,
               "on_cancel_clicked" : gtk.main_quit,
               "on_snapshotmanager_delete_event" : gtk.main_quit,
               "on_enablebutton_toggled" : self.on_enablebutton_toggled,
               "on_defaultfsradio_toggled" : self.on_defaultfsradio_toggled,
               "on_selectfsradio_toggled" : self.on_selectfsradio_toggled,
               "on_capspinbutton_value_changed" : self.on_capspinbutton_value_changed,
               "on_deletesnapshots_clicked" : self.on_deletesnapshots_clicked}
        self.xml.signal_autoconnect(dic)

        # Set TreeViews
        self.liststorefs = gtk.ListStore(bool, str, str, gobject.TYPE_PYOBJECT)
        for fs in self.controller.zfs_fs:
            if fs.is_included() == True:
                self.liststorefs.append([True, fs.mountpoint, fs.name, fs])
            else:
                self.liststorefs.append([False, fs.mountpoint, fs.name, fs])

        self.fstv = self.xml.get_widget("fstreeview")
        self.fstv.set_sensitive(False)
        # FIXME: A bit hacky but it seems to work nicely
        self.fstv.set_size_request(10,
                                   100 + (len(self.controller.zfs_fs) - 2) *
                                   10)
        self.fstv.set_model(self.liststorefs)

        self.cell0 = gtk.CellRendererToggle()
        self.cell1 = gtk.CellRendererText()
        self.cell2 = gtk.CellRendererText()
 
        self.tvradiocol = gtk.TreeViewColumn(_("Select"),
                                             self.cell0, active=0)
        self.fstv.append_column(self.tvradiocol)
        self.TvNameCol = gtk.TreeViewColumn(_("Mount Point"),
                                            self.cell1, text=1)
        self.fstv.append_column(self.TvNameCol)
        self.TvMountpointCol = gtk.TreeViewColumn(_("File System Name"),
                                                  self.cell2, text=2)
        self.fstv.append_column(self.TvMountpointCol)
        self.cell0.connect('toggled', self.row_toggled)
        self.fsframe = self.xml.get_widget("filesysframe")
        self.fsframe.connect('unmap', self.fsframe_unmap)

        # Initialise SMF service instance state.
        self.smfmanager = SMFManager()
        if self.smfmanager.svccode == 0:
            if self.smfmanager.svcstate == "disabled":
                self.xml.get_widget("enablebutton").set_active(False)
            elif self.smfmanager.svcstate == "offline":
                self.xml.get_widget("toplevel").set_sensitive(False)
                errors = ''.join("%s\n" % (error) for error in \
                    self.smfmanager.find_dependency_errors())
                dialog = gtk.MessageDialog(self.xml.get_widget("toplevel"),
                                           0,
                                           gtk.MESSAGE_ERROR,
                                           gtk.BUTTONS_CLOSE,
                                           _("Snapshot manager service dependency error"))
                dialog.format_secondary_text(_("The snapshot manager service has "
                                             "been placed offline due to a dependency "
                                             "problem. The following dependency problems "
                                             "were found:\n\n%s\n\nSee the svcs(1) man "
                                             "page for more information") % errors)
                dialog.run()
                sys.exit(1)
            elif self.smfmanager.svcstate == "maintenance":
                self.xml.get_widget("toplevel").set_sensitive(False)
                dialog = gtk.MessageDialog(self.xml.get_widget("toplevel"),
                                           0,
                                           gtk.MESSAGE_ERROR,
                                           gtk.BUTTONS_CLOSE,
                                           _("Snapshot manager service error"))
                dialog.format_secondary_text(_("The snapshot manager service has "
                                             "encountered a problem and has been "
                                             "disabled until the problem is fixed."
                                             "\n\nSee the svcs(1) man page for more "
                                             "information."))
                dialog.run()
                sys.exit(1)
            else:
                # FIXME: Check transitional states 
                self.xml.get_widget("enablebutton").set_active(True)
        elif self.smfmanager.svccode == 1:
            self.xml.get_widget("toplevel").set_sensitive(False)
            dialog = gtk.MessageDialog(self.xml.get_widget("toplevel"),
                                       0,
                                       gtk.MESSAGE_ERROR,
                                       gtk.BUTTONS_CLOSE,
                                       _("Snapshot manager service error"))
            dialog.format_secondary_text(_("The snapshot manager service does "
                                         "not appear to be installed on this "
                                         "system."
                                         "\n\nSee the svcs(1) man page for more "
                                         "information."))
            dialog.run()
            sys.exit(1)

        # Emit a toggled signal so that the initial GUI state is consistent
        self.xml.get_widget("enablebutton").emit("toggled")
        # Check the snapshotting policy (UserData (default), or Custom)
        if self.smfmanager.customselection == "true":
            self.xml.get_widget("selectfsradio").set_active(True)
            # Show the advanced controls so the user can see the
            # customised configuration.
            if self.smfmanager.svcstate != "disabled":
                self.xml.get_widget("expander").set_expanded(True)
        else: # "false" or any other non "true" value
            self.xml.get_widget("defaultfsradio").set_active(True)

        # Set the cleanup threshhold value
        spinButton = self.xml.get_widget("capspinbutton")
        critLevel = self.smfmanager.get_critical_level()
        warnLevel = self.smfmanager.get_warning_level()

        # Force the warning level to something practical
        # on the lower end, and make it no greater than the
        # critical level specified in the SVC instance.
        spinButton.set_range(70, critLevel)
        if warnLevel > 70:
            spinButton.set_value(warnLevel)
        else:
            spinButton.set_value(70)

    def row_toggled(self, renderer, path):
        model = self.fstv.get_model()
        iter = model.get_iter(path)
        state = renderer.get_active()
        if state == False:
            self.liststorefs.set_value(iter, 0, True)
        else:
            self.liststorefs.set_value(iter, 0, False)

    def on_ok_clicked(self, widget):
        enabled = self.xml.get_widget("enablebutton").get_active()
        if enabled == False:
            self.smfmanager.disable_service()
            # Ignore any possible changes to the snapshot configuration
            # of filesystems if the service is disabled.
            # So nothing else to do here.
        else:
            model = self.fstv.get_model()
            snapuserdata = self.xml.get_widget("defaultfsradio").get_active()
            if snapuserdata == True:
                self.smfmanager.set_selection_propval("false")
                model.foreach(self.set_default_state)
            else:
                model.foreach(self.set_fs_state)
                self.smfmanager.set_selection_propval("true")
            level = self.xml.get_widget("capspinbutton").get_value_as_int()
            self.smfmanager.set_warning_level(level)
            # Set the service state last so that the ZFS filesystems
            # are correctly tagged before the snapshot scripts check them
            try:
                self.smfmanager.enable_service()
            except:
                print "Problem enabling the service"

        gtk.main_quit()

    def on_enablebutton_toggled(self, widget):
        expander = self.xml.get_widget("expander")    
        enabled = widget.get_active()
        self.xml.get_widget("filesysframe").set_sensitive(enabled)
        expander.set_sensitive(enabled)
        if (enabled == False):
            expander.set_expanded(False)

    def on_defaultfsradio_toggled(self, widget):
        if widget.get_active() == True:
            self.xml.get_widget("fstreeview").set_sensitive(False)

    def on_selectfsradio_toggled(self, widget):
       if widget.get_active() == True:
            self.xml.get_widget("fstreeview").set_sensitive(True)

    def on_capspinbutton_value_changed(self, widget):
        value = widget.get_value_as_int()

    def fsframe_unmap(self, widget):
        """Auto shrink the window by subtracting the frame's height
           requistion from the window's height requisition"""
        myrequest = widget.size_request()
        toplevel = self.xml.get_widget("toplevel")
        toprequest = toplevel.size_request()
        toplevel.resize(toprequest[0], toprequest[1] - myrequest[1])

    def set_default_state(self, model, path, iter):
        fs = self.liststorefs.get_value(iter, 3)
        mountpoint = self.liststorefs.get_value(iter, 1)
        fs.commit_state(True)

    def set_fs_state(self, model, path, iter):
        fs = self.liststorefs.get_value(iter, 3)
        included = self.liststorefs.get_value(iter, 0)
        fs.commit_state(included)

    def on_deletesnapshots_clicked(self, widget):
        cmdpath = os.path.join(os.path.dirname(self.execpath), \
                                "../lib/time-slider-delete")
        fin,fout = os.popen4(cmdpath)


def main(argv):
    rbacp = RBACprofile()
    # The user security attributes checked are the following:
    # 1. The "Primary Administrator" role
    # 2. The "solaris.smf.manage.zfs-auto-snapshot" auth
    # 3. The "Service Management" profile
    # 4. The "ZFS Files System Management" profile.
    #
    # Valid combinations of the above are:
    # - 1
    # - 2 & 4
    # - 3 & 4
    # Note that an effective UID=0 will match any profile search so
    # no need to check it explicitly.
    if rbacp.has_profile("Primary Administrator") or \
            rbacp.has_profile("ZFS File System Management") and \
            (rbacp.has_auth("solaris.smf.manage.zfs-auto-snapshot") or \
                rbacp.has_profile("Service Management")):
        manager = SnapshotManager(argv)
        gtk.main()
    elif os.path.exists(argv) and os.path.exists("/usr/bin/gksu"):
        # Run via gksu, which will prompt for the root password
        os.execl("/usr/bin/gksu", "gksu", argv);
        # Shouldn't reach this point
        sys.exit(1)
    else:
        # FIXME: Pop up an error dialog and exit.
        dialog = gtk.MessageDialog(None,
                                   0,
                                   gtk.MESSAGE_ERROR,
                                   gtk.BUTTONS_CLOSE,
                                   _("Insufficient Priviliges"))
        dialog.format_secondary_text(_("The snapshot manager service requires "
                                       "administrative privileges to run. "
                                       "You have not been assigned the necessary"
                                       "administrative priviliges."
                                       "\n\nConsult your system administrator "))
        dialog.run()
        print argv + "is not a valid executable path"
        sys.exit(1)

